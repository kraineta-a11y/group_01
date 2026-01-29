import mysql.connector as mdb
from datetime import datetime, timedelta
from decimal import Decimal

def get_db_connection():
    return mdb.connect(
        host='Netarosh.mysql.pythonanywhere-services.com',
        user='Netarosh',
        password='group01root',
        database='Netarosh$FLYTAU'
    )

def get_user_role(session):
    """Determine role based on session info (email or ID)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if "manager_employee_id" in session:
        cursor.execute("SELECT * FROM Manager WHERE Employee_id = %s", (session["manager_employee_id"],))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return 'manager'
    if "client_email" in session:
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s", (session["client_email"],))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return 'client'
    cursor.close()
    conn.close()
    return 'guest'

def update_flight_status():
    # runs periodically to update flight status based on current time
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # First, auto-cancel ACTIVE flights that are past departure time but lack required crew
    cursor.execute("""
        SELECT f.Flight_number, f.Plane_id, fr.Duration
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_status = 'ACTIVE'
        AND TIMESTAMP(f.Departure_date, f.Departure_time) < NOW()
    """)
    
    past_flights = cursor.fetchall()
    
    for flight in past_flights:
        flight_number = flight['Flight_number']
        plane_id = flight['Plane_id']
        duration = flight['Duration']
        is_long_haul = duration > 360
        
        # Check crew assignments
        required_pilots = 3 if is_long_haul else 2
        required_stewards = 6 if is_long_haul else 3
        
        cursor.execute("""
            SELECT COUNT(DISTINCT Employee_id) as pilot_count
            FROM Pilots_in_flight
            WHERE Flight_number = %s
        """, (flight_number,))
        pilot_result = cursor.fetchone()
        pilot_count = pilot_result['pilot_count'] if pilot_result else 0
        
        cursor.execute("""
            SELECT COUNT(DISTINCT Employee_id) as steward_count
            FROM Stewards_in_flight
            WHERE Flight_number = %s
        """, (flight_number,))
        steward_result = cursor.fetchone()
        steward_count = steward_result['steward_count'] if steward_result else 0
        
        # If crew is incomplete, auto-cancel the flight
        if pilot_count < required_pilots or steward_count < required_stewards:
            # Cancel active bookings (system cancellation, not customer)
            cursor.execute("""
                UPDATE Booking
                SET Booking_status = 'SYSTEM_CANCELLED'
                WHERE Flight_number = %s
                AND Booking_status = 'ACTIVE'
            """, (flight_number,))
            
            # Remove crew assignments
            cursor.execute("DELETE FROM Pilots_in_flight WHERE Flight_number = %s", (flight_number,))
            cursor.execute("DELETE FROM Stewards_in_flight WHERE Flight_number = %s", (flight_number,))
            
            # Zero out pricing
            cursor.execute("""
                UPDATE Flight_pricing
                SET Price = 0
                WHERE Flight_number = %s
            """, (flight_number,))
            
            # Mark flight as cancelled
            cursor.execute("""
                UPDATE Flight
                SET Flight_status = 'CANCELLED'
                WHERE Flight_number = %s
            """, (flight_number,))
    
    # Then, update flights that have landed (past their arrival time)
    cursor.execute("""
        UPDATE Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        SET f.Flight_status = 'LANDED'
        WHERE
            f.Flight_status = 'ACTIVE'
            AND TIMESTAMP(f.Departure_date, f.Departure_time)
                + INTERVAL fr.Duration MINUTE
                < NOW()
    """)

    conn.commit()
    cursor.close()
    conn.close()

def update_booking_status():
    # runs periodically to update booking status based on current time
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE Booking b
        JOIN Flight f ON b.Flight_number = f.Flight_number
        SET b.Booking_status = 'COMPLETED'
        WHERE
            f.Flight_status = 'LANDED'
    """)

    conn.commit()
    cursor.close()
    conn.close()

def get_available_planes(flight_number):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT f.Flight_number, f.Departure_date, f.Departure_time, f.Flight_status,
               fr.Duration, fr.Origin_airport, fr.Destination_airport
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    flight = cursor.fetchone()
    if not flight:
        cursor.close(); conn.close()
        return []

    dep_time = (datetime.min + flight['Departure_time']).time()
    dep_dt = datetime.combine(flight['Departure_date'], dep_time)
    arr_dt = dep_dt + timedelta(minutes=flight['Duration'])

    origin = flight['Origin_airport']
    dest   = flight['Destination_airport']
    long_haul = flight['Duration'] > 360

    query = """
    SELECT p.Plane_id, p.Manufacturer, p.Size
    FROM Plane p
    WHERE 1=1

      -- 1) אין חפיפה בזמן עם טיסות אחרות (לא מבוטלות)
      AND NOT EXISTS (
        SELECT 1
        FROM Flight f2
        JOIN Flying_route fr2 ON fr2.Route_id = f2.Route_id
        WHERE f2.Plane_id = p.Plane_id
          AND f2.Flight_number <> %s
          AND f2.Flight_status <> 'CANCELLED'
          AND TIMESTAMP(f2.Departure_date, f2.Departure_time) < %s
          AND TIMESTAMP(f2.Departure_date, f2.Departure_time) + INTERVAL fr2.Duration MINUTE > %s
      )

      -- 2) המטוס חייב להיות ב-Origin בזמן dep_dt (לפי הטיסה האחרונה שנחתה לפני dep_dt)
      AND (
        NOT EXISTS (
          SELECT 1
          FROM Flight fprev
          JOIN Flying_route frprev ON frprev.Route_id = fprev.Route_id
          WHERE fprev.Plane_id = p.Plane_id
            AND fprev.Flight_number <> %s
            AND fprev.Flight_status <> 'CANCELLED'
            AND TIMESTAMP(fprev.Departure_date, fprev.Departure_time) + INTERVAL frprev.Duration MINUTE <= %s
        )
        OR (
          SELECT frprev.Destination_airport
          FROM Flight fprev
          JOIN Flying_route frprev ON frprev.Route_id = fprev.Route_id
          WHERE fprev.Plane_id = p.Plane_id
            AND fprev.Flight_number <> %s
            AND fprev.Flight_status <> 'CANCELLED'
            AND TIMESTAMP(fprev.Departure_date, fprev.Departure_time) + INTERVAL frprev.Duration MINUTE <= %s
          ORDER BY TIMESTAMP(fprev.Departure_date, fprev.Departure_time) + INTERVAL frprev.Duration MINUTE DESC
          LIMIT 1
        ) = %s
      )

      -- 3) אם יש טיסה עתידית אחרי arr_dt, היא חייבת לצאת מ-dest (כדי שהשרשרת הגיונית)
      AND (
        NOT EXISTS (
          SELECT 1
          FROM Flight fnext
          WHERE fnext.Plane_id = p.Plane_id
            AND fnext.Flight_number <> %s
            AND fnext.Flight_status <> 'CANCELLED'
            AND TIMESTAMP(fnext.Departure_date, fnext.Departure_time) >= %s
        )
        OR (
          SELECT frnext.Origin_airport
          FROM Flight fnext
          JOIN Flying_route frnext ON frnext.Route_id = fnext.Route_id
          WHERE fnext.Plane_id = p.Plane_id
            AND fnext.Flight_number <> %s
            AND fnext.Flight_status <> 'CANCELLED'
            AND TIMESTAMP(fnext.Departure_date, fnext.Departure_time) >= %s
          ORDER BY TIMESTAMP(fnext.Departure_date, fnext.Departure_time) ASC
          LIMIT 1
        ) = %s
      )
    """

    params = [
        flight_number, arr_dt, dep_dt,       # overlap
        flight_number, dep_dt,               # prev exists
        flight_number, dep_dt, origin,       # prev destination
        flight_number, arr_dt,               # next exists
        flight_number, arr_dt, dest          # next origin
    ]

    if long_haul:
        query += "\nAND p.Size = 'LARGE'"

    cursor.execute(query, params)
    results = cursor.fetchall()

    cursor.close()
    conn.close()
    return results



# In get_available_staff:
def get_available_staff(flight_number, employee_table, assignment_table, extra_conditions="", pending_flight=None):
    """Return staff members not assigned to conflicting flights and located at the origin.
    
    Args:
        flight_number: Flight ID (None if using pending_flight)
        employee_table: 'Pilot' or 'Steward'
        assignment_table: 'Pilots_in_flight' or 'Stewards_in_flight'
        extra_conditions: Additional WHERE conditions (e.g., long haul qualification)
        pending_flight: Dict with pending flight data (duration, origin, etc.) if flight not yet in DB
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Handle pending flight (not yet in database)
    if flight_number is None and pending_flight:
        from datetime import datetime, timedelta, time
        
        # Get flight details from pending_flight dict
        dep_date = datetime.fromisoformat(pending_flight['departure_date']).date()
        dep_time = time.fromisoformat(pending_flight['departure_time'])
        dep_dt = datetime.combine(dep_date, dep_time)
        arr_dt = dep_dt + timedelta(minutes=pending_flight['duration'])
        origin = pending_flight['origin']
    else:
        # Get flight details from database
        query = """
            SELECT f.*, fr.*
            FROM Flight f
            JOIN Flying_route fr ON f.Route_id = fr.Route_id
            WHERE f.Flight_number = %s
        """
        cursor.execute(query, (flight_number,))
        flight = cursor.fetchone()
        
        if not flight:
            cursor.close()
            conn.close()
            return []
        
        # defining departure and arrival datetimes
        dep_time_td = flight['Departure_time']   # timedelta
        dep_time = (datetime.min + dep_time_td).time()

        dep_dt = datetime.combine(
            flight['Departure_date'],
            dep_time
        )

        arr_dt = dep_dt + timedelta(minutes=flight['Duration'])
        origin = flight['Origin_airport']

    query = f"""
        SELECT e.Employee_id,
               e.Hebrew_first_name,
               e.Hebrew_last_name
        FROM {employee_table} e
        WHERE 1=1
        {extra_conditions}
        AND e.Employee_id NOT IN (
            SELECT a.Employee_id
            FROM {assignment_table} a
            JOIN Flight f2 ON a.Flight_number = f2.Flight_number
            JOIN Flying_route fr2 ON f2.Route_id = fr2.Route_id
            WHERE
                TIMESTAMP(f2.Departure_date, f2.Departure_time) < %s
            AND TIMESTAMP(f2.Departure_date, f2.Departure_time)
                + INTERVAL fr2.Duration MINUTE > %s
        )
        AND (
            -- Last flight before dep_dt landed at origin (or no previous flight)
            (SELECT fr2.Destination_airport
             FROM {assignment_table} a2
             JOIN Flight f2 ON a2.Flight_number = f2.Flight_number
             JOIN Flying_route fr2 ON f2.Route_id = fr2.Route_id
             WHERE a2.Employee_id = e.Employee_id
             AND TIMESTAMP(f2.Departure_date, f2.Departure_time) < %s
             ORDER BY TIMESTAMP(f2.Departure_date, f2.Departure_time) DESC
             LIMIT 1) IS NULL
            OR
            (SELECT fr2.Destination_airport
             FROM {assignment_table} a2
             JOIN Flight f2 ON a2.Flight_number = f2.Flight_number
             JOIN Flying_route fr2 ON f2.Route_id = fr2.Route_id
             WHERE a2.Employee_id = e.Employee_id
             AND TIMESTAMP(f2.Departure_date, f2.Departure_time) < %s
             ORDER BY TIMESTAMP(f2.Departure_date, f2.Departure_time) DESC
             LIMIT 1) = %s
        )
    """

    cursor.execute(query, (arr_dt, dep_dt, dep_dt, dep_dt, origin))
    result = cursor.fetchall()

    cursor.close()
    conn.close()
    return result

def get_available_pilots(flight_number, long_haul_required, pending_flight=None):
    condition = ""
    if long_haul_required:
        condition = "AND e.Long_haul_qualified = TRUE"

    return get_available_staff(
        flight_number,
        employee_table="Pilot",
        assignment_table="Pilots_in_flight",
        extra_conditions=condition,
        pending_flight=pending_flight
    )

def get_available_stewards(flight_number, long_haul_required, pending_flight=None):
    condition = ""
    if long_haul_required:
        condition = "AND e.Long_haul_qualified = TRUE"
    return get_available_staff(
        flight_number,
        employee_table="Steward",
        assignment_table="Stewards_in_flight", 
        extra_conditions=condition,
        pending_flight=pending_flight
    )

def is_long_haul_flight(flight_number):
    # Check duration from Flying_route
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT fr.Duration
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    route = cursor.fetchone()
    long_haul_required = route and route['Duration'] > 360
    cursor.close()
    conn.close()
    return long_haul_required

def build_edit_flight_context(flight_number, error=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT f.Flight_number, p.Size, f.Route_id, f.Departure_date, f.Departure_time, f.Flight_status, f.Plane_id AS Plane_id
, fr.Origin_airport, fr.Destination_airport
        FROM Flight f
        JOIN Plane p ON f.Plane_id = p.Plane_id
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    flight = cursor.fetchone()

    if not flight:
        cursor.close()
        conn.close()
        return None
    
    cursor.execute("SELECT 1 FROM Flight_pricing WHERE Flight_number = %s LIMIT 1", (flight_number,))

    flight['economy_price'] = None
    flight['business_price'] = None
    context = {}
    prices_exist = cursor.fetchone() is not None

    cursor.execute("SELECT Route_id, Origin_airport, Destination_airport FROM Flying_route")
    route = cursor.fetchall()

    cursor.execute("SELECT Plane_id, Manufacturer FROM Plane")
    plane = cursor.fetchall()

    cursor.execute("SELECT Employee_id, Hebrew_first_name, Hebrew_last_name FROM Pilot")
    pilots = cursor.fetchall()

    cursor.execute("SELECT Employee_id FROM Pilots_in_flight WHERE Flight_number = %s", (flight_number,))
    assigned_pilots = {row['Employee_id'] for row in cursor.fetchall()}

    cursor.execute("SELECT Employee_id, Hebrew_first_name, Hebrew_last_name FROM Steward")
    stewards = cursor.fetchall()

    cursor.execute("SELECT Employee_id FROM Stewards_in_flight WHERE Flight_number = %s", (flight_number,))
    assigned_stewards = {row['Employee_id'] for row in cursor.fetchall()}

    cursor.execute("SELECT Price, Class_type FROM Flight_pricing WHERE Flight_number = %s", (flight_number,))
    prices = cursor.fetchall()
    for p in prices:
        if p['Class_type'] == 'ECONOMY':
            flight['economy_price'] = p['Price']
        elif p['Class_type'] == 'BUSINESS':
            flight['business_price'] = p['Price']    
    context['can_edit_economy'] = flight['economy_price'] is None
    # Business price can be edited if:
    # 1. It doesn't exist yet, OR
    # 2. It still equals the default 1.5x economy price
    context['can_edit_business'] = True  # Default to allowing edits
    if flight['business_price'] is not None and flight['economy_price'] is not None:
        # Business exists, check if it's still at default multiplier
        expected_business = flight['economy_price'] * Decimal('1.5')
        if flight['business_price'] != expected_business:
            # Business price has been changed from default - lock it
            context['can_edit_business'] = False
    cursor.close()
    conn.close()

    return {
        'flight': flight,
        'routes': route,
        'planes': plane,
        'pilots': pilots,
        'stewards': stewards,
        'assigned_pilots': assigned_pilots,
        'assigned_stewards': assigned_stewards,
        'error': error,
        'context': context,
        'can_edit_economy': context['can_edit_economy'],
        'can_edit_business': context['can_edit_business']
    }

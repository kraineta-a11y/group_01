import mysql.connector as mdb
from datetime import datetime, timedelta

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
    cursor = conn.cursor()

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

def get_available_planes(flight_number):
    """Return planes not assigned to conflicting flights."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get flight details
    query = """
        SELECT f.*, fr.*
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """
    cursor.execute(query, (flight_number,))
    flight = cursor.fetchone()
    # defining departure and arrival datetimes

    dep_time_td = flight['Departure_time']   # timedelta
    dep_time = (datetime.min + dep_time_td).time()
    dep_dt = datetime.combine(
        flight['Departure_date'],
        dep_time
    )

    arr_dt = dep_dt + timedelta(minutes=flight['Duration'])

    query = """
        SELECT p.Plane_id, p.Manufacturer, p.Size
        FROM Plane p
        WHERE p.Plane_id NOT IN (
            SELECT f2.Plane_id
            FROM Flight f2
            JOIN Flying_route fr2 ON f2.Route_id = fr2.Route_id
            WHERE
                TIMESTAMP(f2.Departure_date, f2.Departure_time) < %s
            AND TIMESTAMP(f2.Departure_date, f2.Departure_time)
                + INTERVAL fr2.Duration MINUTE > %s
        )
    """
    cursor.execute(query, (arr_dt, dep_dt))
    results = cursor.fetchall()

    cursor.close()
    conn.close()
    return results

def get_available_staff(flight_number, employee_table, assignment_table, extra_conditions=""):
    """Return staff members not assigned to conflicting flights."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get flight details
    query = """
        SELECT f.*, fr.*
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """
    cursor.execute(query, (flight_number,))
    flight = cursor.fetchone()
    # defining departure and arrival datetimes
    dep_time_td = flight['Departure_time']   # timedelta
    dep_time = (datetime.min + dep_time_td).time()

    dep_dt = datetime.combine(
        flight['Departure_date'],
        dep_time
    )

    arr_dt = dep_dt + timedelta(minutes=flight['Duration'])

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
    """

    cursor.execute(query, (arr_dt, dep_dt))
    result = cursor.fetchall()

    cursor.close()
    conn.close()
    return result

def get_available_pilots(flight_number, long_haul_required):
    condition = ""
    if long_haul_required:
        condition = "AND e.Long_haul_qualified = TRUE"

    return get_available_staff(
        flight_number,
        employee_table="Pilot",
        assignment_table="Pilots_in_flight",
        extra_conditions=condition
    )

def get_available_stewards(flight_number, long_haul_required):
    condition = ""
    if long_haul_required:
        condition = "AND e.Long_haul_qualified = TRUE"
    return get_available_staff(
        flight_number,
        employee_table="Steward",
        assignment_table="Stewards_in_flight", 
        extra_conditions=condition
    )

def is_long_haul_flight(flight_number):
    # Get plane size from DB
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT p.Size 
        FROM Plane p
        JOIN Flight f ON p.Plane_id = f.Plane_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    plane = cursor.fetchone()
    plane_size = plane['Size'] if plane else None
    long_haul_required = plane_size == 'LARGE'
    cursor.close()
    conn.close()
    return long_haul_required

def build_edit_flight_context(flight_number, error=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT f.Flight_number, p.Size, f.Route_id, f.Departure_date, f.Departure_time, f.Flight_status, p.plane_id, fr.Origin_airport, fr.Destination_airport
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
    
    flight['economy_price'] = None
    flight['business_price'] = None

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
        'error': error
    }
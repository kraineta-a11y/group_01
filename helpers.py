from datetime import datetime, timedelta
import string

def time_handle_normalize(departure_time):
    # normalize departure time
    if isinstance(departure_time, str):
        # could be "14:30" or "14:30:00"
        try:
            dep_time = datetime.strptime(departure_time, "%H:%M").time()
        except ValueError:
            dep_time = datetime.strptime(departure_time, "%H:%M:%S").time()
    elif isinstance(departure_time, timedelta):
        dep_time = (datetime.min + departure_time).time()
    else:
        dep_time = departure_time  # already a datetime.time

    return dep_time

def handle_errors(f):
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            from flask import render_template
            return render_template('error.html', error_message=str(e))
    return wrapper

def generate_seats_for_plane(plane_id):
    from database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Check if seats already exist for this plane
    cursor.execute("SELECT 1 FROM Seat WHERE Plane_id = %s LIMIT 1", (plane_id,))
    if cursor.fetchone():
        # Seats already exist, skip
        cursor.close()
        conn.close()
        return
    
    cursor.execute("""
        SELECT Class_type, first_row, last_row, first_col, last_col
        FROM Class
        WHERE Plane_id = %s
    """, (plane_id,))
    classes = cursor.fetchall()

    for c in classes:
        rows = range(c['first_row'], c['last_row'] + 1)

        cols = string.ascii_uppercase[
            string.ascii_uppercase.index(c['first_col']):
            string.ascii_uppercase.index(c['last_col']) + 1
        ]

        for row in rows:
            for col in cols:
                cursor.execute("""
                    INSERT IGNORE INTO Seat (Plane_id, Row_num, Col_num, Class_type)
                    VALUES (%s, %s, %s, %s)
                """, (plane_id, row, col, c['Class_type']))

    conn.commit()
    cursor.close()
    conn.close()

def handle_flight_update(flight_number, request, session):
    from database import get_db_connection
    from flask import redirect, url_for
    from werkzeug.exceptions import abort
    # ---- Parse form inputs ----
    route_id = request.form['route']
    status = request.form['status']
    economy_price = float(request.form['economy_price'])
    business_price = (
        float(request.form['business_price'])
        if 'business_price' in request.form and request.form['business_price']
        else None
    )

    departure_date = datetime.strptime(
        request.form['departure_date'], "%Y-%m-%d"
    ).date()

    time_str = request.form['departure_time']

    try:
        departure_time = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        departure_time = datetime.strptime(time_str, "%H:%M:%S").time()

    dep_dt = datetime.combine(departure_date, departure_time)
    now = datetime.now()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # ---- Cancellation policy ----
        if status == 'SYSTEM_CANCELLED':
            if (dep_dt - now).total_seconds() < 72 * 3600:
                return "Cannot cancel flight within 72 hours of departure."
            status = 'CANCELLED'
            # Cancel active bookings
            cursor.execute("""
                UPDATE Booking
                SET Booking_status = 'SYSTEM_CANCELLED'
                WHERE Flight_number = %s
                  AND Booking_status = 'ACTIVE'
            """, (flight_number,))

            # Remove crew assignments
            cursor.execute("DELETE FROM Pilots_in_flight WHERE Flight_number = %s", (flight_number,))
            cursor.execute("DELETE FROM Stewards_in_flight WHERE Flight_number = %s", (flight_number,))

            # Zero prices
            economy_price = 0
            if business_price is not None:
                business_price = 0

        # ---- Update flight ----
        cursor.execute("""
            UPDATE Flight
            SET Route_id = %s,
                Departure_date = %s,
                Departure_time = %s,
                Flight_status = %s
            WHERE Flight_number = %s
        """, (
            route_id,
            departure_date,
            departure_time,
            status,
            flight_number
        ))

        # ---- Update economy price ----
        cursor.execute("""
            UPDATE Flight_pricing
            SET Price = %s
            WHERE Flight_number = %s
              AND Class_type = 'ECONOMY'
        """, (economy_price, flight_number))

        # ---- Update business price if applicable ----
        if business_price is not None:
            cursor.execute("""
                UPDATE Flight_pricing
                SET Price = %s
                WHERE Flight_number = %s
                  AND Class_type = 'BUSINESS'
            """, (business_price, flight_number))

        conn.commit()

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('edit_flight', flight_number=flight_number))

def handle_crew_update(flight_number, request):
    from database import get_db_connection, is_long_haul_flight, build_edit_flight_context
    from flask import render_template, redirect, url_for
    from werkzeug.exceptions import abort
    pilot_ids = request.form.getlist('pilots')
    steward_ids = request.form.getlist('stewards')

    # Validate flight exists
    if not flight_number:
        abort(400, description="Flight number missing")

    # Determine long/short haul
    long_haul_required = is_long_haul_flight(flight_number)

    # Validate crew size
    if long_haul_required:
        if len(pilot_ids) != 3 or len(steward_ids) != 6:
            context = build_edit_flight_context(
                flight_number,
                error="Long-haul flights require exactly 3 pilots and 6 stewards."
            )
            return render_template('edit_flight.html', **context)
    else:
        if len(pilot_ids) != 2 or len(steward_ids) != 3:
            context = build_edit_flight_context(
                flight_number,
                error="Short-haul flights require exactly 2 pilots and 3 stewards."
            )
            return render_template('edit_flight.html', **context)

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Remove existing assignments
        cursor.execute(
            "DELETE FROM Pilots_in_flight WHERE Flight_number = %s",
            (flight_number,)
        )
        cursor.execute(
            "DELETE FROM Stewards_in_flight WHERE Flight_number = %s",
            (flight_number,)
        )

        # Insert new pilots
        for pid in pilot_ids:
            cursor.execute(
                """
                INSERT INTO Pilots_in_flight (Employee_id, Flight_number)
                VALUES (%s, %s)
                """,
                (flight_number, pid)
            )

        # Insert new stewards
        for sid in steward_ids:
            cursor.execute(
                """
                INSERT INTO Stewards_in_flight (Employee_id, Flight_number)
                VALUES (%s, %s)
                """,
                (flight_number, sid)
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('edit_flight', flight_number=flight_number))
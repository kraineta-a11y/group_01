from flask import Flask, render_template, redirect, request, session
from flask_session import Session
from datetime import timedelta
import random
import os
import mysql.connector as mdb
from flask import url_for
from datetime import datetime, timedelta, time
from decimal import Decimal
from werkzeug.exceptions import abort

from database import *
from helpers import *




application = Flask(__name__)

session_dir = os.path.join(os.getcwd(), "flask_session_data")
if not os.path.exists(session_dir):
    os.makedirs(session_dir)

application.config.update(
    SESSION_TYPE="filesystem",
    SESSION_FILE_DIR=session_dir,
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_REFRESH_EACH_REQUEST=True,
    SESSION_COOKIE_SECURE=True
)

Session(application)


# --- Database connection ---

def handle_flight_update(flight_number):
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


def handle_crew_update(flight_number):
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
                INSERT INTO Pilots_in_flight (Flight_number, Employee_id)
                VALUES (%s, %s)
                """,
                (flight_number, pid)
            )

        # Insert new stewards
        for sid in steward_ids:
            cursor.execute(
                """
                INSERT INTO Stewards_in_flight (Flight_number, Employee_id)
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

import string

def generate_seats_for_plane(plane_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

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
                    INSERT INTO Seat (Plane_id, Row_num, Col_num, Class_type)
                    VALUES (%s, %s, %s, %s)
                """, (plane_id, row, col, c['Class_type']))

    conn.commit()
    cursor.close()
    conn.close()

@handle_errors
@application.route('/admin')
def admin_dashboard():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM Flight ORDER BY Departure_date, Departure_time ASC")
    flights= cursor.fetchall()

    update_flight_status()
    update_booking_status()

    cursor.execute("SELECT * FROM Pilot")
    pilots= cursor.fetchall()

    cursor.execute("SELECT * FROM Steward")
    stewards= cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('admin_dashboard.html', flights=flights, pilots=pilots, stewards=stewards)

# seat generation to insert seats into planes- intended to be used only once to fill in missing data, but wont break if used again. 

@handle_errors
@application.route('/admin/generate_all_seats')
def admin_fix_existing_seats():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    updated_seats = 0

    # 1. Get all planes
    cursor.execute("SELECT Plane_id FROM Plane")
    planes = cursor.fetchall()

    for plane in planes:
        plane_id = plane['Plane_id']

        # 2. Get classes for plane
        cursor.execute("""
            SELECT Class_type, first_row, last_row, first_col, last_col
            FROM Class
            WHERE Plane_id = %s
        """, (plane_id,))
        classes = cursor.fetchall()

        # 3. Update existing Seat table with correct class_type
        for cls in classes:
            class_type = cls['Class_type']

            for row in range(cls['first_row'], cls['last_row'] + 1):
                for col_ord in range(ord(cls['first_col']), ord(cls['last_col']) + 1):
                    col = chr(col_ord)

                    cursor.execute("""
                        UPDATE Seat
                        SET Class_type = %s
                        WHERE Plane_id = %s
                          AND Row_num = %s
                          AND Col_num = %s
                          AND (Class_type IS NULL OR Class_type != %s)
                    """, (class_type, plane_id, row, col, class_type))

                    updated_seats += cursor.rowcount

    conn.commit()
    cursor.close()
    conn.close()

    return f"Done. Seats updated: {updated_seats}"
# admin reports

@handle_errors
@application.route('/admin/reports')
def admin_reports():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Example report: Flight counts by status
    cursor.execute("""
        SELECT AVG(t.occupancy_pct) AS avg_occupancy_pct
        FROM (
            SELECT
                f.Flight_number,
                100.0 * SUM(CASE WHEN s.Availability = 0 THEN 1 ELSE 0 END)
                    / NULLIF(COUNT(s.Plane_id), 0) AS occupancy_pct
            FROM Flight f
            LEFT JOIN Seats_in_flight s
            ON f.Flight_number = s.Flight_number
            AND f.Plane_id     = s.Plane_id
            WHERE f.Flight_status = 'LANDED'
            GROUP BY f.Flight_number
        ) AS t;
    """)
    results = cursor.fetchall()
    avg_taken_seats = float(results[0]['avg_occupancy_pct']) if results else 0

    cursor.execute("""
SELECT
    COALESCE(SUM(
        CASE
            WHEN sio.Booking_number IS NULL THEN 0
            WHEN b.Booking_status = 'CUSTOMER_CANCELLED' THEN fp.Price * 0.05
            ELSE fp.Price
        END
    ), 0) AS price,
    p.Size,
    p.Manufacturer,
    c.Class_type
FROM Flight f
JOIN Plane p
  ON p.Plane_id = f.Plane_id
JOIN Class c
  ON c.Plane_id = f.Plane_id

LEFT JOIN (
    SELECT Flight_number, Plane_id, Class_type, MAX(Price) AS Price
    FROM Flight_pricing
    GROUP BY Flight_number, Plane_id, Class_type
) fp
  ON fp.Flight_number = f.Flight_number
 AND fp.Plane_id     = f.Plane_id
 AND fp.Class_type   = c.Class_type

LEFT JOIN Booking b
  ON b.Flight_number = f.Flight_number
 AND b.Booking_status IN ('ACTIVE', 'COMPLETED', 'CUSTOMER_CANCELLED')

LEFT JOIN Seats_in_order sio
  ON sio.Booking_number = b.Booking_number
 AND sio.Plane_id       = f.Plane_id
 AND sio.row_num BETWEEN c.first_row AND c.last_row
 AND sio.col_num BETWEEN c.first_col AND c.last_col

WHERE f.Flight_status IN ('LANDED', 'FULLY BOOKED', 'ACTIVE')
GROUP BY p.Size, p.Manufacturer, c.Class_type;""")
    
    money_intake = cursor.fetchall()

    cursor.execute("""
SELECT
    p.Employee_id,
    'PILOT' AS role,
    COALESCE(SUM(CASE
        WHEN fr.Duration <= 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_short_duration,
    COALESCE(SUM(CASE
        WHEN fr.Duration > 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_long_duration
FROM Pilot p
LEFT JOIN Pilots_in_flight pif
    ON pif.Employee_id = p.Employee_id
LEFT JOIN Flight f
    ON f.Flight_number = pif.Flight_number
   AND f.Flight_status = 'LANDED'
LEFT JOIN Flying_route fr
    ON fr.Route_id = f.Route_id
GROUP BY p.Employee_id

UNION ALL

SELECT
    s.Employee_id,
    'STEWARD' AS role,
    COALESCE(SUM(CASE
        WHEN fr.Duration <= 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_short_duration,
    COALESCE(SUM(CASE
        WHEN fr.Duration > 360 THEN fr.Duration / 60.0
        ELSE 0
    END), 0) AS sum_long_duration
FROM Steward s
LEFT JOIN Stewards_in_flight sif
    ON sif.Employee_id = s.Employee_id
LEFT JOIN Flight f
    ON f.Flight_number = sif.Flight_number
   AND f.Flight_status = 'LANDED'
LEFT JOIN Flying_route fr
    ON fr.Route_id = f.Route_id
GROUP BY s.Employee_id;
""")
    
    staff_flight_hours = cursor.fetchall()
    cursor.close()
    conn.close()


    return render_template(
        'reports.html',
        avg_taken_seats=avg_taken_seats,
        money_intake=money_intake,
        staff_flight_hours=staff_flight_hours
    )

# Admin add planes

@handle_errors
@application.route('/admin/add_plane', methods=['GET', 'POST'])
def add_plane():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    if request.method == 'POST':
        manufacturer = request.form['manufacturer']
        size = request.form['size']

        # שומרים זמנית עד שלב המחלקות
        session['pending_plane'] = {
            'manufacturer': manufacturer,
            'size': size
        }

        return redirect(url_for('add_classes'))

    return render_template('add_plane.html')

import string
import mysql.connector as mdb
from datetime import datetime

@handle_errors
@application.route('/admin/add_plane/classes', methods=['GET', 'POST'])
def add_classes():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    pending = session.get('pending_plane')
    if not pending:
        return redirect(url_for('add_plane'))

    size = pending['size']

    def seats_count(first_row, last_row, first_col, last_col, class_name):
        if first_row <= 0 or last_row <= 0:
            return None, f"{class_name}: rows must be positive."
        if last_row < first_row:
            return None, f"{class_name}: last row must be >= first row."

        first_col = (first_col or "").strip().upper()
        last_col  = (last_col  or "").strip().upper()

        if len(first_col) != 1 or len(last_col) != 1:
            return None, f"{class_name}: seat columns must be a single letter (A-Z)."
        if first_col not in string.ascii_uppercase or last_col not in string.ascii_uppercase:
            return None, f"{class_name}: seat columns must be A-Z (English letters only)."
        if last_col < first_col:
            return None, f"{class_name}: last column must be >= first column."

        rows = last_row - first_row + 1
        cols = ord(last_col) - ord(first_col) + 1
        return rows * cols, None

    if request.method == 'POST':
        # ---- parse ----
        if size == 'LARGE':
            bus_first_row = int(request.form['bus_first_row'])
            bus_last_row  = int(request.form['bus_last_row'])
            bus_first_col = request.form['bus_first_col']
            bus_last_col  = request.form['bus_last_col']

        eco_first_row = int(request.form['eco_first_row'])
        eco_last_row  = int(request.form['eco_last_row'])
        eco_first_col = request.form['eco_first_col']
        eco_last_col  = request.form['eco_last_col']

        # ---- validate economy ----
        eco_cnt, err = seats_count(eco_first_row, eco_last_row, eco_first_col, eco_last_col, "Economy Class")
        if err:
            return render_template('add_plane_classes.html', size=size, error=err)

        # ---- validate business + overlap ----
        bus_cnt = 0
        if size == 'LARGE':
            bus_cnt, err = seats_count(bus_first_row, bus_last_row, bus_first_col, bus_last_col, "Business Class")
            if err:
                return render_template('add_plane_classes.html', size=size, error=err)

            overlap = not (bus_last_row < eco_first_row or eco_last_row < bus_first_row)
            if overlap:
                return render_template(
                    'add_plane_classes.html',
                    size=size,
                    error="Business and Economy rows overlap. Please set non-overlapping row ranges."
                )

        total_seats = eco_cnt + bus_cnt
        class_num = 2 if size == 'LARGE' else 1

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            conn.start_transaction()

            # plane_id חדש רק אחרי שהכל תקין
            cursor.execute("SELECT MAX(Plane_id) AS max_num FROM Plane")
            max_plane = cursor.fetchone()
            plane_id = (max_plane['max_num'] or 0) + 1

            # INSERT Plane (כאן ורק כאן)
            cursor.execute("""
                INSERT INTO Plane (Plane_id, Manufacturer, Size, Purchase_date, Number_of_classes, Number_of_seats)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (plane_id, pending['manufacturer'], size, datetime.now().date(), class_num, total_seats))

            # INSERT Classes
            cursor.execute("""
                INSERT INTO Class (Plane_id, Class_type, first_row, last_row, first_col, last_col)
                VALUES (%s, 'ECONOMY', %s, %s, %s, %s)
            """, (plane_id, eco_first_row, eco_last_row, eco_first_col.strip().upper(), eco_last_col.strip().upper()))

            if size == 'LARGE':
                cursor.execute("""
                    INSERT INTO Class (Plane_id, Class_type, first_row, last_row, first_col, last_col)
                    VALUES (%s, 'BUSINESS', %s, %s, %s, %s)
                """, (plane_id, bus_first_row, bus_last_row, bus_first_col.strip().upper(), bus_last_col.strip().upper()))

            conn.commit()

        except mdb.Error as e:
            conn.rollback()
            return render_template('add_plane_classes.html', size=size, error=f"Database error: {e}")

        finally:
            cursor.close()
            conn.close()

        # seats רק אחרי commit
        generate_seats_for_plane(plane_id)

        # מנקים את ההמתנה
        session.pop('pending_plane', None)

        return redirect(url_for('admin_dashboard'))

    return render_template('add_plane_classes.html', size=size)




# Admin employee management 

@handle_errors
@application.route('/admin/employees')
def employees():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified
        FROM Pilot
    """)
    pilots = cursor.fetchall()

    cursor.execute("""
        SELECT Employee_id, Hebrew_first_name, Hebrew_last_name
        FROM Steward
    """)
    stewards = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template(
        'employees.html',
        pilots=pilots,
        stewards=stewards
    )

# Add employees
@handle_errors
@application.route('/admin/employees/add/pilot', methods=['GET', 'POST'])
def add_pilot():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")
    if request.method == 'POST':
        first = request.form['first_name']
        last = request.form['last_name']
        long_haul = 'long_haul' in request.form
        city = request.form['city']
        street = request.form['street']
        house_number = request.form['house_number']
        phone_number = request.form['phone_number']
        zip_code = request.form['zip_code']
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # create pilot id 

        cursor.execute("SELECT MAX(Employee_id) AS max_num FROM Pilot")
        max_pilot = cursor.fetchone()
        if max_pilot['max_num'] is None:
            pilot_id = 1
        else:
            pilot_id = max_pilot['max_num'] + 1
        cursor.execute("""
            INSERT INTO Pilot (Employee_id, Hebrew_first_name, Hebrew_last_name, Added_by_manager_id, City, Street, House_number, Phone_number, Zip_code, Employment_date, Long_haul_qualified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (pilot_id, first, last, session.get('manager_employee_id'), city, street, house_number, phone_number, zip_code, datetime.now().date(), long_haul))
        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('employees'))

    return render_template('add_pilot.html')

@handle_errors
@application.route('/admin/employees/add/steward', methods=['GET', 'POST'])
def add_steward():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")
    if request.method == 'POST':
        first = request.form['first_name']
        last = request.form['last_name']
        city = request.form['city']
        street = request.form['street']
        house_number = request.form['house_number']
        phone_number = request.form['phone_number']
        zip_code = request.form['zip_code']
        long_haul = 'long_haul' in request.form

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # create steward id
        cursor.execute("SELECT MAX(Employee_id) AS max_num FROM Steward")
        max_steward = cursor.fetchone()
        if max_steward['max_num'] is None:
            steward_id = 1
        else:
            steward_id = max_steward['max_num'] + 1

        cursor.execute("""
            INSERT INTO Steward (Employee_id, Hebrew_first_name, Hebrew_last_name, Added_by_manager_id, City, Street, House_number, Phone_number, Zip_code, Employment_date, Long_haul_qualified)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (steward_id, first, last, session.get('manager_employee_id'), city, street, house_number, phone_number, zip_code, datetime.now().date(), long_haul))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('employees'))

    return render_template('add_steward.html')

# Edit employees

import mysql.connector as mdb

import mysql.connector as mdb

@handle_errors
@application.route('/admin/employees/pilots/<int:pilot_id>/edit', methods=['GET', 'POST'])
def edit_pilot(pilot_id):
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if request.method == 'POST':
            first_name = (request.form.get('first_name') or "").strip()
            last_name  = (request.form.get('last_name') or "").strip()

            city         = (request.form.get('city') or "").strip()
            street       = (request.form.get('street') or "").strip()
            house_number = (request.form.get('house_number') or "").strip()
            phone_number = (request.form.get('phone_number') or "").strip()
            zip_code     = (request.form.get('zip_code') or "").strip()
            long_haul    = 1 if 'long_haul' in request.form else 0

            if not first_name or not last_name:
                cursor.execute("""
                    SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                           City, Street, House_number, Phone_number, Zip_code
                    FROM Pilot
                    WHERE Employee_id = %s
                """, (pilot_id,))
                pilot = cursor.fetchone()
                return render_template('edit_pilot.html', pilot=pilot, error="First name and last name are required.")

            cursor.execute("""
                UPDATE Pilot
                SET Hebrew_first_name = %s,
                    Hebrew_last_name  = %s,
                    Long_haul_qualified = %s,
                    City = %s,
                    Street = %s,
                    House_number = %s,
                    Phone_number = %s,
                    Zip_code = %s
                WHERE Employee_id = %s
            """, (first_name, last_name, long_haul, city, street, house_number, phone_number, zip_code, pilot_id))

            conn.commit()
            return redirect(url_for('employees'))

        # GET
        cursor.execute("""
            SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                   City, Street, House_number, Phone_number, Zip_code
            FROM Pilot
            WHERE Employee_id = %s
        """, (pilot_id,))
        pilot = cursor.fetchone()

        if not pilot:
            abort(404, description="Pilot not found")

        return render_template('edit_pilot.html', pilot=pilot)

    except mdb.Error as e:
        conn.rollback()
        cursor.execute("""
            SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                   City, Street, House_number, Phone_number, Zip_code
            FROM Pilot
            WHERE Employee_id = %s
        """, (pilot_id,))
        pilot = cursor.fetchone()
        return render_template('edit_pilot.html', pilot=pilot, error=f"Database error: {e}")

    finally:
        cursor.close()
        conn.close()


import mysql.connector as mdb

import mysql.connector as mdb

@handle_errors
@application.route('/admin/employees/stewards/<int:steward_id>/edit', methods=['GET', 'POST'])
def edit_steward(steward_id):
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    try:
        if request.method == 'POST':
            first_name = (request.form.get('first_name') or "").strip()
            last_name  = (request.form.get('last_name') or "").strip()

            city         = (request.form.get('city') or "").strip()
            street       = (request.form.get('street') or "").strip()
            house_number = (request.form.get('house_number') or "").strip()
            phone_number = (request.form.get('phone_number') or "").strip()
            zip_code     = (request.form.get('zip_code') or "").strip()
            long_haul    = 1 if 'long_haul' in request.form else 0

            if not first_name or not last_name:
                cursor.execute("""
                    SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                           City, Street, House_number, Phone_number, Zip_code
                    FROM Steward
                    WHERE Employee_id = %s
                """, (steward_id,))
                steward = cursor.fetchone()
                return render_template('edit_steward.html', steward=steward, error="First name and last name are required.")

            cursor.execute("""
                UPDATE Steward
                SET Hebrew_first_name = %s,
                    Hebrew_last_name  = %s,
                    Long_haul_qualified = %s,
                    City = %s,
                    Street = %s,
                    House_number = %s,
                    Phone_number = %s,
                    Zip_code = %s
                WHERE Employee_id = %s
            """, (first_name, last_name, long_haul, city, street, house_number, phone_number, zip_code, steward_id))

            conn.commit()
            return redirect(url_for('employees'))

        # GET
        cursor.execute("""
            SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                   City, Street, House_number, Phone_number, Zip_code
            FROM Steward
            WHERE Employee_id = %s
        """, (steward_id,))
        steward = cursor.fetchone()

        if not steward:
            abort(404, description="Steward not found")

        return render_template('edit_steward.html', steward=steward)

    except mdb.Error as e:
        conn.rollback()
        cursor.execute("""
            SELECT Employee_id, Hebrew_first_name, Hebrew_last_name, Long_haul_qualified,
                   City, Street, House_number, Phone_number, Zip_code
            FROM Steward
            WHERE Employee_id = %s
        """, (steward_id,))
        steward = cursor.fetchone()
        return render_template('edit_steward.html', steward=steward, error=f"Database error: {e}")

    finally:
        cursor.close()


# Delete employees

@handle_errors
@application.route('/admin/employees/pilots/<int:pilot_id>/delete', methods=['POST'])
def delete_pilot(pilot_id):
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Block deletion if assigned to flights
    cursor.execute("""
        SELECT 1 FROM Pilots_in_flight
        WHERE Employee_id = %s
        LIMIT 1
    """, (pilot_id,))
    in_use = cursor.fetchone()

    if in_use:
        cursor.close()
        conn.close()
        abort(400, description="Cannot delete pilot assigned to flights")

    cursor.execute("""
        DELETE FROM Pilot WHERE Employee_id = %s
    """, (pilot_id,))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('employees'))

@handle_errors
@application.route('/admin/employees/stewards/<int:steward_id>/delete', methods=['POST'])
def delete_steward(steward_id):
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Block deletion if assigned to flights
    cursor.execute("""
        SELECT 1 FROM Stewards_in_flight
        WHERE Employee_id = %s
        LIMIT 1
    """, (steward_id,))
    in_use = cursor.fetchone()

    if in_use:
        cursor.close()
        conn.close()
        abort(400, description="Cannot delete steward assigned to flights")

    cursor.execute("""
        DELETE FROM Steward WHERE Employee_id = %s
    """, (steward_id,))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('employees'))

# view and manage flights 

@handle_errors
@application.route('/admin/flights', methods=['GET'])
def admin_flights():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    update_flight_status()
    update_booking_status()

    status_filter = (request.args.get('status') or "").strip()  # "" = All

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT
            f.Flight_number,
            fr.Origin_airport,
            fr.Destination_airport,
            COUNT(DISTINCT pf.Employee_id) AS pilot_count,
            COUNT(DISTINCT sf.Employee_id) AS steward_count,
            p.Size,
            COALESCE(NULLIF(TRIM(UPPER(f.Flight_status)), ''), 'ACTIVE') AS Flight_status
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        JOIN Plane p ON f.Plane_id = p.Plane_id
        LEFT JOIN Pilots_in_flight pf ON f.Flight_number = pf.Flight_number
        LEFT JOIN Stewards_in_flight sf ON f.Flight_number = sf.Flight_number
    """

    params = []
    if status_filter != "":
        query += " WHERE TRIM(UPPER(f.Flight_status)) = %s "
        params.append(status_filter.strip().upper())

    query += """
        GROUP BY f.Flight_number, p.Size, fr.Origin_airport, fr.Destination_airport, f.Flight_status
        ORDER BY f.Departure_date, f.Departure_time
    """

    cursor.execute(query, params)
    flights = cursor.fetchall()

    cursor.close()
    conn.close()

    # Crew readiness
    for flight in flights:
        if flight['Size'] == 'LARGE':
            required_pilots, required_stewards = 3, 6
        else:
            required_pilots, required_stewards = 2, 3

        flight['ready'] = (
            flight['pilot_count'] == required_pilots and
            flight['steward_count'] == required_stewards
        )

    status_options = [
        ("", "All"),
        ("ACTIVE", "Active"),
        ("DELAYED", "Delayed"),
        ("LANDED", "Landed"),
        ("CANCELLED", "Cancelled"),
        ("FULLY BOOKED", "Fully Booked"),
    ]

    return render_template(
        'flights.html',
        flights=flights,
        selected_status=status_filter.upper() if status_filter else "",
        status_options=status_options
    )



@handle_errors
@application.route('/admin/flights/<int:flight_number>/edit', methods=['GET', 'POST'])
def edit_flight(flight_number):
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    if request.method == 'POST':
        action = (request.form.get('action') or "").strip()

        # קוראים לפונקציות בלי להעביר request/session
        if action == 'update_flight':
            return handle_flight_update(flight_number)

        if action == 'update_crew':
            return handle_crew_update(flight_number)

        # action לא מוכר -> מחזירים לעמוד עם הודעה במקום קריסה
        context = build_edit_flight_context(flight_number, error="Invalid action submitted.")
        return render_template('edit_flight.html', **context)

    # GET
    context = build_edit_flight_context(flight_number)
    if not context:
        abort(404, description="Flight not found")

    return render_template('edit_flight.html', **context)




@handle_errors
@application.route('/admin/create-flight', methods=['GET', 'POST'])
def admin_create_flight():
    error = None
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # 1. Load Dropdown Data
    cursor.execute("SELECT DISTINCT Origin_airport FROM Flying_route")
    origins = cursor.fetchall()
    cursor.execute("SELECT DISTINCT Destination_airport FROM Flying_route")
    destinations = cursor.fetchall()
    cursor.execute("SELECT Plane_id, Manufacturer FROM Plane")
    planes = cursor.fetchall()

    if request.method == 'POST':
        # 2. Capture Form Data
        origin = request.form['origin']
        destination = request.form['destination']
        plane_id = request.form['plane_id']
        price = request.form['price']
        manager_id = session.get('manager_employee_id', 1) # Fallback ID if session missing

        # 3. Check Route
        cursor.execute("""
            SELECT Route_id, Duration FROM Flying_route
            WHERE Origin_airport = %s AND Destination_airport = %s
        """, (origin, destination))
        route = cursor.fetchone()
        
        if not route:
            cursor.close(); conn.close()
            return render_template('create_flight.html', origins=origins, destinations=destinations, planes=planes, error="No such route exists.")

        route_id = route['Route_id']
        dur = route['Duration']

        # 4. Check Plane Size Suitability
        cursor.execute("SELECT Size FROM Plane WHERE Plane_id = %s", (plane_id,))
        plane_data = cursor.fetchone()
        plane_size = plane_data['Size']

        if plane_size == 'SMALL' and dur > 180:
            cursor.close(); conn.close()
            return render_template('create_flight.html', origins=origins, destinations=destinations, planes=planes, error="Plane too small for long-haul.")

        # 5. Process Date/Time
        dep_date_obj = datetime.strptime(request.form['departure_date'], "%Y-%m-%d").date()
        dep_time_raw = request.form['departure_time']
        
        # Normalize time input
        if isinstance(dep_time_raw, str):
            dep_time_obj = datetime.strptime(dep_time_raw, "%H:%M").time()
        elif isinstance(dep_time_raw, timedelta):
            dep_time_obj = (datetime.min + dep_time_raw).time()
        else:
            dep_time_obj = dep_time_raw

        # Calculate Timestamps
        dep_dt = datetime.combine(dep_date_obj, dep_time_obj)
        arr_dt = dep_dt + timedelta(minutes=dur)

        # ---------------------------------------------------------
        # CHECK 1: TIME AVAILABILITY
        # ---------------------------------------------------------
        # We check if this plane is flying anytime between our Start and End
        time_query = """
            SELECT 1 FROM Flight f
            JOIN Flying_route fr ON f.Route_id = fr.Route_id
            WHERE f.Plane_id = %s
            AND TIMESTAMP(f.Departure_date, f.Departure_time) < %s
            AND ADDTIME(TIMESTAMP(f.Departure_date, f.Departure_time), SEC_TO_TIME(fr.Duration * 60)) > %s
        """
        cursor.execute(time_query, (plane_id, arr_dt, dep_dt))
        if cursor.fetchone():
            cursor.close(); conn.close()
            return render_template('create_flight.html', origins=origins, destinations=destinations, planes=planes, error="Plane is already in the air during this time.")

        # ---------------------------------------------------------
        # CHECK 2: LOCATION CONTINUITY
        # ---------------------------------------------------------
        # Find the very last flight this plane finished BEFORE our new departure
        loc_query = """
            SELECT fr.Destination_airport
            FROM Flight f
            JOIN Flying_route fr ON f.Route_id = fr.Route_id
            WHERE f.Plane_id = %s
            AND TIMESTAMP(f.Departure_date, f.Departure_time) < %s
            ORDER BY TIMESTAMP(f.Departure_date, f.Departure_time) DESC
            LIMIT 1
        """
        cursor.execute(loc_query, (plane_id, dep_dt))
        last_flight = cursor.fetchone()

        # If the plane has flown before, verify it landed at our new Origin
        if last_flight:
            last_location = last_flight['Destination_airport']
            if last_location != origin:
                cursor.close(); conn.close()
                error_msg = f"Logistics Error: Plane is currently at {last_location}, cannot depart from {origin}."
                return render_template('create_flight.html', origins=origins, destinations=destinations, planes=planes, error=error_msg)

        # ---------------------------------------------------------
        # INSERT FLIGHT
        # ---------------------------------------------------------
        cursor.execute("SELECT MAX(Flight_number) AS max_num FROM Flight")
        res = cursor.fetchone()
        flight_number = (res['max_num'] or 0) + 1

        cursor.execute("""
            INSERT INTO Flight (Flight_number, Plane_id, Route_id, Departure_date, Departure_time, Flight_status)
            VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
        """, (flight_number, plane_id, route_id, dep_date_obj, dep_time_obj))

        # Insert Pricing (Economy)
        cursor.execute("""
            INSERT INTO Flight_pricing (Flight_number, Plane_id, Price, Employee_id, Class_type)
            VALUES (%s, %s, %s, %s, 'ECONOMY')
        """, (flight_number, plane_id, price, manager_id))

        # Insert Pricing (Business - Optional)
        if plane_size == 'LARGE':
            cursor.execute("""
                INSERT INTO Flight_pricing (Flight_number, Plane_id, Price, Employee_id, Class_type)
                VALUES (%s, %s, %s, %s, 'BUSINESS')
            """, (flight_number, plane_id, float(price) * 1.5, manager_id))

        # ---------------------------------------------------------
        # GENERATE SEATS
        # ---------------------------------------------------------
        # Helper function to generate seats to avoid duplicate code
        def generate_seats(class_type):
            cursor.execute("""
                SELECT first_row, last_row, first_col, last_col
                FROM Class WHERE Plane_id = %s AND Class_type = %s
            """, (plane_id, class_type))
            seat_conf = cursor.fetchone()
            
            if seat_conf:
                seats_data = []
                for r in range(seat_conf['first_row'], seat_conf['last_row'] + 1):
                    for c_ord in range(ord(seat_conf['first_col']), ord(seat_conf['last_col']) + 1):
                        seats_data.append((flight_number, plane_id, r, chr(c_ord), 1))
                
                if seats_data:
                    cursor.executemany("""
                        INSERT INTO Seats_in_flight (Flight_number, Plane_id, Row_num, Col_num, Availability)
                        VALUES (%s, %s, %s, %s, %s)
                    """, seats_data)

        generate_seats('ECONOMY')
        if plane_size == 'LARGE':
            generate_seats('BUSINESS')

        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for('assign_crew', flight_number=flight_number))

    cursor.close()
    conn.close()
    return render_template('create_flight.html', origins=origins, destinations=destinations, planes=planes, error=error)

@handle_errors
@application.route('/admin/assign_crew', methods=['POST', 'GET'])
def assign_crew():
    error = None

            
    conn = get_db_connection()
    cursor = conn.cursor()
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    if request.method == 'POST':
        action = request.form.get('action')
        flight_number = request.form.get('flight_number')
        
        # --------- DELETE FLOW ----------
        if action == 'delete':
            cursor.execute("DELETE FROM Seats_in_flight WHERE Flight_number=%s", (flight_number,))
            cursor.execute("DELETE FROM Flight_pricing WHERE Flight_number=%s", (flight_number,))
            cursor.execute("DELETE FROM Pilots_in_flight WHERE Flight_number=%s", (flight_number,))
            cursor.execute("DELETE FROM Stewards_in_flight WHERE Flight_number=%s", (flight_number,))
            cursor.execute("DELETE FROM Flight WHERE Flight_number=%s", (flight_number,))
            conn.commit()
            cursor.close()
            conn.close()
            return redirect(url_for('admin_dashboard'))
        
        # ---------- ASSIGN CREW FLOW ----------
        flight_number = request.form.get('flight_number')
        pilots = request.form.getlist('pilots')
        stewards = request.form.getlist('stewards')

        long_haul_required = is_long_haul_flight(flight_number)


        # checking long haul requirements are met
        if long_haul_required:
            if len(pilots) != 3 or len(stewards) != 6:
                cursor.close()
                conn.close()
                error = "Invalid crew assignment for long-haul flight."
                return render_template(
                    'assign_crew.html',
                    flight_number=flight_number,
                    pilots=get_available_pilots(flight_number, long_haul_required),
                    stewards=get_available_stewards(flight_number, long_haul_required),
                    long_haul_required=long_haul_required,
                    error=error
                )
        else:
            if len(pilots) != 2 or len(stewards) != 3:
                cursor.close()
                conn.close()
                error = "Invalid crew assignment for short-haul flight."
                return render_template(
                    'assign_crew.html',
                    flight_number=flight_number,
                    pilots=get_available_pilots(flight_number, long_haul_required),
                    stewards=get_available_stewards(flight_number, long_haul_required),
                    long_haul_required=long_haul_required,
                    error=error
                )

        for pilot_id in pilots:
            cursor.execute("""
                INSERT INTO Pilots_in_flight (Employee_id, Flight_number)
                VALUES (%s, %s)
            """, (pilot_id, flight_number))

        for steward_id in stewards:
            cursor.execute("""
                INSERT INTO Stewards_in_flight (Employee_id, Flight_number)
                VALUES (%s, %s)
            """, (steward_id, flight_number))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('admin_dashboard'))

    # GET — show available staff
    flight_number = request.args.get('flight_number')
    long_haul_required = is_long_haul_flight(flight_number)
    available_pilots = get_available_pilots(flight_number, long_haul_required)
    available_stewards = get_available_stewards(flight_number, long_haul_required)
    if long_haul_required:
        if len(available_pilots) < 3 or len(available_stewards) < 6:
            error = "Not enough available crew members found for this flight."
    else:
        if len(available_pilots) < 2 or len(available_stewards) < 3:
            error = "Not enough available crew members found for this flight."
    return render_template(
        'assign_crew.html',
        flight_number=flight_number,
        pilots=available_pilots,
        stewards=available_stewards,
        long_haul_required=long_haul_required,
        error=error
    )

@handle_errors
@application.route("/")
def landing_page():
    """Landing page route that redirects based on user role."""
    role = get_user_role(session)

    if role == 'manager':
        return redirect(url_for('admin_dashboard'))
    
    # Load airport list for search dropdowns
    update_flight_status()
    update_booking_status()
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT Airport_code FROM Airport")
    airports = cursor.fetchall()

    # Guests and registered clients see search
    return render_template('landing_page.html', role=role, airports=airports)

@handle_errors
@application.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        identifier = request.form['identifier']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check in managers table
        cursor.execute("SELECT * FROM Manager WHERE Employee_id = %s AND Manager_password = %s", (identifier, password))
        manager = cursor.fetchone()
        if manager:
            session['manager_employee_id'] = manager['Employee_id']
            cursor.close()
            conn.close()
            return redirect(url_for('admin_dashboard'))

        # Check in registered table
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s AND Registered_password = %s", (identifier, password))
        client = cursor.fetchone()
        if client:
            session['client_email'] = client['Email']
            cursor.close()
            conn.close()
            return redirect(url_for('landing_page'))

        cursor.close()
        conn.close()
        abort(401, description="Invalid credentials")

    return render_template('login.html')

@handle_errors
@application.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        passport_number = request.form['passport_number']
        birth_date = request.form['birth_date']
        phone_number = request.form['phone_number']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if email exists in registered clients
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            abort(400, description="Email already registered")
        
        #check if email exists in clients
        cursor.execute("SELECT * FROM Client WHERE Email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
        else:
            # Insert Email into Client table
            first_name = name.split()[0]
            last_name = ' '.join(name.split()[1:]) if len(name.split()) > 1 else ''
            cursor.execute(
                "INSERT INTO Client (Email, English_first_name, English_last_name) VALUES (%s, %s, %s)",
                (email, first_name, last_name)
            )
        # Insert new client
        cursor.execute(
            "INSERT INTO Registered_client (Email, Passport_number, Birth_date, Registered_password, Registration_date) VALUES (%s, %s, %s, %s, CURDATE())",
            (email, passport_number, birth_date, password)
        )
        # Insert phone number
        cursor.execute(
            "INSERT INTO Phone_numbers (Email, Phone_number) VALUES (%s, %s)",
            (email, phone_number)
        )
        conn.commit()
        cursor.close()
        conn.close()

        session['client_email'] = email  # log them in immediately
        return redirect(url_for('landing_page'))

    return render_template('register.html')


@handle_errors
@application.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing_page'))

@handle_errors
@application.route('/search', methods=['GET'])
def search():
    if get_user_role(session) == 'manager':
        abort(403, description="Forbidden")
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # load airport list
    cursor.execute("SELECT Airport_code FROM Airport")
    airports = cursor.fetchall()

    origin = request.args.get('origin') 
    destination = request.args.get('destination')
    date = request.args.get('date')

    # Implementing search logic
    query = """
        SELECT *
        FROM Flight AS f
        JOIN Flying_route AS fr ON f.Route_id = fr.Route_id
        JOIN Flight_pricing AS fp 
            ON f.Flight_number = fp.Flight_number 
        AND f.Plane_id = fp.Plane_id
        WHERE f.Flight_status = 'ACTIVE'
    """

    params = []

    if origin:
        query += " AND fr.Origin_airport = %s"
        params.append(origin)

    if destination:
        query += " AND fr.Destination_airport = %s"
        params.append(destination)

    if date:
        query += " AND f.Departure_date = %s"
        params.append(date)

    query += " ORDER BY f.Departure_date, f.Departure_time"

    cursor.execute(query, params)

    flights = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('landing_page.html', role=get_user_role(session), flights=flights, airports=airports)

@handle_errors
@application.route('/flight_view/<int:flight_number>', methods=['GET','POST'])
def flight_view(flight_number):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    class_type = request.args.get('class_type')
    query = """
                SELECT f.* , fr.Origin_airport, fr.Destination_airport, fr.Duration, fp.Price, fp.Class_type
                FROM 
                    Flight as f
                JOIN
                    Flying_route as fr ON f.Route_id = fr.Route_id
                JOIN 
                    Flight_pricing as fp ON f.Flight_number = fp.Flight_number AND f.Plane_id = fp.Plane_id
                WHERE 
                    f.Flight_number = %s
                    AND fp.Class_type = %s
            """
    cursor.execute(query, (flight_number,class_type))
    flights = cursor.fetchone()
    cursor.fetchall()

    # calculate arrival time
    dep_time = time_handle_normalize(flights['Departure_time'])

    dep_dt = datetime.combine(
        flights['Departure_date'],
        dep_time
    )
    session['class'] = class_type
    arr_dt = dep_dt + timedelta(minutes=flights['Duration'])
    flights['Arrival_time'] = arr_dt
    cursor.close()
    conn.close()

    return render_template('flight_view.html', role=get_user_role(session), flight=flights)

@handle_errors
@application.route('/check_out/<int:flight_number>/passengers', methods=['GET', 'POST'])
def passenger_count(flight_number):
    if request.method == 'POST':
        count = int(request.form['passenger_count'])
        # get user
        if get_user_role(session) == 'client':
            email = session.get('client_email')
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT r.Passport_number, r.Birth_date, c.English_first_name, c.English_last_name, p.Phone_number FROM Registered_client AS r JOIN Client AS c ON r.Email = c.Email JOIN Phone_numbers AS r.Email = p.Email WHERE r.Email = %s", (email,))
            user = cursor.fetchone()
            user['type'] = 'ADULT' if (datetime.now().date() - user['Birth_date']).days // 365 < 18 else 'CHILD'
            cursor.close()
            conn.close()
        else:
            user = None
        return redirect(url_for('passenger_details', flight_number=flight_number, count=count, role=get_user_role(session), user=user))

    return render_template('passenger_count.html', flight_number=flight_number)

@handle_errors
@application.route('/checkout/<int:flight_number>/passengers/details', methods=['GET', 'POST'])
def passenger_details(flight_number):
    count = int(request.args.get('count'))
    if count < 1 or count > 7:
        abort(400, description="Invalid passenger count")
    if request.method == 'GET':
        if get_user_role(session) == 'client':
            # Pre-fill with registered client info
            email = session.get('client_email')
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT r.Passport_number, r.Birth_date, c.English_first_name, c.English_last_name, p.Phone_number FROM Registered_client AS r JOIN Client AS c ON r.Email = c.Email JOIN Phone_numbers AS r.Email = p.Email WHERE r.Email = %s", (email,))
            user = cursor.fetchone()
            user['type'] = 'ADULT' if (datetime.now().date() - user['Birth_date']).days // 365 >= 18 else 'CHILD'
            cursor.close()
            conn.close()
            return render_template(
                'passenger_details.html',
                flight_number=flight_number,
                count=count,
                user=user,
                role=get_user_role(session)
            )
    if request.method == 'POST':
        passengers = []
        for i in range(1, count + 1):
            passengers.append({
                "name": request.form[f"name_{i}"],
                "id": request.form[f"id_{i}"],
                "type": request.form[f"type_{i}"],
                "Email": request.form.get(f"email", None),
                "birthdate": request.form.get(f"birthdate", None),
                "phone_number": request.form.get(f"phone_number", None)
            })

        session['passengers'] = passengers
        
        # Disallow proceeding if all passengers are children
        if all(p['type'] == 'CHILD' for p in passengers):
            abort(400, description="At least one adult passenger is required.")
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT Row_num, Col_num, Availability
            FROM Seats_in_flight
            WHERE Flight_number = %s
            ORDER BY Row_num, Col_num
        """, (flight_number,))
        seats = cursor.fetchall()
        cursor.close()
        conn.close()
        return redirect(url_for('seat_selection', flight_number=flight_number, count=count))

    return render_template(
        'passenger_details.html',
        flight_number=flight_number,
        count=count,
        role=get_user_role(session)
    )

from collections import defaultdict

@handle_errors
@application.route('/checkout/<int:flight_number>/passengers/seat_selection', methods=['GET', 'POST'])
def seat_selection(flight_number):
    count = int(request.args.get('count'))
    class_type = session.get('class')
    # helper function to load seats and return them with consistent format
    def load_seat_rows():
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT sif.Row_num, sif.Col_num, sif.Availability
            FROM Seats_in_flight AS sif
            JOIN Seat AS s 
                ON sif.Plane_id = s.Plane_id
                AND sif.Row_num = s.Row_num 
                AND sif.Col_num = s.Col_num
            WHERE sif.Flight_number = %s 
                AND s.Class_type = %s     
            ORDER BY Row_num, Col_num
        """, (flight_number,class_type))
        seats = cursor.fetchall()
        cursor.close()
        conn.close()

        seat_rows = defaultdict(list)
        for seat in seats:
            seat_rows[seat['Row_num']].append(seat)

        return dict(seat_rows)

    if request.method == 'POST':
        selected_seats = []
        for i in range(1, count + 1):
            s = request.form.get(f"seat_{i}")
            if not s: # dont continue if there are no seats
                seats = load_seat_rows()
                return render_template(
                    'seat_selection.html',
                    flight_number=flight_number,
                    seats=seats,
                    count=count,
                    role=get_user_role(session),
                    error="Please choose a seat for every passenger."
                )
            selected_seats.append(s)

        # prevent user from picking the same seat twice
        if len(set(selected_seats)) != len(selected_seats):
            seats = load_seat_rows()
            return render_template(
                'seat_selection.html',
                flight_number=flight_number,
                seats=seats,
                count=count,
                role=get_user_role(session),
                error="You cannot select the same seat more than once. Please choose different seats."
            )

        session['selected_seats'] = selected_seats
        return redirect(url_for('order_summary', flight_number=flight_number))

    # GET
    seats = load_seat_rows()
    return render_template(
        'seat_selection.html',
        flight_number=flight_number,
        seats=seats,
        count=count,
        role=get_user_role(session)
    )


@handle_errors
@application.route('/checkout/<int:flight_number>/summary', methods=['GET', 'POST'])
def order_summary(flight_number):
    passengers = session.get('passengers')
    seats = session.get('selected_seats')

    if not passengers or not seats:
        abort(400, description="Session expired")

    # parse seats
    parsed_seats = []
    for s in seats:
        row = int(s[:-1])
        col = s[-1]
        parsed_seats.append({"row": row, "col": col})

    session['selected_seats'] = parsed_seats


    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Flight info + plane id
    cursor.execute("""
        SELECT f.Flight_number, f.Departure_date, f.Departure_time,
               fr.Origin_airport, fr.Destination_airport,
               f.Plane_id
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    flight = cursor.fetchone()

    if not flight:
        cursor.close()
        conn.close()
        abort(404, description="Flight not found")

    plane_id = flight['Plane_id']

    # Prices per seat
    total_price = 0
    seat_prices = []

    for seat in parsed_seats:
        cursor.execute("""
            SELECT fp.Price
            FROM Flight_pricing fp
            JOIN Seat s 
              ON fp.Class_type = s.Class_type
             AND s.Plane_id = %s
             AND s.Row_num = %s
             AND s.Col_num = %s
            WHERE fp.Flight_number = %s
                    AND fp.Plane_id = %s
        """, (plane_id, seat['row'], seat['col'], flight_number, plane_id))

        row = cursor.fetchone()
        price = row['Price'] if row else 0

        total_price += price
        seat_prices.append(price)

    cursor.close()
    conn.close()

    if request.method == 'POST':
        return redirect(url_for('confirm_booking', flight_number=flight_number))

    return render_template(
        'order_summary.html',
        flight=flight,
        passengers=passengers,
        seats=parsed_seats,
        seat_prices=seat_prices,
        total_price=total_price,
        role=get_user_role(session),
        flight_number=flight_number
    )

@handle_errors
@application.route('/checkout/<int:flight_number>/confirm', methods=['POST'])
def confirm_booking(flight_number):
    passengers = session['passengers']
    seats = session['selected_seats']

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create booking
    if get_user_role(session) == 'client':
        email = session.get('client_email')
    else:
        email = passengers[0]['Email']  # Use first passenger's email for guest bookings
        phone_number = passengers[0]['phone_number']
        # Enter into Client table if not exists
        cursor.execute("SELECT 1 FROM Client WHERE Email = %s", (email,))
        if not cursor.fetchone():
            first_name = passengers[0]['name'].split()[0]
            last_name = ' '.join(passengers[0]['name'].split()[1:]) if len(passengers[0]['name'].split()) > 1 else ''
            cursor.execute(
                "INSERT INTO Client (Email, English_first_name, English_last_name) VALUES (%s, %s, %s)",
                (email, first_name, last_name)
            )
            cursor.exectue(
                "INSERT INTO Phone_numbers (Email, Phone_number) VALUES (%s, %s)",
                (email,phone_number)
            )
    # generate booking number
    cursor.execute("SELECT MAX(Booking_number) FROM Booking")
    max_booking = cursor.fetchone()[0]
    booking_number = max_booking + 1 if max_booking else 1
    # Insert booking
    cursor.execute("""
        INSERT INTO Booking (Flight_number, Email, Booking_number, Booking_date, Booking_status, Number_of_tickets, Passport_number, Birth_date)
        VALUES (%s, %s, %s, CURDATE(), 'ACTIVE', %s, %s, %s)
    """, (flight_number, email, booking_number, len(passengers), passengers[0]['id'], passengers[0]['birthdate']))
    Booking_number = booking_number
    # Assign seats + mark unavailable
    for s in seats:
        cursor.execute("""
            UPDATE Seats_in_flight
            SET Availability = 0
            WHERE Flight_number = %s
              AND Row_num = %s
              AND Col_num = %s
        """, (flight_number, s['row'], s['col']))
        # Insert into Seats_in_order
        cursor.execute("""
            INSERT INTO Seats_in_order (Booking_number, Plane_id, Row_num, Col_num)
            VALUES (%s,
                (SELECT Plane_id FROM Flight WHERE Flight_number = %s),
                %s, %s)
        """, (Booking_number, flight_number, s['row'], s['col']))

    conn.commit()
    cursor.close()
    conn.close()

    session.pop('passengers')
    session.pop('selected_seats')

    return redirect(url_for('booking_success', Booking_number=Booking_number))

@handle_errors
@application.route('/booking/success/<int:Booking_number>')
def booking_success(Booking_number):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.Booking_number, f.Flight_number,
               fr.Origin_airport, fr.Destination_airport,
               f.Departure_date, f.Departure_time
        FROM Booking b
        JOIN Flight f ON b.Flight_number = f.Flight_number
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        WHERE b.Booking_number = %s
    """, (Booking_number,))
    booking = cursor.fetchone()

    cursor.close()
    conn.close()

    if not booking:
        abort(404, description="Booking not found")

    return render_template(
        'booking_success.html',
        booking=booking,
        role=get_user_role(session)
    )

# Manage bookings

@handle_errors
@application.route('/manage-booking', methods=['GET', 'POST'])
def manage_booking():
    if request.method == 'GET':
        return render_template('manage_booking.html', role=get_user_role(session))

    # POST
    if get_user_role(session) == 'client':
        email = session.get('client_email')
        return redirect(url_for('manage_booking_result', method='registered', email=email))

    # guest
    booking_number = request.form.get('booking_number')
    passport_number = request.form.get('passport_number')
    return redirect(url_for('manage_booking_result',
                            method='guest',
                            booking_number=booking_number,
                            passport_number=passport_number))

@handle_errors
@application.route('/manage-booking/result')
def manage_booking_result():
    method = request.args.get('method')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if method == 'registered':
        email = request.args.get('email')
        cursor.execute("""
            SELECT *
            FROM Booking
            WHERE Email = %s
            ORDER BY Booking_date DESC
        """, (email,))
        bookings = cursor.fetchall()
    else:
        booking_number = request.args.get('booking_number')
        passport_number = request.args.get('passport_number')

        cursor.execute("""
            SELECT *
            FROM Booking
            WHERE Booking_number = %s
              AND Passport_number = %s
        """, (booking_number, passport_number))
        bookings = cursor.fetchall()

    if not bookings:
        cursor.close()
        conn.close()
        abort(404, description="No bookings found")

    # load seats
    for b in bookings:
        cursor.execute("""
            SELECT Row_num, Col_num
            FROM Seats_in_order
            WHERE Booking_number = %s
        """, (b['Booking_number'],))
        b['seats'] = cursor.fetchall()

    # load seat prices
    for b in bookings:
        cursor.execute("""
            SELECT fp.Price, c.Class_type, f.Departure_date, f.Departure_time,
                fr.Origin_airport, fr.Destination_airport
            FROM Seats_in_order s
            JOIN Booking b ON b.Booking_number = s.Booking_number
            JOIN Flight f ON f.Flight_number = b.Flight_number
            JOIN Flying_route fr ON f.Route_id = fr.Route_id
            JOIN Class c ON c.Plane_id = f.Plane_id
                        AND s.Row_num BETWEEN c.first_row AND c.last_row
                        AND s.Col_num BETWEEN c.first_col AND c.last_col
            JOIN Flight_pricing fp ON fp.Flight_number = f.Flight_number
                                AND fp.Class_type = c.Class_type
                                AND fp.Plane_id = f.Plane_id
            WHERE s.Booking_number = %s
        """, (b['Booking_number'],))
        prices = cursor.fetchall()
        if not prices:
            b['flight_info'] = None
            b['seat_prices'] = []
        else:
            b['flight_info'] = {
                'Departure_date': prices[0]['Departure_date'],
                'Departure_time': prices[0]['Departure_time'],
                'Origin_airport': prices[0]['Origin_airport'],
                'Destination_airport': prices[0]['Destination_airport']
            }
            b['error'] = None
            b['seat_prices'] = prices

        for p in prices:
            b['price'] = p['Price']
        total_price = sum(p['Price'] for p in prices)
        if b['Booking_status'] != 'ACTIVE':
            cursor.execute("""
                SELECT f.Departure_date, f.Departure_time,
                    fr.Origin_airport, fr.Destination_airport, fp.Price
                FROM Flight f
                JOIN Flying_route fr ON f.Route_id = fr.Route_id
                JOIN Flight_pricing fp on f.Flight_number = fp.Flight_number
                WHERE f.Flight_number = %s
            """, (b['Flight_number'],))
            flight = cursor.fetchone()
            cursor.fetchall()
            b['flight_info'] = flight
            total_price = flight['Price']
        # refund logic (unchanged semantics)
        if b['Booking_status'] == 'CUSTOMER_CANCELLED':
            b['refund'] = round(total_price * Decimal(0.05))
        elif b['Booking_status'] == 'SYSTEM_CANCELLED':
            b['refund'] = total_price
        else:
            b['refund'] = 0

        b['total_price'] = total_price

    cursor.close()
    conn.close()

    return render_template(
        'manage_booking_result.html',
        bookings=bookings,
        role=get_user_role(session)
    )


@handle_errors
@application.route('/manage-booking/cancel/<int:booking_number>', methods=['POST'])
def cancel_booking(booking_number):

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.Flight_number,
               f.Departure_date,
               f.Departure_time
        FROM Booking b
        JOIN Flight f ON b.Flight_number = f.Flight_number
        WHERE b.Booking_number = %s
    """, (booking_number,))
    row = cursor.fetchone()

    if not row:
        cursor.close()
        conn.close()
        abort(404, description="Booking not found")

    dep_date = row['Departure_date']
    dep_time_raw = row['Departure_time']

    if isinstance(dep_time_raw, timedelta):
        dep_time = (datetime.min + dep_time_raw).time()
    else:
        dep_time = dep_time_raw  # already a datetime.time

    dep_dt = datetime.combine(dep_date, dep_time)

    now = datetime.now()

    if (dep_dt - now).total_seconds() < 36 * 3600:
        cursor.close()
        conn.close()
        return "Cannot cancel flight within 36 hours of departure."

    flight_number = row['Flight_number']

    # cancel booking
    cursor.execute("""
        UPDATE Booking
        SET Booking_status = 'CUSTOMER_CANCELLED'
        WHERE Booking_number = %s
    """, (booking_number,))

    # free seats
    cursor.execute("""
        SELECT Row_num, Col_num
        FROM Seats_in_order
        WHERE Booking_number = %s
    """, (booking_number,))
    seats = cursor.fetchall()

    for s in seats:
        cursor.execute("""
            UPDATE Seats_in_flight
            SET Availability = 1
            WHERE Flight_number = %s
              AND Row_num = %s
              AND Col_num = %s
        """, (flight_number, s['Row_num'], s['Col_num']))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('manage_booking'))


@application.errorhandler(404)
def invalid_route(e):
    message = getattr(e, 'description', None)
    if message:
        return render_template('error.html', error_message=message), 404
    return redirect("/")


@application.errorhandler(400)
def bad_request(e):
    message = getattr(e, 'description', 'Bad Request')
    return render_template('error.html', error_message=message), 400


@application.errorhandler(403)
def forbidden(e):
    message = getattr(e, 'description', 'Forbidden')
    return render_template('error.html', error_message=message), 403


@application.errorhandler(401)
def unauthorized(e):
    message = getattr(e, 'description', 'Unauthorized')
    return render_template('error.html', error_message=message), 401


@handle_errors
@application.route('/admin/schedules')
def admin_schedules():
    if get_user_role(session) != 'manager':
        abort(403, description="Forbidden")

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Planes schedules
    planes_query = """
        SELECT p.Plane_id, p.Manufacturer, p.Size,
               f.Flight_number, fr.Origin_airport, fr.Destination_airport,
               f.Departure_date, f.Departure_time, f.Flight_status
        FROM Plane p
        LEFT JOIN Flight f ON p.Plane_id = f.Plane_id
        LEFT JOIN Flying_route fr ON f.Route_id = fr.Route_id
        ORDER BY p.Plane_id, f.Departure_date, f.Departure_time
    """
    cursor.execute(planes_query)
    plane_flights = cursor.fetchall()

    # Group by plane
    planes = {}
    for pf in plane_flights:
        pid = pf['Plane_id']
        if pid not in planes:
            planes[pid] = {
                'manufacturer': pf['Manufacturer'],
                'size': pf['Size'],
                'flights': [],
                'current_location': None
            }
        if pf['Flight_number']:
            planes[pid]['flights'].append({
                'flight_number': pf['Flight_number'],
                'origin': pf['Origin_airport'],
                'destination': pf['Destination_airport'],
                'departure_date': pf['Departure_date'],
                'departure_time': pf['Departure_time'],
                'status': pf['Flight_status']
            })

    # Set current location to the destination of the last LANDED flight
    for pid, plane in planes.items():
        landed_flights = [f for f in plane['flights'] if f['status'] == 'LANDED']
        if landed_flights:
            # Since flights are ordered by date, the last one is the most recent
            plane['current_location'] = landed_flights[-1]['destination']

    # For planes without flights, set default location or something, but assume they start somewhere.

    # Pilots schedules
    pilots_query = """
        SELECT p.Employee_id, p.Hebrew_first_name, p.Hebrew_last_name,
               f.Flight_number, fr.Origin_airport, fr.Destination_airport,
               f.Departure_date, f.Departure_time, f.Flight_status
        FROM Pilot p
        LEFT JOIN Pilots_in_flight pif ON p.Employee_id = pif.Employee_id
        LEFT JOIN Flight f ON pif.Flight_number = f.Flight_number
        LEFT JOIN Flying_route fr ON f.Route_id = fr.Route_id
        ORDER BY p.Employee_id, f.Departure_date, f.Departure_time
    """
    cursor.execute(pilots_query)
    pilot_flights = cursor.fetchall()

    pilots = {}
    for pf in pilot_flights:
        eid = pf['Employee_id']
        if eid not in pilots:
            pilots[eid] = {
                'name': f"{pf['Hebrew_first_name']} {pf['Hebrew_last_name']}",
                'flights': []
            }
        if pf['Flight_number']:
            pilots[eid]['flights'].append({
                'flight_number': pf['Flight_number'],
                'origin': pf['Origin_airport'],
                'destination': pf['Destination_airport'],
                'departure_date': pf['Departure_date'],
                'departure_time': pf['Departure_time'],
                'status': pf['Flight_status']
            })

    # Stewards schedules
    stewards_query = """
        SELECT s.Employee_id, s.Hebrew_first_name, s.Hebrew_last_name,
               f.Flight_number, fr.Origin_airport, fr.Destination_airport,
               f.Departure_date, f.Departure_time, f.Flight_status
        FROM Steward s
        LEFT JOIN Stewards_in_flight sif ON s.Employee_id = sif.Employee_id
        LEFT JOIN Flight f ON sif.Flight_number = f.Flight_number
        LEFT JOIN Flying_route fr ON f.Route_id = fr.Route_id
        ORDER BY s.Employee_id, f.Departure_date, f.Departure_time
    """
    cursor.execute(stewards_query)
    steward_flights = cursor.fetchall()

    stewards = {}
    for sf in steward_flights:
        eid = sf['Employee_id']
        if eid not in stewards:
            stewards[eid] = {
                'name': f"{sf['Hebrew_first_name']} {sf['Hebrew_last_name']}",
                'flights': []
            }
        if sf['Flight_number']:
            stewards[eid]['flights'].append({
                'flight_number': sf['Flight_number'],
                'origin': sf['Origin_airport'],
                'destination': sf['Destination_airport'],
                'departure_date': sf['Departure_date'],
                'departure_time': sf['Departure_time'],
                'status': sf['Flight_status']
            })

    cursor.close()
    conn.close()

    return render_template('schedules.html', planes=planes, pilots=pilots, stewards=stewards)


@application.errorhandler(500)
def internal_error(e):
    return render_template('error.html', error_message="Internal Server Error"), 500

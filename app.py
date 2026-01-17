from flask import Flask, render_template, redirect, request, session
from flask_session import Session
from datetime import timedelta
import random
import os
import mysql.connector as mdb
from flask import url_for
from datetime import datetime, timedelta




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
def get_db_connection():
    return mdb.connect(
        host='Netarosh.mysql.pythonanywhere-services.com',
        user='Netarosh',
        password='group01root',
        database='Netarosh$FLYTAU'
    )

def get_user_role():
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
        SELECT f.Flight_number, p.Size, f.Route_id, f.Departure_date, f.Departure_time, f.Flight_status, p.plane_id
        FROM Flight f
        JOIN Plane p ON f.Plane_id = p.Plane_id
        WHERE f.Flight_number = %s
    """, (flight_number,))
    flight = cursor.fetchone()

    if not flight:
        cursor.close()
        conn.close()
        return None

    cursor.execute("SELECT Employee_id, Hebrew_first_name, Hebrew_last_name FROM Pilot")
    pilots = cursor.fetchall()

    cursor.execute("SELECT Employee_id FROM Pilots_in_flight WHERE Flight_number = %s", (flight_number,))
    assigned_pilots = {row['Employee_id'] for row in cursor.fetchall()}

    cursor.execute("SELECT Employee_id, Hebrew_first_name, Hebrew_last_name FROM Steward")
    stewards = cursor.fetchall()

    cursor.execute("SELECT Employee_id FROM Stewards_in_flight WHERE Flight_number = %s", (flight_number,))
    assigned_stewards = {row['Employee_id'] for row in cursor.fetchall()}

    cursor.close()
    conn.close()

    return {
        'flight': flight,
        'pilots': pilots,
        'stewards': stewards,
        'assigned_pilots': assigned_pilots,
        'assigned_stewards': assigned_stewards,
        'error': error
    }
# flight and crew management helpers

def handle_flight_update(flight_number):
    route_id = request.form['origin']
    date = request.form['departure_date']
    time = request.form['departure_time']
    status = request.form['status']

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE Flight
        SET Route_id = %s,
            Departure_date = %s,
            Departure_time = %s,
            Flight_status = %s
        WHERE Flight_number = %s
    """, (route_id, date, time, status, flight_number))

    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for('edit_flight', flight_number=flight_number))

def handle_crew_update(flight_number):
    pilot_ids = request.form.getlist('pilots')
    steward_ids = request.form.getlist('stewards')

    # Validate flight exists
    if not flight_number:
        return "Flight number missing", 400

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

@application.route("/")
def landing_page():
    """Landing page route that redirects based on user role."""
    role = get_user_role()

    if role == 'manager':
        return redirect(url_for('admin_dashboard'))

    # Guests and registered clients see search
    return render_template('landing_page.html', role=role)

@application.route('/admin')
def admin_dashboard():
    if get_user_role() != 'manager':
        return "Forbidden", 403
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM Flight ORDER BY Departure_date, Departure_time ASC")
    flights= cursor.fetchall()

    cursor.execute("SELECT * FROM Pilot")
    pilots= cursor.fetchall()

    cursor.execute("SELECT * FROM Steward")
    stewards= cursor.fetchall()

    cursor.close()
    conn.close()
    return render_template('admin_dashboard.html', flights=flights, pilots=pilots, stewards=stewards)

@application.route('/admin/create_flight', methods=['POST'])
def create_flight():
    manager_id = session['manager_employee_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get form data
    origin = request.form['origin']
    destination = request.form['destination']
    departure_date = request.form['departure_date']
    departure_time = request.form['departure_time']
    price = request.form['price']
    # Get route ID 
    cursor.execute(
        "SELECT Route_id FROM Flying_route WHERE Origin_airport = %s AND Destination_airport = %s",
        (origin, destination)
    )
    route = cursor.fetchone()
    route_id = route['Route_id']
    # Insert flight into database
    cursor.execute(
        "INSERT INTO Flight (Route_id, Origin_airport, Destination_airport, Departure_date, Departure_time, Status) VALUES (%s,%s, %s, %s, %s, 'ACTIVE')",
        (route_id, origin, destination, departure_date, departure_time)
    )
    flight_number = cursor.lastrowid
    # Insert flight pricing
    cursor.execute(
        "INSERT INTO Flight_pricing (Employee_id, Flight_number, Price) VALUES (%s, %s, %s)",
        (manager_id, flight_number, price)
    )
    conn.commit()
    
    cursor.close()
    conn.close()

@application.route('/admin/flights', methods=['GET'])
def admin_flights(): # View and manage flights
    if get_user_role() != 'manager':
        return "Forbidden", 403
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    query = """
        SELECT
            f.Flight_number,
            fr.Origin_airport,
            fr.Destination_airport,
            COUNT(DISTINCT pf.Employee_id) AS pilot_count,
            COUNT(DISTINCT sf.Employee_id) AS steward_count,
            p.Size
        FROM Flight f
        JOIN Flying_route fr ON f.Route_id = fr.Route_id
        JOIN Plane p ON f.Plane_id = p.Plane_id
        LEFT JOIN Pilots_in_flight pf ON f.Flight_number = pf.Flight_number
        LEFT JOIN Stewards_in_flight sf ON f.Flight_number = sf.Flight_number
        GROUP BY f.Flight_number, p.Size, fr.Origin_airport, fr.Destination_airport
    """

    cursor.execute(query)
    flights = cursor.fetchall()

    cursor.close()
    conn.close()

    for flight in flights:
        if flight['Size'] == 'LARGE':
            required_pilots = 3
            required_stewards = 6
        else:
            required_pilots = 2
            required_stewards = 3

        flight['ready'] = (
            flight['pilot_count'] == required_pilots and
            flight['steward_count'] == required_stewards
        )

    return render_template('flights.html', flights=flights)

@application.route('/admin/flights/<int:flight_number>/edit', methods=['GET', 'POST'])
def edit_flight(flight_number):
    if get_user_role() != 'manager':
        return "Forbidden", 403

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'update_flight':
            return handle_flight_update(flight_number)

        if action == 'update_crew':
            return handle_crew_update(flight_number)

    context = build_edit_flight_context(flight_number)
    if not context:
        return "Flight not found", 404

    return render_template('edit_flight.html', **context)

@application.route('/admin/add_staff', methods=['POST'])
def add_staff():
    if get_user_role() != 'manager':
        return "Forbidden", 403
    manager_id = session['manager_employee_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get form data
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']
    employee_id = request.form['employee_id']
    role = request.form['role']
    first_name = name.split()[0]
    last_name = ' '.join(name.split()[1:]) if len(name.split()) > 1 else ''

    # Insert staff into database based on role
    cursor.execute(
        "INSERT INTO {role} (Employee_id, Added_by_manager_id, Hebrew_first_name, Hebrew_last_name, Employment_date) VALUES (%s, %s, %s, %s, %s)".format(role=role),
        (employee_id, manager_id, first_name, last_name, datetime.now().date())
    )
    conn.commit()

    cursor.close()
    conn.close()    

@application.route('/admin/create-flight', methods=['GET', 'POST'])
def admin_create_flight():

    error = None
    if get_user_role() != 'manager':
        return "Forbidden", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Load airports for dropdowns
    cursor.execute("SELECT DISTINCT Origin_airport FROM Flying_route")
    origins = cursor.fetchall()

    cursor.execute("SELECT DISTINCT Destination_airport FROM Flying_route")
    destinations = cursor.fetchall()

    cursor.execute("SELECT Plane_id, Manufacturer FROM Plane")
    planes = cursor.fetchall()

    if request.method == 'POST':
        origin = request.form['origin']
        destination = request.form['destination']
        departure_date = request.form['departure_date']
        departure_time = request.form['departure_time']
        plane_id = request.form['plane_id']
        price = request.form['price']
        manager_id = session['manager_employee_id']

        # Find route
        cursor.execute("""
            SELECT Route_id, Duration
            FROM Flying_route
            WHERE Origin_airport = %s AND Destination_airport = %s
        """, (origin, destination))

        route = cursor.fetchone()
        dur = route['Duration'] if route else None
        # if no such route exists
        if not route:
            cursor.close()
            conn.close()
            error = "No such route exists."
            return render_template(
                'create_flight.html',
                origins=origins,
                destinations=destinations,
                planes=planes,
                error=error
            )

        route_id = route['Route_id']

        # check plane id vs route compatibility
        cursor.execute(""" SELECT Size FROM Plane WHERE Plane_id = %s """, (plane_id,))
        plane = cursor.fetchone()
        plane_size = plane['Size'] if plane else None
        if plane_size == 'SMALL' and dur > 180:
            cursor.close()
            conn.close()
            error = "Selected plane is not suitable for this long-haul route."
            return render_template(
                'create_flight.html',
                origins=origins,
                destinations=destinations,
                planes=planes,
                error=error
            )

        # Create flight- get flight number
        cursor.execute("SELECT MAX(Flight_number) AS max_num FROM Flight")
        max_flight = cursor.fetchone()
        if max_flight['max_num'] is None:
            flight_number = 1
        else:
            flight_number = max_flight['max_num'] + 1

        cursor.execute("""
            INSERT INTO Flight (Flight_number, Plane_id, Route_id, Departure_date, Departure_time, Flight_status)
            VALUES (%s, %s, %s, %s, %s, 'ACTIVE')
        """, (flight_number, plane_id, route_id, departure_date, departure_time))

        # Set pricing
        cursor.execute("""
            INSERT INTO Flight_pricing (Flight_number, Plane_id, Price, Employee_id, Class_type)
            VALUES (%s, %s, %s, %s, 'ECONOMY')
        """, (flight_number, plane_id, price, manager_id))

        conn.commit()
        cursor.close()
        conn.close()

        return redirect(url_for('assign_crew', flight_number=flight_number))
    cursor.close()
    conn.close()

    return render_template(
        'create_flight.html',
        origins=origins,
        destinations=destinations,
        planes=planes,
        error=error
    )

@application.route('/admin/assign_crew', methods=['POST', 'GET'])
def assign_crew():
    error = None

    if get_user_role() != 'manager':
        return "Forbidden", 403

    if request.method == 'POST':
        flight_number = request.form.get('flight_number')
        pilots = request.form.getlist('pilots')
        stewards = request.form.getlist('stewards')

        long_haul_required = is_long_haul_flight(flight_number)
        
        conn = get_db_connection()
        cursor = conn.cursor()

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

    return render_template(
        'assign_crew.html',
        flight_number=flight_number,
        pilots=available_pilots,
        stewards=available_stewards,
        long_haul_required=long_haul_required,
        error=error
    )

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
        return "Invalid credentials", 401

    return render_template('login.html')

@application.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        passport_number = request.form['passport_number']
        birth_date = request.form['birth_date']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check if email exists in registered clients
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s", (email,))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return "Email already registered", 400
        
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
        conn.commit()
        cursor.close()
        conn.close()

        session['client_email'] = email  # log them in immediately
        return redirect(url_for('landing_page'))

    return render_template('register.html')


@application.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing_page'))

@application.route('/search', methods=['GET'])
def search():
    origin = request.args.get('origin')
    destination = request.args.get('destination')
    date = request.args.get('date')
    print(f"Searching flights: {origin} → {destination} on {date}")
    #Sanity checks
    if not origin or not destination or not date:
        return redirect(url_for('landing_page'))
    # Implementing search logic
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
                SELECT * 
                FROM 
                    Flight as f
                JOIN
                    Flying_route as fr ON f.Route_id = fr.Route_id
                WHERE 
                    fr.Origin_airport = %s AND 
                    fr.Destination_airport = %s AND 
                    f.Departure_date = %s AND
                    f.Flight_status = 'ACTIVE'
                ORDER BY f.Departure_time
            """
    
    cursor.execute(query, (origin, destination, date))
    flights = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('landing_page.html', role=get_user_role(), flights=flights)

@application.route('/flight_view/<int:flight_number>', methods=['GET','POST'])
def flight_view(flight_number):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
                SELECT f.* , fr.Origin_airport, fr.Destination_airport, fr.Duration
                FROM 
                    Flight as f
                JOIN
                    Flying_route as fr ON f.Route_id = fr.Route_id
                WHERE 
                    f.Flight_number = %s
            """
    ### REMEMBER TO ADD MORE DETAILS LIKE FLIGHT DURATION, SEATS, CLASS, ETC ETC
    cursor.execute(query, (flight_number,))
    flights = cursor.fetchone()
    return render_template('flight_view.html', role=get_user_role(), flight=flights)

@application.route('/check_out', methods=['GET','POST'])
def check_out():
    flight_number = request.args.get('flight_number')
    client_email = session['client_email']

    return render_template('check_out.html', role=get_user_role())

@application.errorhandler(404)
def invalid_route(e):
    return redirect("/")


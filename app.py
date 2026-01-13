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
    dep_dt = datetime.combine(
            flight['Departure_date'],
            flight['Departure_time']
        )
    arr_dt = dep_dt + timedelta(minutes=flight['Duration'])

    lquery = f"""
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
        assignment_table="Pilot_in_flight",
        extra_conditions=condition
    )
def get_available_stewards(flight_number, long_haul_required):
    condition = ""
    if long_haul_required:
        condition = "AND e.Long_haul_qualified = TRUE"
    return get_available_staff(
        flight_number,
        employee_table="Steward",
        assignment_table="Steward_in_flight", 
        extra_conditions=condition
    )

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
    if get_user_role() != 'manager':
        return "Forbidden", 403

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Load airports for dropdowns
    cursor.execute("SELECT DISTINCT Origin_airport FROM Flying_route")
    origins = cursor.fetchall()

    cursor.execute("SELECT DISTINCT Destination_airport FROM Flying_route")
    destinations = cursor.fetchall()

    if request.method == 'POST':
        origin = request.form['origin']
        destination = request.form['destination']
        departure_date = request.form['departure_date']
        departure_time = request.form['departure_time']
        price = request.form['price']
        manager_id = session['manager_employee_id']

        # Find route
        cursor.execute("""
            SELECT Route_id
            FROM Flying_route
            WHERE Origin_airport = %s AND Destination_airport = %s
        """, (origin, destination))

        route = cursor.fetchone()

        if not route:
            cursor.close()
            conn.close()
            return "No such route exists", 400

        route_id = route['Route_id']
        try:
            # Create flight
            cursor.execute("""
                INSERT INTO Flight (Route_id, Departure_date, Departure_time, Flight_status, Route_id)
                VALUES (%s, %s, %s, 'ACTIVE', %s)
            """, (route_id, departure_date, departure_time, route_id))

            flight_number = cursor.lastrowid

            # Set pricing
            cursor.execute("""
                INSERT INTO Flight_pricing (Flight_number, Price, Manager_employee_id)
                VALUES (%s, %s, %s)
            """, (flight_number, price, manager_id))

            conn.commit()

        except Exception as e:
            conn.rollback()
            raise e

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('assign_crew', flight_number=flight_number))
    cursor.close()
    conn.close()

    return render_template(
        'create_flight.html',
        origins=origins,
        destinations=destinations
    )

@application.route('/admin/assign_crew', methods=['POST', 'GET'])
def assign_crew():
    if get_user_role() != 'manager':
        return "Forbidden", 403

    flight_number = request.args.get('flight_number')
    if request.method == 'POST':
        pilots = request.form.getlist('pilots')
        stewards = request.form.getlist('stewards')

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            for pilot_id in pilots:
                cursor.execute("""
                    INSERT INTO Pilot_in_flight (Employee_id, Flight_number)
                    VALUES (%s, %s)
                """, (pilot_id, flight_number))

            for steward_id in stewards:
                cursor.execute("""
                    INSERT INTO Steward_in_flight (Employee_id, Flight_number)
                    VALUES (%s, %s)
                """, (steward_id, flight_number))

            conn.commit()

        except Exception:
            conn.rollback()
            raise

        finally:
            cursor.close()
            conn.close()

        return redirect(url_for('admin_dashboard'))

    # GET — show available staff
    available_pilots = get_available_staff(flight_number, role='pilot')
    available_stewards = get_available_staff(flight_number, role='steward')

    return render_template(
        'assign_crew.html',
        flight_number=flight_number,
        pilots=available_pilots,
        stewards=available_stewards
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


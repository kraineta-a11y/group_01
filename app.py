from flask import Flask, render_template, redirect, request, session
from flask_session import Session
from datetime import timedelta
from utils import *
import random
import os
import mysql.connector as mdb

application = Flask(__name__)

session_dir = os.path.join(os.getcwd(), "flask_session_data")
if not os.path.exists(session_dir):
    os.makedirs(session_dir)

application.config.update(
    SESSION_TYPE="filesystem",
    SESSION_FILE_DIR="home/Netarosh/projects/group_01/flask_session_data",
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
        user='root',
        password='root',
        database='Netarosh$FLYTAU'
    )

def get_user_role():
    """Determine role based on session info (email or ID)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if "manager_id" in session:
        cursor.execute("SELECT * FROM Manager WHERE Employee_id = %s", (session["manager_id"],))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return 'manager'
    if "client_id" in session:
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s", (session["client_id"],))
        if cursor.fetchone():
            cursor.close()
            conn.close()
            return 'client'
    cursor.close()
    conn.close()
    return 'guest'

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
    return "Welcome to the admin dashboard!"

@application.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # Check in managers table
        cursor.execute("SELECT * FROM Manager WHERE Employee_id = %s AND Manager_password = %s", (email, password))
        manager = cursor.fetchone()
        if manager:
            session['manager_id'] = manager['id']
            cursor.close()
            conn.close()
            return redirect(url_for('admin_dashboard'))

        # Check in registered table
        cursor.execute("SELECT * FROM Registered_client WHERE Email = %s AND Registered_password = %s", (email, password))
        client = cursor.fetchone()
        if client:
            session['client_id'] = client['id']
            cursor.close()
            conn.close()
            return redirect(url_for('landing_page'))

        cursor.close()
        conn.close()
        return "Invalid credentials", 401

    return render_template('login.html')

@application.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('landing_page'))

@application.errorhandler(404)
def invalid_route(e):
    return redirect("/")


@application.route("/", methods=["POST", "GET"])
def home_page():
    user_name = session.get("user_name")
    if user_name:
        ensure_user(user_name)
        phase = get_phase()
        if phase == "idle":
            return render_template("wait.html", name=user_name)
        elif phase == "started":
            return redirect("/play")
        else:   # phase == "ended"
            return redirect("/results")
    else:
        if request.method == "POST":
            user_name = request.form.get("user_name")
            is_ok = ensure_user(user_name)
            if is_ok:
                session["user_name"] = user_name
                return redirect("/add_question")
            else:
                return render_template("name.html",
                                       error="Error: User already exists or DB failed.")
        else:
            return render_template("name.html")


@application.route("/add_question", methods=["GET", "POST"])
def add_question():
    user_name = session.get("user_name")
    phase = get_phase()
    if user_name and phase == "idle":
        if request.method == "POST":
            q = request.form.get("question")
            a = request.form.get("answer1")
            w1 = request.form.get("answer2")
            w2 = request.form.get("answer3")
            is_ok = Question.add(Question(q, a, w1, w2))
            if is_ok:
                return render_template("wait.html", name=user_name)
            else:
                return render_template("add.html",
                                       error="Error: Question already exists or DB failed.")
        return render_template("add.html")
    return redirect("/")


@application.route("/play", methods=["GET", "POST"])
def play():
    user_name = session.get("user_name")
    phase = get_phase()
    if user_name and phase == "started":
        if request.method == "POST":
            q_id = request.form.get("q_id")
            chosen = request.form.get("choice")
            q = Question.get(q_id)
            if chosen == q.correct_answer:
                inc_user_score(user_name, 1)
                add_answered(user_name, int(q_id))
                session["error_msg"] = False
            else:
                session["error_msg"] = "Wrong answer, try again!"
            return redirect("/play")

        all_qs = Question.all_questions()
        answered = get_answered(user_name)
        remaining = [q for q in all_qs if q[0] not in answered]

        if not remaining:
            score = get_score(user_name)
            return render_template("done.html", score=score)

        q_id, q_text = random.choice(remaining)
        q = Question.get(q_id)

        answers = [q.correct_answer, q.wrong_answer1, q.wrong_answer2]
        random.shuffle(answers)

        return render_template("play.html", q_id=q_id, q=q, answers=answers, error_msg=session.get("error_msg"))
    return redirect("/")


@application.route("/results")
def results():
    scores = get_scores()
    return render_template("results.html", scores=scores)


@application.route("/admin", methods=["GET", "POST"])
def admin():
    msg = None
    phase = get_phase()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "start":
            set_phase("started")
            msg = "Game started."
        elif action == "end":
            set_phase("ended")
            msg = "Game ended. Showing results."
        elif action == "reset":
            reset_db()
            msg = "Database reset. Phase is idle now."
    return render_template("admin.html", phase=phase, msg=msg)


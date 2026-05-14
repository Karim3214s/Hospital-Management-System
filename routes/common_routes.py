import email

from flask import Blueprint, render_template, request, session, redirect, jsonify
from sqlalchemy.orm import Session
from database import get_db
from models import Appointment, Doctor, DoctorLeave, DoctorSlot, User, Patient, AuditLog, Department
import hashlib, datetime, secrets
from flask import current_app

common_bp = Blueprint("common", __name__)

# ───────────────── Helpers ─────────────────

def hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

def log_action(db: Session, user_id, user_name, role, action, entity=None, detail=None):
    db.add(AuditLog(
        user_id=user_id,
        user_name=user_name,
        role=role,
        action=action,
        entity=entity,
        detail=detail,
        timestamp=datetime.datetime.now()
    ))
    db.commit()

ROLE_MAP = {
    1: "Admin", 2: "Doctor", 3: "Receptionist", 4: "Nurse",
    5: "Patient", 6: "Helper", 7: "Auditor"
}

ROLE_HOME = {
    "Admin": "/admin/dashboard",
    "Doctor": "/doctor/calendar",
    "Receptionist": "/receptionist/dashboard",
    "Patient": "/patient/profile",
    "Auditor": "/dashboard",
    "Nurse": "/doctor/calendar",
    "Helper": "/doctor/calendar",
}

# ───────────────── Dashboard Redirect ─────────────────
@common_bp.route("/dashboard")
def index():
    if "user_id" not in session:
        return redirect("/login")

    role = session.get("role", "")

    if role == "Admin":
        return redirect("/admin/dashboard")

    elif role == "Doctor":
        return redirect("/doctor/calendar")

    elif role == "Receptionist":
        return redirect("/receptionist/dashboard")

    elif role == "Patient":
        return redirect("/patient/profile")

    elif role == "Auditor":
        return render_template("auditor/dashboard.html")   # ✅ THIS FIXES LOOP

    return redirect("/login")   

# ───────────────── Login ─────────────────

@common_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("common/login.html")

    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    db = next(get_db())
    user = db.query(User).filter(
        User.Email == email,
        User.is_active == True
    ).first()

    if not user or user.Password != hash_password(password):
        return render_template("common/login.html", error="Invalid email or password.")

    role_name = ROLE_MAP.get(user.Role_ID, "Unknown")
    initials = "".join(w[0].upper() for w in (user.Name or "U").split()[:2])

    session["user_id"] = user.User_ID
    session["user_name"] = user.Name
    session["user_initials"] = initials
    session["role"] = role_name
    session["role_id"] = user.Role_ID
    session["entity_id"] = user.Linked_Entity_ID

    log_action(db, user.User_ID, user.Name, role_name, "LOGIN",
               entity="Session", detail=f"Login from {request.remote_addr}")

    # FIRST LOGIN CHECK
    if user.force_password_change:
        return redirect("/first-login")

    return redirect(ROLE_HOME.get(role_name, "/login"))

# ───────────────── Logout ─────────────────

@common_bp.route("/logout")
def logout():
    db = next(get_db())

    if "user_id" in session:
        log_action(db,
                   session["user_id"],
                   session.get("user_name", ""),
                   session.get("role", ""),
                   "LOGOUT",
                   entity="Session")

    session.clear()
    return redirect("/login")

# ───────────────── Register ─────────────────

@common_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("public/register.html")

    data = request.form

    fname = data.get("fname", "").strip()
    lname = data.get("lname", "").strip()
    dob = data.get("dob")
    gender = data.get("gender", "")
    phone = data.get("phone", "").strip()
    address = data.get("address", "").strip()
    email = data.get("email", "").strip()
    password = data.get("password", "")

    if not all([fname, lname, dob, gender, phone]):
        return render_template("public/register.html", error="Fill all required fields.")

    db = next(get_db())

    if email:
        if db.query(User).filter(User.Email == email).first():
            return render_template("public/register.html", error="Email already exists.")

    try:
        dob_date = datetime.date.fromisoformat(dob)
    except:
        return render_template("public/register.html", error="Invalid DOB.")

    patient = Patient(
        FName=fname,
        LName=lname,
        Gender=gender,
        Date_Of_Birth=dob_date,
        contact_No=phone,
        pt_Address=address
    )

    db.add(patient)
    db.flush()

    if email and password:
        user = User(
            Email=email,
            Password=hash_password(password),
            Name=f"{fname} {lname}",
            Role_ID=5,
            Linked_Entity_ID=patient.patient_Id,
            is_active=True,
            force_password_change=True
        )
        db.add(user)
        db.flush()
        patient.User_ID = user.User_ID

    db.commit()

    if email:
        try:
            current_app.send_email(
                subject="Welcome to Marvel Hospitals",
                recipients=[email],
                body=f"""
    Dear {fname} {lname},

    Welcome to Marvel Hospitals 🎉

    Your account has been successfully created.

    ━━━━━━━━━━━━━━━━━━━━━━━
    🌐 Login Here
    ━━━━━━━━━━━━━━━━━━━━━━━
    http://localhost:5000/login

    We are happy to have you with us.

    Regards,  
    Marvel Hospitals
    """
            )
        except Exception as e:
            print("Email failed:", e)

# 🔥 EXISTING RETURN
    return render_template("common/login.html",
                        success="Account created successfully.")

# ───────────────── Forgot Password ─────────────────

@common_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("common/forgot_password.html")

    email = request.form.get("email", "").strip()
    db = next(get_db())

    user = db.query(User).filter(User.Email == email).first()

    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expiry = datetime.datetime.now() + datetime.timedelta(hours=2)
        db.commit()

        reset_link = request.host_url + f"reset-password/{token}"

        print(f"[DEBUG] Reset link: {reset_link}")

    return render_template("common/forgot_password.html",
                           success="If email exists, reset link sent.")

# ───────────────── Reset Password ─────────────────

@common_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    db = next(get_db())

    user = db.query(User).filter(
        User.reset_token == token,
        User.reset_token_expiry > datetime.datetime.now()
    ).first()

    if not user:
        return render_template("common/reset_password.html",
                               error="Invalid or expired link.")

    if request.method == "GET":
        return render_template("common/reset_password.html", token=token)

    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if len(password) < 8:
        return render_template("common/reset_password.html",
                               token=token, error="Min 8 characters.")

    if password != confirm:
        return render_template("common/reset_password.html",
                               token=token, error="Passwords mismatch.")

    user.Password = hash_password(password)
    user.reset_token = None
    user.reset_token_expiry = None
    user.force_password_change = False

    db.commit()

    log_action(db, user.User_ID, user.Name,
               ROLE_MAP.get(user.Role_ID, ""),
               "RESET_PASSWORD")

    return render_template("common/login.html",
                           success="Password updated successfully.")

# ───────────────── First Login ─────────────────

@common_bp.route("/first-login", methods=["GET", "POST"])
def first_login():
    if "user_id" not in session:
        return redirect("/login")

    if request.method == "GET":
        return render_template("common/first_login.html")

    password = request.form.get("password", "")
    confirm = request.form.get("confirm_password", "")

    if len(password) < 8:
        return render_template("common/first_login.html",
                               error="Min 8 characters.")

    if password != confirm:
        return render_template("common/first_login.html",
                               error="Passwords mismatch.")

    db = next(get_db())
    user = db.query(User).filter(User.User_ID == session["user_id"]).first()

    user.Password = hash_password(password)
    user.force_password_change = False
    user.password_changed_at = datetime.datetime.now()

    db.commit()

    log_action(db, user.User_ID, user.Name,
               session.get("role", ""),
               "FIRST_LOGIN_PASSWORD_CHANGE")

    return redirect(ROLE_HOME.get(session.get("role", ""), "/dashboard"))

# ───────────────── APIs ─────────────────

@common_bp.route("/api/departments")
def api_departments():
    db = next(get_db())
    rows = db.query(Department).all()

    return [{"dept_Id": d.dept_Id, "dept_Name": d.dept_Name} for d in rows]

@common_bp.route("/api/doctors")
def api_doctors():
    dept = request.args.get("dept")
    db = next(get_db())

    q = db.query(Doctor)
    if dept:
        q = q.filter(Doctor.dept_Id == int(dept))

    rows = q.all()

    return [{
        "doct_Id": d.doct_Id,
        "FName": d.FName,
        "LName": d.LName
    } for d in rows]

@common_bp.route("/api/slots")
def api_slots():

    doctor_id = request.args.get("doctor")
    date_str  = request.args.get("date", "")

    db = next(get_db())

    if not doctor_id:
        return jsonify([])

    # ─────────────────────────────────────────────
    # VALIDATE DATE
    # ─────────────────────────────────────────────
    try:
        appt_date = datetime.date.fromisoformat(date_str)

    except ValueError:
        return jsonify([])

    # ─────────────────────────────────────────────
    # GET BOOKED APPOINTMENTS
    # ─────────────────────────────────────────────
    booked = db.query(Appointment).filter(
        Appointment.doct_Id == int(doctor_id),
        Appointment.appointment_Date == appt_date,
        Appointment.appointment_status.notin_(["Cancelled"])
    ).all()

    booked_times = set()

    for a in booked:

        if a.slot_time:

            booked_times.add(
                a.slot_time.strftime("%H:%M")
            )

    # ─────────────────────────────────────────────
    # HOSPITAL SLOT TIMINGS
    # ─────────────────────────────────────────────
    start_time = datetime.time(10, 0)   # 10:00 AM
    end_time   = datetime.time(16, 0)   # 4:00 PM

    slot_minutes = 30

    # ─────────────────────────────────────────────
    # CURRENT TIME + BUFFER
    # ─────────────────────────────────────────────
    now = datetime.datetime.now()

    buffer_time = (
        now + datetime.timedelta(minutes=30)
    ).time()

    # ─────────────────────────────────────────────
    # GENERATE SLOTS
    # ─────────────────────────────────────────────
    available_slots = []

    current = datetime.datetime.combine(
        appt_date,
        start_time
    )

    end_dt = datetime.datetime.combine(
        appt_date,
        end_time
    )

    while current < end_dt:

        slot_time = current.time()

        time_str = slot_time.strftime("%H:%M")

        # 🔥 HIDE EXPIRED TODAY SLOTS
        if (
            appt_date == now.date()
            and slot_time <= buffer_time
        ):

            current += datetime.timedelta(
                minutes=slot_minutes
            )

            continue

        # 🔥 SKIP BOOKED SLOTS
        if time_str in booked_times:

            current += datetime.timedelta(
                minutes=slot_minutes
            )

            continue

        available_slots.append({
            "time": time_str
        })

        current += datetime.timedelta(
            minutes=slot_minutes
        )

    return jsonify(available_slots)

@common_bp.route("/api/check-doctor-leave")
def check_doctor_leave():

    doctor_id = request.args.get("doctor")
    date_str  = request.args.get("date")

    if not doctor_id or not date_str:

        return jsonify({
            "on_leave": False
        })

    db = next(get_db())

    try:

        appointment_date = datetime.date.fromisoformat(
            date_str
        )

    except:
        return jsonify({
            "on_leave": False
        })

    leave = db.query(DoctorLeave).filter(
        DoctorLeave.doct_Id == int(doctor_id),
        DoctorLeave.status == "Approved",
        DoctorLeave.leave_from <= appointment_date,
        DoctorLeave.leave_to >= appointment_date
    ).first()

    return jsonify({
        "on_leave": leave is not None
    })
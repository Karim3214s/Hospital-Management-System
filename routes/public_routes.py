from flask import Blueprint, jsonify, render_template, request, redirect, session, url_for, flash
from database import get_db,db
from models import Appointment, FeeMaster, Helper, Nurse, Patient, Doctor, Department, ContactMessage, DoctorLeave
import datetime
import random

public_bp = Blueprint("public", __name__)

# ─────────────────────────────────────────────
# HOME
# ─────────────────────────────────────────────
@public_bp.route("/")
def home():
    db = next(get_db())

    try:
        stats = {
            "patients": db.query(Patient).count(),
            "doctors": db.query(Doctor).count(),
            "staff": db.query(Nurse).count() + db.query(Helper).count()
        }

        return render_template("public/index.html", stats=stats)
    finally:
        db.close()


# ─────────────────────────────────────────────
# STATIC PAGES
# ─────────────────────────────────────────────
@public_bp.route("/about")
def about():
    return render_template("public/about.html")


@public_bp.route("/services")
def services():
    return render_template("public/services.html")


@public_bp.route("/doctors")
def doctors():
    return render_template("public/doctors.html")


# ─────────────────────────────────────────────
# BOOK APPOINTMENT (NO PAYMENT HERE)
# ─────────────────────────────────────────────
@public_bp.route("/appointment", methods=["GET", "POST"])
def appointment():

    db = next(get_db())
    user_id = session.get("user_id")

    # Load common data
    doctors = db.query(Doctor).all()
    departments = db.query(Department).all()

    # 🔒 NOT LOGGED IN
    if not user_id:
        if request.method == "POST":
            flash("Please login or register to book an appointment", "warning")
            return redirect(url_for("common.login"))

        return render_template(
            "public/appointment.html",
            doctors=doctors,
            departments=departments,
            is_logged_in=False
        )

    # 🔒 GET PATIENT PROFILE
    patient = db.query(Patient).filter_by(user_id=user_id).first()

    if not patient:
        flash("Please complete patient registration first", "warning")
        return redirect("/patient-register")

    # ───── HANDLE BOOKING ─────
    if request.method == "POST":

        appt_date = request.form.get("appointment_Date")
        appt_time = request.form.get("time")

        try:
            appt_date = datetime.datetime.strptime(appt_date, "%Y-%m-%d").date()
        except:
            appt_date = datetime.date.today()
        
        # ✅ CONVERT TIME STRING → TIME OBJECT
        try:
            slot_time = datetime.datetime.strptime(appt_time, "%H:%M").time()
        except:
            flash("Invalid time format", "danger")
            return redirect("/appointment")

        # 🔥 CREATE APPOINTMENT (NO PAYMENT)
        # 🔥 GET DOCTOR
        doctor_id = request.form.get("doct_Id")

        doctor = db.query(Doctor).filter_by(doct_Id=doctor_id).first()

        # ─────────────────────────────────────────────
        # CHECK DOCTOR LEAVE
        # ─────────────────────────────────────────────

        leave = db.query(DoctorLeave).filter(
            DoctorLeave.doct_Id == doctor_id,
            DoctorLeave.status == "Approved",
            DoctorLeave.leave_from <= appt_date,
            DoctorLeave.leave_to >= appt_date
        ).first()

        if leave:

            flash(
                "Doctor is on leave. No slots available.",
                "danger"
            )

            return redirect("/appointment")

        # 🔥 GET CONSULTATION FEE (FROM DOCTOR OR DEPARTMENT)
        consultation_fee = None

        if doctor:
            consultation_fee = doctor.department.consultation_fee   # or use FeeMaster if you have

        # 🔥 CREATE APPOINTMENT
        appt = Appointment(
            patient_Id=patient.patient_Id,
            doct_Id=doctor_id or None,
            reason=request.form.get("reason"),
            appointment_Date=appt_date,
            slot_time=slot_time,
            mode_of_appointment=request.form.get("mode_of_appointment"),

            # 🔥 ADD THIS LINE (VERY IMPORTANT)
            consultation_fee=consultation_fee,

            appointment_status="Booked",
            token_no=random.randint(100, 999),
            created_at=datetime.datetime.utcnow()
        )

        db.add(appt)
        db.commit()

        flash(f"Appointment booked successfully. OPID: {appt.appointment_Id}", "success")

        return redirect("/my-appointments")   # 🔥 UPDATED

    return render_template(
        "public/appointment.html",
        doctors=doctors,
        departments=departments,
        patient=patient,
        is_logged_in=True
    )


# ─────────────────────────────────────────────
# PATIENT DASHBOARD (MY APPOINTMENTS)
# ─────────────────────────────────────────────
@public_bp.route("/my-appointments")
def my_appointments():

    db = next(get_db())
    user_id = session.get("user_id")

    if not user_id:
        return redirect("/login")

    patient = db.query(Patient).filter_by(user_id=user_id).first()

    if not patient:
        flash("Please complete registration", "warning")
        return redirect("/patient-register")

    appts = db.query(Appointment)\
        .filter(Appointment.patient_Id == patient.patient_Id)\
        .order_by(Appointment.appointment_Id.desc())\
        .all()

    return render_template(
        "public/my_appointments.html",
        appointments=appts,
        patient=patient
    )


# ─────────────────────────────────────────────
# CONTACT
# ─────────────────────────────────────────────
@public_bp.route("/contact", methods=["GET", "POST"])
def contact():

    db = next(get_db())

    try:

        if request.method == "POST":

            msg = ContactMessage(
                name=request.form["name"],
                email=request.form["email"],
                subject=request.form["subject"],
                message=request.form["message"]
            )

            db.add(msg)
            db.commit()

            flash("Message sent successfully", "success")

            return redirect(url_for("public.contact"))

        return render_template("public/contact.html")

    finally:
        db.close()

# ─────────────────────────────────────────────
# PATIENT REGISTER PAGE (UI ONLY)
# ─────────────────────────────────────────────
@public_bp.route("/patient-register")
def patient_register():
    return render_template("public/register_public.html")


# ─────────────────────────────────────────────
# SUCCESS PAGE (OPTIONAL)
# ─────────────────────────────────────────────
@public_bp.route("/appointment-success")
def appointment_success():
    return render_template("public/appointment_success.html")


@public_bp.route("/api/consultation-fee")
def get_consultation_fee():

    db = next(get_db())

    dept_id = request.args.get("dept")
    doctor_id = request.args.get("doctor")

    try:
        # 🔥 doctor-specific fee
        fee = db.query(FeeMaster).filter(
            FeeMaster.doct_Id == doctor_id,
            FeeMaster.fee_type == "consultation",
            FeeMaster.is_active == True
        ).first()

        # 🔥 fallback dept fee
        if not fee:
            fee = db.query(FeeMaster).filter(
                FeeMaster.dept_Id == dept_id,
                FeeMaster.doct_Id.is_(None),
                FeeMaster.fee_type == "consultation",
                FeeMaster.is_active == True
            ).first()

        return jsonify({
            "fee": float(fee.amount) if fee else 0
        })

    finally:
        db.close()

@public_bp.route("/api/departments")
def get_departments():
    db = next(get_db())

    depts = db.query(Department).all()

    return jsonify([
        {
            "dept_Id": d.dept_Id,
            "dept_Name": d.dept_Name
        } for d in depts
    ])

@public_bp.route("/api/doctors")
def get_doctors():

    db = next(get_db())
    dept = request.args.get("dept")

    doctors = db.query(Doctor).filter(
        Doctor.dept_Id == dept
    ).all()

    return jsonify([
        {
            "doct_Id": d.doct_Id,
            "FName": d.FName,
            "LName": d.LName
        } for d in doctors
    ])



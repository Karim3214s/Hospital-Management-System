from decimal import Decimal

from flask import Blueprint, render_template, request, session, redirect, jsonify
from sqlalchemy import func, and_
from database import db, get_db
from models import DoctorSlot, FeeMaster, MedicalRecord, Patient, Appointment, Doctor, Department, Bill, Payment, TreatmentCatalogue, User, AuditLog,Treatment
from config import PAGINATION
import datetime, math, hashlib
from datetime import timedelta
from models import Patient, User
import razorpay
from dateutil.relativedelta import relativedelta


razorpay_client = razorpay.Client(auth=("rzp_test_Sg1XNkaEMXPDyB", "KqK3L7z3UueGR0yEUpQ3MQNj"))
receptionist_bp = Blueprint("receptionist", __name__, url_prefix="/receptionist")

# ── Auth guard ────────────────────────────────────────────────────────────────

def _guard():
    if session.get("role") not in ("Receptionist", "Admin"):
        return redirect("/login")
    return None

def _log(db, action, entity=None, detail=None):
    db.add(AuditLog(
        user_id=session.get("user_id"), user_name=session.get("user_name",""),
        role=session.get("role",""), action=action, entity=entity, detail=detail,
        timestamp=datetime.datetime.now()
    ))
    db.commit()

# ── Page routes ───────────────────────────────────────────────────────────────

@receptionist_bp.route("/dashboard")
def dashboard():
    g = _guard()
    if g: return g
    return render_template("receptionist/dashboard.html")

@receptionist_bp.route("/register-patient")
def register_patient_page():
    g = _guard()
    if g: return g
    return render_template("receptionist/register_patient.html")

@receptionist_bp.route("/book-appointment")
def book_appointment():
    g = _guard()
    if g: return g
    return render_template("receptionist/book_appointment.html")

@receptionist_bp.route("/check-in")
def check_in():
    g = _guard()
    if g: return g
    return render_template("receptionist/check_in.html")

@receptionist_bp.route("/generate-bill")
def generate_bill():
    g = _guard()
    if g: return g
    return render_template("receptionist/generate_bill.html")

@receptionist_bp.route("/record-payment")
def record_payment():
    g = _guard()
    if g: return g
    return render_template("receptionist/record_payment.html")

@receptionist_bp.route("/audit-logs")
def audit_logs():
    g = _guard()
    if g: return g
    return render_template("receptionist/audit_logs.html")

# ══════════════════════════════════════════════════════════════════════════════
#  API — Dashboard stats
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/dashboard-stats")
def api_dashboard_stats():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db    = next(get_db())
    today = datetime.date.today()

    appts_today    = db.query(func.count(Appointment.appointment_Id))\
                       .filter(Appointment.appointment_Date == today).scalar() or 0
    checked_in     = db.query(func.count(Appointment.appointment_Id))\
                       .filter(Appointment.appointment_Date == today,
                               Appointment.appointment_status == "Checked-In").scalar() or 0
    pending_checkin= db.query(func.count(Appointment.appointment_Id))\
                       .filter(Appointment.appointment_Date == today,
                               Appointment.appointment_status == "Scheduled").scalar() or 0
    bills_pending = db.query(func.count(Bill.bill_id))\
        .filter(Bill.bill_status.in_(["Pending","Partial"]))\
        .scalar() or 0

    return jsonify({
        "appts_today"    : appts_today,
        "checked_in"     : checked_in,
        "pending_checkin": pending_checkin,
        "bills_pending"  : bills_pending,
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Today's queue (paginated)
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/today-queue")
def api_today_queue():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    page     = int(request.args.get("page", 1))
    per_page = PAGINATION["appointments"]
    db       = next(get_db())
    today    = datetime.date.today()

    q = db.query(Appointment, Patient, Doctor, Department)\
          .join(Patient,    Patient.patient_Id == Appointment.patient_Id)\
          .join(Doctor,     Doctor.doct_Id     == Appointment.doct_Id)\
          .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
          .filter(Appointment.appointment_Date == today)\
          .order_by(Appointment.appointment_Date)

    total = q.count()
    rows  = q.offset((page-1)*per_page).limit(per_page).all()

    items = [{
        "appointment_Id"    : a.appointment_Id,
        "patient_name"      : f"{p.FName} {p.LName}",
        "doctor_name"       : f"Dr. {d.FName} {d.LName}",
        "dept_name"         : dept.dept_Name if dept else "—",
        "appointment_time"  : str(a.appointment_Date) if a.appointment_Date else "—",
        "appointment_status": a.appointment_status,
    } for a, p, d, dept in rows]

    return jsonify({"items": items, "total": total,
                    "total_pages": math.ceil(total/per_page) or 1})


# ══════════════════════════════════════════════════════════════════════════════
#  API — Book appointment
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/book-appointment", methods=["POST"])
def api_book_appointment():
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    body = request.get_json() or {}
    db = next(get_db())

    # ── Validate date ─────────────────────────────────────
    try:
        appt_date = datetime.date.fromisoformat(body.get("appointment_date", ""))
    except ValueError:
        return jsonify({"detail": "Invalid date"}), 400

    doctor_id = body.get("doct_id")
    patient_id = body.get("patient_id")

    # ── 🔥 FETCH CONSULTATION FEE FROM FEEMASTER ──────────
    fee_record = db.query(FeeMaster).filter(
        FeeMaster.doct_Id == doctor_id
    ).first()

    consultation_fee = fee_record.consultation_fee if fee_record else 0

    # ── OPTIONAL: fallback to Doctor table if needed ──────
    if consultation_fee == 0:
        doctor = db.query(Doctor).filter(
            Doctor.doct_Id == doctor_id
        ).first()

        if doctor and hasattr(doctor, "consultation_fee"):
            consultation_fee = doctor.consultation_fee or 0

    time_str = body.get("slot_time")

    try:
        slot_time = datetime.datetime.strptime(time_str, "%H:%M").time()
    except:
        return jsonify({"detail": "Invalid slot time"}), 400

    # ── Create appointment ───────────────────────────────
    appt = Appointment(
        patient_Id=patient_id,
        doct_Id=doctor_id,
        consultation_fee=consultation_fee,
        reason=body.get("reason", ""),
        appointment_Date=appt_date,
        slot_time=slot_time,   # ✅ ADD THIS
        mode_of_appointment=body.get("mode_of_appointment", "In-Person"),
        appointment_status="Scheduled",
    )

    db.add(appt)
    db.commit()

    # ── Log ──────────────────────────────────────────────
    _log(db, "BOOK_APPT",
         entity=f"APT-{str(appt.appointment_Id).zfill(4)}",
         detail=f"Patient {patient_id} → Dr. {doctor_id} on {appt_date}, Fee: {consultation_fee}")

    return jsonify({
        "ok": True,
        "appointment_id": appt.appointment_Id,
        "consultation_fee": float(consultation_fee),
        "message": f"Appointment booked successfully with consultation fee ₹{consultation_fee}"
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Available slots
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/slots")
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

# ══════════════════════════════════════════════════════════════════════════════
#  API — Pending check-in list
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/pending-checkin")
def api_pending_checkin():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    page     = int(request.args.get("page", 1))
    per_page = PAGINATION["appointments"]
    search   = request.args.get("search","").strip()
    db       = next(get_db())
    today    = datetime.date.today()

    q = db.query(Appointment, Patient, Doctor, Department)\
          .join(Patient,    Patient.patient_Id == Appointment.patient_Id)\
          .join(Doctor,     Doctor.doct_Id     == Appointment.doct_Id)\
          .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
          .filter(Appointment.appointment_Date == today,
                  Appointment.appointment_status == "Scheduled")

    if search:
        q = q.filter((Patient.FName.ilike(f"%{search}%")) |
                     (Patient.LName.ilike(f"%{search}%")))

    total = q.count()
    rows  = q.order_by(Appointment.appointment_Date).offset((page-1)*per_page).limit(per_page).all()

    items = [{
        "appointment_Id"    : a.appointment_Id,
        "patient_name"      : f"{p.FName} {p.LName}",
        "doctor_name"       : f"Dr. {d.FName} {d.LName}",
        "dept_name"         : dept.dept_Name if dept else "—",
        "appointment_time"  : str(a.appointment_Date),
        "appointment_status": a.appointment_status,
    } for a, p, d, dept in rows]

    return jsonify({"items": items, "total": total,
                    "total_pages": math.ceil(total/per_page) or 1})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Patients list (for dropdowns)
# ══════════════════════════════════════════════════════════════════════════════
@receptionist_bp.route("/api/receptionist/patients-list")
def api_patients_list():
    db = next(get_db())   # ✅ REQUIRED

    pts = db.query(Patient).all()

    return jsonify([
        {
            "patient_Id": p.patient_Id,
            "name": f"{p.FName} {p.LName}"
        }
        for p in pts
    ])

# ══════════════════════════════════════════════════════════════════════════════
#  API — Appointments by patient (for bill dropdown)
# ══════════════════════════════════════════════════════════════════════════════

@receptionist_bp.route("/api/receptionist/appointments-by-patient/<int:pid>")
def api_appts_by_patient(pid):
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db    = next(get_db())
    appts = db.query(Appointment)\
              .filter(Appointment.patient_Id == pid,
                      Appointment.appointment_status.in_(["Checked-In","In-Progress","Completed"]))\
              .order_by(Appointment.appointment_Date.desc()).limit(20).all()
    return jsonify([{
        "appointment_Id"  : a.appointment_Id,
        "appointment_date": str(a.appointment_Date),
        "appointment_status": a.appointment_status,
    } for a in appts])


@receptionist_bp.route("/api/receptionist/treatment-by-record/<int:record_id>")
def get_treatment(record_id):

    treatments = db.query(Treatment).filter(
        Treatment.record_id == record_id
    ).all()

    items = [
        {"name": t.description, "cost": float(t.cost)}
        for t in treatments
    ]

    return jsonify({"items": items})

@receptionist_bp.route("/api/receptionist/treatment-by-patient/<int:pid>")
def get_treatment_by_patient(pid):

    treatments = db.query(Treatment).filter(
        Treatment.patient_Id == pid
    ).all()

    return jsonify({
        "items": [
            {"name": t.description, "cost": float(t.cost)}
            for t in treatments
        ]
    })

@receptionist_bp.route("/api/receptionist/bill/<int:bill_id>")
def get_bill(bill_id):

    bill = db.query(Bill).get(bill_id)

    treatments = db.query(Treatment).filter(
        Treatment.record_id == bill.record_Id
    ).all()

    return jsonify({
        "patient_Id": bill.patient_Id,
        "items": [
            {"name": t.description, "cost": float(t.cost)}
            for t in treatments
        ]
    })

@receptionist_bp.route("/api/receptionist/pay-bill", methods=["POST"])
def pay_bill():

    db = next(get_db())
    body = request.json

    bill = db.session.get(Bill, body.get("bill_id"))

    if not bill:
        return jsonify({"error": "Bill not found"}), 404

    amount = Decimal(str(body.get("amount", 0)))
    method = body.get("payment_method")
    txn_id = body.get("transaction_id")

    # 🔥 VALIDATION
    if method in ["upi", "card"] and not txn_id:
        return jsonify({"error": "Transaction ID required"}), 400

    if method == "cash":
        txn_id = None

    # 🔥 UPDATE BILL
    bill.amount_paid = Decimal(str(bill.amount_paid or 0)) + amount
    bill.balance = Decimal(str(bill.total_amount)) - bill.amount_paid

    if bill.balance <= 0:
        bill.bill_status = "Paid"
    else:
        bill.bill_status = "Partial"

    # 🔥 SAVE PAYMENT
    payment = Payment(
        bill_id=bill.bill_id,
        amount=float(amount),
        payment_method=method,
        transaction_id=txn_id,
        payment_status="Paid"
    )

    db.add(payment)
    db.commit()

    return jsonify({
        "status": bill.bill_status,
        "balance": float(bill.balance)
    })


@receptionist_bp.route("/api/receptionist/bills")
def get_bills():

    bills = db.query(Bill, Patient)\
        .join(Patient, Bill.patient_Id == Patient.patient_Id)\
        .all()

    return jsonify([
        {
            "bill_id": b.bill_id,
            "total_amount": float(b.total_amount),
            "bill_status": b.bill_status or "Pending",
            "patient_name": f"{p.FName} {p.LName}",  # ✅ REQUIRED
            "date": str(b.created_at.date()) if b.created_at else ""
        }
        for b, p in bills
    ])

@receptionist_bp.route("/api/receptionist/all-treatments")
def get_all_treatments():
    db = next(get_db())

    treatments = db.query(TreatmentCatalogue).filter(
        TreatmentCatalogue.is_active == True
    ).all()

    return jsonify([
        {
            "id": t.treatment_id,
            "name": t.treatment_name,
            "cost": float(t.default_cost)
        }
        for t in treatments
    ])

@receptionist_bp.route("/api/receptionist/completed-opds")
def completed_opds():

    db = next(get_db())

    rows = db.query(Appointment, Patient)\
        .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
        .filter(Appointment.appointment_status == "Completed")\
        .order_by(Appointment.appointment_Id.desc())\
        .all()

    return jsonify([
        {
            "appointment_Id": a.appointment_Id,
            "patient_Id": p.patient_Id,
            "patient_name": f"{p.FName} {p.LName}"
        }
        for a, p in rows
    ])

@receptionist_bp.route("/api/receptionist/treatments-by-opid/<int:opid>")
def treatments_by_opid(opid):

    db = next(get_db())

    records = db.query(MedicalRecord)\
        .filter(MedicalRecord.appointment_Id == opid)\
        .all()

    return jsonify([
        {
            "name": r.treatment,
            "cost": 500   # you can later map actual cost
        }
        for r in records
    ])

@receptionist_bp.route("/api/receptionist/opds-by-patient/<int:pid>")
def opds_by_patient(pid):
    db = next(get_db())

    data = db.query(Appointment)\
        .filter(Appointment.patient_Id == pid)\
        .order_by(Appointment.appointment_Id.desc())\
        .all()

    return jsonify([
        {
            "appointment_Id": a.appointment_Id,
            "date": str(a.appointment_Date)
        }
        for a in data
    ])

@receptionist_bp.route("/api/receptionist/consultation-by-opid/<int:opid>")
def consultation_by_opid(opid):

    db = next(get_db())

    appt = db.query(Appointment).filter_by(appointment_Id=opid).first()

    if not appt:
        return jsonify(None)

    doctor = db.query(Doctor).filter_by(doct_Id=appt.doct_Id).first()

    fee = appt.consultation_fee   # 🔥 snapshot

    # 🔥 CHECK PAYMENT STATUS
    bill = db.query(Bill).filter_by(appointment_Id=opid).first()

    already_paid = False
    if bill and bill.bill_status == "Paid":
        already_paid = True

    return jsonify({
        "name": "Consultation",
        "doctor": f"{doctor.FName} {doctor.LName}" if doctor else "Doctor",
        "cost": fee,
        "already_paid": already_paid
    })

@receptionist_bp.route("/api/receptionist/create-razorpay-order", methods=["POST"])
def create_razorpay_order():

    db = next(get_db())
    data = request.get_json()

    try:
        amount = int(float(data.get("amount", 0)) * 100)

        if amount <= 0:
            return jsonify({"error": "Invalid amount"}), 400

        # 🔥 RETRY LOGIC
        import time
        for i in range(3):
            try:
                order = razorpay_client.order.create({
                    "amount": amount,
                    "currency": "INR",
                    "payment_capture": 1
                })
                break
            except Exception as e:
                print(f"Retry {i+1} failed:", str(e))
                time.sleep(1)
        else:
            return jsonify({"error": "Razorpay connection failed"}), 500

        return jsonify(order)

    except Exception as e:
        print("ERROR creating order:", str(e))
        return jsonify({"error": "Internal server error"}), 500


@receptionist_bp.route("/api/receptionist/verify-payment", methods=["POST"])
def verify_payment():

    db = next(get_db())
    data = request.get_json()

    try:
        params_dict = {
            "razorpay_order_id": data.get("razorpay_order_id"),
            "razorpay_payment_id": data.get("razorpay_payment_id"),
            "razorpay_signature": data.get("razorpay_signature")
        }

        # 🔥 VERIFY SIGNATURE
        razorpay_client.utility.verify_payment_signature(params_dict)

        bill_id = data.get("bill_id")

        bill = db.query(Bill).filter(Bill.bill_id == bill_id).first()

        if not bill:
            return jsonify({"status": "Failed", "error": "Bill not found"})

        amount = bill.balance

        # 🔥 UPDATE BILL
        bill.amount_paid = Decimal(str(bill.amount_paid or 0)) + amount
        bill.balance = bill.total_amount - bill.amount_paid

        if bill.balance <= 0:
            bill.bill_status = "Paid"
        else:
            bill.bill_status = "Partial"

        # 🔥 SAVE PAYMENT
        payment = Payment(
            bill_id=bill.bill_id,
            amount=float(amount),
            payment_method="razorpay",
            transaction_id=data.get("razorpay_payment_id"),
            payment_status="Paid"
        )

        db.add(payment)
        db.commit()

        return jsonify({
            "status": bill.bill_status,
            "balance": float(bill.balance)
        })

    except Exception as e:
        return jsonify({"status": "Failed", "error": str(e)})
    
@receptionist_bp.route('/api/receptionist/send-upi-request', methods=['POST'])
def send_upi_request():

    data = request.get_json()

    amount = data.get("amount")
    vpa = data.get("vpa")

    if not amount or not vpa:
        return jsonify({
            "status": "failed",
            "error": "Missing amount or UPI ID"
        })

    print(f"Simulated UPI request → {vpa} for ₹{amount}")

    return jsonify({
        "status": "request_sent"
    })


def _time_since(dt):
    """Helper to show time elapsed since completion"""
    if not dt:
        return "—"
    delta = datetime.datetime.now() - dt
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = (delta.seconds % 3600) // 60
    return f"{minutes}m ago"


# ── MODIFIED: REGISTER PATIENT (Replace existing function around line 145) ────

@receptionist_bp.route("/api/receptionist/register-patient", methods=["POST"])
def register_patient_api():
    """Register new patient and create user account with temporary password"""
    
    session_db = next(get_db())
    
    try:
        data = request.get_json()
        
        from datetime import datetime
        dob = datetime.strptime(data.get("dob"), "%Y-%m-%d").date()
        
        # Create patient record
        patient = Patient(
            FName=data.get("fname"),
            LName=data.get("lname"),
            Gender=data.get("gender"),
            Date_Of_Birth=dob,
            contact_No=data.get("phone"),
            pt_Address=data.get("address"),
            blood_group=data.get("blood_group"),
            emergency_contact=data.get("emergency_contact"),
            email=data.get("email")
        )
        
        session_db.add(patient)
        session_db.flush()
        
        email = data.get("email")
        
        if email:
            existing = session_db.query(User).filter(User.Email == email).first()
            
            if existing:
                user = existing
            else:
                # ✅ CREATE ACTIVE USER WITH TEMPORARY PASSWORD
                import hashlib
                temp_password = "HMS@123"  # Temporary password
                
                user = User(
                    Email=email,
                    Name=f"{data.get('fname')} {data.get('lname')}",
                    Role_ID=5,  # Patient role
                    is_active=True,  # ✅ Changed from False to True
                    force_password_change=True,  # ✅ Force password change on first login
                    Password=hashlib.sha256(temp_password.encode()).hexdigest()
                )
                session_db.add(user)
                session_db.flush()
                
                # ✅ SEND EMAIL WITH CREDENTIALS
                try:
                    from flask import current_app
                    current_app.send_email(
                        subject="HMS - Your Patient Account Has Been Created",
                        recipients=[email],
                        body=f"""Dear {data.get('fname')} {data.get('lname')},

Welcome to our Hospital Management System!

Your patient account has been created successfully.

Login Credentials:
Email: {email}
Temporary Password: {temp_password}

IMPORTANT: For security reasons, you will be required to change your password when you first login.

You can access your account here: {request.host_url}login

If you have any questions, please contact the hospital reception.

Best regards,
Hospital Management Team"""
                    )
                except Exception as e:
                    print(f"Failed to send email: {e}")
            
            patient.User_ID = user.User_ID
        
        session_db.commit()
        
        # ✅ LOG THE REGISTRATION WITH PROPER ENTITY FORMAT
        _log(session_db, "REGISTER_PATIENT", 
             entity=f"PT-{str(patient.patient_Id).zfill(4)}", 
             detail=f"Registered {patient.FName} {patient.LName}, Email: {email or 'N/A'}")
        
        return jsonify({
            "patient_id": patient.patient_Id,
            "message": "Patient registered successfully" + 
                      (f". Login credentials sent to {email}" if email else "")
        })
    
    finally:
        session_db.close()


# ── NEW ROUTE: CHECK-IN APPOINTMENT ──────────────────────────────────────────

@receptionist_bp.route("/api/receptionist/check-in/<int:appointment_id>", methods=["POST"])
def api_check_in(appointment_id):
    """Check-in a patient - updates appointment status to Checked-In"""
    
    g = _guard()
    if g: 
        return jsonify({"detail": "Forbidden"}), 403
    
    db = next(get_db())
    
    # Get appointment
    appt = db.query(Appointment).filter_by(appointment_Id=appointment_id).first()
    
    if not appt:
        return jsonify({"error": "Appointment not found"}), 404
    
    # Validate current status
    if appt.appointment_status != "Scheduled":
        return jsonify({
            "error": f"Cannot check-in. Current status: {appt.appointment_status}"
        }), 400
    
    # ✅ UPDATE STATUS TO CHECKED-IN
    appt.appointment_status = "Checked-In"
    appt.checked_in_at = datetime.datetime.now()
    db.commit()
    
    # ✅ LOG WITH OPID FORMAT
    _log(db, "CHECK_IN", 
         entity=f"OPID-{str(appointment_id).zfill(6)}", 
         detail=f"Patient ID {appt.patient_Id} checked in for appointment")
    
    return jsonify({
        "ok": True, 
        "opid": appointment_id,
        "status": "Checked-In",
        "checked_in_at": str(appt.checked_in_at),
        "message": f"Patient checked in successfully. OPID: {str(appointment_id).zfill(6)}"
    })


# ── NEW ROUTE: PENDING BILLING ───────────────────────────────────────────────

@receptionist_bp.route("/api/receptionist/pending-billing")
def api_pending_billing():
    """Get all completed appointments without bills - ready for billing"""
    
    g = _guard()
    if g: 
        return jsonify({"detail": "Forbidden"}), 403
    
    db = next(get_db())
    
    # ✅ QUERY COMPLETED APPOINTMENTS WITHOUT BILLS
    # This is the KEY query that makes the flow work!
    rows = db.query(Appointment, Patient, Doctor)\
        .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
        .join(Doctor, Doctor.doct_Id == Appointment.doct_Id)\
        .outerjoin(Bill, Bill.appointment_Id == Appointment.appointment_Id)\
        .filter(
            Appointment.appointment_status == "Completed",
            Bill.bill_id == None  # No bill created yet
        )\
        .order_by(Appointment.completed_at.desc())\
        .all()
    
    return jsonify([{
        "opid": a.appointment_Id,
        "opid_display": f"OPID-{str(a.appointment_Id).zfill(6)}",
        "patient_id": p.patient_Id,
        "patient_name": f"{p.FName} {p.LName}",
        "doctor_name": f"Dr. {d.FName} {d.LName}",
        "appointment_date": str(a.appointment_Date),
        "completed_at": str(a.completed_at) if a.completed_at else "—",
        "time_elapsed": _time_since(a.completed_at) if a.completed_at else "—",
        "needs_billing": True
    } for a, p, d in rows])


# ── MODIFIED: GENERATE BILL (Update to link with OPID) ───────────────────────
# This function should already exist, just ensure it properly links appointment_Id

@receptionist_bp.route("/api/receptionist/generate-bill", methods=["POST"])
def api_generate_bill():
    """Generate bill for a completed appointment using OPID"""
    
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403
    
    db = next(get_db())
    body = request.get_json() or {}
    
    # ✅ GET OPID FROM REQUEST
    opid = body.get("opid") or body.get("appointment_id")
    patient_id = body.get("patient_id")
    
    if not opid:
        return jsonify({"error": "OPID (appointment_id) is required"}), 400
    
    # ✅ VERIFY APPOINTMENT IS COMPLETED
    appt = db.query(Appointment).filter_by(appointment_Id=opid).first()
    
    if not appt:
        return jsonify({"error": "Appointment not found"}), 404
    
    if appt.appointment_status != "Completed":
        return jsonify({
            "error": f"Cannot generate bill. Appointment status: {appt.appointment_status}"
        }), 400
    
    # Check if bill already exists
    existing_bill = db.query(Bill).filter_by(appointment_Id=opid).first()
    if existing_bill:
        return jsonify({
            "error": "Bill already exists for this appointment",
            "bill_id": existing_bill.bill_id
        }), 400
    
    # Get treatments for this appointment
    treatments = db.query(MedicalRecord)\
        .filter_by(appointment_Id=opid)\
        .all()
    
    # Calculate total
    total_amount = 0
    
    # Add consultation fee
    if appt.consultation_fee:
        total_amount += appt.consultation_fee
    
    # Add treatment costs
    for treatment in treatments:
        # Get cost from treatment catalogue
        catalogue = db.query(TreatmentCatalogue)\
            .filter_by(treatment_name=treatment.treatment)\
            .first()
        if catalogue:
            total_amount += catalogue.default_cost
    
    # ✅ CREATE BILL WITH OPID LINK
    bill = Bill(
        patient_Id=patient_id or appt.patient_Id,
        appointment_Id=opid,  # ✅ CRITICAL: Link to OPID
        total_amount=total_amount,
        amount_paid=0,
        balance=total_amount,
        bill_status="Pending",
        bill_date=datetime.date.today(),
        created_by=session.get("user_id")
    )
    
    db.add(bill)
    db.commit()
    
    # ✅ LOG WITH OPID
    _log(db, "GENERATE_BILL",
         entity=f"OPID-{str(opid).zfill(6)}",
         detail=f"Bill #{bill.bill_id} generated for patient {patient_id}, Amount: ₹{total_amount}")
    
    return jsonify({
        "ok": True,
        "bill_id": bill.bill_id,
        "opid": opid,
        "total_amount": float(total_amount),
        "message": f"Bill generated successfully for OPID-{str(opid).zfill(6)}"
    })


@receptionist_bp.route("/api/receptionist/check-in/<int:aid>", methods=["POST"])
def check_in_patient(aid):

    db = next(get_db())

    appt = db.query(Appointment).filter(
        Appointment.appointment_Id == aid
    ).first()

    if not appt:
        return jsonify({"error": "Appointment not found"}), 404

    appt.appointment_status = "Checked-In"
    appt.checked_in_at = datetime.datetime.now()

    db.commit()

    return jsonify({"success": True})

# ════════════════════════════════════════════════════════════════════════
# 📊 ANALYTICS ROUTES — RECEPTIONIST
# ════════════════════════════════════════════════════════════════════════

@receptionist_bp.route("/analytics")
def analytics_page():
    g = _guard()
    if g: return g
    return render_template("receptionist/analytics.html")


# ─────────────────────────────────────────────
# SUMMARY (Today KPIs)
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/summary")
def api_analytics_summary():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())
    today = datetime.date.today()

    return jsonify({
        "today_appointments": db.query(func.count(Appointment.appointment_Id))
            .filter(Appointment.appointment_Date == today).scalar() or 0,

        "checked_in": db.query(func.count(Appointment.appointment_Id))
            .filter(Appointment.appointment_Date == today,
                    Appointment.appointment_status == "Checked-In").scalar() or 0,

        "new_patients_today": db.query(func.count(Patient.patient_Id))
            .filter(func.date(Patient.registration_date) == today).scalar() or 0,

        "pending_payments": db.query(func.count(Bill.bill_id))
            .filter(Bill.bill_status.in_(["Pending","Partial"])).scalar() or 0
    })


# ─────────────────────────────────────────────
# DAILY APPOINTMENT TREND (LAST 30 DAYS)
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/appointment-trend")
def api_appointment_trend():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())
    today = datetime.date.today()

    data = {}
    for i in range(29, -1, -1):
        d = today - datetime.timedelta(days=i)
        count = db.query(func.count(Appointment.appointment_Id))\
            .filter(Appointment.appointment_Date == d).scalar() or 0
        key = d.strftime("%d %b")
        data[key] = count

    return jsonify({
        "labels": list(data.keys()),
        "counts": list(data.values())
    })


# ─────────────────────────────────────────────
# APPOINTMENT STATUS
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/appointment-status")
def api_appointment_status():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())

    rows = db.query(
        Appointment.appointment_status,
        func.count(Appointment.appointment_Id)
    ).group_by(Appointment.appointment_status).all()

    return jsonify({
        "labels": [r[0] for r in rows],
        "counts": [r[1] for r in rows]
    })


# ─────────────────────────────────────────────
# TIME SLOT DISTRIBUTION
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/appointments-by-timeslot")
def api_timeslot():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())

    buckets = {
        "Morning":0,
        "Afternoon":0,
        "Evening":0,
        "Night":0
    }

    for (t,) in db.query(Appointment.slot_time):
        if not t: continue
        h = t.hour

        if 6 <= h < 12: buckets["Morning"] += 1
        elif 12 <= h < 17: buckets["Afternoon"] += 1
        elif 17 <= h < 21: buckets["Evening"] += 1
        else: buckets["Night"] += 1

    return jsonify({
        "labels": list(buckets.keys()),
        "counts": list(buckets.values())
    })


# ─────────────────────────────────────────────
# DOCTOR QUEUE (TODAY)
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/doctor-queue-today")
def api_doctor_queue():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())
    today = datetime.date.today()

    rows = db.query(
        Doctor.FName,
        Doctor.LName,
        func.count(Appointment.appointment_Id)
    ).join(Appointment)\
     .filter(Appointment.appointment_Date == today)\
     .group_by(Doctor.doct_Id).all()

    return jsonify({
        "labels": [f"{r[0]} {r[1]}" for r in rows],
        "counts": [r[2] for r in rows]
    })


# ─────────────────────────────────────────────
# REGISTRATIONS (LAST 6 MONTHS)
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/registrations-per-month")
def api_registrations():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())

    rows = db.query(
        func.to_char(Patient.registration_date, 'YYYY-MM'),
        func.count(Patient.patient_Id)
    ).group_by(func.to_char(Patient.registration_date, 'YYYY-MM')).all()

    data = {r[0]: r[1] for r in rows}

    labels, counts = [], []
    today = datetime.date.today()

    for i in range(5, -1, -1):
        m = today - relativedelta(months=i)
        key = m.strftime("%Y-%m")
        labels.append(key)
        counts.append(data.get(key, 0))

    return jsonify({"labels": labels, "counts": counts})


# ─────────────────────────────────────────────
# PATIENT GENDER
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/patient-gender")
def api_gender():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())

    gender_map = {"Male":0, "Female":0, "Other":0}

    for (g,) in db.query(Patient.Gender):
        if not g: continue
        g = g.lower()

        if g in ["male","m"]:
            gender_map["Male"] += 1
        elif g in ["female","f"]:
            gender_map["Female"] += 1
        else:
            gender_map["Other"] += 1

    return jsonify({
        "labels": list(gender_map.keys()),
        "counts": list(gender_map.values())
    })


# ─────────────────────────────────────────────
# PAYMENT METHODS
# ─────────────────────────────────────────────
@receptionist_bp.route("/api/analytics/payment-methods")
def api_payment_methods():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    db = next(get_db())

    rows = db.query(
        Payment.payment_method,
        func.count(Payment.payment_id)
    ).group_by(Payment.payment_method).all()

    return jsonify({
        "labels": [r[0] for r in rows],
        "counts": [r[1] for r in rows]
    })
from flask import Blueprint, render_template, request, session, redirect, jsonify
from database import get_db
from models import DoctorLeave, FeeMaster, Patient, Appointment, Bill, MedicalRecord, Doctor, Department, AuditLog
from config import PAGINATION
import datetime, math

patient_bp = Blueprint("patient", __name__)

# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────

def _guard_page():
    if not session.get("entity_id"):
        return redirect("/login")
    return None


def _guard_api():
    return session.get("entity_id") is not None

def _patient_id():
    return session.get("entity_id")

# ─────────────────────────────────────────────────────────────
# Page routes
# ─────────────────────────────────────────────────────────────

@patient_bp.route("/patient/profile")
def profile():
    g = _guard_page()
    return g if g else render_template("patient/profile.html")

@patient_bp.route("/patient/appointments")
def appointments():
    g = _guard_page()
    return g if g else render_template("patient/my_appointments.html")

@patient_bp.route("/patient/bills")
def bills():
    g = _guard_page()
    return g if g else render_template("patient/my_bills.html")

@patient_bp.route("/patient/treatments")
def treatments():
    g = _guard_page()
    return g if g else render_template("patient/view_treatments.html")

# ─────────────────────────────────────────────────────────────
# PROFILE
# ─────────────────────────────────────────────────────────────

@patient_bp.route("/api/patient/profile")
def api_profile():

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    db = next(get_db())

    p = db.query(Patient).filter(
        Patient.patient_Id == _patient_id()
    ).first()

    return jsonify({
        "FName": p.FName,
        "LName": p.LName,
        "Gender": p.Gender,
        "Date_Of_Birth": str(p.Date_Of_Birth) if p.Date_Of_Birth else None,
        "contact_No": p.contact_No,
        "pt_Address": p.pt_Address
    })


@patient_bp.route("/api/patient/profile", methods=["PUT"])
def update_profile():

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    db = next(get_db())
    body = request.get_json()

    p = db.query(Patient).filter(
        Patient.patient_Id == _patient_id()
    ).first()

    p.FName = body.get("fname", p.FName)
    p.LName = body.get("lname", p.LName)
    p.Gender = body.get("gender", p.Gender)
    p.contact_No = body.get("phone", p.contact_No)
    p.pt_Address = body.get("address", p.pt_Address)

    if body.get("dob"):
        p.Date_Of_Birth = datetime.date.fromisoformat(body["dob"])

    db.commit()

    return jsonify({"success": True})

# ─────────────────────────────────────────────────────────────
# APPOINTMENTS
# ─────────────────────────────────────────────────────────────

@patient_bp.route("/api/patient/appointments")
def api_appointments():

    if not _guard_api():
        return jsonify({"detail":"Forbidden"}),403

    page     = int(request.args.get("page", 1))
    per_page = PAGINATION["appointments"]
    tab      = request.args.get("tab", "All")

    db    = next(get_db())
    pid   = _patient_id()
    today = datetime.date.today()

    q = db.query(Appointment, Doctor, Department, Bill)\
    .join(Doctor, Doctor.doct_Id == Appointment.doct_Id)\
    .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
    .outerjoin(Bill, Bill.appointment_Id == Appointment.appointment_Id)\
    .filter(Appointment.patient_Id == pid)

    if tab == "Upcoming":
        q = q.filter(
            Appointment.appointment_Date >= today,
            Appointment.appointment_status == "Scheduled"
        )

    elif tab == "Past":
        q = q.filter(
            Appointment.appointment_Date < today,
            Appointment.appointment_status == "Completed"
        )

    elif tab == "Cancelled":
        q = q.filter(
            Appointment.appointment_status == "Cancelled"
        )

    total = q.count()

    rows = q.order_by(
        Appointment.appointment_Date.desc()
    ).offset(
        (page-1)*per_page
    ).limit(per_page).all()

    items = [{
        "appointment_Id": a.appointment_Id,
        "doctor_name": f"{d.FName} {d.LName}",
        "dept_name": dept.dept_Name if dept else "",
        "reason": a.reason,
        "appointment_date": str(a.appointment_Date),
        "appointment_time": a.slot_time.strftime("%H:%M") if a.slot_time else "—",
        "appointment_status": a.appointment_status,

    # 🔥 ADD THIS
            "balance": float(b.balance) if b else 0
        } for a,d,dept,b in rows]

    return jsonify({
        "items": items,
        "total": total,
        "total_pages": math.ceil(total/per_page) or 1
    })


@patient_bp.route("/api/patient/appointments/<int:aid>/cancel", methods=["POST"])
def cancel_appointment(aid):

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    db = next(get_db())

    appt = db.query(Appointment).filter(
        Appointment.appointment_Id == aid
    ).first()

    appt.appointment_status = "Cancelled"

    db.commit()

    return jsonify({"ok": True})

# ─────────────────────────────────────────────────────────────
# BOOK
# ─────────────────────────────────────────────────────────────

@patient_bp.route("/api/patient/book", methods=["POST"])
def patient_book():

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    body = request.get_json()

    db = next(get_db())
    # ─────────────────────────────────────────────
    # CHECK DOCTOR LEAVE
    # ─────────────────────────────────────────────
    appointment_date = datetime.date.fromisoformat(
        body["date"]
    )

    leave = db.query(DoctorLeave).filter(
        DoctorLeave.doct_Id == body["doctor_id"],
        DoctorLeave.status == "Approved",
        DoctorLeave.leave_from <= appointment_date,
        DoctorLeave.leave_to >= appointment_date
    ).first()

    if leave:

        return jsonify({
            "error": "Doctor is on leave for selected date"
        }), 400

        # 🔥 GET DOCTOR
    doctor = db.query(Doctor).filter(
        Doctor.doct_Id == body["doctor_id"]
    ).first()

    # 🔥 FETCH FEE FROM FEEMASTER
    fee = db.query(FeeMaster).filter(
        FeeMaster.doct_Id == body["doctor_id"],
        FeeMaster.fee_type == "consultation",
        FeeMaster.is_active == True
    ).first()

    # 🔥 FALLBACK TO DEPARTMENT
    if not fee:
        fee = db.query(FeeMaster).filter(
            FeeMaster.dept_Id == doctor.dept_Id,
            FeeMaster.doct_Id.is_(None),
            FeeMaster.fee_type == "consultation",
            FeeMaster.is_active == True
        ).first()

    consultation_fee = fee.amount if fee else 0

    slot_str = body.get("slot")

    if not slot_str:
        return jsonify({"error": "Slot is required"}), 400

    print("Received slot:", slot_str)   # debug

    try:
        # 24-hour format → 09:00
        slot_time = datetime.datetime.strptime(slot_str, "%H:%M").time()

    except:
        try:
            # with seconds → 09:00:00
            slot_time = datetime.datetime.strptime(slot_str, "%H:%M:%S").time()

        except:
            try:
                # AM/PM format → 03:00 PM
                slot_time = datetime.datetime.strptime(slot_str, "%I:%M %p").time()

            except:
                return jsonify({"error": f"Invalid slot format: {slot_str}"}), 400


    # 🔥 CREATE APPOINTMENT
    appt = Appointment(
        patient_Id = session["entity_id"],
        doct_Id = body["doctor_id"],
        appointment_Date = body["date"],
        slot_time = slot_time,
        appointment_status = "Scheduled",
        reason = body.get("reason"),
        consultation_fee = consultation_fee   # ✅ VERY IMPORTANT
    )

    db.add(appt)
    db.commit()

    bill = Bill(
        patient_Id = session["entity_id"],
        appointment_Id = appt.appointment_Id,
        total_amount = consultation_fee,
        amount_paid = 0,
        balance = consultation_fee,
        bill_status = "Pending",
        bill_date = datetime.date.today()
    )

    db.add(bill)
    db.commit()

    return {"ok": True}

# ─────────────────────────────────────────────────────────────
# BILLS
# ─────────────────────────────────────────────────────────────
@patient_bp.route("/api/patient/bills")
def api_bills():

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    db = next(get_db())

    rows = db.query(Bill).filter(
        Bill.patient_Id == _patient_id()
    ).all()

    items = []

    total = len(rows)
    paid = 0
    partial = 0
    pending = 0

    for b in rows:

        total_amount = float(b.total_amount or 0)
        amount_paid = float(b.amount_paid or 0)
        balance = total_amount - amount_paid

        # 🔥 STATUS LOGIC
        if balance == 0 and total_amount > 0:
            status = "Paid"
            paid += 1
        elif amount_paid > 0 and balance > 0:
            status = "Partial"
            partial += 1
        else:
            status = "Pending"
            pending += 1

        items.append({
            "bill_Id": b.bill_id,
            "bill_date": str(b.bill_date),
            "notes": b.notes,
            "total_amount": total_amount,
            "amount_paid": amount_paid,
            "balance": balance,
            "bill_status": status
        })

    return jsonify({
        "items": items,
        "total_pages": 1,
        "stats": {
            "total": total,
            "paid": paid,
            "partial": partial,
            "pending": pending
        }
    })

# ─────────────────────────────────────────────────────────────
# TREATMENTS
# ─────────────────────────────────────────────────────────────

@patient_bp.route("/api/patient/treatments")
def api_treatments():

    if not _guard_api():
        return jsonify({"error":"Unauthorized"}),403

    db = next(get_db())

    rows = db.query(
        MedicalRecord, Doctor, Department
    ).outerjoin(
        Doctor, Doctor.doct_Id == MedicalRecord.doct_Id
    ).outerjoin(
        Department, Department.dept_Id == Doctor.dept_Id
    ).filter(
        MedicalRecord.patient_Id == _patient_id()
    ).all()

    items = []

    for r, d, dept in rows:
        items.append({
            "visit_Date": str(r.visit_Date),
            "diagnosis": r.diagnosis,
            "treatment": r.treatment,
            "doctor_name": f"{d.FName} {d.LName}" if d else "—",
            "dept_name": dept.dept_Name if dept else "—"
        })

    return jsonify({
        "items": items,
        "total": len(items),
        "total_pages": 1
    })

@patient_bp.route("/api/fee")
def get_fee():

    if not _guard_api():
        return jsonify({"error": "Unauthorized"}), 403

    doctor_id = request.args.get("doctor")

    db = next(get_db())

    # 🔥 GET DOCTOR
    doctor = db.query(Doctor).filter(
        Doctor.doct_Id == doctor_id
    ).first()

    if not doctor:
        return jsonify({"fee": 0})

    # 🔥 FIRST: doctor-specific fee
    fee = db.query(FeeMaster).filter(
        FeeMaster.doct_Id == doctor_id,
        FeeMaster.fee_type == "consultation",
        FeeMaster.is_active == True
    ).first()

    # 🔥 SECOND: department fallback
    if not fee:
        fee = db.query(FeeMaster).filter(
            FeeMaster.dept_Id == doctor.dept_Id,
            FeeMaster.doct_Id.is_(None),
            FeeMaster.fee_type == "consultation",
            FeeMaster.is_active == True
        ).first()

    return jsonify({
        "fee": fee.amount if fee else 0
    })
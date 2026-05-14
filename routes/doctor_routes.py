from flask import flash

from flask import Blueprint, render_template, request, session, redirect, jsonify, url_for
from sqlalchemy import func, or_
from database import get_db,db, get_db_ctx
from models import (Doctor, Appointment, Patient, MedicalRecord,
                    Department, Bill, AuditLog, TreatmentCatalogue, User, DoctorLeave)
from config import PAGINATION
import datetime, math
from datetime import datetime, date
from sqlalchemy import case

doctor_bp = Blueprint("doctor", __name__, url_prefix="/doctor")

# ── Auth guard ────────────────────────────────────────────────────────────────

def _guard():
    if session.get("role") not in ("Doctor",):
        return redirect("/login")
    return None

def _doctor_id():
    db = next(get_db())

    user_id = session.get("user_id")

    doctor = db.query(Doctor)\
        .filter(Doctor.User_ID == user_id)\
        .first()

    return doctor.doct_Id if doctor else None

def _log(db, action, entity=None, detail=None):
    db.add(AuditLog(
        user_id=session.get("user_id"), user_name=session.get("user_name",""),
        role="Doctor", action=action, entity=entity, detail=detail,
        timestamp=datetime.now()
    ))
    db.commit()

# ── Page routes ───────────────────────────────────────────────────────────────

@doctor_bp.route("/calendar")
def calendar():
    g = _guard(); return g if g else render_template("doctor/calendar.html")

@doctor_bp.route("/appointments")
def appointments():
    g = _guard(); return g if g else render_template("doctor/appointments.html")

@doctor_bp.route("/patient-history")
def patient_history():
    g = _guard(); return g if g else render_template("doctor/patient_history.html")


@doctor_bp.route("/profile")
def profile():
    g = _guard(); return g if g else render_template("doctor/profile.html")

@doctor_bp.route("/dashboard")
def dashboard():
    g = _guard()
    if g: return g
    return render_template("/doctor/dashboard.html")

# ══════════════════════════════════════════════════════════════════════════════
#  API — Calendar stats
# ══════════════════════════════════════════════════════════════════════════════
@doctor_bp.route("/api/calendar-stats")
def api_calendar_stats():

    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    db  = next(get_db())
    did = _doctor_id()

    if not did:
        return jsonify({
            "total": 0,
            "in_progress": 0,
            "checked_in": 0,
            "scheduled": 0
        })

    today = datetime.now().date()

    today_q = db.query(Appointment).filter(
        Appointment.doct_Id == did,
        func.date(Appointment.appointment_Date) == today
    )

    total = today_q.count()

    in_progress = today_q.filter(
        func.lower(func.trim(Appointment.appointment_status))
        == "in-progress"
    ).count()

    checked_in = today_q.filter(
        func.lower(func.trim(Appointment.appointment_status))
        == "checked-in"
    ).count()

    scheduled = today_q.filter(
        func.lower(func.trim(Appointment.appointment_status))
        == "scheduled"
    ).count()

    return jsonify({
        "total": total,
        "in_progress": in_progress,
        "checked_in": checked_in,
        "scheduled": scheduled
    })
# ══════════════════════════════════════════════════════════════════════════════
#  API — Appointments (calendar + list view)
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/appointments")
def api_doctor_appointments():

    g = _guard()
    if g: 
        return jsonify({"detail":"Forbidden"}), 403

    page     = int(request.args.get("page", 1))
    per_page = PAGINATION["appointments"]
    date_str = request.args.get("date","")
    tab      = request.args.get("tab","Today")
    search   = request.args.get("search","").strip()

    db  = next(get_db())
    did = _doctor_id()

    today = datetime.now().date()

    q = db.query(Appointment, Patient)\
          .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
          .filter(Appointment.doct_Id == did)


    # ----- tab filter -----
    if date_str:
        try:
            d = date.fromisoformat(date_str)
            q = q.filter(Appointment.appointment_Date == d)
        except ValueError:
            pass

    elif tab == "Today":
        q = q.filter(func.date(Appointment.appointment_Date) == today)

    elif tab == "Upcoming":
        q = q.filter(
            func.date(Appointment.appointment_Date) > today,
            Appointment.appointment_status.in_(["Scheduled","Checked-In"])
        )

    elif tab == "Past":
        q = q.filter(func.date(Appointment.appointment_Date) < today)


    # ----- search -----
    if search:
        q = q.filter(or_(
            Patient.FName.ilike(f"%{search}%"),
            Patient.LName.ilike(f"%{search}%")
        ))


    total = q.count()

    rows = q.order_by(
        Appointment.appointment_Date.desc()
    ).offset(
        (page-1)*per_page
    ).limit(
        per_page
    ).all()


    # ---------- AUTO COMPLETE ----------
    now = datetime.now()

    for appt, patient in rows:

        if (
            appt.appointment_status in ["Scheduled","Checked-In"]
            and appt.appointment_Date == now.date()
            and appt.slot_time
        ):

            appt_dt = datetime.combine(
                appt.appointment_Date,
                appt.slot_time
            )

            if appt_dt < now:
                appt.appointment_status = "Completed"
                appt.completed_at = datetime.now()

    db.commit()


    items = [{
        "appointment_Id"    : a.appointment_Id,
        "patient_name"      : f"{p.FName} {p.LName}",
        "patient_Id"        : p.patient_Id,
        "reason"            : a.reason,
        "appointment_date"  : str(a.appointment_Date),
        "appointment_time": a.slot_time.strftime("%H:%M") if a.slot_time else None,
        "appointment_status": a.appointment_status,
    } for a, p in rows]


    return jsonify({
        "items": items,
        "total": total,
        "total_pages": math.ceil(total/per_page) or 1
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Active appointments for treatment dropdown
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/active-appointments")
def api_active_appointments():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db  = next(get_db())
    did = _doctor_id()

    rows = db.query(Appointment, Patient)\
             .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
             .filter(Appointment.doct_Id == did,
                     Appointment.appointment_status.in_(["Checked-In","In-Progress"]))\
             .order_by(Appointment.appointment_Date.desc()).all()

    return jsonify([{
        "appointment_Id"    : a.appointment_Id,
        "patient_name"      : f"{p.FName} {p.LName}",
        "patient_Id"        : p.patient_Id,
        "appointment_date"  : str(a.appointment_Date),
        "appointment_time": str(a.slot_time) if a.slot_time else "—",
        "appointment_status": a.appointment_status,
    } for a, p in rows])

# ══════════════════════════════════════════════════════════════════════════════
#  API — Single appointment detail
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/appointment/<int:aid>")
def api_appointment_detail(aid):
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db   = next(get_db())
    row  = db.query(Appointment, Patient)\
             .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
             .filter(Appointment.appointment_Id == aid).first()
    if not row:
        return jsonify({"detail":"Not found"}), 404
    a, p = row
    return jsonify({
        "appointment_Id"    : a.appointment_Id,
        "patient_name"      : f"{p.FName} {p.LName}",
        "patient_Id"        : p.patient_Id,
        "reason"            : a.reason,
        "appointment_date"  : str(a.appointment_Date),
          "appointment_time": str(a.slot_time) if a.slot_time else "—",
        "appointment_status": a.appointment_status,
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Treatment catalogue
# ══════════════════════════════════════════════════════════════════════════════
@doctor_bp.route("/api/treatment-catalogue")
def api_treatment_catalogue():

    g = _guard()
    if g:
        return jsonify({"detail":"Forbidden"}),403

    db = next(get_db())

    rows = db.query(TreatmentCatalogue)\
        .filter(
            TreatmentCatalogue.is_active == True
        )\
        .order_by(
            TreatmentCatalogue.treatment_name
        ).all()

    # remove duplicates
    seen = set()
    unique = []

    for r in rows:
        if r.treatment_name not in seen:
            seen.add(r.treatment_name)
            unique.append(r)

    return jsonify([{
        "id": r.treatment_id,
        "name": r.treatment_name,
        "default_cost": r.default_cost
    } for r in unique])


# ══════════════════════════════════════════════════════════════════════════════
#  API — Search patients
# ══════════════════════════════════════════════════════════════════════════════
@doctor_bp.route("/api/search-patients")
def api_search_patients():
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    q_str = request.args.get("q", "").strip()

    db = next(get_db())

    query = db.query(Patient)

    if q_str:
        # 🔥 If input is numeric → search by ID
        if q_str.isdigit():
            query = query.filter(Patient.patient_Id == int(q_str))
        else:
            # 🔥 Otherwise → search by name
            query = query.filter(or_(
                Patient.FName.ilike(f"%{q_str}%"),
                Patient.LName.ilike(f"%{q_str}%")
            ))

    pts = query.limit(10).all()

    return jsonify([
        {
            "patient_Id": p.patient_Id,
            "FName": p.FName,
            "LName": p.LName
        }
        for p in pts
    ])

# ══════════════════════════════════════════════════════════════════════════════
#  API — Patient detail
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/patient/<int:pid>")
def api_patient_detail(pid):
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db = next(get_db())
    p  = db.query(Patient).filter(Patient.patient_Id == pid).first()
    if not p:
        return jsonify({"detail":"Not found"}), 404
    return jsonify({
        "patient_Id"   : p.patient_Id,
        "FName"        : p.FName, "LName": p.LName,
        "Gender"       : p.Gender,
        "Date_Of_Birth": str(p.Date_Of_Birth) if p.Date_Of_Birth else None,
        "contact_No"   : p.contact_No,
        "pt_Address"   : p.pt_Address,
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Patient treatment history (read-only)
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/patient-history/<int:pid>")
def api_patient_history(pid):
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    page     = int(request.args.get("page", 1))
    per_page = PAGINATION["treatments"]
    db       = next(get_db())

    q = db.query(MedicalRecord, Doctor)\
          .outerjoin(Doctor, Doctor.doct_Id == MedicalRecord.doct_Id)\
          .filter(MedicalRecord.patient_Id == pid)\
          .order_by(MedicalRecord.visit_Date.desc())

    total = q.count()
    rows  = q.offset((page-1)*per_page).limit(per_page).all()

    items = [{
        "record_Id"  : r.record_Id,
        "visit_Date" : str(r.visit_Date) if r.visit_Date else "—",
        "diagnosis"  : r.diagnosis,
        "treatment"  : r.treatment,
        "doctor_name": f"Dr. {d.FName} {d.LName}" if d else "—",
    } for r, d in rows]

    return jsonify({"items": items, "total": total,
                    "total_pages": math.ceil(total/per_page) or 1})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Doctor profile
# ══════════════════════════════════════════════════════════════════════════════

@doctor_bp.route("/api/profile")
def api_doctor_profile():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db  = next(get_db())
    did = _doctor_id()
    doc = db.query(Doctor, Department)\
            .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
            .filter(Doctor.doct_Id == did).first()
    if not doc:
        return jsonify({"detail":"Not found"}), 404
    d, dept = doc
    user = db.query(User).filter(User.User_ID == d.User_ID).first()
    return jsonify({
        "doct_Id"     : d.doct_Id,
        "FName"       : d.FName, "LName": d.LName,
        "Gender"      : d.Gender,
        "contact_No"  : d.contact_No,
        "surgeon_Type": d.surgeon_Type,
        "office_No"   : d.office_No,
        "dept_Name"   : dept.dept_Name if dept else "—",
        "email"       : user.Email if user else "—",
    })

@doctor_bp.route("/api/profile", methods=["PUT"])
def api_update_profile():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    body = request.get_json() or {}
    db   = next(get_db())
    doc  = db.query(Doctor).filter(Doctor.doct_Id == _doctor_id()).first()
    if not doc:
        return jsonify({"detail":"Not found"}), 404
    doc.FName      = body.get("fname", doc.FName)
    doc.LName      = body.get("lname", doc.LName)
    doc.contact_No = body.get("contact_no", doc.contact_No)
    doc.office_No  = body.get("office_no", doc.office_No)
    db.commit()
    _log(db, "UPDATE_PROFILE", detail="Doctor updated own profile")
    return jsonify({"ok": True})

@doctor_bp.route("/api/appointments/<int:id>/start", methods=["POST"])
def start_appt(id):
    """Start treatment for a checked-in appointment"""
    
    db = next(get_db())
    
    # Get appointment
    a = db.query(Appointment).get(id)
    
    if not a:
        return jsonify({"error": "Appointment not found"}), 404
    
    # ✅ VALIDATE STATUS - Must be Checked-In
    if a.appointment_status != "Checked-In":
        return jsonify({
            "error": f"Cannot start treatment. Patient must be checked-in first. Current status: {a.appointment_status}",
            "current_status": a.appointment_status
        }), 400
    
    # ✅ UPDATE STATUS TO IN-PROGRESS
    a.appointment_status = "In-Progress"
    db.commit()
    
    # ✅ LOG WITH OPID FORMAT
    _log(db, "START_TREATMENT", 
         entity=f"OPID-{str(id).zfill(6)}", 
         detail=f"Doctor started treatment for patient {a.patient_Id}")
    
    return jsonify({
        "ok": True,
        "opid": id,
        "status": "In-Progress",
        "message": f"Treatment started for OPID-{str(id).zfill(6)}"
    })


# ── MODIFIED: ADD TREATMENT (Replace existing function around line 307) ───────

@doctor_bp.route("/api/add-treatment", methods=["POST"])
def api_add_treatment():
    """Add treatment and mark appointment as completed"""
    
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    body = request.get_json() or {}

    if not body.get("appointment_id"):
        return jsonify({"error": "appointment_id (OPID) is required"}), 400

    db = next(get_db())
    did = _doctor_id()
    
    # ✅ GET AND VALIDATE APPOINTMENT
    appt_id = body.get("appointment_id")
    appt = db.query(Appointment).filter_by(appointment_Id=appt_id).first()
    
    if not appt:
        return jsonify({"error": "Appointment not found"}), 404
    
    # ✅ VALIDATE STATUS - Should be In-Progress
    if appt.appointment_status != "In-Progress":
        return jsonify({
            "error": f"Treatment can only be completed for in-progress appointments. Current status: {appt.appointment_status}",
            "current_status": appt.appointment_status
        }), 400

    # ────── DATE HANDLING ──────
    try:
        visit_date = date.fromisoformat(
            body.get("visit_date", str(date.today()))
        )
    except:
        visit_date = date.today()

    # ────── FOLLOW-UP HANDLING ──────
    next_visit = None
    followup_required = False

    if body.get("next_visit"):
        try:
            next_visit = date.fromisoformat(body.get("next_visit"))
            followup_required = True
        except:
            pass

    # ────── GET COST FROM CATALOGUE ──────
    treatment_name = body.get("treatment")
    
    t = db.query(TreatmentCatalogue)\
        .filter(TreatmentCatalogue.treatment_name == treatment_name)\
        .first()
    
    cost = float(t.default_cost) if t else 0

    # ────── SAVE MEDICAL RECORD ──────
    record = MedicalRecord(
        doct_Id=did,
        patient_Id=body.get("patient_id"),
        appointment_Id=appt_id,  # ✅ Link to OPID
        visit_Date=visit_date,
        diagnosis=body.get("diagnosis", ""),
        treatment=treatment_name,
        prescription=body.get("prescription", ""),
        followup_required=followup_required,
        next_Visit=next_visit,
        # Add vitals if provided
        curr_Weight=body.get("weight"),
        curr_height=body.get("height"),
        curr_Blood_Pressure=body.get("blood_pressure"),
        curr_Temp_F=body.get("temperature")
    )

    db.add(record)
    db.flush()
    
    db.commit()
    
    # ✅ LOG WITH OPID - This is critical for receptionist to see
    _log(db, "ADD_TREATMENT",
        entity=f"OPID-{str(appt_id).zfill(6)}",
        detail=f"Treatment added for patient {body.get('patient_id')}. Treatment: {treatment_name}")
    
    return jsonify({
        "ok": True,
        "record_id": record.record_Id,
        "opid": appt_id,
        "opid_display": f"OPID-{str(appt_id).zfill(6)}",
        "cost": cost,
        "status": "In-Progress",
        "message": "Treatment added successfully. Complete the appointment to enable billing."
    })


# ── OPTIONAL: ADD ENDPOINT TO VIEW APPOINTMENT HISTORY ────────────────────────

@doctor_bp.route("/api/appointment/<int:opid>/history")
def api_appointment_history(opid):
    """Get complete history for an OPID including all treatments and records"""
    
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403
    
    db = next(get_db())
    
    # Get appointment
    appt = db.query(Appointment, Patient, Doctor)\
        .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
        .join(Doctor, Doctor.doct_Id == Appointment.doct_Id)\
        .filter(Appointment.appointment_Id == opid)\
        .first()
    
    if not appt:
        return jsonify({"error": "Appointment not found"}), 404
    
    a, p, d = appt
    
    # Get all medical records for this appointment
    records = db.query(MedicalRecord)\
        .filter_by(appointment_Id=opid)\
        .all()
    
    # Get bill if exists
    bill = db.query(Bill).filter_by(appointment_Id=opid).first()
    
    return jsonify({
        "opid": opid,
        "opid_display": f"OPID-{str(opid).zfill(6)}",
        "patient": {
            "id": p.patient_Id,
            "name": f"{p.FName} {p.LName}",
            "gender": p.Gender,
            "dob": str(p.Date_Of_Birth) if p.Date_Of_Birth else None,
            "contact": p.contact_No
        },
        "doctor": {
            "id": d.doct_Id,
            "name": f"Dr. {d.FName} {d.LName}"
        },
        "appointment": {
            "date": str(a.appointment_Date),
            "time": str(a.slot_time) if a.slot_time else None,
            "status": a.appointment_status,
            "reason": a.reason,
            "created_at": str(a.created_at) if a.created_at else None,
            "checked_in_at": str(a.checked_in_at) if a.checked_in_at else None,
            "completed_at": str(a.completed_at) if a.completed_at else None
        },
        "treatments": [{
            "record_id": r.record_Id,
            "visit_date": str(r.visit_Date) if r.visit_Date else None,
            "diagnosis": r.diagnosis,
            "treatment": r.treatment,
            "prescription": r.prescription,
            "followup_required": r.followup_required,
            "next_visit": str(r.next_Visit) if r.next_Visit else None
        } for r in records],
        "billing": {
            "bill_id": bill.bill_id if bill else None,
            "total_amount": float(bill.total_amount) if bill else None,
            "status": bill.bill_status if bill else "Not Generated"
        } if bill else None
    })

@doctor_bp.route("/api/appointments/<int:id>/complete", methods=["POST"])
def complete_appt(id):
    db = next(get_db())

    a = db.query(Appointment).get(id)

    if not a:
        return jsonify({"error": "Appointment not found"}), 404

    if a.appointment_status != "In-Progress":
        return jsonify({
            "error": f"Only in-progress appointments can be completed. Current status: {a.appointment_status}"
        }), 400

    a.appointment_status = "Completed"
    a.completed_at = datetime.now()

    db.commit()

    _log(db, "COMPLETE_TREATMENT",
         entity=f"OPID-{str(id).zfill(6)}",
         detail=f"Appointment completed for patient {a.patient_Id}")

    return jsonify({
        "ok": True,
        "status": "Completed",
        "message": "Appointment completed successfully. Ready for billing."
    })
# ══════════════════════════════════════════════════════════════════════
# 📊 ANALYTICS ROUTES — Doctor
# ══════════════════════════════════════════════════════════════════════

@doctor_bp.route("/analytics")
def analytics():
    g = _guard()
    if g: return g
    return render_template("doctor/dashboard.html")


# ── SUMMARY KPIs ──────────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-summary")
def api_my_summary():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        today = date.today()

        total_appts = db_s.query(func.count(Appointment.appointment_Id))\
            .filter(Appointment.doct_Id == did).scalar() or 0

        today_appts = db_s.query(func.count(Appointment.appointment_Id))\
            .filter(Appointment.doct_Id == did,
                    Appointment.appointment_Date == today).scalar() or 0

        completed = db_s.query(func.count(Appointment.appointment_Id))\
            .filter(Appointment.doct_Id == did,
                    Appointment.appointment_status == "Completed").scalar() or 0

        unique_patients = db_s.query(func.count(func.distinct(Appointment.patient_Id)))\
            .filter(Appointment.doct_Id == did).scalar() or 0

        return jsonify({
            "total_appointments": total_appts,
            "today_appointments": today_appts,
            "completed_appointments": completed,
            "unique_patients": unique_patients
        })


# ── APPOINTMENT TREND ─────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-appointment-trend")
def api_my_appointment_trend():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        rows = db_s.query(
            func.to_char(Appointment.appointment_Date, 'YYYY-MM'),
            func.count(Appointment.appointment_Id)
        ).filter(Appointment.doct_Id == did)\
         .group_by(func.to_char(Appointment.appointment_Date, 'YYYY-MM'))\
         .order_by(func.to_char(Appointment.appointment_Date, 'YYYY-MM')).all()

        return jsonify({
            "labels": [r[0] for r in rows],
            "counts": [r[1] for r in rows]
        })


# ── APPOINTMENT STATUS ────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-appointment-status")
def api_my_appointment_status():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        rows = db_s.query(
            Appointment.appointment_status,
            func.count(Appointment.appointment_Id)
        ).filter(Appointment.doct_Id == did)\
         .group_by(Appointment.appointment_status).all()

        return jsonify({
            "labels": [r[0] for r in rows],
            "counts": [r[1] for r in rows]
        })


# ── TIME SLOT DISTRIBUTION ────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-timeslot-distribution")
def api_my_timeslot_distribution():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        slots = db_s.query(Appointment.slot_time)\
            .filter(Appointment.doct_Id == did,
                    Appointment.slot_time != None).all()

        buckets = {
            "Morning (6-12)": 0,
            "Afternoon (12-17)": 0,
            "Evening (17-21)": 0
        }

        for (t,) in slots:
            h = t.hour
            if 6 <= h < 12:
                buckets["Morning (6-12)"] += 1
            elif 12 <= h < 17:
                buckets["Afternoon (12-17)"] += 1
            else:
                buckets["Evening (17-21)"] += 1

        return jsonify({
            "labels": list(buckets.keys()),
            "counts": list(buckets.values())
        })


# ── TOP DIAGNOSES ─────────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-top-diagnoses")
def api_my_top_diagnoses():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        rows = db_s.query(
            MedicalRecord.diagnosis,
            func.count(MedicalRecord.record_Id)
        ).filter(MedicalRecord.doct_Id == did,
                 MedicalRecord.diagnosis != None)\
         .group_by(MedicalRecord.diagnosis)\
         .order_by(func.count(MedicalRecord.record_Id).desc())\
         .limit(10).all()

        return jsonify({
            "labels": [r[0][:40] if r[0] else "N/A" for r in rows],
            "counts": [r[1] for r in rows]
        })


# ── PATIENT AGE GROUPS ────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-patient-age-groups")
def api_my_patient_age_groups():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        rows = db_s.query(Patient.Date_Of_Birth)\
            .join(Appointment, Appointment.patient_Id == Patient.patient_Id)\
            .filter(Appointment.doct_Id == did,
                    Patient.Date_Of_Birth != None).all()

        today = date.today()

        groups = {"0-18":0,"19-35":0,"36-50":0,"51-65":0,"65+":0}

        for (dob,) in rows:
            age = (today - dob).days // 365

            if age <= 18: groups["0-18"] += 1
            elif age <= 35: groups["19-35"] += 1
            elif age <= 50: groups["36-50"] += 1
            elif age <= 65: groups["51-65"] += 1
            else: groups["65+"] += 1

        return jsonify({
            "labels": list(groups.keys()),
            "counts": list(groups.values())
        })


# ── NO-SHOW TREND ─────────────────────────────────────────────────────
@doctor_bp.route("/api/analytics/my-noshow-trend")
def api_my_noshow_trend():
    g = _guard()
    if g: return g

    did = _doctor_id()
    if not did:
        return jsonify({"detail": "Doctor not found"}), 404

    with get_db_ctx() as db_s:
        rows = db_s.query(
            func.to_char(Appointment.appointment_Date, 'YYYY-MM'),
            func.count(Appointment.appointment_Id),
            func.sum(
                case(
                    (Appointment.appointment_status == "No-show", 1),
                    else_=0
                )
            )
        ).filter(Appointment.doct_Id == did)\
         .group_by(func.to_char(Appointment.appointment_Date, 'YYYY-MM'))\
         .order_by(func.to_char(Appointment.appointment_Date, 'YYYY-MM')).all()

        return jsonify({
            "labels": [r[0] for r in rows],
            "total": [r[1] for r in rows],
            "noshows": [int(r[2] or 0) for r in rows]
        })
    

@doctor_bp.route("/apply_leave", methods=["GET", "POST"])
def apply_leave():

    did = _doctor_id()

    if not did:
        flash("Doctor profile not found", "danger")
        return redirect("/doctor/dashboard")

    if request.method == "POST":

        leave = DoctorLeave(
            doct_Id=did,
            leave_from=request.form["leave_from"],
            leave_to=request.form["leave_to"],
            reason=request.form["reason"]
        )

        db.session.add(leave)
        db.session.commit()

        flash("Leave request submitted", "success")

        return redirect(url_for("doctor.apply_leave"))

    leaves = DoctorLeave.query.filter_by(
        doct_Id=did
    ).all()

    return render_template(
        "doctor/apply_leave.html",
        leaves=leaves
    )


# ─────────────────────────────────────────────────────────────────────────────
# DOCTOR LEAVES — cancel a pending request
# ─────────────────────────────────────────────────────────────────────────────

@doctor_bp.route("/cancel_leave/<int:leave_id>")
def cancel_leave(leave_id):
    """
    Allow a doctor to cancel their own leave request, but only while
    it is still Pending. Approved / Rejected leaves cannot be withdrawn
    this way (contact the admin instead).
    """

    # Verify the leave belongs to the currently logged-in doctor
    leave = DoctorLeave.query.filter_by(
        leave_id = leave_id,
        doct_Id  = session.get("linked_id")
    ).first_or_404()

    if leave.status != "Pending":
        flash(
            f"Only pending requests can be cancelled. "
            f"This request is already {leave.status}.",
            "danger"
        )
        return redirect(url_for("doctor.apply_leave"))

    db.session.delete(leave)
    db.session.commit()

    flash("Leave request cancelled successfully.", "success")
    return redirect(url_for("doctor.apply_leave"))
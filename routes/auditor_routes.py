from flask import Blueprint, render_template, request, session, redirect, jsonify, make_response
from sqlalchemy import func
from database import get_db
from models import (AuditLog, Appointment, Patient, Doctor, Department,
                    Bill, Payment, MedicalRecord)
from config import PAGINATION
import datetime, math, csv, io
from models import RoomRecord, BedRecord, Treatment, TreatmentCatalogue


auditor_bp = Blueprint("auditor", __name__)

auditor_bp = Blueprint(
    "auditor",
    __name__,
    url_prefix="/auditor"
)

# ── Auth guard ────────────────────────────────────────────────────────────────

def _guard():
    if session.get("role") not in ("Auditor", "Admin"):
        return redirect("/login")
    return None

@auditor_bp.route("/dashboard")
def dashboard():
    g = _guard()
    return g if g else render_template("auditor/dashboard.html")

# ── Page routes ───────────────────────────────────────────────────────────────

@auditor_bp.route("/reports")
def reports():
    g = _guard(); return g if g else render_template("auditor/view_reports.html")

@auditor_bp.route("/billing-reports")
def billing_reports():
    g = _guard(); return g if g else render_template("auditor/billing_reports.html")

@auditor_bp.route("/export")
def export():
    g = _guard(); return g if g else render_template("auditor/export_reports.html")

@auditor_bp.route("/audit-logs")
def audit_logs():
    g = _guard(); return g if g else render_template("auditor/audit_logs.html")

# ══════════════════════════════════════════════════════════════════════════════
#  API — View Reports (clinical stats)
# ══════════════════════════════════════════════════════════════════════════════

@auditor_bp.route("/api/reports")
def api_reports():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    date_from = request.args.get("date_from","")
    date_to   = request.args.get("date_to","")
    db        = next(get_db())

    pt_q  = db.query(func.count(Patient.patient_Id))
    ap_q  = db.query(func.count(Appointment.appointment_Id))
    if date_from:
        ap_q = ap_q.filter(Appointment.appointment_Date >= date_from)
    if date_to:
        ap_q = ap_q.filter(Appointment.appointment_Date <= date_to)

    total_patients = pt_q.scalar() or 0
    appointments   = ap_q.scalar() or 0
    active_doctors = db.query(func.count(Doctor.doct_Id)).scalar() or 0
    departments    = db.query(func.count(Department.dept_Id)).scalar() or 0

    # Appointments by department
    dept_rows = db.query(Department.dept_Name, func.count(Appointment.appointment_Id))\
                  .outerjoin(Doctor,      Doctor.dept_Id == Department.dept_Id)\
                  .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)
    if date_from:
        dept_rows = dept_rows.filter(Appointment.appointment_Date >= date_from)
    if date_to:
        dept_rows = dept_rows.filter(Appointment.appointment_Date <= date_to)
    dept_rows = dept_rows.group_by(Department.dept_Name).all()

    # Doctor performance
    doc_rows = db.query(Doctor, Department,
                        func.count(Appointment.appointment_Id).label("total"),
                        func.count(Appointment.appointment_Id).filter(
                            Appointment.appointment_status == "Completed").label("completed"))\
                 .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
                 .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
                 .group_by(Doctor.doct_Id, Department.dept_Id)\
                 .order_by(func.count(Appointment.appointment_Id).desc())\
                 .limit(10).all()

    return jsonify({
        "total_patients": total_patients,
        "appointments"  : appointments,
        "active_doctors": active_doctors,
        "departments"   : departments,
        "dept_labels"   : [r[0] for r in dept_rows],
        "dept_counts"   : [r[1] for r in dept_rows],
        "doctor_perf"   : [{
            "name"     : f"Dr. {r.Doctor.FName} {r.Doctor.LName}" if r.Doctor.FName and r.Doctor.LName else "Unknown Doctor",
            "dept"     : r.Department.dept_Name if r.Department else "—",
            "total"    : r.total,
            "completed": r.completed,
        } for r in doc_rows],
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Billing reports
# ══════════════════════════════════════════════════════════════════════════════

@auditor_bp.route("/api/billing-reports")
def api_billing_reports():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403
    db = next(get_db())

    total_rev  = db.query(func.coalesce(func.sum(Bill.total_amount), 0)).scalar() or 0
    collected  = db.query(func.coalesce(func.sum(Bill.amount_paid),  0)).scalar() or 0
    pending_amt= db.query(func.coalesce(func.sum(Bill.balance), 0))\
                   .filter(Bill.bill_status == "Pending").scalar() or 0
    partial_amt= db.query(func.coalesce(func.sum(Bill.balance), 0))\
                   .filter(Bill.bill_status == "Partial").scalar() or 0

    def fmt(v):
        return f"{v/100000:.1f}L" if v >= 100000 else f"{int(v):,}"

    status_rows = db.query(Bill.bill_status, func.count(Bill.bill_id))\
                    .group_by(Bill.bill_status).all()

    dept_rows = db.query(Department.dept_Name,
                         func.count(Bill.bill_id).label("bills"),
                         func.coalesce(func.sum(Bill.total_amount),0).label("rev"))\
                  .outerjoin(Doctor,      Doctor.dept_Id     == Department.dept_Id)\
                  .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
                  .outerjoin(Bill,        Bill.appointment_Id == Appointment.appointment_Id)\
                  .group_by(Department.dept_Name)\
                  .order_by(func.coalesce(func.sum(Bill.total_amount),0).desc()).all()

    return jsonify({
        "total_revenue": fmt(total_rev),
        "collected"    : fmt(collected),
        "pending"      : fmt(pending_amt),
        "partial"      : fmt(partial_amt),
        "status_labels": [r[0] for r in status_rows],
        "status_counts": [r[1] for r in status_rows],
        "dept_revenue" : [{"dept": r[0], "bills": r[1], "revenue": fmt(r[2])} for r in dept_rows],
    })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Export CSV
# ══════════════════════════════════════════════════════════════════════════════

@auditor_bp.route("/api/export")
def api_export():
    g = _guard()
    if g: return jsonify({"detail":"Forbidden"}), 403

    report_type = request.args.get("type","appointments")
    date_from   = request.args.get("date_from","")
    date_to     = request.args.get("date_to","")
    dept_f      = request.args.get("dept","")
    db          = next(get_db())

    output = io.StringIO()
    writer = csv.writer(output)

    if report_type == "appointments":
        writer.writerow(["ID","Patient","Doctor","Department","Date","Status","Reason"])
        q = db.query(Appointment, Patient, Doctor, Department)\
              .join(Patient,    Patient.patient_Id == Appointment.patient_Id)\
              .join(Doctor,     Doctor.doct_Id     == Appointment.doct_Id)\
              .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)
        if date_from: q = q.filter(Appointment.appointment_Date >= date_from)
        if date_to:   q = q.filter(Appointment.appointment_Date <= date_to)
        if dept_f:    q = q.filter(Doctor.dept_Id == int(dept_f))
        for a, p, d, dept in q.all():
            writer.writerow([a.appointment_Id, f"{p.FName} {p.LName}",
                             f"Dr. {d.FName} {d.LName}",
                             dept.dept_Name if dept else "—",
                             a.appointment_Date, a.appointment_status, a.reason])

    elif report_type == "billing":
        writer.writerow(["Bill#","Patient","Total","Paid","Balance","Status","Date"])
        q = db.query(Bill, Patient).join(Patient, Patient.patient_Id == Bill.patient_Id)
        if date_from: q = q.filter(Bill.bill_date >= date_from)
        if date_to:   q = q.filter(Bill.bill_date <= date_to)
        for b, p in q.all():
            writer.writerow([f"BL-{str(b.bill_id).zfill(4)}", f"{p.FName} {p.LName}",
                             b.total_amount, b.amount_paid, b.balance, b.bill_status, b.bill_date])

    elif report_type == "patients":
        writer.writerow(["ID","First Name","Last Name","Gender","DOB","Phone","Address"])
        for p in db.query(Patient).all():
            writer.writerow([f"PT-{str(p.patient_Id).zfill(4)}", p.FName, p.LName,
                             p.Gender, p.Date_Of_Birth, p.contact_No, p.pt_Address])

    elif report_type == "doctor_performance":
        writer.writerow(["Doctor","Department","Total Appts","Completed"])
        rows = db.query(Doctor, Department,
                        func.count(Appointment.appointment_Id).label("total"),
                        func.count(Appointment.appointment_Id).filter(
                            Appointment.appointment_status == "Completed").label("done"))\
                 .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
                 .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
                 .group_by(Doctor.doct_Id, Department.dept_Id).all()
        for d, dept, total, done in rows:
            writer.writerow([f"Dr. {d.FName} {d.LName}",
                             dept.dept_Name if dept else "—", total, done])

    elif report_type == "audit_log":
        writer.writerow(["Timestamp","User","Role","Action","Entity","Detail"])
        q = db.query(AuditLog)
        if date_from: q = q.filter(AuditLog.timestamp >= date_from)
        if date_to:   q = q.filter(AuditLog.timestamp <= date_to)
        for l in q.order_by(AuditLog.timestamp.desc()).all():
            writer.writerow([l.timestamp, l.user_name, l.role, l.action, l.entity, l.detail])

    # Log the export
    db.add(AuditLog(
        user_id=session.get("user_id"), user_name=session.get("user_name",""),
        role=session.get("role",""), action="EXPORT_REPORT",
        entity=report_type,
        detail=f"date_from={date_from} date_to={date_to}",
        timestamp=datetime.datetime.now()
    ))
    db.commit()

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"]        = "text/csv"
    resp.headers["Content-Disposition"] = f'attachment; filename="HMS_{report_type}.csv"'
    return resp

# ══════════════════════════════════════════════════════════════════════════════
#  API — Audit logs (shared: admin + auditor + receptionist)
# ══════════════════════════════════════════════════════════════════════════════

@auditor_bp.route("/api/audit-logs")
def api_audit_logs():
    role = session.get("role","")
    if role not in ("Admin","Auditor","Receptionist"):
        return jsonify({"detail":"Forbidden"}), 403

    page      = int(request.args.get("page", 1))
    per_page  = PAGINATION["audit_logs"]
    user_f    = request.args.get("user","").strip()
    role_f    = request.args.get("role","").strip()
    action_f  = request.args.get("action","").strip()
    date_from = request.args.get("date_from","")
    date_to   = request.args.get("date_to","")
    db        = next(get_db())

    q = db.query(AuditLog)

    # Receptionists only see their own logs
    if role == "Receptionist":
        q = q.filter(AuditLog.user_id == session.get("user_id"))

    if user_f:   q = q.filter(AuditLog.user_name.ilike(f"%{user_f}%"))
    if role_f:   q = q.filter(AuditLog.role == role_f)
    if action_f: q = q.filter(AuditLog.action == action_f)
    if date_from:
        try:
            q = q.filter(AuditLog.timestamp >= datetime.datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(AuditLog.timestamp <= datetime.datetime.fromisoformat(date_to + "T23:59:59"))
        except ValueError:
            pass

    total = q.count()
    rows  = q.order_by(AuditLog.timestamp.desc())\
             .offset((page-1)*per_page).limit(per_page).all()

    items = [{
    "log_Id"   : l.id,
    "timestamp": l.timestamp.strftime("%d %b %Y  %H:%M") if l.timestamp else "—",
    "user_name": l.user_name,
    "role"     : l.role,
    "action"   : l.action,
    "entity"   : l.entity,
    "detail"   : l.detail,
} for l in rows]

    return jsonify({"items": items, "total": total,
                    "total_pages": math.ceil(total/per_page) or 1})

# ── CSV export shortcut ───────────────────────────────────────────────────────

@auditor_bp.route("/api/export/audit-logs")
def api_audit_logs_export():
    role = session.get("role","")
    if role not in ("Admin","Auditor","Receptionist"):
        return jsonify({"detail":"Forbidden"}), 403
    db  = next(get_db())
    q   = db.query(AuditLog)
    if role == "Receptionist":
        q = q.filter(AuditLog.user_id == session.get("user_id"))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Timestamp","User","Role","Action","Entity","Detail"])
    for l in q.order_by(AuditLog.timestamp.desc()).all():
        writer.writerow([l.timestamp, l.user_name, l.role, l.action, l.entity, l.detail])

    resp = make_response(output.getvalue())
    resp.headers["Content-Type"]        = "text/csv"
    resp.headers["Content-Disposition"] = 'attachment; filename="HMS_AuditLog.csv"'
    return resp

@auditor_bp.route("/api/dashboard")
def auditor_dashboard():

    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    db = next(get_db())

    # ─────────────────────────────
    # Helper
    # ─────────────────────────────
    def to_float(val):
        try:
            return float(val or 0)
        except:
            return 0.0

    # ─────────────────────────────
    # KPI SECTION
    # ─────────────────────────────

    total_appointments = db.query(
        func.count(Appointment.appointment_Id)
    ).scalar() or 0

    total_revenue = to_float(
        db.query(func.sum(Bill.total_amount)).scalar()
    )

    collected_revenue = to_float(
        db.query(func.sum(Payment.amount)).scalar()
    )

    pending_bills = db.query(
        func.count(Bill.bill_id)
    ).filter(Bill.balance > 0).scalar() or 0

    # ─────────────────────────────
    # ACTIVE ADMISSIONS
    # ─────────────────────────────

    active_rooms = db.query(func.count(RoomRecord.admisson_ID))\
        .filter(RoomRecord.discharge_Date.is_(None)).scalar() or 0

    active_beds = db.query(func.count(BedRecord.admission_Id))\
        .filter(BedRecord.discharge_Date.is_(None)).scalar() or 0

    active_admissions = active_rooms + active_beds

    # ─────────────────────────────
    # AUDIT FLAGS
    # ─────────────────────────────

    missing_txn = db.query(func.count(Payment.payment_id))\
        .filter((Payment.transaction_id == None) | (Payment.transaction_id == ""))\
        .scalar() or 0

    revenue_mismatch = abs(total_revenue - collected_revenue)

    unpaid_high = db.query(func.count(Bill.bill_id))\
        .filter(Bill.balance > 5000).scalar() or 0

    # ─────────────────────────────
    # ✅ REVENUE TREND (NO DUPLICATION)
    # ─────────────────────────────

    today = datetime.date.today()
    revenue_labels = []
    revenue_data = []

    for i in range(6, -1, -1):
        day = today - datetime.timedelta(days=i)

        start = datetime.datetime.combine(day, datetime.time.min)
        end = datetime.datetime.combine(day, datetime.time.max)

        total = to_float(
            db.query(func.sum(Payment.amount))
            .filter(Payment.paid_at >= start,
                    Payment.paid_at <= end)
            .scalar()
        )

        revenue_labels.append(day.strftime("%d %b"))
        revenue_data.append(total)

    # ─────────────────────────────
    # ✅ FIX: PAYMENT SUBQUERY (CRITICAL)
    # ─────────────────────────────

    payment_subq = db.query(
        Bill.appointment_Id.label("appt_id"),
        func.sum(Payment.amount).label("revenue")
    ).join(
        Payment, Payment.bill_id == Bill.bill_id
    ).group_by(
        Bill.appointment_Id
    ).subquery()

    # ─────────────────────────────
    # DEPARTMENT ANALYSIS (FIXED)
    # ─────────────────────────────

    dept_rows = db.query(
        Department.dept_Name,
        func.count(func.distinct(Appointment.appointment_Id)),
        func.coalesce(func.sum(payment_subq.c.revenue), 0)
    ).outerjoin(
        Doctor, Doctor.dept_Id == Department.dept_Id
    ).outerjoin(
        Appointment, Appointment.doct_Id == Doctor.doct_Id
    ).outerjoin(
        payment_subq, payment_subq.c.appt_id == Appointment.appointment_Id
    ).group_by(
        Department.dept_Name
    ).order_by(
        func.coalesce(func.sum(payment_subq.c.revenue), 0).desc()
    ).all()

    dept_labels = []
    dept_counts = []
    dept_revenue = []

    for d in dept_rows:
        dept_labels.append(d[0])
        dept_counts.append(d[1] or 0)
        dept_revenue.append(to_float(d[2]))

    # ─────────────────────────────
    # TOP DOCTORS (FIXED)
    # ─────────────────────────────

    doctor_rows = db.query(
        Doctor.FName,
        Doctor.LName,
        func.count(func.distinct(Appointment.appointment_Id)),
        func.coalesce(func.sum(payment_subq.c.revenue), 0)
    ).outerjoin(
        Appointment, Appointment.doct_Id == Doctor.doct_Id
    ).outerjoin(
        payment_subq, payment_subq.c.appt_id == Appointment.appointment_Id
    ).group_by(
        Doctor.doct_Id
    ).order_by(
        func.coalesce(func.sum(payment_subq.c.revenue), 0).desc()
    ).limit(5).all()

    top_doctors = []

    for d in doctor_rows:
        top_doctors.append({
            "name": f"Dr. {d[0] or ''} {d[1] or ''}".strip(),
            "appointments": d[2] or 0,
            "revenue": to_float(d[3])
        })

    # ─────────────────────────────
    # FINAL RESPONSE
    # ─────────────────────────────

    return jsonify({
        "total_appointments": total_appointments,
        "total_revenue": total_revenue,
        "collected_revenue": collected_revenue,
        "pending_bills": pending_bills,
        "active_admissions": active_admissions,

        "audit_flags": {
            "missing_txn": missing_txn,
            "revenue_mismatch": revenue_mismatch,
            "high_unpaid": unpaid_high
        },

        "revenue_labels": revenue_labels,
        "revenue_data": revenue_data,

        "dept_labels": dept_labels,
        "dept_counts": dept_counts,
        "dept_revenue": dept_revenue,

        "top_doctors": top_doctors
    })


@auditor_bp.route("/api/departments")
def get_departments():
    g = _guard()
    if g:
        return jsonify({"detail": "Forbidden"}), 403

    db = next(get_db())

    depts = db.query(Department.dept_Id, Department.dept_Name).all()

    return jsonify([
        {"dept_Id": d[0], "dept_Name": d[1]}
        for d in depts
    ])
@auditor_bp.route("/appointments")
def view_appointments():
    g = _guard(); return g if g else render_template("auditor/appointments.html")
 
@auditor_bp.route("/patients")
def view_patients():
    g = _guard(); return g if g else render_template("auditor/patients.html")
 
@auditor_bp.route("/doctors")
def view_doctors():
    g = _guard(); return g if g else render_template("auditor/doctors.html")
 
@auditor_bp.route("/departments")
def view_departments():
    g = _guard(); return g if g else render_template("auditor/departments.html")
 
@auditor_bp.route("/billing")
def view_billing():
    g = _guard(); return g if g else render_template("auditor/billing.html")
 
@auditor_bp.route("/users")
def view_users():
    g = _guard(); return g if g else render_template("auditor/users.html")
 
# # ── API: Analytics (charts 1,2,5,6,8,9,10,11,12) ───────────────────────────
 
# @auditor_bp.route("/api/analytics")
# def api_analytics():
#     g = _guard()
#     if g: return jsonify({"detail": "Forbidden"}), 403
 
#     date_from = request.args.get("date_from", "")
#     date_to   = request.args.get("date_to", "")
#     db        = next(get_db())
#     today     = datetime.date.today()
 
#     def to_float(v):
#         try: return float(v or 0)
#         except: return 0.0
 
#     # ── Chart 1: Appointment Trend (last 30 days by week) ────────────────────
#     appt_trend_labels = []
#     appt_trend_data   = []
#     for i in range(11, -1, -1):
#         day = today - datetime.timedelta(days=i*3)
#         cnt = db.query(func.count(Appointment.appointment_Id))\
#                 .filter(Appointment.appointment_Date == day).scalar() or 0
#         appt_trend_labels.append(day.strftime("%d %b"))
#         appt_trend_data.append(cnt)
 
#     # ── Chart 2: Day of Week ──────────────────────────────────────────────────
#     day_of_week = [0]*7  # Mon=0 … Sun=6
#     q = db.query(Appointment.appointment_Date)
#     if date_from: q = q.filter(Appointment.appointment_Date >= date_from)
#     if date_to:   q = q.filter(Appointment.appointment_Date <= date_to)
#     for (d,) in q.all():
#         if d:
#             day_of_week[d.weekday()] += 1
 
#     # ── Chart 5: Patient Registrations Over Time (last 12 months) ────────────
#     reg_labels = []
#     reg_data   = []
#     for i in range(11, -1, -1):
#         month_start = (today.replace(day=1) - datetime.timedelta(days=i*28)).replace(day=1)
#         if i == 0:
#             month_end = today
#         else:
#             next_m = (month_start + datetime.timedelta(days=32)).replace(day=1)
#             month_end = next_m - datetime.timedelta(days=1)
#         cnt = db.query(func.count(Patient.patient_Id))\
#                 .filter(Patient.registration_date >= month_start,
#                         Patient.registration_date <= month_end).scalar() or 0
#         reg_labels.append(month_start.strftime("%b %y"))
#         reg_data.append(cnt)
 
#     # ── Chart 6: Age Histogram ────────────────────────────────────────────────
#     age_labels = ["0-18", "19-35", "36-50", "51-65", "65+"]
#     age_data   = [0, 0, 0, 0, 0]
#     patients = db.query(Patient.Date_Of_Birth).filter(Patient.Date_Of_Birth != None).all()
#     for (dob,) in patients:
#         if not dob: continue
#         try:
#             age = (today - dob).days // 365
#         except: continue
#         if   age <= 18: age_data[0] += 1
#         elif age <= 35: age_data[1] += 1
#         elif age <= 50: age_data[2] += 1
#         elif age <= 65: age_data[3] += 1
#         else:           age_data[4] += 1
 
#     # ── Chart 8: System Usage by Role ────────────────────────────────────────
#     role_rows = db.query(AuditLog.role, func.count(AuditLog.id))\
#                   .group_by(AuditLog.role).order_by(func.count(AuditLog.id).desc()).all()
#     role_labels = [r[0] or "Unknown" for r in role_rows]
#     role_data   = [r[1] for r in role_rows]
 
#     # ── Chart 9: Treatment Cost Distribution ─────────────────────────────────
#     cost_labels = ["₹0-500", "₹501-1K", "₹1K-2.5K", "₹2.5K-5K", "₹5K+"]
#     cost_data   = [0, 0, 0, 0, 0]

#     try:

#         costs = db.query(Treatment.cost).filter(Treatment.cost != None).all()

#         for (c,) in costs:
#             c = float(c or 0)
#             if   c <= 500:  cost_data[0] += 1
#             elif c <= 1000: cost_data[1] += 1
#             elif c <= 2500: cost_data[2] += 1
#             elif c <= 5000: cost_data[3] += 1
#             else:           cost_data[4] += 1

#     except Exception as e:
#         print("Treatment data not available:", e)
 
#     # ── Chart 10: Payment Mode Distribution ──────────────────────────────────
#     pay_rows = db.query(Payment.payment_method, func.count(Payment.payment_id))\
#                  .filter(Payment.payment_method != None)\
#                  .group_by(Payment.payment_method).all()
#     pay_mode_labels = [r[0] for r in pay_rows]
#     pay_mode_data   = [r[1] for r in pay_rows]
 
#     # ── Chart 11: Appointment Status ─────────────────────────────────────────
#     status_rows = db.query(Appointment.appointment_status,
#                            func.count(Appointment.appointment_Id))\
#                     .group_by(Appointment.appointment_status).all()
#     status_labels = [r[0] or "Unknown" for r in status_rows]
#     status_data   = [r[1] for r in status_rows]
 
#     # ── Chart 12: Doctor Performance (Top 8) ─────────────────────────────────
#     doc_rows = db.query(
#         Doctor.FName, Doctor.LName,
#         func.count(Appointment.appointment_Id).label("total"),
#         func.count(Appointment.appointment_Id).filter(
#             Appointment.appointment_status == "Completed").label("done")
#     ).outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
#      .group_by(Doctor.doct_Id)\
#      .order_by(func.count(Appointment.appointment_Id).desc())\
#      .limit(8).all()
 
#     doc_perf_labels = [f"Dr. {r[0] or ''} {r[1] or ''}".strip() for r in doc_rows]
#     doc_perf_total  = [r[2] for r in doc_rows]
#     doc_perf_done   = [r[3] for r in doc_rows]
 
#     return jsonify({
#         "appt_trend_labels": appt_trend_labels,
#         "appt_trend_data"  : appt_trend_data,
#         "day_of_week"      : day_of_week,
#         "reg_labels"       : reg_labels,
#         "reg_data"         : reg_data,
#         "age_labels"       : age_labels,
#         "age_data"         : age_data,
#         "role_labels"      : role_labels,
#         "role_data"        : role_data,
#         "cost_labels"      : cost_labels,
#         "cost_data"        : cost_data,
#         "pay_mode_labels"  : pay_mode_labels,
#         "pay_mode_data"    : pay_mode_data,
#         "status_labels"    : status_labels,
#         "status_data"      : status_data,
#         "doc_perf_labels"  : doc_perf_labels,
#         "doc_perf_total"   : doc_perf_total,
#         "doc_perf_done"    : doc_perf_done,
#     })
 
 
# ── API: Appointments list (paginated, filterable) ───────────────────────────
 
@auditor_bp.route("/api/appointments")
def api_appointments():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page      = int(request.args.get("page", 1))
    per_page  = PAGINATION.get("appointments", 15)
    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")
    status_f  = request.args.get("status", "")
    dept_f    = request.args.get("dept", "")
    db        = next(get_db())
 
    q = db.query(Appointment, Patient, Doctor, Department)\
          .join(Patient,    Patient.patient_Id    == Appointment.patient_Id)\
          .join(Doctor,     Doctor.doct_Id        == Appointment.doct_Id)\
          .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)
 
    if date_from: q = q.filter(Appointment.appointment_Date >= date_from)
    if date_to:   q = q.filter(Appointment.appointment_Date <= date_to)
    if status_f:  q = q.filter(func.lower(Bill.bill_status) == status_f.lower())
    if dept_f:    q = q.filter(Doctor.dept_Id == int(dept_f))
 
    total = q.count()
 
    # Stats (apply same filters)
    stats = {
        "total"    : total,
        "completed": q.filter(Appointment.appointment_status == "Completed").count(),
        "scheduled": q.filter(Appointment.appointment_status == "Scheduled").count(),
        "cancelled": q.filter(Appointment.appointment_status == "Cancelled").count(),
    }
 
    rows = q.order_by(Appointment.appointment_Date.desc())\
            .offset((page-1)*per_page).limit(per_page).all()
 
    items = [{
        "id"         : a.appointment_Id,
        "patient_name": f"{p.FName} {p.LName}",
        "doctor_name" : f"Dr. {d.FName} {d.LName}",
        "dept_name"   : dept.dept_Name if dept else "—",
        "date"        : str(a.appointment_Date) if a.appointment_Date else "—",
        "slot"        : str(a.slot_time) if a.slot_time else "—",
        "status"      : a.appointment_status,
        "mode"        : a.mode_of_appointment,
        "fee"         : a.consultation_fee or 0,
    } for a, p, d, dept in rows]
 
    return jsonify({
        "items": items, "total": total, "stats": stats,
        "total_pages": math.ceil(total / per_page) or 1
    })
 
 
# ── API: Patients list ───────────────────────────────────────────────────────
 
@auditor_bp.route("/api/patients")
def api_patients():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page     = int(request.args.get("page", 1))
    per_page = PAGINATION.get("patients", 15)
    search   = request.args.get("search", "").strip()
    gender   = request.args.get("gender", "")
    reg_from = request.args.get("reg_from", "")
    reg_to   = request.args.get("reg_to", "")
    db       = next(get_db())
    today    = datetime.date.today()
    month_start = today.replace(day=1)
 
    q = db.query(Patient)
    if search: q = q.filter(
        (Patient.FName + " " + Patient.LName).ilike(f"%{search}%"))
    if gender:   q = q.filter(Patient.Gender == gender)
    if reg_from: q = q.filter(Patient.registration_date >= reg_from)
    if reg_to:   q = q.filter(Patient.registration_date <= reg_to)
 
    total = q.count()
    male   = db.query(func.count(Patient.patient_Id)).filter(Patient.Gender=="Male").scalar() or 0
    female = db.query(func.count(Patient.patient_Id)).filter(Patient.Gender=="Female").scalar() or 0
    this_month = db.query(func.count(Patient.patient_Id))\
                   .filter(Patient.registration_date >= month_start).scalar() or 0
 
    rows = q.order_by(Patient.registration_date.desc())\
            .offset((page-1)*per_page).limit(per_page).all()
 
    items = [{
        "id"        : p.patient_Id,
        "name"      : f"{p.FName} {p.LName}",
        "gender"    : p.Gender,
        "dob"       : str(p.Date_Of_Birth) if p.Date_Of_Birth else "—",
        "phone"     : p.contact_No,
        "blood_group": p.blood_group or "—",
        "registered": p.registration_date.strftime("%d %b %Y") if p.registration_date else "—",
    } for p in rows]
 
    return jsonify({
        "items": items, "total": total,
        "total_pages": math.ceil(total / per_page) or 1,
        "stats": {"total": total, "male": male, "female": female, "this_month": this_month}
    })
 
 
# ── API: Doctors list ────────────────────────────────────────────────────────
 
@auditor_bp.route("/api/doctors")
def api_doctors():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page     = int(request.args.get("page", 1))
    per_page = PAGINATION.get("doctors", 15)
    search   = request.args.get("search", "").strip()
    dept_f   = request.args.get("dept", "")
    gender_f = request.args.get("gender", "")
    db       = next(get_db())
 
    q = db.query(Doctor, Department)\
          .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)
    if search: q = q.filter(
        (Doctor.FName + " " + Doctor.LName).ilike(f"%{search}%"))
    if dept_f:   q = q.filter(Doctor.dept_Id == int(dept_f))
    if gender_f: q = q.filter(Doctor.Gender == gender_f)
 
    total = q.count()
    total_docs  = db.query(func.count(Doctor.doct_Id)).scalar() or 0
    total_depts = db.query(func.count(Department.dept_Id)).scalar() or 0
    total_heads = db.query(func.count(Doctor.doct_Id)).filter(Doctor.is_dept_head==True).scalar() or 0
    avg_exp = db.query(func.avg(Doctor.experience_years)).scalar()
    avg_exp = round(float(avg_exp), 1) if avg_exp else 0
 
    rows = q.order_by(Doctor.FName).offset((page-1)*per_page).limit(per_page).all()
 
    items = [{
        "id"          : d.doct_Id,
        "name"        : f"{d.FName} {d.LName}",
        "dept"        : dept.dept_Name if dept else "—",
        "specialisation": d.surgeon_Type or "—",
        "gender"      : d.Gender,
        "experience"  : d.experience_years,
        "contact"     : d.contact_No,
        "is_head"     : bool(d.is_dept_head),
    } for d, dept in rows]
 
    return jsonify({
        "items": items, "total": total,
        "total_pages": math.ceil(total / per_page) or 1,
        "stats": {"total": total_docs, "depts": total_depts,
                  "heads": total_heads, "avg_exp": avg_exp}
    })
 
 
# ── API: Departments detail ──────────────────────────────────────────────────
 
@auditor_bp.route("/api/departments-detail")
def api_departments_detail():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page     = int(request.args.get("page", 1))
    per_page = PAGINATION.get("departments", 20)
    search   = request.args.get("search", "").strip()
    db       = next(get_db())
 
    payment_subq = db.query(
        Bill.appointment_Id.label("appt_id"),
        func.sum(Payment.amount).label("revenue")
    ).join(Payment, Payment.bill_id == Bill.bill_id)\
     .group_by(Bill.appointment_Id).subquery()
 
    q = db.query(
        Department.dept_Id,
        Department.dept_Name,
        func.count(func.distinct(Doctor.doct_Id)).label("doc_count"),
        func.count(func.distinct(Appointment.appointment_Id)).label("appt_count"),
        func.coalesce(func.sum(payment_subq.c.revenue), 0).label("revenue")
    ).outerjoin(Doctor,      Doctor.dept_Id     == Department.dept_Id)\
     .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
     .outerjoin(payment_subq, payment_subq.c.appt_id == Appointment.appointment_Id)\
     .group_by(Department.dept_Id, Department.dept_Name)
 
    if search: q = q.filter(Department.dept_Name.ilike(f"%{search}%"))
 
    all_rows = q.all()
    total = len(all_rows)
    rows  = all_rows[(page-1)*per_page : page*per_page]
 
    items = [{
        "id"               : r[0],
        "name"             : r[1],
        "doctor_count"     : r[2] or 0,
        "appointment_count": r[3] or 0,
        "revenue"          : float(r[4] or 0),
    } for r in rows]
 
    return jsonify({
        "items": items, "total": total,
        "total_pages": math.ceil(total / per_page) or 1
    })
 
 
# ── API: Bills list ──────────────────────────────────────────────────────────
 
@auditor_bp.route("/api/bills")
def api_bills():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page      = int(request.args.get("page", 1))
    per_page  = PAGINATION.get("bills", 15)
    search    = request.args.get("search", "").strip()
    status_f  = request.args.get("status", "")
    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")
    db        = next(get_db())
 
    q = db.query(Bill, Patient).join(Patient, Patient.patient_Id == Bill.patient_Id)
    if search: q = q.filter(
        (Patient.FName + " " + Patient.LName).ilike(f"%{search}%"))
    if status_f:  q = q.filter(func.lower(Bill.bill_status) == status_f.lower())
    if date_from: q = q.filter(Bill.bill_date >= date_from)
    if date_to:   q = q.filter(Bill.bill_date <= date_to)
 
    total = q.count()
 
    total_billed  = db.query(func.coalesce(func.sum(Bill.total_amount), 0)).scalar() or 0
    collected     = db.query(func.coalesce(func.sum(Bill.amount_paid), 0)).scalar() or 0
    pending_bal   = db.query(func.coalesce(func.sum(Bill.balance), 0))\
                      .filter(Bill.balance > 0).scalar() or 0
    overdue_cnt   = db.query(func.count(Bill.bill_id))\
                      .filter(Bill.balance > 5000).scalar() or 0
 
    rows = q.order_by(Bill.bill_date.desc())\
            .offset((page-1)*per_page).limit(per_page).all()
 
    items = [{
        "id"     : b.bill_id,
        "patient": f"{p.FName} {p.LName}",
        "total"  : float(b.total_amount or 0),
        "paid"   : float(b.amount_paid or 0),
        "balance": float(b.balance or 0),
        "status" : b.bill_status,
        "date"   : str(b.bill_date) if b.bill_date else "—",
        "notes"  : b.notes or "",
    } for b, p in rows]
 
    return jsonify({
        "items": items, "total": total,
        "total_pages": math.ceil(total / per_page) or 1,
        "kpi": {
            "total_billed": float(total_billed),
            "collected"   : float(collected),
            "pending"     : float(pending_bal),
            "overdue"     : overdue_cnt,
        }
    })
 
 
# ── API: Users list ──────────────────────────────────────────────────────────
 
@auditor_bp.route("/api/users")
def api_users():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403
 
    page     = int(request.args.get("page", 1))
    per_page = PAGINATION.get("users", 15)
    search   = request.args.get("search", "").strip()
    role_f   = request.args.get("role", "")
    active_f = request.args.get("active", "")
    db       = next(get_db())
 
    from models import User
    from sqlalchemy import Integer as SAInt
    from sqlalchemy.orm import aliased
 
    # Build a query joining users with their role name
    # roles table: id, name  |  users table: Role_ID FK -> roles.id
    from models import Role as RoleModel
    q = db.query(User, RoleModel).outerjoin(RoleModel, RoleModel.id == User.Role_ID)
 
    if search: q = q.filter(
        User.Name.ilike(f"%{search}%") | User.Email.ilike(f"%{search}%"))
    if role_f:   q = q.filter(RoleModel.name == role_f)
    if active_f != "": q = q.filter(User.is_active == bool(int(active_f)))
 
    total = q.count()
 
    # Role counts for stat cards
    role_count_rows = db.query(RoleModel.name, func.count(User.User_ID))\
                        .outerjoin(User, User.Role_ID == RoleModel.id)\
                        .group_by(RoleModel.name).all()
    role_counts = {r[0]: r[1] for r in role_count_rows}
 
    rows = q.order_by(User.Name).offset((page-1)*per_page).limit(per_page).all()
 
    items = [{
        "id"       : u.User_ID,
        "name"     : u.Name,
        "email"    : u.Email,
        "role"     : r.name if r else "—",
        "is_active": u.is_active,
    } for u, r in rows]
 
    return jsonify({
        "items": items, "total": total,
        "total_pages": math.ceil(total / per_page) or 1,
        "role_counts": role_counts,
    })

@auditor_bp.route("/api/analytics")
def api_analytics():
    g = _guard()
    if g: return jsonify({"detail": "Forbidden"}), 403

    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")
    db        = next(get_db())
    today     = datetime.date.today()

    def to_float(v):
        try: return float(v or 0)
        except: return 0.0

    # ── Chart 1: Appointment Trend (36 days in 3-day buckets) ───────────────
    appt_trend_labels, appt_trend_data = [], []
    for i in range(11, -1, -1):
        day = today - datetime.timedelta(days=i*3)
        cnt = db.query(func.count(Appointment.appointment_Id))\
                .filter(Appointment.appointment_Date == day).scalar() or 0
        appt_trend_labels.append(day.strftime("%d %b"))
        appt_trend_data.append(cnt)

    # ── Chart 2: Day of Week ─────────────────────────────────────────────────
    # ── Chart 2: Peak Booking Days (Optimized)
    weekday_rows = db.query(
        func.extract('dow', Appointment.appointment_Date),
        func.count(Appointment.appointment_Id)
    )

    if date_from:
        weekday_rows = weekday_rows.filter(Appointment.appointment_Date >= date_from)
    if date_to:
        weekday_rows = weekday_rows.filter(Appointment.appointment_Date <= date_to)

    weekday_rows = weekday_rows.group_by(
        func.extract('dow', Appointment.appointment_Date)
    ).all()

    # PostgreSQL: 0=Sunday, 6=Saturday
    labels = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
    day_of_week = [0]*7

    for d, count in weekday_rows:
        day_of_week[int(d)] = count

    # ── Chart 5: Patient Registrations (12 months) ──────────────────────────
    reg_labels, reg_data = [], []
    for i in range(11, -1, -1):
        month_start = (today.replace(day=1) - datetime.timedelta(days=i*28)).replace(day=1)
        month_end   = today if i == 0 else (month_start + datetime.timedelta(days=32)).replace(day=1) - datetime.timedelta(days=1)
        cnt = db.query(func.count(Patient.patient_Id))\
                .filter(Patient.registration_date >= month_start,
                        Patient.registration_date <= month_end).scalar() or 0
        reg_labels.append(month_start.strftime("%b %y"))
        reg_data.append(cnt)

    # ── Chart 6: Age Histogram ───────────────────────────────────────────────
    age_labels = ["0-18","19-35","36-50","51-65","65+"]
    age_data   = [0,0,0,0,0]
    for (dob,) in db.query(Patient.Date_Of_Birth).filter(Patient.Date_Of_Birth != None).all():
        try:
            age = (today - dob).days // 365
            if   age <= 18: age_data[0] += 1
            elif age <= 35: age_data[1] += 1
            elif age <= 50: age_data[2] += 1
            elif age <= 65: age_data[3] += 1
            else:           age_data[4] += 1
        except: pass

    # ── Appointment Status ───────────────────────────────────────────────────
    status_rows = db.query(Appointment.appointment_status,
                           func.count(Appointment.appointment_Id))\
                    .group_by(Appointment.appointment_status).all()
    status_labels = [r[0] or "Unknown" for r in status_rows]
    status_data   = [r[1] for r in status_rows]

    # ── Chart 9: Treatment Cost Distribution ─────────────────────────────────
    # ── Chart 9: Treatment Cost Distribution (Catalogue Based)
    cost_labels = ["₹0-500","₹501-1K","₹1K-2.5K","₹2.5K-5K","₹5K+"]
    cost_data   = [0,0,0,0,0]

    rows = db.query(TreatmentCatalogue.default_cost)\
        .filter(TreatmentCatalogue.default_cost != None)\
        .all()

    for (c,) in rows:
        c = float(c or 0)

        if c <= 500:
            cost_data[0] += 1
        elif c <= 1000:
            cost_data[1] += 1
        elif c <= 2500:
            cost_data[2] += 1
        elif c <= 5000:
            cost_data[3] += 1
        else:
            cost_data[4] += 1

    # ── Payment Mode ─────────────────────────────────────────────────────────
    pay_rows = db.query(Payment.payment_method, func.count(Payment.payment_id))\
                 .filter(Payment.payment_method != None)\
                 .group_by(Payment.payment_method).all()
    pay_mode_labels = [r[0] for r in pay_rows]
    pay_mode_data   = [r[1] for r in pay_rows]

    # ── Doctor Performance (Top 6) ───────────────────────────────────────────
    doc_rows = db.query(
        Doctor.FName, Doctor.LName,
        func.count(Appointment.appointment_Id).label("total"),
        func.count(Appointment.appointment_Id).filter(
            Appointment.appointment_status == "Completed").label("done")
    ).outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
     .group_by(Doctor.doct_Id)\
     .order_by(func.count(Appointment.appointment_Id).desc())\
     .limit(6).all()
    doc_perf_labels = [f"Dr. {r[0] or ''} {r[1] or ''}".strip() for r in doc_rows]
    doc_perf_total  = [r[2] for r in doc_rows]
    doc_perf_done   = [r[3] for r in doc_rows]

    # ── NEW: Disease → Department ─────────────────────────────────────────────
    # Source: MedicalRecord.diagnosis (free-text) joined to Department via Doctor
    # We group by (diagnosis, dept_name) and return top 15 most common
    disease_dept_labels, disease_dept_depts, disease_dept_counts = [], [], []
    try:
        # ── FIXED: Disease → Department (NO DUPLICATES)

        disease_dept_labels = []
        disease_dept_depts  = []
        disease_dept_counts = []

        disease_rows = db.query(
            MedicalRecord.diagnosis,
            func.count(MedicalRecord.record_Id).label("cnt")
        ).filter(
            MedicalRecord.diagnosis != None,
            MedicalRecord.diagnosis != ""
        )

        if date_from:
            disease_rows = disease_rows.filter(MedicalRecord.created_at >= date_from)
        if date_to:
            disease_rows = disease_rows.filter(MedicalRecord.created_at <= date_to)

        disease_rows = disease_rows.group_by(
            MedicalRecord.diagnosis
        ).order_by(
            func.count(MedicalRecord.record_Id).desc()
        ).limit(10).all()


        for diag, count in disease_rows:

            # find most common department for this disease
            dept_row = db.query(
                Department.dept_Name,
                func.count(MedicalRecord.record_Id)
            ).join(
                Doctor, Doctor.doct_Id == MedicalRecord.doct_Id
            ).join(
                Department, Department.dept_Id == Doctor.dept_Id
            ).filter(
                MedicalRecord.diagnosis == diag
            ).group_by(
                Department.dept_Name
            ).order_by(
                func.count(MedicalRecord.record_Id).desc()
            ).first()

            disease_dept_labels.append(
                (diag[:30] + "…") if len(diag) > 30 else diag
            )

            disease_dept_counts.append(count)

            disease_dept_depts.append(
                dept_row[0] if dept_row else "General"
    )
    except Exception as e:
        pass  # silently skip if MedicalRecord not available

    # ── Gender breakdown ─────────────────────────────────────────────────────
    gender_rows = db.query(Patient.Gender, func.count(Patient.patient_Id))\
                    .filter(Patient.Gender != None)\
                    .group_by(Patient.Gender).all()
    gender_labels = [r[0] for r in gender_rows]
    gender_data   = [r[1] for r in gender_rows]

    # ── Blood Group breakdown ────────────────────────────────────────────────
    blood_rows = db.query(Patient.blood_group, func.count(Patient.patient_Id))\
                   .filter(Patient.blood_group != None, Patient.blood_group != "")\
                   .group_by(Patient.blood_group)\
                   .order_by(func.count(Patient.patient_Id).desc()).all()
    blood_labels = [r[0] for r in blood_rows]
    blood_data   = [r[1] for r in blood_rows]

    # ── Blood Group Distribution ─────────────────
    blood_rows = db.query(
        Patient.blood_group,
        func.count(Patient.patient_Id)
    ).filter(
        Patient.blood_group != None
    ).group_by(
        Patient.blood_group
    ).all()

    blood_labels = [r[0] for r in blood_rows]
    blood_data = [r[1] for r in blood_rows]

    return jsonify({
        # Appointment trend
        "appt_trend_labels" : appt_trend_labels,
        "appt_trend_data"   : appt_trend_data,
        "day_of_week"       : day_of_week,
        # Patient
        "reg_labels"        : reg_labels,
        "reg_data"          : reg_data,
        "age_labels"        : age_labels,
        "age_data"          : age_data,
        "gender_labels"     : gender_labels,
        "gender_data"       : gender_data,
        "blood_labels"      : blood_labels,
        "blood_data"        : blood_data,
        # Clinical
        "disease_dept_labels": disease_dept_labels,
        "disease_dept_depts" : disease_dept_depts,
        "disease_dept_counts": disease_dept_counts,
        "cost_labels": cost_labels,
        "cost_data": cost_data,        # Financial
        "pay_mode_labels"   : pay_mode_labels,
        "pay_mode_data"     : pay_mode_data,
        #blood group distribution
        "blood_labels": blood_labels,
        "blood_data": blood_data,
        # Appointment quality
        "status_labels"     : status_labels,
        "status_data"       : status_data,
        # Doctor performance
        "doc_perf_labels"   : doc_perf_labels,
        "doc_perf_total"    : doc_perf_total,
        "doc_perf_done"     : doc_perf_done,
    })
from flask import Blueprint, flash, render_template, request, session, redirect, jsonify, url_for
from flask_mail import Message
from sqlalchemy import func
import datetime, math, hashlib
from flask import current_app
from dateutil.relativedelta import relativedelta
from flask import request, redirect, flash
from models import ContactMessage
from database import get_db, get_db_ctx, db
from config import mail

# Local imports
from database import get_db, get_db_ctx,db
from models import (User, Doctor, Department, Patient, Appointment,
                    Bill, Payment, AuditLog, Role, ContactMessage, DoctorLeave)
from config import PAGINATION

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")



# ── Auth guard ────────────────────────────────────────────────────────────────

def require_admin():
    if session.get("role") != "Admin":
        return redirect("/login")
    return None

# ── Page routes ───────────────────────────────────────────────────────────────

@admin_bp.route("/dashboard")
def dashboard():
    g = require_admin()
    if g: return g
    return render_template("admin/dashboard.html")

@admin_bp.route("/users")
def users():
    g = require_admin()
    if g: return g
    return render_template("admin/users.html")

@admin_bp.route("/doctors")
def doctors():
    g = require_admin()
    if g: return g
    return render_template("admin/doctors.html")

@admin_bp.route("/departments")
def departments():
    g = require_admin()
    if g: return g
    return render_template("admin/departments.html")

@admin_bp.route("/patients")
def admin_patients():
    g = require_admin()
    if g: return g
    return render_template("admin/patients.html")

@admin_bp.route("/appointments")
def appointments():
    g = require_admin()
    if g: return g
    return render_template("admin/appointments.html")

@admin_bp.route("/billing")
def billing():
    g = require_admin()
    if g: return g
    return render_template("admin/billing.html")

@admin_bp.route("/audit-logs")
def audit_logs():
    g = require_admin()
    if g: return g
    return render_template("admin/audit_logs.html")

# ══════════════════════════════════════════════════════════════════════════════
#  API — Dashboard KPIs
# ══════════════════════════════════════════════════════════════════════════════
@admin_bp.route("/api/kpis")
def api_kpis():
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    with get_db_ctx() as db:
        today = datetime.date.today()

        total_patients = db.query(func.count(Patient.patient_Id)).scalar() or 0

        appts_today = db.query(func.count(Appointment.appointment_Id))\
            .filter(Appointment.appointment_Date == today).scalar() or 0

        pending_bills = db.query(func.count(Bill.bill_id))\
            .filter(Bill.bill_status.in_(["Pending", "Partial"])).scalar() or 0

        month_start = today.replace(day=1)
        revenue = db.query(func.coalesce(func.sum(Payment.amount), 0))\
            .filter(Payment.paid_at >= month_start).scalar() or 0

        week_labels, week_data = [], []
        for i in range(7):
            d = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=i)
            cnt = db.query(func.count(Appointment.appointment_Id))\
                .filter(Appointment.appointment_Date == d).scalar() or 0
            week_labels.append(d.strftime("%a"))
            week_data.append(cnt)

        dept_rows = db.query(Department.dept_Name, func.count(Appointment.appointment_Id))\
            .outerjoin(Doctor, Doctor.dept_Id == Department.dept_Id)\
            .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
            .group_by(Department.dept_Name).all()

        return jsonify({
            "total_patients": total_patients,
            "appts_today": appts_today,
            "pending_bills": pending_bills,
            "revenue_month": revenue,
            "weekly_labels": week_labels,
            "weekly_counts": week_data,
            "dept_labels": [r[0] for r in dept_rows],
            "dept_counts": [r[1] for r in dept_rows]
        })

# ══════════════════════════════════════════════════════════════════════════════
#  API — Recent Appointments
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/appointments/recent")
def api_recent_appts():
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    with get_db_ctx() as db:
        page = int(request.args.get("page", 1))
        per_page = PAGINATION["appointments"]

        q = db.query(Appointment, Patient, Doctor, Department)\
            .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
            .join(Doctor, Doctor.doct_Id == Appointment.doct_Id)\
            .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
            .order_by(Appointment.appointment_Date.desc())

        total = q.count()
        rows = q.offset((page-1)*per_page).limit(per_page).all()

        items = [{
            "appointment_Id": a.appointment_Id,
            "patient_name": f"{p.FName} {p.LName}",
            "doctor_name": f"{d.FName} {d.LName}",
            "dept_name": dept.dept_Name if dept else "—",
            "appointment_date": str(a.appointment_Date),
            "appointment_status": a.appointment_status
        } for a,p,d,dept in rows]

        return jsonify({"items": items, "total": total, "total_pages": math.ceil(total/per_page) or 1})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Users CRUD
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/users")
def api_users_list():
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    page, per_page = int(request.args.get("page", 1)), PAGINATION["users"]
    search, role_f, status_f = request.args.get("search","").strip(), request.args.get("role","").strip(), request.args.get("status","").strip()

    with get_db_ctx() as db:
        q = db.query(User, Role).outerjoin(Role, Role.id == User.Role_ID)
        if search:
            q = q.filter((User.Name.ilike(f"%{search}%")) | (User.Email.ilike(f"%{search}%")))
        if role_f:
            q = q.filter(Role.name == role_f)
        if status_f:
            q = q.filter(User.is_active == (status_f == "Active"))

        total = q.count()
        rows = q.order_by(User.User_ID.desc()).offset((page-1)*per_page).limit(per_page).all()

        items = [{
            "User_ID": u.User_ID, "Name": u.Name, "Email": u.Email,
            "Role_ID": u.Role_ID, "role_name": r.name if r else "—", "is_active": u.is_active,
        } for u, r in rows]

        return jsonify({"items": items, "total": total, "total_pages": math.ceil(total/per_page) or 1})

@admin_bp.route("/api/admin/users/<int:uid>")
def api_user_get(uid):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    with get_db_ctx() as db:
        user = db.query(User).filter(User.User_ID == uid).first()
        if not user: return jsonify({"detail": "Not found"}), 404
        return jsonify({"User_ID": user.User_ID, "Name": user.Name, "Email": user.Email, "Role_ID": user.Role_ID, "is_active": user.is_active})

@admin_bp.route("/api/admin/users", methods=["POST"])
def api_user_create():

    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    import secrets

    body = request.get_json() or {}

    with get_db_ctx() as db:

        # 🔥 Generate secure random password
        raw_password = secrets.token_urlsafe(8)   # stronger than token_hex

        user = User(
            Name=body.get("name", ""),
            Email=body.get("email", ""),
            Password=hashlib.sha256(raw_password.encode()).hexdigest(),
            Role_ID=body.get("role_id"),
            is_active=True,
            force_password_change=True
        )

        db.add(user)
        db.commit()

        role = body.get("role_id")

        # 🔥 PROFESSIONAL EMAIL TEMPLATE
        role_name = {
            1: "Administrator",
            2: "Doctor",
            3: "Nurse",
            5: "Support Staff",
            6: "Receptionist",
            7: "Auditor"
        }.get(role, "User")

        email_body = f"""
Dear {user.Name},

Welcome to Marvel Hospitals.

Your account has been successfully created and you are now registered as a {role_name} in our system.

━━━━━━━━━━━━━━━━━━━━━━━
🔐 Login Credentials
━━━━━━━━━━━━━━━━━━━━━━━
Email    : {user.Email}
Password : {raw_password}

⚠️ IMPORTANT:
For security reasons, you are required to change your password upon your first login.

━━━━━━━━━━━━━━━━━━━━━━━
🌐 Access the system
━━━━━━━━━━━━━━━━━━━━━━━
Login here: http://localhost:5000/login

If you face any issues, please contact the system administrator.

We are excited to have you onboard and look forward to your contribution.

Warm regards,  
Marvel Hospitals  
Hospital Management System (HMS)
"""

        # 🔥 Send email
        if user.Email:
            current_app.send_email(
                subject="Your HMS Account Credentials",
                recipients=[user.Email],
                body=email_body
            )

        _log(db, "ADD_USER", f"User {user.Email} created")

        return jsonify({
            "ok": True,
            "user_id": user.User_ID
        })
    
@admin_bp.route("/api/admin/users/<int:uid>", methods=["PUT"])
def api_user_update(uid):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    body = request.get_json() or {}
    with get_db_ctx() as db:
        user = db.query(User).filter(User.User_ID == uid).first()
        if not user: return jsonify({"detail": "Not found"}), 404
        user.Name, user.Email, user.Role_ID = body.get("name", user.Name), body.get("email", user.Email), body.get("role_id", user.Role_ID)
        if body.get("password"):
            user.Password = hashlib.sha256(body["password"].encode()).hexdigest()
        db.commit()
        _log(db, "UPDATE_USER", f"User {uid} updated")
        return jsonify({"ok": True})

@admin_bp.route("/api/admin/users/<int:uid>/toggle", methods=["POST"])
def api_user_toggle(uid):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    with get_db_ctx() as db:
        user = db.query(User).filter(User.User_ID == uid).first()
        if not user: return jsonify({"detail": "Not found"}), 404
        user.is_active = not user.is_active
        db.commit()
        _log(db, "ACTIVATE_USER" if user.is_active else "DEACTIVATE_USER", f"User {uid} status changed")
        return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Doctors CRUD
# ══════════════════════════════════════════════════════════════════════════════
@admin_bp.route("/api/admin/doctors")
def api_doctors():

    page = int(request.args.get("page", 1))
    per_page = PAGINATION.get("doctors", 10)

    search = request.args.get("search", "")
    dept = request.args.get("dept", "")

    with get_db_ctx() as db:

        q = db.query(Doctor, Department)\
              .outerjoin(Department, Doctor.dept_Id == Department.dept_Id)

        if search:
            q = q.filter(
                (Doctor.FName.ilike(f"%{search}%")) |
                (Doctor.LName.ilike(f"%{search}%"))
            )

        if dept:
            q = q.filter(Doctor.dept_Id == int(dept))

        # ✅ TOTAL COUNT (before pagination)
        total = q.count()

        # ✅ APPLY PAGINATION
        rows = q.order_by(Doctor.doct_Id.desc())\
                .offset((page - 1) * per_page)\
                .limit(per_page)\
                .all()

        items = []

        for d, dept in rows:
            items.append({
                "doct_Id": d.doct_Id,
                "User_ID": d.User_ID,
                "FName": d.FName,
                "LName": d.LName,
                "dept_Name": dept.dept_Name if dept else None,
                "surgeon_Type": d.surgeon_Type,
                "contact_No": d.contact_No
            })

        # ✅ CALCULATE TOTAL PAGES
        total_pages = math.ceil(total / per_page) if total else 1

        return jsonify({
            "items": items,
            "total": total,
            "total_pages": total_pages,
            "page": page
        })

@admin_bp.route("/api/admin/doctors/<int:did>")
def api_doctor_get(did):
    with get_db_ctx() as db:
        doc = db.query(Doctor).filter(Doctor.doct_Id == did).first()
        if not doc: return jsonify({"detail": "Not found"}), 404
        return jsonify({k: getattr(doc, k) for k in ["doct_Id","FName","LName","Gender","contact_No","surgeon_Type","office_No","dept_Id"]})
    

@admin_bp.route("/api/admin/doctors", methods=["POST"])
def api_doctor_create():

    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    body = request.get_json() or {}

    with get_db_ctx() as db:

        user = User(
            Name = f"{body.get('fname')} {body.get('lname')}",
            Email = body.get("email"),
            Password = hashlib.sha256("doctor123".encode()).hexdigest(),
            Role_ID = 2,
            is_active = True
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        doc = Doctor(
            User_ID = user.User_ID,

            FName = body.get("fname"),
            LName = body.get("lname"),
            Gender = body.get("gender"),

            dept_Id = body.get("dept_id"),

            contact_No = body.get("contact_no"),
            surgeon_Type = body.get("surgeon_type"),
            office_No = body.get("office_no"),

            experience_years = body.get("experience_years"),
            is_dept_head = body.get("is_dept_head"),
            notes = body.get("notes")
        )

        db.add(doc)
        db.commit()

        if user.Email:
            current_app.send_email(
                "Doctor Account Created",
                [user.Email],
                f"""
Dear Dr. {doc.FName} {doc.LName},

Welcome to Marvel Hospitals.

Login Email : {user.Email}
Password : doctor123

Regards
Marvel Hospitals
"""
            )

        _log(db, "ADD_DOCTOR", f"Dr. {doc.FName} {doc.LName} added")

        return jsonify({"ok": True})
    

# =================================================================═════════════════════════════════════════════════════════════
#  API — Doctors CRUD (continued)   
# =================================================================═════════════════════════════════════════════════════════════
@admin_bp.route("/api/admin/doctors/<int:did>", methods=["PUT"])
def api_doctor_update(did):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    body = request.get_json() or {}
    with get_db_ctx() as db:
        doc = db.query(Doctor).filter(Doctor.doct_Id == did).first()
        if not doc: return jsonify({"detail": "Not found"}), 404
        for k, v in {"FName":"fname","LName":"lname","Gender":"gender","dept_Id":"dept_id","contact_No":"contact_no","surgeon_Type":"surgeon_type","office_No":"office_no"}.items():
            setattr(doc, k, body.get(v, getattr(doc, k)))
        db.commit()
        _log(db, "UPDATE_DOCTOR", f"Doctor {did} updated")
        return jsonify({"ok": True})

@admin_bp.route("/api/admin/doctors-by-dept/<int:dept_id>")
def api_doctors_by_dept(dept_id):
    with get_db_ctx() as db:
        docs = db.query(Doctor).filter(Doctor.dept_Id == dept_id).all()
        return jsonify([{"doct_Id": d.doct_Id, "FName": d.FName, "LName": d.LName} for d in docs])

# ══════════════════════════════════════════════════════════════════════════════
#  API — Departments CRUD
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/departments")
def api_departments_list():
    page, per_page = int(request.args.get("page", 1)), PAGINATION["departments"]
    search = request.args.get("search","").strip()
    with get_db_ctx() as db:
        q = db.query(Department)
        if search: q = q.filter(Department.dept_Name.ilike(f"%{search}%"))
        if "page" not in request.args:
            rows = q.order_by(Department.dept_Name).all()
            return jsonify([{"dept_Id": d.dept_Id, "dept_Name": d.dept_Name} for d in rows])
        total = q.count()
        rows = q.order_by(Department.dept_Name).offset((page-1)*per_page).limit(per_page).all()
        items = [{"dept_Id": d.dept_Id, "dept_Name": d.dept_Name, "doctor_count": db.query(func.count(Doctor.doct_Id)).filter(Doctor.dept_Id == d.dept_Id).scalar() or 0} for d in rows]
        return jsonify({"items": items, "total": total, "total_pages": math.ceil(total/per_page) or 1})

@admin_bp.route("/api/admin/departments", methods=["POST"])
def api_dept_create():
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    body = request.get_json() or {}
    with get_db_ctx() as db:
        dept = Department(dept_Name=body.get("dept_Name",""))
        db.add(dept); db.commit()
        _log(db, "ADD_DEPT", f"Department '{dept.dept_Name}' created")
        return jsonify({"ok": True})

@admin_bp.route("/api/admin/departments/<int:did>", methods=["PUT"])
def api_dept_update(did):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    body = request.get_json() or {}
    with get_db_ctx() as db:
        dept = db.query(Department).filter(Department.dept_Id == did).first()
        if not dept: return jsonify({"detail": "Not found"}), 404
        dept.dept_Name = body.get("dept_Name", dept.dept_Name)
        db.commit()
        _log(db, "UPDATE_DEPT", f"Department {did} updated")
        return jsonify({"ok": True})

@admin_bp.route("/api/admin/departments/<int:did>", methods=["DELETE"])
def api_dept_delete(did):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    with get_db_ctx() as db:
        docs = db.query(func.count(Doctor.doct_Id)).filter(Doctor.dept_Id == did).scalar()
        if docs: return jsonify({"detail": f"Cannot delete: {docs} doctors assigned"}), 400
        dept = db.query(Department).filter(Department.dept_Id == did).first()
        if dept: db.delete(dept); db.commit(); _log(db, "DELETE_DEPT", f"Department {did} deleted")
        return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Patients
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/api/admin/patients")
def api_patients_list():
    page, per_page = int(request.args.get("page", 1)), int(request.args.get("per_page", PAGINATION["patients"]))
    search, gender = request.args.get("search","").strip(), request.args.get("gender","").strip()
    with get_db_ctx() as db:
        q = db.query(Patient)
        if search: q = q.filter((Patient.FName.ilike(f"%{search}%")) | (Patient.LName.ilike(f"%{search}%")))
        if gender: q = q.filter(Patient.Gender == gender)
        total = q.count()
        rows = q.order_by(Patient.patient_Id.desc()).offset((page-1)*per_page).limit(per_page).all()
        items = [{"patient_Id": p.patient_Id, "FName": p.FName, "LName": p.LName, "Gender": p.Gender, "Date_Of_Birth": str(p.Date_Of_Birth) if p.Date_Of_Birth else None, "contact_No": p.contact_No, "pt_Address": p.pt_Address} for p in rows]
        return jsonify({"items": items, "total": total, "total_pages": math.ceil(total/per_page) or 1})

@admin_bp.route("/api/admin/patients/<int:pid>")
def api_patient_get(pid):
    with get_db_ctx() as db:
        p = db.query(Patient).filter(Patient.patient_Id == pid).first()
        if not p: return jsonify({"detail": "Not found"}), 404
        return jsonify({"patient_Id": p.patient_Id, "FName": p.FName, "LName": p.LName, "Gender": p.Gender, "Date_Of_Birth": str(p.Date_Of_Birth) if p.Date_Of_Birth else None, "contact_No": p.contact_No, "pt_Address": p.pt_Address})

# ══════════════════════════════════════════════════════════════════════════════
#  API — Appointments (admin)
# ══════════════════════════════════════════════════════════════════════════════
@admin_bp.route("/api/admin/appointments")
def api_appts_list():

    page = int(request.args.get("page", 1))
    per_page = PAGINATION["appointments"]

    date_from = request.args.get("date_from")
    date_to   = request.args.get("date_to")
    status    = request.args.get("status")

    with get_db_ctx() as db:

        q = db.query(Appointment)\
            .join(Patient, Patient.patient_Id == Appointment.patient_Id)\
            .join(Doctor, Doctor.doct_Id == Appointment.doct_Id)\
            .outerjoin(Department, Department.dept_Id == Doctor.dept_Id)\
            .add_entity(Patient)\
            .add_entity(Doctor)\
            .add_entity(Department)

        # date range filter
        if date_from:
            q = q.filter(
                Appointment.appointment_Date >= date_from
            )

        if date_to:
            q = q.filter(
                Appointment.appointment_Date <= date_to
            )

        # status filter
        if status:
            q = q.filter(
                Appointment.appointment_status == status
            )

        total = q.count()

        rows = q.order_by(
            Appointment.appointment_Date.desc()
        ).offset(
            (page-1)*per_page
        ).limit(per_page).all()

        items = [{
            "appointment_Id": a.appointment_Id,
            "patient_name": f"{p.FName} {p.LName}",
            "doctor_name": f"{d.FName} {d.LName}",
            "dept_name": dept.dept_Name if dept else "—",
            "appointment_date": str(a.appointment_Date),
            "appointment_status": a.appointment_status
        } for a,p,d,dept in rows]

        return jsonify({
            "items": items,
            "total": total,
            "total_pages": math.ceil(total/per_page) or 1
        })

@admin_bp.route("/api/admin/appointments/<int:aid>/cancel", methods=["POST"])
def api_cancel_appt(aid):
    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403
    with get_db_ctx() as db:
        appt = db.query(Appointment).filter(Appointment.appointment_Id == aid).first()
        if not appt: return jsonify({"detail": "Not found"}), 404
        appt.appointment_status = "Cancelled"
        db.commit()
        _log(db, "CANCEL_APPT", f"Appointment {aid} cancelled")
        return jsonify({"ok": True})

# ── Internal helper ───────────────────────────────────────────────────────────

def _log(db, action, detail=None):
    db.add(AuditLog(
        user_id=session.get("user_id"),
        user_name=session.get("user_name",""),
        role=session.get("role",""),
        action=action, detail=detail,
        timestamp=datetime.datetime.now()
    ))
    db.commit()


@admin_bp.route("/api/admin/doctors/<int:did>", methods=["DELETE"])
def api_doctor_delete(did):

    if session.get("role") != "Admin":
        return jsonify({"detail":"Forbidden"}),403

    with get_db_ctx() as db:

        doc = db.query(Doctor)\
                .filter(Doctor.doct_Id == did)\
                .first()

        if not doc:
            return jsonify({"detail":"Not found"}),404

        # delete linked user
        if doc.User_ID:
            user = db.query(User)\
                     .filter(User.User_ID == doc.User_ID)\
                     .first()

            if user:
                db.delete(user)

        db.delete(doc)
        db.commit()

        return jsonify({"ok":True})
    

@admin_bp.route("/admin/api/admin/departments", methods=["POST"])
def create_department():
    g = require_admin()
    if g: return g

    body = request.get_json()

    with get_db_ctx() as db:
        dept = Department(dept_Name=body.get("dept_name"))
        db.add(dept)
        db.commit()

        return jsonify({
            "dept_Id": dept.dept_Id,
            "dept_Name": dept.dept_Name
        })
    
@admin_bp.route("/api/admin/users/<int:id>", methods=["DELETE"])
def delete_user(id):

    if session.get("role") != "Admin":
        return jsonify({"detail": "Forbidden"}), 403

    with get_db_ctx() as db:

        user = db.query(User).filter(User.User_ID == id).first()

        if not user:
            return jsonify({"error": "User not found"}), 404

        # 🔥 CHECK LINKED PATIENT
        patient = db.query(Patient).filter(Patient.User_ID == id).first()

        if patient:
            db.delete(patient)

        # 🔥 DELETE USER
        db.delete(user)
        db.commit()

        return jsonify({"ok": True, "message": "User deleted successfully"})
    
# ══════════════════════════════════════════════════════════════════════════════
#  ANALYTICS ROUTES — Admin Dashboard
# ══════════════════════════════════════════════════════════════════════════════

@admin_bp.route("/analytics")
def analytics():
    g = require_admin()
    if g: return g
    return render_template("admin/analytics.html")


# ── #1: Patient Age Groups ───────────────────────────────────────────────
@admin_bp.route("/api/analytics/patient-age-groups")
def api_patient_age_groups():
    with get_db_ctx() as db:
        patients = db.query(Patient.Date_Of_Birth).filter(Patient.Date_Of_Birth != None).all()
        today = datetime.date.today()

        groups = {"0-18": 0, "19-35": 0, "36-50": 0, "51-65": 0, "65+": 0}

        for (dob,) in patients:
            age = (today - dob).days // 365
            if age <= 18: groups["0-18"] += 1
            elif age <= 35: groups["19-35"] += 1
            elif age <= 50: groups["36-50"] += 1
            elif age <= 65: groups["51-65"] += 1
            else: groups["65+"] += 1

        return jsonify({"labels": list(groups.keys()), "data": list(groups.values())})


# ── #2: Patient Gender ───────────────────────────────────────────────────
@admin_bp.route("/api/analytics/patient-gender")
def api_patient_gender():
    with get_db_ctx() as db:
        rows = db.query(Patient.Gender).all()

        gender_map = {"Male": 0, "Female": 0, "Other": 0}

        for (g,) in rows:
            if not g:
                continue

            g = g.lower()

            if g in ["male", "m"]:
                gender_map["Male"] += 1
            elif g in ["female", "f"]:
                gender_map["Female"] += 1
            else:
                gender_map["Other"] += 1

        return jsonify({
            "labels": list(gender_map.keys()),
            "data": list(gender_map.values())
        })


# ── #3: Registrations per Month ──────────────────────────────────────────
@admin_bp.route("/api/analytics/patient-registrations")
def api_patient_registrations():
    with get_db_ctx() as db:
        rows = db.query(
            func.to_char(Patient.registration_date, 'YYYY-MM'),
            func.count(Patient.patient_Id)
        ).group_by(func.to_char(Patient.registration_date, 'YYYY-MM')).all()

        data = {r[0]: r[1] for r in rows}

        # 🔥 Last 6 months (fill missing)
        labels, counts = [], []
        today = datetime.date.today()

        for i in range(5, -1, -1):
            m = today - relativedelta(months=i)
            key = m.strftime("%Y-%m")
            labels.append(key)
            counts.append(data.get(key, 0))

        return jsonify({"labels": labels, "data": counts})


# ── #5: Patients per Doctor ──────────────────────────────────────────────
@admin_bp.route("/api/analytics/patients-per-doctor")
def api_patients_per_doctor():
    with get_db_ctx() as db:
        rows = db.query(
            Doctor.FName, Doctor.LName,
            func.count(Appointment.appointment_Id)
        ).outerjoin(Appointment)\
        .group_by(Doctor.doct_Id)\
        .order_by(func.count(Appointment.appointment_Id).desc())\
        .limit(10).all()

        return jsonify({
            "labels": [f"Dr. {r[0]} {r[1]}" for r in rows],
            "data": [r[2] for r in rows]
        })


# ── #6: Doctors by Specialization ────────────────────────────────────────
@admin_bp.route("/api/analytics/doctors-by-department")
def api_doctors_by_department():
    with get_db_ctx() as db:
        rows = db.query(
            Department.dept_Name,
            func.count(Doctor.doct_Id)
        ).select_from(Department)\
         .outerjoin(Doctor, Doctor.dept_Id == Department.dept_Id)\
         .group_by(Department.dept_Name).all()

        # 🔥 remove empty departments
        rows = [r for r in rows if r[1] > 0]

        # 🔥 sort descending
        rows = sorted(rows, key=lambda x: x[1], reverse=True)

        # 🔥 top 8 only (clean UI)
        rows = rows[:8]

        return jsonify({
            "labels": [r[0] for r in rows],
            "data": [r[1] for r in rows]
        })


# ── #8: Appointments by Department ───────────────────────────────────────
@admin_bp.route("/api/analytics/appointments-by-department")
def api_appointments_by_department():
    with get_db_ctx() as db:
        rows = db.query(
            Department.dept_Name,
            func.count(Appointment.appointment_Id)
        ).select_from(Department)\
         .outerjoin(Doctor, Doctor.dept_Id == Department.dept_Id)\
         .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
         .group_by(Department.dept_Name).all()

        # 🔥 remove zero values
        rows = [r for r in rows if r[1] > 0]

        # 🔥 sort descending
        rows = sorted(rows, key=lambda x: x[1], reverse=True)

        # 🔥 keep top 6, rest as "Others"
        top = rows[:6]
        others = sum(r[1] for r in rows[6:])

        if others > 0:
            top.append(("Others", others))

        return jsonify({
            "labels": [r[0] for r in top],
            "data": [r[1] for r in top]
        })

# ── #9: Doctor Experience ────────────────────────────────────────────────
@admin_bp.route("/api/analytics/doctor-experience")
def api_doctor_experience():
    with get_db_ctx() as db:
        rows = db.query(Doctor.experience_years).all()

        buckets = {
            "0-1 yr": 0,
            "1-2 yrs": 0,
            "2-3 yrs": 0,
            "3-4 yrs": 0,
            "4-5 yrs": 0
        }

        for (exp,) in rows:
            if exp is None:
                continue

            if exp <= 1:
                buckets["0-1 yr"] += 1
            elif exp <= 2:
                buckets["1-2 yrs"] += 1
            elif exp <= 3:
                buckets["2-3 yrs"] += 1
            elif exp <= 4:
                buckets["3-4 yrs"] += 1
            else:
                buckets["4-5 yrs"] += 1

        return jsonify({"labels": list(buckets.keys()), "data": list(buckets.values())})


# ── #12: Appointment Status ──────────────────────────────────────────────
@admin_bp.route("/api/analytics/appointment-status")
def api_appointment_status():
    with get_db_ctx() as db:
        rows = db.query(
            Appointment.appointment_status,
            func.count(Appointment.appointment_Id)
        ).group_by(Appointment.appointment_status).all()

        return jsonify({
            "labels": [r[0] for r in rows],
            "data": [r[1] for r in rows]
        })


# ── #13: Time Slots ──────────────────────────────────────────────────────
@admin_bp.route("/api/analytics/appointments-by-timeslot")
def api_appointments_by_timeslot():
    with get_db_ctx() as db:
        slots = db.query(Appointment.slot_time).all()

        buckets = {
            "Morning": 0,
            "Late Morning": 0,
            "Afternoon": 0,
            "Evening": 0,
            "Night": 0
        }

        for (t,) in slots:
            h = t.hour if t else 0
            if 6 <= h < 10: buckets["Morning"] += 1
            elif 10 <= h < 14: buckets["Late Morning"] += 1
            elif 14 <= h < 18: buckets["Afternoon"] += 1
            elif 18 <= h < 22: buckets["Evening"] += 1
            else: buckets["Night"] += 1

        return jsonify({"labels": list(buckets.keys()), "data": list(buckets.values())})    


# ── #21: Revenue by Month ────────────────────────────────────────────────
@admin_bp.route("/api/analytics/revenue-by-month")
def api_revenue_by_month():
    with get_db_ctx() as db:
        rows = db.query(
            func.to_char(Payment.paid_at, 'YYYY-MM'),
            func.sum(Payment.amount)
        ).group_by(func.to_char(Payment.paid_at, 'YYYY-MM')).all()

        data = {r[0]: float(r[1] or 0) for r in rows}

        labels, revenue = [], []
        today = datetime.date.today()

        for i in range(5, -1, -1):
            m = today - relativedelta(months=i)
            key = m.strftime("%Y-%m")
            labels.append(key)
            revenue.append(data.get(key, 0))

        return jsonify({"labels": labels, "revenue": revenue})


# ── #22: Revenue by Department ───────────────────────────────────────────
@admin_bp.route("/api/analytics/revenue-by-department")
def api_revenue_by_department():
    with get_db_ctx() as db:
        rows = db.query(
            Department.dept_Name,
            func.coalesce(func.sum(Payment.amount), 0)
        ).select_from(Department)\
         .outerjoin(Doctor, Doctor.dept_Id == Department.dept_Id)\
         .outerjoin(Appointment, Appointment.doct_Id == Doctor.doct_Id)\
         .outerjoin(Bill, Bill.appointment_Id == Appointment.appointment_Id)\
         .outerjoin(Payment, Payment.bill_id == Bill.bill_id)\
         .group_by(Department.dept_Name).all()

        return jsonify({
            "labels": [r[0] for r in rows],
            "revenue": [float(r[1]) for r in rows]
        })
    

# ── #23: Payment Methods ────────────────────────────────────────────────
@admin_bp.route("/api/analytics/payment-methods")
def api_payment_methods():
    with get_db_ctx() as db:
        rows = db.query(
            Payment.payment_method,
            func.count(Payment.payment_id)
        ).group_by(Payment.payment_method).all()

        return jsonify({
            "labels": [r[0] or "Unknown" for r in rows],
            "data": [r[1] for r in rows]
        })


# ── #24: Billed vs Paid ─────────────────────────────────────────────────
@admin_bp.route("/api/analytics/billed-vs-paid")
def api_billed_vs_paid():
    with get_db_ctx() as db:
        rows = db.query(
            func.to_char(Bill.bill_date, 'YYYY-MM'),
            func.sum(Bill.total_amount),
            func.sum(Bill.amount_paid)
        ).group_by(
            func.to_char(Bill.bill_date, 'YYYY-MM')
        ).all()

        data = {r[0]: (float(r[1] or 0), float(r[2] or 0)) for r in rows}

        labels, billed, paid = [], [], []
        today = datetime.date.today()

        for i in range(5, -1, -1):
            m = today - relativedelta(months=i)
            key = m.strftime("%Y-%m")

            labels.append(key)
            b, p = data.get(key, (0, 0))
            billed.append(b)
            paid.append(p)

        return jsonify({
            "labels": labels,
            "billed": billed,
            "paid": paid
        })


# ── #30: Summary KPIs ───────────────────────────────────────────────────
@admin_bp.route("/api/analytics/summary")
def api_analytics_summary():
    with get_db_ctx() as db:
        today = datetime.date.today()

        return jsonify({
            "total_patients": db.query(func.count(Patient.patient_Id)).scalar() or 0,
            "total_doctors": db.query(func.count(Doctor.doct_Id)).scalar() or 0,
            "active_appointments": db.query(func.count(Appointment.appointment_Id))
                .filter(Appointment.appointment_status == "Scheduled").scalar() or 0,
            "pending_balance": db.query(func.sum(Bill.balance)).scalar() or 0,
            "month_revenue": db.query(func.sum(Payment.amount))
                .filter(Payment.paid_at >= today.replace(day=1)).scalar() or 0
        })
    

@admin_bp.route("/messages")
def view_messages():

    messages = ContactMessage.query.order_by(
        ContactMessage.created_at.desc()
    ).all()

    return render_template(
        "admin/messages.html",
        messages=messages
    )

@admin_bp.route("/doctor_leaves")
def doctor_leaves():

    leaves = DoctorLeave.query.order_by(
        DoctorLeave.applied_at.desc()
    ).all()

    return render_template(
        "admin/doctor_leaves.html",
        leaves=leaves
    )



@admin_bp.route("/mark_message_read/<int:message_id>")
def mark_message_read(message_id):

    db = next(get_db())

    try:

        msg = db.query(ContactMessage).filter_by(
            message_id=message_id
        ).first()

        if not msg:

            flash("Message not found", "danger")

            return redirect("/admin/messages")

        msg.status = "Read"

        db.commit()

        flash("Message marked as read", "success")

        return redirect("/admin/messages")

    finally:

        db.close()


@admin_bp.route("/delete_message/<int:message_id>")
def delete_message(message_id):

    db = next(get_db())

    try:

        msg = db.query(ContactMessage).filter_by(
            message_id=message_id
        ).first()

        if not msg:
            flash("Message not found", "danger")
            return redirect("/admin/messages")

        db.delete(msg)

        db.commit()

        flash("Message deleted successfully", "success")

        return redirect("/admin/messages")

    finally:
        db.close()


@admin_bp.route("/reply_message", methods=["POST"])
def reply_message():

    db = next(get_db())

    try:

        message_id = request.form.get("message_id")

        to_email = request.form.get("to_email")

        subject = request.form.get("subject")

        reply_body = request.form.get("reply_body")

        # GET ORIGINAL MESSAGE
        msg = db.query(ContactMessage).filter_by(
            message_id=message_id
        ).first()

        if not msg:

            flash("Message not found", "danger")

            return redirect("/admin/messages")

        # SEND EMAIL
        email = Message(
            subject=subject,
            recipients=[to_email]
        )

        email.body = f"""
Hello {msg.name},

{reply_body}

Regards,
Marvel Hospitals
Support Team
"""

        mail.send(email)

        # UPDATE STATUS
        msg.status = "Read"

        db.commit()

        flash(
            f"Reply sent to {to_email}",
            "success"
        )

        return redirect("/admin/messages")

    except Exception as e:

        db.rollback()

        flash(
            f"Mail sending failed: {str(e)}",
            "danger"
        )

        return redirect("/admin/messages")

    finally:

        db.close()

 
 
def _notify_doctor_leave(leave, approved: bool):
    """
    Internal helper:
    Sends email to doctor when leave is approved/rejected.
    """

    try:

        from models import Doctor, User

        # GET DOCTOR
        doctor = Doctor.query.get(leave.doct_Id)

        if not doctor:
            return

        # GET LINKED USER
        user = User.query.filter_by(
            User_ID=doctor.User_ID
        ).first()

        if not user:
            return

        if not user.Email:
            return

        # STATUS
        status_word = (
            "Approved"
            if approved
            else "Rejected"
        )

        # EMAIL SUBJECT
        subject = (
            f"Your Leave Request has been "
            f"{status_word}"
        )

        # EMAIL BODY
        body = f"""
Dear Dr. {doctor.FName} {doctor.LName},

Your leave request has been {status_word.lower()}.

━━━━━━━━━━━━━━━━━━━━━━━
Leave Details
━━━━━━━━━━━━━━━━━━━━━━━

From : {leave.leave_from}
To   : {leave.leave_to}

Reason:
{leave.reason or 'N/A'}

━━━━━━━━━━━━━━━━━━━━━━━

If you have questions, please contact administration.

Regards,
Marvel Hospitals
Hospital Management System
"""

        # SEND EMAIL
        current_app.send_email(
            subject=subject,
            recipients=[user.Email],
            body=body
        )

    except Exception as e:

        print(
            "Leave notification failed:",
            str(e)
        )

        # Never break approval flow
        pass
 

@admin_bp.route("/approve_leave/<int:leave_id>")
def approve_leave(leave_id):

    leave = DoctorLeave.query.get_or_404(leave_id)

    leave.status = "Approved"

    db.session.commit()

    _notify_doctor_leave(leave, approved=True)

    flash("Leave approved successfully", "success")

    return redirect(url_for("admin.doctor_leaves"))


@admin_bp.route("/reject_leave/<int:leave_id>")
def reject_leave(leave_id):

    leave = DoctorLeave.query.get_or_404(leave_id)

    leave.status = "Rejected"

    db.session.commit()

    _notify_doctor_leave(leave, approved=False)

    flash("Leave rejected", "danger")

    return redirect(url_for("admin.doctor_leaves"))
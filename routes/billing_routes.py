from flask import Blueprint, request, session, jsonify
from database import get_db
from models import Bill, Payment, Patient, AuditLog
from config import PAGINATION
from decimal import Decimal
import math
from datetime import date
from sqlalchemy import or_, func, cast, String
billing_bp = Blueprint("billing", __name__)

# ─────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────

def _allowed():
    return session.get("role") in ("Admin", "Receptionist", "Auditor", "Patient")


def _log(db, action, entity=None, detail=None):
    db.add(AuditLog(
        user_id=session.get("user_id"),
        user_name=session.get("user_name", ""),
        role=session.get("role", ""),
        action=action,
        entity=entity,
        detail=detail
    ))
    db.commit()


# ─────────────────────────────────────────────
# GET /api/billing  (LIST BILLS)
# ─────────────────────────────────────────────
@billing_bp.route("/api/billing")
def api_bills_list():

    if not _allowed():
        return jsonify({"detail": "Forbidden"}), 403

    db = next(get_db())

    try:
        page = int(request.args.get("page", 1))
        per_page = PAGINATION["billing"]

        search = request.args.get("search", "").strip()
        status = request.args.get("status", "").strip()

        q = db.query(Bill, Patient)\
              .join(Patient, Patient.patient_Id == Bill.patient_Id)

        # 🔥 SEARCH FIX (IMPORTANT)
        if search:
            search_lower = f"%{search.lower()}%"

            q = q.filter(or_(
                func.lower(Patient.FName).like(search_lower),
                func.lower(Patient.LName).like(search_lower),

                # Full name search
                func.lower(Patient.FName + " " + Patient.LName).like(search_lower),

                # Bill ID search
                cast(Bill.bill_id, String).like(f"%{search}%"),

                # Appointment ID search
                cast(Bill.appointment_Id, String).like(f"%{search}%")
            ))

        # 🔥 STATUS FIX (case insensitive)
        if status:
            q = q.filter(func.lower(Bill.bill_status) == status.lower())

        total = q.count()

        rows = q.order_by(
            Bill.created_at.desc(),
            Bill.bill_id.desc()
        ).offset((page - 1) * per_page)\
         .limit(per_page)\
         .all()

        items = []
        for b, p in rows:
            items.append({
                "bill_id": b.bill_id,
                "appointment_Id": b.appointment_Id,
                "patient_name": f"{p.FName} {p.LName}",
                "description": b.notes,
                "total_amount": float(b.total_amount or 0),
                "amount_paid": float(b.amount_paid or 0),
                "balance": float(b.balance or 0),

                # 🔥 IMPORTANT FIX (frontend expects this key)
                "bill_status": b.bill_status,

                "created_at": str(b.created_at),
            })

        return jsonify({
            "items": items,
            "total": total,
            "total_pages": math.ceil(total / per_page) or 1
        })

    finally:
        db.close()


# ─────────────────────────────────────────────
# GET /api/billing/<id>  (DETAIL)
# ─────────────────────────────────────────────

@billing_bp.route("/api/billing/<int:bid>")
def api_bill_detail(bid):

    db = next(get_db())

    try:
        bill = db.query(Bill)\
                 .filter(Bill.bill_id == bid)\
                 .first()

        if not bill:
            return jsonify({"detail": "Not found"}), 404

        pt = db.query(Patient)\
               .filter(Patient.patient_Id == bill.patient_Id)\
               .first()

        return jsonify({
            "bill_id": bill.bill_id,
            "appointment_Id": bill.appointment_Id,   # ✅ OPID
            "patient_name": f"{pt.FName} {pt.LName}" if pt else "—",
            "description": bill.notes,
            "total_amount": float(bill.total_amount or 0),
            "amount_paid": float(bill.amount_paid or 0),
            "balance": float(bill.balance or 0),
            "status": bill.bill_status,
            "created_at": str(bill.created_at),
        })

    finally:
        db.close()


# ─────────────────────────────────────────────
# POST /api/billing  (CREATE BILL)
# ─────────────────────────────────────────────

@billing_bp.route("/api/billing", methods=["POST"])
def api_bill_create():

    if session.get("role") not in ["Admin", "Receptionist"]:
        return jsonify({"detail": "Forbidden"}), 403

    db = next(get_db())

    try:
        body = request.get_json()

        # 🔥 VALIDATION
        if not body.get("appointment_id"):
            return jsonify({"detail": "appointment_id required"}), 400

        total = Decimal(str(body.get("total_amount", 0)))

        bill = Bill(
            patient_Id=body["patient_id"],
            appointment_Id=body.get("appointment_id"),   # ✅ OPID LINK
            total_amount=total,
            amount_paid=Decimal("0"),
            balance=total,
            bill_status="Pending",
            bill_date=date.today(),
            notes=body.get("description"),
            created_by=session.get("user_id")
        )

        db.add(bill)
        db.commit()

        _log(db, "Bill Created", "Billing",
             f"Bill #{bill.bill_id} OPID {bill.appointment_Id}")

        return jsonify({
            "ok": True,
            "bill_id": bill.bill_id
        })

    finally:
        db.close()


# ─────────────────────────────────────────────
# POST /api/billing/payment  (PAY BILL)
# ─────────────────────────────────────────────
@billing_bp.route("/api/billing/payment", methods=["POST"])
def api_record_payment():

    if session.get("role") not in ["Admin", "Receptionist"]:
        return jsonify({"detail": "Forbidden"}), 403

    db = next(get_db())

    try:
        body = request.get_json()

        bill = db.query(Bill)\
            .filter(Bill.bill_id == body.get("bill_id"))\
            .first()

        if not bill:
            return jsonify({"detail": "Bill not found"}), 404

        amount = Decimal(str(body.get("amount") or 0))

        if amount <= 0:
            return jsonify({"detail": "Invalid amount"}), 400

        # 🔥 CURRENT BALANCE
        current_balance = Decimal(str(bill.balance or 0))

        # 🚫 PREVENT OVERPAYMENT
        if amount > current_balance:
            return jsonify({
                "detail": f"Amount exceeds remaining balance (₹{current_balance})"
            }), 400

        # 🚫 BLOCK PAYMENT IF ALREADY PAID
        if current_balance == Decimal("0"):
            return jsonify({
                "detail": "Bill already fully paid"
            }), 400

        # ✅ CREATE PAYMENT RECORD
        payment = Payment(
            bill_id=bill.bill_id,
            amount=float(amount),
            payment_method=body.get("payment_method"),
            transaction_id=body.get("transaction_id"),
            payment_status="Paid"
        )

        db.add(payment)

        # 🔥 SAFE DECIMAL UPDATE
        bill.amount_paid = (bill.amount_paid or Decimal("0")) + amount
        bill.balance = (bill.total_amount or Decimal("0")) - bill.amount_paid

        # 🔥 FINAL STATUS FIX
        if bill.balance <= Decimal("0"):
            bill.balance = Decimal("0")
            bill.bill_status = "Paid"
        elif bill.amount_paid > Decimal("0"):
            bill.bill_status = "Partial"
        else:
            bill.bill_status = "Pending"

        db.commit()

        _log(
            db,
            "Payment Recorded",
            "Billing",
            f"Bill #{bill.bill_id} | Paid ₹{amount} | Balance ₹{bill.balance}"
        )

        return jsonify({
            "ok": True,
            "status": bill.bill_status,
            "balance": float(bill.balance),
            "amount_paid": float(bill.amount_paid)
        })

    except Exception as e:
        db.rollback()
        return jsonify({"detail": str(e)}), 500

    finally:
        db.close()
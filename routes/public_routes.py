from flask import Blueprint, render_template

public_bp = Blueprint("public", __name__)

# Demo data — no database required
DEMO_STATS = {
    "patients": 75000,
    "doctors": 45,
    "staff": 120
}


@public_bp.route("/")
def home():
    return render_template(
        "public/index.html",
        stats=DEMO_STATS
    )


@public_bp.route("/about")
def about():
    return render_template("public/about.html")


@public_bp.route("/services")
def services():
    return render_template("public/services.html")


@public_bp.route("/doctors")
def doctors():
    return render_template("public/doctors.html")


@public_bp.route("/appointment")
def appointment():
    return render_template(
        "public/appointment.html",
        doctors=[],
        departments=[],
        is_logged_in=False,
        patient=None,
        today=""
    )


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")


@public_bp.route("/patient-register")
def patient_register():
    return render_template("public/register.html")


@public_bp.route("/appointment-success")
def appointment_success():
    return render_template("public/appointment_success.html")

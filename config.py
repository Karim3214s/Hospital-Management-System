from flask_mail import Mail
import os

mail = Mail()

# ── Secret key ────────────────────────────────
SECRET_KEY = "hms-super-secret-key-change-in-prod"

# ── Database Configuration ────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

if DATABASE_URL:
    DATABASE_URL += "?sslmode=require"

SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False

# ── Pagination ────────────────────────────────
PAGINATION = {
    "default": 10,
    "patients": 10,
    "doctors": 10,
    "appointments": 10,
    "billing": 10,
    "audit_logs": 15,
    "users": 10,
    "departments": 10,
    "treatments": 10,
}

# ── Mail Configuration ───────────────────────
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True

MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

MAIL_DEFAULT_SENDER = (
    "HMS",
    os.environ.get("MAIL_USERNAME")
)

# ── App meta ─────────────────────────────────
APP_NAME = "Hospital Management System"
APP_ABBR = "HMS"
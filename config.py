import os

# ─────────────────────────────────────────────
# SECRET KEY
# ─────────────────────────────────────────────
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "hms-super-secret-key-change-in-prod"
)

# ─────────────────────────────────────────────
# DATABASE CONFIGURATION
# ─────────────────────────────────────────────
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace(
        "postgres://",
        "postgresql://",
        1
    )

SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False

# ─────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────
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

# ─────────────────────────────────────────────
# APP META
# ─────────────────────────────────────────────
APP_NAME = "Hospital Management System"
APP_ABBR = "HMS"
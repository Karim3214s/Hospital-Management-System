from flask_mail import Mail
import urllib.parse

mail = Mail()

# ── Secret key ────────────────────────────────
SECRET_KEY = "hms-super-secret-key-change-in-prod"

# ── Database Configuration ────────────────────
DB_NAME = "HMS_DB"
DB_USER = "postgres"
DB_PASS = urllib.parse.quote_plus("K@rim3214s")
DB_HOST = "localhost"
DB_PORT = "5432"

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# REQUIRED for Flask-SQLAlchemy
SQLALCHEMY_DATABASE_URI = DATABASE_URL
SQLALCHEMY_TRACK_MODIFICATIONS = False


# ── Pagination ────────────────────────────────
PAGINATION = {
    "default":      10,
    "patients":     10,
    "doctors":      10,
    "appointments": 10,
    "billing":      10,
    "audit_logs":   15,
    "users":        10,
    "departments":  10,
    "treatments":   10,
}

# ── Mail Configuration ───────────────────────
MAIL_SERVER = "smtp.gmail.com"
MAIL_PORT = 587
MAIL_USE_TLS = True
MAIL_USERNAME = "shaik.karim3214@gmail.com"
MAIL_PASSWORD = "svktbjrxzathdztn"
MAIL_DEFAULT_SENDER = ("HMS", "shaik.karim3214@gmail.com")

# ── App meta ─────────────────────────────────
APP_NAME = "Hospital Management System"
APP_ABBR = "HMS"
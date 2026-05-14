"""
HMS — Hospital Management System
Flask application entry point
"""

from flask import Flask, session, redirect
from flask_mail import Message
from flask_migrate import Migrate

import config
from config import mail

# 🔹 DATABASE
from database import db

# 🔹 BLUEPRINTS
from routes.common_routes       import common_bp
from routes.admin_routes        import admin_bp
from routes.receptionist_routes import receptionist_bp
from routes.doctor_routes       import doctor_bp
from routes.patient_routes      import patient_bp
from routes.auditor_routes      import auditor_bp
from routes.billing_routes      import billing_bp
from routes.public_routes       import public_bp
from routes.chatbot_routes      import chatbot_bp   # ✅ NEW (Ollama chatbot)


# ─────────────────────────────────────────────────────────
# APP FACTORY
# ─────────────────────────────────────────────────────────
def create_app():

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static"
    )

    # 🔐 SECRET KEY
    app.secret_key = config.SECRET_KEY

    # 🔹 CONFIG LOAD
    app.config.from_object(config)

    # 🔹 DATABASE CONFIG
    app.config["SQLALCHEMY_DATABASE_URI"] = config.DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # 🔹 INIT EXTENSIONS
    db.init_app(app)
    Migrate(app, db)
    mail.init_app(app)

    # ─────────────────────────────────────────────────────
    # GLOBAL EMAIL FUNCTION
    # ─────────────────────────────────────────────────────
    def send_email(subject, recipients, body):

        if not recipients:
            return

        recipients = [r for r in recipients if r]

        if not recipients:
            return

        msg = Message(
            subject=subject,
            recipients=recipients,
            body=body
        )

        mail.send(msg)

    app.send_email = send_email

    # ─────────────────────────────────────────────────────
    # REGISTER BLUEPRINTS
    # ─────────────────────────────────────────────────────
    app.register_blueprint(common_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(receptionist_bp)
    app.register_blueprint(doctor_bp)
    app.register_blueprint(patient_bp)
    app.register_blueprint(auditor_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(public_bp)

    # ✅ CHATBOT ROUTE
    app.register_blueprint(chatbot_bp)

    # ─────────────────────────────────────────────────────
    # TEMPLATE SESSION ACCESS
    # ─────────────────────────────────────────────────────
    @app.context_processor
    def inject_session():
        return {"session": session}

    # ─────────────────────────────────────────────────────
    # ERROR HANDLERS
    # ─────────────────────────────────────────────────────
    @app.errorhandler(401)
    def unauthorized(_):
        return redirect("/login")

    @app.errorhandler(403)
    def forbidden(_):
        return redirect("/login")

    @app.errorhandler(404)
    def not_found(e):
        return (
            "<h2 style='font-family:sans-serif;text-align:center;margin-top:4rem'>"
            "404 — Page not found. <a href='/'>Go home</a></h2>"
        ), 404

    return app


# ─────────────────────────────────────────────────────────
# RUN APP
# ─────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, use_reloader=True)
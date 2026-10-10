"""Shared plain-text email utility backed by the application's Flask-Mail setup."""

from flask import current_app
from flask_mail import Message

from .. import mail


def send_email(to_email, subject, body):
    """Send one plain-text message using the existing configured Flask-Mail.

    SMTP errors deliberately propagate to the caller, preserving the
    authentication routes' previous behavior and enabling safe retry logic.
    """
    message = Message(
        subject=subject,
        recipients=[to_email],
        body=body,
        sender=current_app.config["MAIL_DEFAULT_SENDER"],
    )
    mail.send(message)

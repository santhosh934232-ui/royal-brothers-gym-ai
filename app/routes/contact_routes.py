"""
Royal Brothers Fitness Gym - Contact Routes
Handles the public contact form submission from contact.html.

Registered in app/__init__.py under url_prefix="/api/contact", so full path:
    POST /api/contact/send
"""

import re

from flask import Blueprint, request, jsonify

from ..models import create_contact_message

contact_bp = Blueprint("contact_bp", __name__)

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@contact_bp.route("/send", methods=["POST"])
def send_message():
    data = request.get_json() if request.is_json else request.form

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip().lower()
    subject = (data.get("subject") or "").strip()
    message = (data.get("message") or "").strip()

    # ---------- Validation ----------
    if not all([name, phone, email, subject, message]):
        return jsonify({"success": False, "message": "All fields are required."}), 400

    if not EMAIL_PATTERN.match(email):
        return jsonify({"success": False, "message": "Please enter a valid email address."}), 400

    if len(phone) < 10:
        return jsonify({"success": False, "message": "Please enter a valid phone number."}), 400

    create_contact_message(name, phone, email, subject, message)

    return jsonify({
        "success": True,
        "message": "Thanks for reaching out! We'll get back to you soon."
    }), 201

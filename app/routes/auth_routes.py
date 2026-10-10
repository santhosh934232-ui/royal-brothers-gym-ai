"""
Royal Brothers Fitness Gym - Auth Routes
Handles register, login, logout, session check, profile updates,
email verification, and forgot/reset password.
 
Registered in app/__init__.py under url_prefix="/api/auth", so full paths are:
    POST /api/auth/register
    POST /api/auth/login
    POST /api/auth/logout
    GET  /api/auth/me
    PUT  /api/auth/profile
    GET  /api/auth/verify-email
    POST /api/auth/resend-verification
    POST /api/auth/forgot-password
    POST /api/auth/reset-password
"""
 
import secrets
import hashlib
from datetime import datetime, timedelta
 
from flask import Blueprint, request, session, jsonify, current_app
from werkzeug.security import generate_password_hash, check_password_hash

from ..services.email_service import send_email
from ..models import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user_profile,
    create_reset_token,
    get_reset_token,
    delete_reset_token,
    update_user_password,
    create_email_verification_token,
    get_email_verification_token,
    delete_email_verification_token,
    mark_user_verified,
    set_failed_login_attempts,
    reset_login_attempts,
)
 
auth_bp = Blueprint("auth_bp", __name__)
 
# ---------- Tunable security settings ----------
RESET_TOKEN_EXPIRY_MINUTES = 30
EMAIL_VERIFICATION_EXPIRY_MINUTES = 30
MAX_FAILED_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
 
ALLOWED_GENDERS = ("male", "female", "other")
MAX_FULL_NAME_LENGTH = 100
 
 
def get_request_data():
    """
    Supports both JSON requests (fetch with Content-Type: application/json)
    and plain HTML form submissions, so it works no matter how your
    frontend JS ends up sending the data.
    """
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form
 
 
def _hash_token(raw_token):
    """Raw tokens only ever appear in the emailed link. We store a
    SHA-256 hash of them in the DB, so a leaked database can't be used
    to verify accounts or reset passwords."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
 
 
def _build_link(path_and_query):
    """Builds an absolute link for emails. Prefers APP_BASE_URL from
    config (set this in production); falls back to the incoming
    request's host during local development."""
    base = current_app.config.get("APP_BASE_URL") or request.host_url.rstrip("/")
    return f"{base.rstrip('/')}/{path_and_query.lstrip('/')}"
 
 
def _send_verification_email(user):
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(minutes=EMAIL_VERIFICATION_EXPIRY_MINUTES)
 
    create_email_verification_token(user["id"], token_hash, expires_at)
 
    verify_link = _build_link(f"verify-email.html?token={raw_token}")
 
    subject = "Verify Your Email - Royal Brothers Fitness Gym"
    body = f"""Hi {user['full_name']},
 
Thanks for signing up at Royal Brothers Fitness Gym!
 
Please verify your email address by clicking the link below. This link expires in {EMAIL_VERIFICATION_EXPIRY_MINUTES} minutes:
 
{verify_link}
 
You won't be able to log in until your email is verified. If you didn't create this account, you can safely ignore this email.
 
- Royal Brothers Fitness Gym
"""
 
    send_email(user["email"], subject, body)
 
 
# ============================================
# REGISTER
# ============================================
 
@auth_bp.route("/register", methods=["POST"])
def register():
    data = get_request_data()
 
    full_name = (data.get("fullName") or "").strip()
    email = (data.get("registerEmail") or "").strip().lower()
    gender = (data.get("gender") or "").strip().lower()
    password = data.get("registerPassword") or ""
    confirm_password = data.get("confirmPassword") or ""
    agree_terms = data.get("agreeTerms")
 
    if not all([full_name, email, gender, password, confirm_password]):
        return jsonify({"success": False, "message": "All fields are required."}), 400
 
    if "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"success": False, "message": "Please enter a valid email address."}), 400
 
    if password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400
 
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400
 
    if gender not in ALLOWED_GENDERS:
        return jsonify({"success": False, "message": "Invalid gender selected."}), 400
 
    if not agree_terms:
        return jsonify({"success": False, "message": "You must agree to the terms."}), 400
 
    if get_user_by_email(email):
        return jsonify({"success": False, "message": "An account with this email already exists."}), 409
 
    password_hash = generate_password_hash(password)
    user_id = create_user(full_name, email, password_hash, gender)
    user = get_user_by_id(user_id)
 
    try:
        _send_verification_email(user)
    except Exception as e:
        current_app.logger.error(f"[register] Failed to send verification email to {email}: {e}")
        return jsonify({
            "success": True,
            "message": (
                "Account created, but we couldn't send the verification email right now. "
                "Please use the 'Resend verification email' option on the login page."
            ),
            "user": {"id": user_id, "full_name": full_name, "email": email}
        }), 201
 
    return jsonify({
        "success": True,
        "message": "Registration successful. Please check your email to verify your account before logging in.",
        "user": {"id": user_id, "full_name": full_name, "email": email}
    }), 201
 
 
# ============================================
# VERIFY EMAIL
# ============================================
 
@auth_bp.route("/verify-email", methods=["GET"])
def verify_email():
    token = (request.args.get("token") or "").strip()
 
    if not token:
        return jsonify({"success": False, "message": "Missing or invalid verification link."}), 400
 
    token_hash = _hash_token(token)
    token_row = get_email_verification_token(token_hash)
 
    if not token_row:
        return jsonify({
            "success": False,
            "message": "This verification link is invalid or has already been used."
        }), 400
 
    if token_row["expires_at"] < datetime.utcnow():
        delete_email_verification_token(token_hash)
        return jsonify({
            "success": False,
            "message": "This verification link has expired. Please request a new one below."
        }), 400
 
    mark_user_verified(token_row["user_id"])
    delete_email_verification_token(token_hash)
 
    return jsonify({
        "success": True,
        "message": "Your email has been verified successfully. You can now log in."
    }), 200
 
 
# ============================================
# RESEND VERIFICATION EMAIL
# ============================================
 
@auth_bp.route("/resend-verification", methods=["POST"])
def resend_verification():
    data = get_request_data()
    email = (data.get("email") or "").strip().lower()
 
    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400
 
    generic_response = jsonify({
        "success": True,
        "message": "If that account needs verifying, a new verification email has been sent."
    })
 
    user = get_user_by_email(email)
 
    if not user or user["is_verified"]:
        return generic_response, 200
 
    try:
        _send_verification_email(user)
    except Exception as e:
        current_app.logger.error(f"[resend verification] Failed to send email to {email}: {e}")
        return jsonify({
            "success": False,
            "message": "Could not send the verification email. Please try again later."
        }), 500
 
    return generic_response, 200
 
 
# ============================================
# LOGIN
# ============================================
 
@auth_bp.route("/login", methods=["POST"])
def login():
    data = get_request_data()
 
    email = (data.get("loginEmail") or "").strip().lower()
    password = data.get("loginPassword") or ""
    remember_me = data.get("rememberMe")
 
    if not email or not password:
        return jsonify({"success": False, "message": "Email and password are required."}), 400
 
    user = get_user_by_email(email)
 
    if not user:
        return jsonify({"success": False, "message": "Invalid email or password."}), 401
 
    now = datetime.utcnow()
    lockout_until = user.get("lockout_until")
 
    if lockout_until and lockout_until > now:
        remaining_seconds = (lockout_until - now).total_seconds()
        remaining_minutes = max(1, int(remaining_seconds // 60) + 1)
        return jsonify({
            "success": False,
            "message": f"Too many failed login attempts. Please try again after {remaining_minutes} minute(s)."
        }), 403
 
    if lockout_until and lockout_until <= now:
        reset_login_attempts(user["id"])
        user["failed_login_attempts"] = 0
        user["lockout_until"] = None
 
    if not check_password_hash(user["password_hash"], password):
        attempts = (user.get("failed_login_attempts") or 0) + 1
 
        if attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            new_lockout_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            set_failed_login_attempts(user["id"], attempts, new_lockout_until)
            return jsonify({
                "success": False,
                "message": f"Too many failed login attempts. Please try again after {LOCKOUT_MINUTES} minutes."
            }), 403
 
        set_failed_login_attempts(user["id"], attempts, None)
        remaining_attempts = MAX_FAILED_LOGIN_ATTEMPTS - attempts
        return jsonify({
            "success": False,
            "message": f"Invalid email or password. {remaining_attempts} attempt(s) remaining before your account is locked."
        }), 401
 
    if not user["is_verified"]:
        return jsonify({
            "success": False,
            "message": "Please verify your email before logging in. Check your inbox for the verification link, or request a new one.",
            "unverified": True
        }), 403
 
    reset_login_attempts(user["id"])
 
    session.permanent = bool(remember_me)
    session["user_id"] = user["id"]
    session["user_name"] = user["full_name"]
 
    return jsonify({
        "success": True,
        "message": "Login successful.",
        "user": {"id": user["id"], "full_name": user["full_name"], "email": user["email"]}
    }), 200
 
 
# ============================================
# LOGOUT
# ============================================
 
@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True, "message": "Logged out."}), 200
 
 
# ============================================
# SESSION CHECK
# ============================================
 
@auth_bp.route("/me", methods=["GET"])
def me():
    """Frontend can call this to check if a user is currently logged in."""
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Not logged in."}), 401
 
    user = get_user_by_id(session["user_id"])
    if not user:
        session.clear()
        return jsonify({"success": False, "message": "Not logged in."}), 401
 
    return jsonify({
        "success": True,
        "user": {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "gender": user["gender"],
        }
    }), 200
 
 
# ============================================
# UPDATE PROFILE (name + gender)
#
# THIS ROUTE WAS MISSING BEFORE -- this is the fix for the
# "Could not reach the server" bug on the Profile page.
# profile.js sends PUT /api/auth/profile, but no such route existed,
# so Flask's static-file catch-all in app.py matched the URL for GET
# only and returned a 405 with an HTML body. profile.js then tried to
# parse that HTML as JSON, which threw and was caught by the generic
# "Could not reach the server" error handler -- even though the server
# was reachable the whole time. Adding this route fixes it at the root.
# ============================================
 
@auth_bp.route("/profile", methods=["PUT"])
def update_profile():
    if "user_id" not in session:
        return jsonify({"success": False, "message": "Please log in first."}), 401
 
    user = get_user_by_id(session["user_id"])
    if not user:
        session.clear()
        return jsonify({"success": False, "message": "Please log in first."}), 401
 
    data = get_request_data()
 
    full_name = (data.get("fullName") or "").strip()
    gender = (data.get("gender") or "").strip().lower()
 
    # ---------- Validation ----------
    if not full_name:
        return jsonify({"success": False, "message": "Full name cannot be empty."}), 400
 
    if len(full_name) > MAX_FULL_NAME_LENGTH:
        return jsonify({
            "success": False,
            "message": f"Full name must be {MAX_FULL_NAME_LENGTH} characters or fewer."
        }), 400
 
    if gender not in ALLOWED_GENDERS:
        return jsonify({"success": False, "message": "Please select a valid gender."}), 400
 
    # ---------- Update database ----------
    try:
        update_user_profile(session["user_id"], full_name, gender)
    except Exception as e:
        current_app.logger.error(
            f"[update profile] DB update failed for user {session['user_id']}: {e}"
        )
        return jsonify({
            "success": False,
            "message": "Could not update your profile right now. Please try again."
        }), 500
 
    # Keep the session's cached display name in sync (used elsewhere,
    # e.g. navbar greetings) so it doesn't go stale until next login.
    session["user_name"] = full_name
 
    updated_user = get_user_by_id(session["user_id"])
 
    return jsonify({
        "success": True,
        "message": "Profile updated successfully.",
        "user": {
            "id": updated_user["id"],
            "full_name": updated_user["full_name"],
            "email": updated_user["email"],
            "gender": updated_user["gender"],
        }
    }), 200
 
 
# ============================================
# FORGOT PASSWORD
# ============================================
 
@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = get_request_data()
    email = (data.get("email") or "").strip().lower()
 
    if not email:
        return jsonify({"success": False, "message": "Email is required."}), 400
 
    user = get_user_by_email(email)
 
    generic_response = jsonify({
        "success": True,
        "message": "If an account exists for that email, a reset link has been sent."
    })
 
    if not user:
        return generic_response, 200
 
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    expires_at = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRY_MINUTES)
 
    create_reset_token(user["id"], token_hash, expires_at)
 
    reset_link = _build_link(f"reset-password.html?token={raw_token}")
 
    subject = "Reset Your Password - Royal Brothers Fitness Gym"
    body = f"""Hi {user['full_name']},
 
We received a request to reset your Royal Brothers Fitness Gym password.
 
Click the link below to set a new password. This link expires in {RESET_TOKEN_EXPIRY_MINUTES} minutes:
 
{reset_link}
 
If you didn't request this, you can safely ignore this email -- your password will not be changed.
 
- Royal Brothers Fitness Gym
"""
 
    try:
        send_email(user["email"], subject, body)
    except Exception as e:
        current_app.logger.error(f"[forgot password] Failed to send email to {user['email']}: {e}")
        return jsonify({
            "success": False,
            "message": "Could not send the reset email. Please try again later."
        }), 500
 
    return generic_response, 200
 
 
# ============================================
# RESET PASSWORD
# ============================================
 
@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    data = get_request_data()
 
    token = (data.get("token") or "").strip()
    new_password = data.get("newPassword") or ""
    confirm_password = data.get("confirmPassword") or ""
 
    if not token:
        return jsonify({"success": False, "message": "Missing or invalid reset link."}), 400
 
    if not new_password or not confirm_password:
        return jsonify({"success": False, "message": "Please fill in both password fields."}), 400
 
    if new_password != confirm_password:
        return jsonify({"success": False, "message": "Passwords do not match."}), 400
 
    if len(new_password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters."}), 400
 
    token_hash = _hash_token(token)
    token_row = get_reset_token(token_hash)
 
    if not token_row:
        return jsonify({
            "success": False,
            "message": "This reset link is invalid or has already been used."
        }), 400
 
    if token_row["expires_at"] < datetime.utcnow():
        delete_reset_token(token_hash)
        return jsonify({
            "success": False,
            "message": "This reset link has expired. Please request a new one."
        }), 400
 
    password_hash = generate_password_hash(new_password)
    update_user_password(token_row["user_id"], password_hash)
 
    delete_reset_token(token_hash)
    reset_login_attempts(token_row["user_id"])
 
    return jsonify({
        "success": True,
        "message": "Your password has been reset successfully. You can now log in."
    }), 200

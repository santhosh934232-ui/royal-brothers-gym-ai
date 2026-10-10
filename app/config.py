"""
Royal Brothers Fitness Gym - Configuration
Holds Flask app settings, SQLite database path, and Gmail SMTP credentials.

IMPORTANT:
All secrets (SECRET_KEY, MAIL_USERNAME, MAIL_PASSWORD) must be set as
environment variables. Nothing sensitive is hardcoded here.
Copy .env.example to .env, fill in your real values, and load it before
running the app (e.g. with `python-dotenv`, or by exporting the vars in
your shell / hosting provider's config panel).
"""

import os
from dotenv import load_dotenv
load_dotenv()


def _require_env(name):
    """Raises a clear error at startup instead of silently running with
    a missing/blank secret."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it (see .env.example) before starting the app."
        )
    return value


def _reminder_lead_days():
    """Parse the configurable reminder lead-time allowlist safely."""
    default = (7, 3, 1)
    raw = os.environ.get("MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS", "7,3,1")
    try:
        values = tuple(int(part.strip()) for part in raw.split(","))
    except (TypeError, ValueError):
        raise RuntimeError("MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS must be comma-separated integers")
    if (not values or len(values) != len(set(values))
            or any(value < 1 or value > 30 for value in values)
            or not set(default).issubset(values)):
        raise RuntimeError(
            "MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS must contain unique values from 1 to 30, "
            "including the defaults 7,3,1"
        )
    return tuple(sorted(values, reverse=True))


def _trusted_proxy_count():
    raw = os.environ.get("TRUSTED_PROXY_COUNT", "0")
    try:
        count = int(raw)
    except (TypeError, ValueError):
        raise RuntimeError("TRUSTED_PROXY_COUNT must be an integer from 0 to 10")
    if count < 0 or count > 10:
        raise RuntimeError("TRUSTED_PROXY_COUNT must be an integer from 0 to 10")
    return count


REMINDER_DEFAULT_LEAD_DAYS = (7, 3, 1)
REMINDER_ALLOWED_LEAD_DAYS = _reminder_lead_days()


# Project root (the folder containing this app/ package), used to build
# a sensible default path for the SQLite database file.
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    # ---------- Flask / Session Settings ----------
    SECRET_KEY = _require_env("SECRET_KEY")
    TRUSTED_PROXY_COUNT = _trusted_proxy_count()

    SESSION_PERMANENT = False

    # Phase 6 membership reminders: change the supported options through
    # MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS (comma-separated, max 30 days).
    MEMBERSHIP_REMINDER_DEFAULT_LEAD_DAYS = REMINDER_DEFAULT_LEAD_DAYS
    MEMBERSHIP_REMINDER_ALLOWED_LEAD_DAYS = REMINDER_ALLOWED_LEAD_DAYS

    # ---------- SQLite Database Settings ----------
    # Path to the SQLite database file. Defaults to a file named
    # "royal_brothers_gym.db" in the project root. Override with the
    # DATABASE_PATH environment variable if you need it stored
    # somewhere else (e.g. a specific writable directory on
    # PythonAnywhere).
    DB_PATH = os.environ.get(
        "DATABASE_PATH",
        os.path.join(_BASE_DIR, "royal_brothers_gym.db"),
    )

    # ---------- Flask-Mail (Gmail SMTP) Settings ----------
    MAIL_SERVER = "smtp.gmail.com"
    MAIL_PORT = 465
    MAIL_USE_TLS = False
    MAIL_USE_SSL = True
    MAIL_USERNAME = _require_env("MAIL_USERNAME")
    MAIL_PASSWORD = _require_env("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = MAIL_USERNAME
    MAIL_TIMEOUT = 10

    # ---------- App URL (used to build verification/reset links) ----------
    # Set this to your real domain in production (e.g. your PythonAnywhere
    # URL). Falls back to request.host_url at runtime if not set.
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "")

    # ---------- Gemini AI ----------
    # Optional at startup: if GEMINI_API_KEY is missing the app still
    # boots normally and only AI features report "not configured"
    # (see app/services/gemini_service.py). NEVER hard-code the key.
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

    # Single place to change the model. Verify names against
    # https://ai.google.dev/gemini-api/docs/deprecations before changing.
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    # Max seconds to wait for Gemini before giving up with a friendly error.
    GEMINI_TIMEOUT_SECONDS = 20

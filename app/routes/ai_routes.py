"""
Royal Brothers Fitness Gym - AI Integration Test Route
TEMPORARY. Exists only to prove the Flask app can talk to Gemini.
It has no UI and no navigation link, and it is admin-only.

Registered in app/__init__.py under url_prefix="/ai", so full path:
    GET /ai/test      (requires an admin to be logged in)

TO REMOVE LATER: delete this file and delete the two lines marked
"Gemini test route" in app/__init__.py. Nothing else depends on it.
"""

from flask import Blueprint, jsonify

from .admin_routes import admin_login_required
from ..config import Config
from ..services.gemini_service import generate_text, GeminiError

ai_bp = Blueprint("ai_bp", __name__)

TEST_PROMPT = "Reply with exactly: Gemini integration successful."
EXPECTED_REPLY = "Gemini integration successful."


@ai_bp.route("/test", methods=["GET"])
@admin_login_required
def test_gemini():
    try:
        reply = generate_text(TEST_PROMPT, max_output_tokens=1024, temperature=0)
    except GeminiError as e:
        return jsonify({
            "success": False,
            "error_code": e.code,
            "message": e.message,
        }), e.http_status

    return jsonify({
        "success": True,
        "model": Config.GEMINI_MODEL,
        "prompt": TEST_PROMPT,
        "response": reply,
        "matches_expected": reply.strip().strip('"').rstrip(".") == EXPECTED_REPLY.rstrip("."),
    }), 200

"""
Royal Brothers Fitness Gym - Gemini AI Service
The ONLY place in the project that talks to the Google Gemini API.
Route files must never import google.genai directly -- they call
generate_text() from here, so the model, timeout, error handling and
secret-safety live in one spot and every future AI feature reuses them.

Usage (from any route or other module):

    from ..services.gemini_service import generate_text, GeminiError

    try:
        answer = generate_text("Your prompt here")
    except GeminiError as e:
        # e.code is a short machine-readable string, e.message is safe
        # to show to a user, e.http_status is a suggested HTTP status.
        ...

Settings (see app/config.py): GEMINI_API_KEY, GEMINI_MODEL,
GEMINI_TIMEOUT_SECONDS.

SECRET SAFETY:
- The API key is read from the environment only (via Config) -- never
  hard-coded.
- Errors raised from here carry fixed, generic messages. The raw SDK /
  network exception text is NEVER copied into them and NEVER logged
  (only the exception's type name and numeric/enum status are), so the
  key cannot leak into API responses, logs or tracebacks shown to users.
"""

import logging

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ..config import Config

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Raised for every failure in this module. `message` is always safe
    to show to an end user (it never contains secrets or internals)."""

    def __init__(self, code, message, http_status=503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


# Fixed, user-safe messages. Never interpolate exception text into these.
_MESSAGES = {
    "not_configured": "The AI service is not configured yet. Please contact the gym administrator.",
    "invalid_key": "The AI service could not be authorised. Please contact the gym administrator.",
    "rate_limited": "The AI service is busy right now. Please try again in a minute.",
    "timeout": "The AI service took too long to respond. Please try again.",
    "unavailable": "The AI service is temporarily unavailable. Please try again later.",
    "model_unavailable": "The configured AI model is unavailable. Please contact the gym administrator.",
    "bad_request": "The AI service could not process that request.",
    "empty_response": "The AI service returned no answer. Please try again.",
    "empty_prompt": "A prompt is required.",
    "unknown": "Something went wrong while contacting the AI service.",
}

_HTTP_STATUS = {
    "not_configured": 503,
    "invalid_key": 502,
    "rate_limited": 429,
    "timeout": 504,
    "unavailable": 503,
    "model_unavailable": 502,
    "bad_request": 502,
    "empty_response": 502,
    "empty_prompt": 400,
    "unknown": 502,
}


def _error(code):
    return GeminiError(code, _MESSAGES[code], _HTTP_STATUS[code])


# Client is created lazily and reused (it is cheap, but there is no need
# to rebuild it for every request). Keyed by the key + timeout so a
# changed setting is picked up.
_client = None
_client_signature = None


def _get_client():
    global _client, _client_signature

    api_key = (Config.GEMINI_API_KEY or "").strip()
    if not api_key:
        raise _error("not_configured")

    signature = (api_key, Config.GEMINI_TIMEOUT_SECONDS)
    if _client is None or signature != _client_signature:
        try:
            _client = genai.Client(
                api_key=api_key,
                # SDK expects milliseconds
                http_options=types.HttpOptions(timeout=int(Config.GEMINI_TIMEOUT_SECONDS * 1000)),
            )
        except Exception as e:
            # Log only the type -- never the message (may echo config).
            logger.error("Gemini client init failed (%s)", type(e).__name__)
            _client = None
            raise _error("unknown")
        _client_signature = signature
    return _client


def is_configured():
    """True when a Gemini API key is set. Returns only a boolean: the key
    itself is never exposed (used by the admin AI overview)."""
    return bool((Config.GEMINI_API_KEY or "").strip())


def _classify_api_error(exc):
    """Maps a google-genai APIError to one of our safe error codes,
    using only its numeric HTTP code and Google's status enum string."""
    http_code = getattr(exc, "code", None)
    status = (getattr(exc, "status", "") or "").upper()

    # Google reports a bad key as HTTP 400 INVALID_ARGUMENT ("API key not
    # valid") or as 401/403. The SDK exposes only the generic status, so
    # 400 is checked against the (safe) message text without ever
    # forwarding it anywhere.
    if http_code in (401, 403) or status in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
        return "invalid_key"
    if http_code == 400:
        text = (getattr(exc, "message", "") or "").lower()
        if "api key" in text or "api_key" in text:
            return "invalid_key"
        return "bad_request"
    if http_code == 404 or status == "NOT_FOUND":
        return "model_unavailable"
    if http_code == 429 or status == "RESOURCE_EXHAUSTED":
        return "rate_limited"
    if http_code == 504 or status == "DEADLINE_EXCEEDED":
        return "timeout"
    if isinstance(http_code, int) and http_code >= 500:
        return "unavailable"
    return "unknown"


def generate_text(prompt, *, system_instruction=None, max_output_tokens=2048, temperature=None):
    """Sends `prompt` to Gemini and returns the response text (str).

    Raises GeminiError (never anything else) on any failure, with a
    user-safe message. Does not touch the database or Flask context, so
    it can be called from any route, script or test.
    """
    if not prompt or not str(prompt).strip():
        raise _error("empty_prompt")

    client = _get_client()

    config_args = {"max_output_tokens": max_output_tokens}
    if system_instruction:
        config_args["system_instruction"] = system_instruction
    if temperature is not None:
        config_args["temperature"] = temperature

    try:
        response = client.models.generate_content(
            model=Config.GEMINI_MODEL,
            contents=str(prompt),
            config=types.GenerateContentConfig(**config_args),
        )
    except genai_errors.APIError as e:
        code = _classify_api_error(e)
        logger.warning(
            "Gemini API error: http=%s status=%s -> %s",
            getattr(e, "code", None), getattr(e, "status", None), code,
        )
        raise _error(code)
    except httpx.TimeoutException:
        logger.warning("Gemini request timed out")
        raise _error("timeout")
    except httpx.HTTPError as e:
        logger.warning("Gemini network error (%s)", type(e).__name__)
        raise _error("unavailable")
    except Exception as e:
        logger.error("Gemini unexpected error (%s)", type(e).__name__)
        raise _error("unknown")

    # .text is None when the answer was blocked or the model returned no
    # text parts (e.g. safety filter, or token limit hit while thinking).
    text = (getattr(response, "text", None) or "").strip()
    if not text:
        logger.warning("Gemini returned no text")
        raise _error("empty_response")
    return text

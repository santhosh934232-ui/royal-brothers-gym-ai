"""
Royal Brothers Fitness Gym - Database Connection Helper
Provides a single function that all route files use to talk to the
database. Uses Python's built-in sqlite3 module (no extra package
required) instead of mysql-connector-python.

COMPATIBILITY LAYER:
The rest of the project (models.py, scripts/create_admin.py) was
written against mysql-connector-python's API: it calls
conn.cursor(dictionary=True), writes queries with %s placeholders,
reads results as dict-like rows (user["email"], user.get(...)), and
compares timestamp columns directly against Python datetime objects
(e.g. token_row["expires_at"] < datetime.utcnow()). SQLite's built-in
sqlite3 module differs on all of these by default. Rather than
rewriting every query and every comparison across the project, this
file wraps sqlite3 so all of that keeps working unchanged:
  - %s placeholders are translated to SQLite's ? placeholders.
  - Every cursor returns plain dict rows (dictionary=True is accepted
    and ignored, since rows are always dicts here).
  - TIMESTAMP/DATETIME columns are automatically converted back into
    real Python datetime objects when read, and Python datetime
    objects are automatically converted to text when written.
"""

import datetime
import sqlite3
from pathlib import Path

from .config import Config


# ---------- datetime <-> SQLite text conversion ----------
# Without this, a Python datetime.datetime bound as a query parameter
# is stored as plain text, and reading it back gives a plain string --
# breaking every expiry/lockout comparison in the project (e.g.
# `token_row["expires_at"] < datetime.utcnow()`), since Python cannot
# compare a string to a datetime. Registering these makes the
# round-trip transparent: every TIMESTAMP/DATETIME column comes back
# as a real datetime object again, exactly like mysql-connector gave.
def _adapt_datetime(dt):
    return dt.isoformat(sep=" ")


def _convert_timestamp(value):
    text = value.decode() if isinstance(value, bytes) else value
    return datetime.datetime.fromisoformat(text)


sqlite3.register_adapter(datetime.datetime, _adapt_datetime)
sqlite3.register_converter("TIMESTAMP", _convert_timestamp)
sqlite3.register_converter("DATETIME", _convert_timestamp)


def _dict_factory(cursor, row):
    """Makes every row behave like a plain dict, e.g. row["email"] and
    row.get("email") both work -- matching what mysql-connector's
    cursor(dictionary=True) returned."""
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class _CompatCursor:
    """Wraps a real sqlite3.Cursor so existing code written for
    mysql-connector (which uses %s placeholders) keeps working
    unchanged against SQLite (which uses ? placeholders)."""

    __slots__ = ("_cursor",)

    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, query, params=None):
        sqlite_query = query.replace("%s", "?")
        if params is None:
            return self._cursor.execute(sqlite_query)
        return self._cursor.execute(sqlite_query, params)

    def __getattr__(self, name):
        # Forwards everything else (fetchone, fetchall, lastrowid,
        # close, etc.) straight to the real sqlite3 cursor.
        return getattr(self._cursor, name)


class _CompatConnection:
    """Wraps a real sqlite3.Connection so conn.cursor(dictionary=True),
    exactly as used throughout models.py for mysql-connector, keeps
    working unchanged -- rows come back as plain dicts either way."""

    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def cursor(self, dictionary=None):
        # `dictionary` is accepted (and ignored) for compatibility --
        # the row factory below already makes every cursor return
        # dict-like rows, regardless of this flag.
        return _CompatCursor(self._conn.cursor())

    def __getattr__(self, name):
        # Forwards everything else (commit, close, etc.) straight to
        # the real sqlite3 connection.
        return getattr(self._conn, name)


def get_db_connection(read_only=False):
    """
    Returns a SQLite connection (wrapped for mysql-connector
    compatibility). Each route function should call this, use it, and
    close it when done -- exactly the same usage pattern as before:

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()

    SQLite connections are lightweight (just a local file handle), so
    unlike the previous MySQL setup, opening and closing one per request
    is fast and safe. When ``read_only=True``, SQLite's URI ``mode=ro`` is
    used so a missing database is not created and writes are rejected by
    SQLite itself.
    """
    try:
        if read_only:
            database_uri = f"{Path(Config.DB_PATH).expanduser().resolve().as_uri()}?mode=ro"
            raw_conn = sqlite3.connect(
                database_uri,
                uri=True,
                detect_types=sqlite3.PARSE_DECLTYPES,
            )
        else:
            raw_conn = sqlite3.connect(Config.DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        raw_conn.row_factory = _dict_factory
        # Enforces ON DELETE CASCADE (used by membership_requests,
        # password_reset_tokens, email_verification_tokens) -- SQLite
        # ignores foreign key constraints unless this is turned on for
        # every connection.
        raw_conn.execute("PRAGMA foreign_keys = ON")
        return _CompatConnection(raw_conn)
    except sqlite3.Error as e:
        # Keep legacy diagnostics for normal connections. Read-only access
        # can fail for missing paths; do not print the configured DB path.
        detail = type(e).__name__ if read_only else str(e)
        print(f"[Database Connection Error] {detail}")
        raise

"""
Royal Brothers Fitness Gym - Models
Functions that read/write to MySQL. Route files call these instead of
writing raw SQL themselves, keeping the query logic in one place.
"""

from .extensions import get_db_connection


# ============================================
# USERS
# ============================================

def create_user(full_name, email, password_hash, gender):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO users (full_name, email, password_hash, gender, is_verified)
           VALUES (%s, %s, %s, %s, 0)""",
        (full_name, email, password_hash, gender),
    )
    conn.commit()
    new_user_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_user_id


def get_user_by_email(email):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def get_user_by_id(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    return user


def update_user_profile(user_id, full_name, gender):
    """Used by the Profile page's Edit Profile form (Bug 5)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET full_name = %s, gender = %s WHERE id = %s",
        (full_name, gender, user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_all_users():
    """Used by the admin dashboard's Manage Members page.

    Only returns users with is_verified = 1. Unverified accounts
    (e.g. someone who registered with a fake/typo'd email and never
    clicked the verification link) are intentionally excluded -- they
    aren't real members yet and shouldn't show up here. As soon as a
    user clicks their verification link, mark_user_verified() flips
    their is_verified flag to 1 and they appear here automatically on
    the next load, with no other change needed.

    Also includes each member's most recent membership plan name as
    `current_plan` (via a join on membership_requests/membership_plans).
    This field is NOT rendered as a new table column -- it exists so the
    admin panel's real-time Members search can filter by plan name
    without changing the existing table UI. It will be NULL for members
    who have never submitted a membership request.

    Note: there is no phone number stored on `users` (phone only exists
    on the unrelated `contact_messages` table), so phone search is not
    possible from this data as-is. See delivery notes.
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """
        SELECT u.id, u.full_name, u.email, u.gender, u.created_at,
               mp.plan_name AS current_plan
        FROM users u
        LEFT JOIN (
            SELECT mr1.user_id, mr1.plan_id
            FROM membership_requests mr1
            INNER JOIN (
                SELECT user_id, MAX(request_date) AS max_date
                FROM membership_requests
                GROUP BY user_id
            ) latest ON mr1.user_id = latest.user_id
                    AND mr1.request_date = latest.max_date
        ) latest_req ON u.id = latest_req.user_id
        LEFT JOIN membership_plans mp ON latest_req.plan_id = mp.id
        WHERE u.is_verified = 1
        ORDER BY u.created_at DESC
        """
    )
    users = cursor.fetchall()
    cursor.close()
    conn.close()
    return users


# ============================================
# EMAIL VERIFICATION
# (Registration workflow: user gets an email with a link, clicks it
# within the expiry window, and their account becomes usable for login
# and visible in the admin Members list.)
# ============================================

def create_email_verification_token(user_id, token_hash, expires_at):
    """Stores a hashed verification token for the given user. Any
    previous tokens for this user are deleted first, so only the most
    recently sent verification link is ever valid (older links become
    invalid automatically, e.g. after using "Resend verification
    email")."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM email_verification_tokens WHERE user_id = %s", (user_id,)
    )
    cursor.execute(
        """INSERT INTO email_verification_tokens (user_id, token_hash, expires_at)
           VALUES (%s, %s, %s)""",
        (user_id, token_hash, expires_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_email_verification_token(token_hash):
    """Returns the token row (with user_id and expires_at) for a given
    hashed token, or None if it doesn't exist. Does NOT check expiry
    itself -- the caller compares expires_at against the current time,
    so callers can distinguish "invalid token" from "expired token"."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM email_verification_tokens WHERE token_hash = %s",
        (token_hash,),
    )
    token_row = cursor.fetchone()
    cursor.close()
    conn.close()
    return token_row


def delete_email_verification_token(token_hash):
    """Removes a single token by its hash. Called right after a
    successful verification (or an expired one) so the link can't be
    reused."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM email_verification_tokens WHERE token_hash = %s", (token_hash,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def mark_user_verified(user_id):
    """Flips is_verified on for the account. Called once the token has
    been validated. This is what makes the user show up in
    get_all_users() and count toward get_dashboard_stats()'s
    total_users."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET is_verified = 1 WHERE id = %s", (user_id,)
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# LOGIN SECURITY (failed-attempt lockout)
# ============================================

def set_failed_login_attempts(user_id, attempts, lockout_until=None):
    """Overwrites the failed-attempt counter and (optionally) sets a
    lockout expiry. Called after a wrong password: attempts is the new
    count, and lockout_until is only passed once the 5th consecutive
    failure is hit."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_login_attempts = %s, lockout_until = %s WHERE id = %s",
        (attempts, lockout_until, user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def reset_login_attempts(user_id):
    """Clears the failed-attempt counter and any lockout. Called after
    a successful login, and also when a lockout has naturally expired
    so the next login attempt starts clean."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET failed_login_attempts = 0, lockout_until = NULL WHERE id = %s",
        (user_id,),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# MEMBERSHIP PLANS
# ============================================

def get_all_plans():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM membership_plans ORDER BY duration_months ASC")
    plans = cursor.fetchall()
    cursor.close()
    conn.close()
    for plan in plans:
        plan["price"] = float(plan["price"])
    return plans


def get_plan_by_id(plan_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM membership_plans WHERE id = %s", (plan_id,))
    plan = cursor.fetchone()
    cursor.close()
    conn.close()
    if plan:
        plan["price"] = float(plan["price"])
    return plan


def create_plan(plan_name, duration_months, price, features):
    """Used by the admin dashboard's Manage Membership Plans page."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO membership_plans (plan_name, duration_months, price, features)
           VALUES (%s, %s, %s, %s)""",
        (plan_name, duration_months, price, features),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_plan(plan_id, plan_name, duration_months, price, features):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE membership_plans
           SET plan_name = %s, duration_months = %s, price = %s, features = %s
           WHERE id = %s""",
        (plan_name, duration_months, price, features, plan_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def delete_plan(plan_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM membership_plans WHERE id = %s", (plan_id,))
    conn.commit()
    cursor.close()
    conn.close()


def get_plan_usage_count(plan_id):
    """Returns how many membership_requests reference this plan (any
    status). Used to block deletion of a plan that's actively in use,
    instead of letting a foreign-key constraint throw an unhandled
    500 error."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT COUNT(*) AS usage_count FROM membership_requests WHERE plan_id = %s",
        (plan_id,),
    )
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result["usage_count"]


# ============================================
# MEMBERSHIP REQUESTS
# (the "Get Started" workflow: user requests a plan, admin approves it)
# ============================================

def create_membership_request(user_id, plan_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO membership_requests (user_id, plan_id, status)
           VALUES (%s, %s, 'pending')""",
        (user_id, plan_id),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def get_active_or_pending_request(user_id):
    """Returns the user's current active/pending request, or None.
    Used to block duplicate requests (Bug 6)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT mr.*, mp.plan_name, mp.duration_months, mp.price
           FROM membership_requests mr
           JOIN membership_plans mp ON mr.plan_id = mp.id
           WHERE mr.user_id = %s AND mr.status IN ('pending', 'active')
           ORDER BY mr.request_date DESC LIMIT 1""",
        (user_id,),
    )
    request = cursor.fetchone()
    cursor.close()
    conn.close()
    if request:
        request["price"] = float(request["price"])
    return request


def get_latest_membership_request(user_id):
    """Returns the user's most recent request regardless of status
    (including rejected), for display on the profile page."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT mr.*, mp.plan_name, mp.duration_months, mp.price
           FROM membership_requests mr
           JOIN membership_plans mp ON mr.plan_id = mp.id
           WHERE mr.user_id = %s
           ORDER BY mr.request_date DESC LIMIT 1""",
        (user_id,),
    )
    request = cursor.fetchone()
    cursor.close()
    conn.close()
    if request:
        request["price"] = float(request["price"])
    return request


def get_all_membership_requests():
    """Used by the admin dashboard to review/approve/reject requests."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT mr.*, mp.plan_name, mp.duration_months, mp.price,
                  u.full_name, u.email
           FROM membership_requests mr
           JOIN membership_plans mp ON mr.plan_id = mp.id
           JOIN users u ON mr.user_id = u.id
           ORDER BY mr.request_date DESC"""
    )
    requests = cursor.fetchall()
    cursor.close()
    conn.close()
    for r in requests:
        r["price"] = float(r["price"])
    return requests


def update_membership_request_status(request_id, status, start_date=None, end_date=None):
    """status must be one of: pending, active, rejected.
    When activating, pass start_date/end_date (calculated by the caller
    based on the plan's duration)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE membership_requests
           SET status = %s, start_date = %s, end_date = %s
           WHERE id = %s""",
        (status, start_date, end_date, request_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_membership_request_by_id(request_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT mr.*, mp.duration_months
           FROM membership_requests mr
           JOIN membership_plans mp ON mr.plan_id = mp.id
           WHERE mr.id = %s""",
        (request_id,),
    )
    request = cursor.fetchone()
    cursor.close()
    conn.close()
    return request


def delete_membership_request(request_id):
    """Permanently deletes a membership request (used by the admin
    dashboard's Membership Requests page to let the admin remove a
    member's membership record, regardless of its status)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM membership_requests WHERE id = %s", (request_id,))
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# CONTACT MESSAGES
# ============================================

def create_contact_message(name, phone, email, subject, message):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO contact_messages (name, phone, email, subject, message)
           VALUES (%s, %s, %s, %s, %s)""",
        (name, phone, email, subject, message),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def get_all_contact_messages():
    """Used by the admin dashboard's Contact Messages page."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM contact_messages ORDER BY created_at DESC")
    messages = cursor.fetchall()
    cursor.close()
    conn.close()
    return messages


def mark_message_as_read(message_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE contact_messages SET is_read = TRUE WHERE id = %s", (message_id,)
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# PASSWORD RESET TOKENS
# (Forgot Password workflow: user requests a reset link, clicks it
# within 30 minutes, and sets a new password.)
# ============================================

def create_reset_token(user_id, token_hash, expires_at):
    """Stores a hashed reset token for the given user. Any previous
    tokens for this user are deleted first, so only one reset link
    is ever valid at a time (older links become invalid automatically
    when a new one is requested)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,)
    )
    cursor.execute(
        """INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
           VALUES (%s, %s, %s)""",
        (user_id, token_hash, expires_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


def get_reset_token(token_hash):
    """Returns the token row (with user_id and expires_at) for a given
    hashed token, or None if it doesn't exist. Does NOT check expiry
    itself -- the caller compares expires_at against the current time,
    so callers can distinguish "invalid token" from "expired token"."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM password_reset_tokens WHERE token_hash = %s",
        (token_hash,),
    )
    token_row = cursor.fetchone()
    cursor.close()
    conn.close()
    return token_row


def delete_reset_token(token_hash):
    """Removes a single token by its hash. Called right after a
    successful password reset so the link can't be reused."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM password_reset_tokens WHERE token_hash = %s", (token_hash,)
    )
    conn.commit()
    cursor.close()
    conn.close()


def update_user_password(user_id, password_hash):
    """Overwrites the user's password hash. Used by the reset-password
    step after the token has been verified."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (password_hash, user_id),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# ADMINS
# ============================================

def get_admin_by_username(username):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admins WHERE username = %s", (username,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin


def get_admin_by_id(admin_id):
    """Used by the secure delete-confirmation workflow to verify the
    password of whichever admin is currently logged in (session
    stores admin_id, not username)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM admins WHERE id = %s", (admin_id,))
    admin = cursor.fetchone()
    cursor.close()
    conn.close()
    return admin


# ============================================
# ADMIN DASHBOARD STATS
# ============================================

def get_dashboard_stats():
    """Used by the admin dashboard's Overview page and sidebar badges.
    Returns total members, pending membership requests, and unread
    contact messages in a single set of queries.

    total_users counts only is_verified = 1, so this card always
    matches the Members list count exactly (unverified/never-confirmed
    signups are excluded from both).
    """
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total_users FROM users WHERE is_verified = 1")
    total_users = cursor.fetchone()["total_users"]

    cursor.execute(
        "SELECT COUNT(*) AS unread_messages FROM contact_messages WHERE is_read = FALSE"
    )
    unread_messages = cursor.fetchone()["unread_messages"]

    cursor.execute(
        "SELECT COUNT(*) AS pending_requests FROM membership_requests WHERE status = 'pending'"
    )
    pending_requests = cursor.fetchone()["pending_requests"]

    cursor.close()
    conn.close()

    return {
        "total_users": total_users,
        "unread_messages": unread_messages,
        "pending_requests": pending_requests,
    }

# ============================================
# FITNESS PROFILES (Step 2)
# One row per member; always keyed by the logged-in user's id.
# ============================================

def get_fitness_profile(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        """SELECT fitness_goal, height_cm, weight_kg, workout_experience,
                  available_workout_minutes, college_work_timing
           FROM fitness_profiles WHERE user_id = %s""",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_fitness_profile(user_id, fitness_goal, height_cm, weight_kg,
                         workout_experience, available_workout_minutes,
                         college_work_timing):
    """Creates the member's fitness profile, or updates it if it exists."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO fitness_profiles
             (user_id, fitness_goal, height_cm, weight_kg, workout_experience,
              available_workout_minutes, college_work_timing, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
           ON CONFLICT(user_id) DO UPDATE SET
             fitness_goal = excluded.fitness_goal,
             height_cm = excluded.height_cm,
             weight_kg = excluded.weight_kg,
             workout_experience = excluded.workout_experience,
             available_workout_minutes = excluded.available_workout_minutes,
             college_work_timing = excluded.college_work_timing,
             updated_at = CURRENT_TIMESTAMP""",
        (user_id, fitness_goal, height_cm, weight_kg, workout_experience,
         available_workout_minutes, college_work_timing),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# WORKOUT PLANS (Step 3)
# Latest AI-generated plan per member, stored as validated JSON text.
# ============================================

def get_workout_plan(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT plan_json, created_at FROM workout_plans WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_workout_plan(user_id, plan_json, created_at):
    """Stores the member's plan, replacing any previous one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO workout_plans (user_id, plan_json, created_at)
           VALUES (%s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             plan_json = excluded.plan_json,
             created_at = excluded.created_at""",
        (user_id, plan_json, created_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# DAILY PLANS (Step 4)
# Latest AI-generated daily schedule per member, stored as validated JSON.
# ============================================

def get_daily_plan(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT plan_json, created_at FROM daily_plans WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_daily_plan(user_id, plan_json, created_at):
    """Stores the member's daily plan, replacing any previous one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO daily_plans (user_id, plan_json, created_at)
           VALUES (%s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             plan_json = excluded.plan_json,
             created_at = excluded.created_at""",
        (user_id, plan_json, created_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# PROGRESS ENTRIES (Step 5)
# Member weight/progress log. EVERY query is scoped by user_id, so a
# member can never read or change another member's entries.
# ============================================

PROGRESS_COLUMNS = "id, entry_date, weight_kg, notes, created_at, updated_at"
PROGRESS_LIST_LIMIT = 500


def list_progress_entries(user_id):
    """The member's entries, oldest first (capped at the newest 500)."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        f"""SELECT {PROGRESS_COLUMNS} FROM (
              SELECT {PROGRESS_COLUMNS} FROM progress_entries
              WHERE user_id = %s ORDER BY entry_date DESC LIMIT %s
            ) ORDER BY entry_date ASC""",
        (user_id, PROGRESS_LIST_LIMIT),
    )
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows


def get_progress_entry(user_id, entry_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        f"SELECT {PROGRESS_COLUMNS} FROM progress_entries WHERE id = %s AND user_id = %s",
        (entry_id, user_id),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def progress_date_exists(user_id, entry_date, exclude_id=None):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id FROM progress_entries WHERE user_id = %s AND entry_date = %s AND id != %s",
        (user_id, entry_date, exclude_id if exclude_id is not None else -1),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row is not None


def create_progress_entry(user_id, entry_date, weight_kg, notes):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO progress_entries (user_id, entry_date, weight_kg, notes)
           VALUES (%s, %s, %s, %s)""",
        (user_id, entry_date, weight_kg, notes),
    )
    conn.commit()
    new_id = cursor.lastrowid
    cursor.close()
    conn.close()
    return new_id


def update_progress_entry(user_id, entry_id, entry_date, weight_kg, notes):
    """Returns True if the member owned that entry and it was updated."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE progress_entries
           SET entry_date = %s, weight_kg = %s, notes = %s, updated_at = CURRENT_TIMESTAMP
           WHERE id = %s AND user_id = %s""",
        (entry_date, weight_kg, notes, entry_id, user_id),
    )
    conn.commit()
    changed = cursor.rowcount > 0
    cursor.close()
    conn.close()
    return changed


def delete_progress_entry(user_id, entry_id):
    """Returns True if the member owned that entry and it was deleted."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM progress_entries WHERE id = %s AND user_id = %s",
        (entry_id, user_id),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    cursor.close()
    conn.close()
    return deleted


# ============================================
# AI INSIGHTS (Step 6)
# Latest AI-generated insight per member, stored as validated JSON.
# ============================================

def get_ai_insight(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT insight_json, created_at FROM ai_insights WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_ai_insight(user_id, insight_json, created_at):
    """Stores the member's insight, replacing any previous one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO ai_insights (user_id, insight_json, created_at)
           VALUES (%s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             insight_json = excluded.insight_json,
             created_at = excluded.created_at""",
        (user_id, insight_json, created_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# WORKOUT RECOMMENDATIONS (Step 7)
# Latest AI-generated recommendation per member, stored as validated JSON.
# ============================================

def get_workout_recommendation(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT recommendation_json, created_at FROM workout_recommendations WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_workout_recommendation(user_id, recommendation_json, created_at):
    """Stores the member's recommendation, replacing any previous one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO workout_recommendations (user_id, recommendation_json, created_at)
           VALUES (%s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             recommendation_json = excluded.recommendation_json,
             created_at = excluded.created_at""",
        (user_id, recommendation_json, created_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# NUTRITION PLANS (Step 8)
# Latest AI-generated nutrition plan per member, stored as validated JSON.
# ============================================

def get_nutrition_plan(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT plan_json, created_at FROM nutrition_plans WHERE user_id = %s",
        (user_id,),
    )
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row


def save_nutrition_plan(user_id, plan_json, created_at):
    """Stores the member's nutrition plan, replacing any previous one."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO nutrition_plans (user_id, plan_json, created_at)
           VALUES (%s, %s, %s)
           ON CONFLICT(user_id) DO UPDATE SET
             plan_json = excluded.plan_json,
             created_at = excluded.created_at""",
        (user_id, plan_json, created_at),
    )
    conn.commit()
    cursor.close()
    conn.close()


# ============================================
# AI RECORD STATISTICS (Step 10 - admin AI management, read-only)
# Counts and latest timestamp of the AI-generated rows each feature has
# saved. Never selects any content column, so no member data leaves here.
# ============================================

# Fixed whitelist (table names are never taken from a request).
AI_RECORD_TABLES = {
    "workout_plan": "workout_plans",
    "daily_plan": "daily_plans",
    "insight": "ai_insights",
    "recommendation": "workout_recommendations",
    "nutrition_plan": "nutrition_plans",
}


def get_ai_record_stats():
    """Returns {key: {"count": int, "latest": str|None} | None}.
    A value of None means that table could not be read (for example the
    database has not been migrated yet): callers show it as unavailable
    instead of failing."""
    stats = {}
    for key, table in AI_RECORD_TABLES.items():
        conn = cursor = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"SELECT COUNT(*) AS total, MAX(created_at) AS latest FROM {table}")
            row = cursor.fetchone()
            stats[key] = {
                "count": int(row["total"]),
                "latest": str(row["latest"]) if row["latest"] else None,
            }
        except Exception:
            stats[key] = None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
    return stats

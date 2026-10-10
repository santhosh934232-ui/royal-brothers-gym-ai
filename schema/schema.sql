-- ============================================
-- Royal Brothers Fitness Gym - Full Database Schema (SQLite)
-- Use this to set up a BRAND NEW database from scratch.
--
-- Unlike MySQL, SQLite has no server or "CREATE DATABASE" step --
-- the database is just this one file. Running this script (see the
-- "Create the SQLite database locally" instructions at the end of
-- this conversation) creates that file with all tables in it.
--
-- If you already have an existing royal_brothers_gym.db file with
-- data in it from an older/partial version of this project, do NOT
-- run this file. Use the backup-first, repeatable runner:
--   python scripts/migrate_db.py --check
--   python scripts/migrate_db.py
-- ============================================

PRAGMA foreign_keys = ON;

-- ---------- ADMINS ----------
CREATE TABLE IF NOT EXISTS admins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- USERS ----------
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  full_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other')),
  google_id TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  profile_photo TEXT DEFAULT NULL,
  -- Set to 1 only after the user clicks their email verification link
  is_verified INTEGER NOT NULL DEFAULT 0,
  -- Consecutive wrong-password count, reset to 0 on successful login
  failed_login_attempts INTEGER NOT NULL DEFAULT 0,
  -- If set and in the future, login is blocked until this time
  lockout_until DATETIME DEFAULT NULL
);

-- ---------- MEMBERSHIP PLANS ----------
CREATE TABLE IF NOT EXISTS membership_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_name TEXT NOT NULL,
  duration_months INTEGER NOT NULL,
  price NUMERIC(10, 2) NOT NULL,
  features TEXT
);

-- ---------- MEMBERSHIP REQUESTS ----------
CREATE TABLE IF NOT EXISTS membership_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  plan_id INTEGER NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'active', 'rejected')),
  request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  start_date DATE DEFAULT NULL,
  end_date DATE DEFAULT NULL,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  FOREIGN KEY (plan_id) REFERENCES membership_plans (id)
);

CREATE INDEX IF NOT EXISTS idx_membership_requests_user_id ON membership_requests (user_id);
CREATE INDEX IF NOT EXISTS idx_membership_requests_plan_id ON membership_requests (plan_id);

-- ---------- CONTACT MESSAGES ----------
CREATE TABLE IF NOT EXISTS contact_messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  phone TEXT NOT NULL,
  email TEXT NOT NULL,
  subject TEXT NOT NULL,
  message TEXT NOT NULL,
  is_read INTEGER DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ---------- PASSWORD RESET TOKENS ----------
CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_password_reset_user_id ON password_reset_tokens (user_id);

-- ---------- EMAIL VERIFICATION TOKENS ----------
CREATE TABLE IF NOT EXISTS email_verification_tokens (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_email_verification_user_id ON email_verification_tokens (user_id);

-- ---------- FITNESS PROFILES (Step 2) ----------
-- One row per member. Members only ever read/write their own row
-- (user_id always comes from the login session, never from the client).
CREATE TABLE IF NOT EXISTS fitness_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  fitness_goal TEXT NOT NULL CHECK (fitness_goal IN ('weight_loss', 'muscle_gain', 'strength', 'endurance', 'general_fitness')),
  height_cm REAL NOT NULL CHECK (height_cm BETWEEN 100 AND 250),
  weight_kg REAL NOT NULL CHECK (weight_kg BETWEEN 30 AND 300),
  workout_experience TEXT NOT NULL CHECK (workout_experience IN ('beginner', 'intermediate', 'advanced')),
  available_workout_minutes INTEGER NOT NULL CHECK (available_workout_minutes BETWEEN 15 AND 240),
  college_work_timing TEXT DEFAULT NULL,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- WORKOUT PLANS (Step 3) ----------
-- Latest AI-generated 7-day plan per member (regenerating replaces it).
CREATE TABLE IF NOT EXISTS workout_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- DAILY PLANS (Step 4) ----------
-- Latest AI-generated daily schedule per member (regenerating replaces it).
CREATE TABLE IF NOT EXISTS daily_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- PROGRESS ENTRIES (Step 5) ----------
-- Member weight/progress log: one entry per member per date. Members only
-- ever read/write their own rows (user_id always comes from the session).
CREATE TABLE IF NOT EXISTS progress_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  entry_date TEXT NOT NULL CHECK (entry_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  weight_kg REAL NOT NULL CHECK (weight_kg BETWEEN 30 AND 300),
  notes TEXT DEFAULT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, entry_date),
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- AI INSIGHTS (Step 6) ----------
-- Latest AI-generated fitness insight per member (regenerating replaces it).
-- Insights are advice only: they never change progress entries or plans.
CREATE TABLE IF NOT EXISTS ai_insights (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  insight_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- WORKOUT RECOMMENDATIONS (Step 7) ----------
-- Latest AI-generated recommendation per member (regenerating replaces it).
-- Suggestions only: they never change the workout plan or progress entries.
CREATE TABLE IF NOT EXISTS workout_recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  recommendation_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);


-- ---------- NUTRITION PLANS (Step 8) ----------
-- Latest AI-generated nutrition plan per member (regenerating replaces it).
-- General guidance only: it never changes the profile, workout plan or progress entries.
CREATE TABLE IF NOT EXISTS nutrition_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- ---------- MEMBERSHIP REMINDER PREFERENCES (Phase 6) ----------
-- Opt-in preference row; absence means disabled. Lead-time choices are
-- normalized; the service uses a server-configured allowlist (bounded here
-- to 1-30 days) and the composite key prevents duplicates.
CREATE TABLE IF NOT EXISTS membership_reminder_preferences (
  user_id INTEGER PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS membership_reminder_lead_times (
  user_id INTEGER NOT NULL,
  lead_days INTEGER NOT NULL CHECK (lead_days BETWEEN 1 AND 30),
  PRIMARY KEY (user_id, lead_days),
  FOREIGN KEY (user_id) REFERENCES membership_reminder_preferences (user_id) ON DELETE CASCADE
);

-- ---------- MEMBERSHIP REMINDER DELIVERY (Phase 7) ----------
-- One row per member/membership/expiry/lead key prevents duplicate success.
-- Individual attempts remain available in the child history table.
CREATE TABLE IF NOT EXISTS membership_reminder_deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  membership_request_id INTEGER NOT NULL,
  expiry_date DATE NOT NULL,
  lead_days INTEGER NOT NULL CHECK (lead_days BETWEEN 1 AND 30),
  reminder_date DATE NOT NULL,
  retry_until_date DATE NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 3),
  retryable INTEGER NOT NULL DEFAULT 1 CHECK (retryable IN (0, 1)),
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  first_attempt_at TIMESTAMP,
  last_attempt_at TIMESTAMP,
  next_attempt_at TIMESTAMP,
  lease_until TIMESTAMP,
  sent_at TIMESTAMP,
  failure_code TEXT CHECK (failure_code IS NULL OR length(failure_code) <= 64),
  failure_reason TEXT CHECK (failure_reason IS NULL OR length(failure_reason) <= 160),
  UNIQUE (user_id, membership_request_id, expiry_date, lead_days),
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE,
  FOREIGN KEY (membership_request_id) REFERENCES membership_requests (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reminder_deliveries_due
  ON membership_reminder_deliveries (status, retryable, next_attempt_at, lease_until);
CREATE INDEX IF NOT EXISTS idx_reminder_deliveries_user_created
  ON membership_reminder_deliveries (user_id, created_at);

CREATE TABLE IF NOT EXISTS membership_reminder_delivery_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  delivery_id INTEGER NOT NULL,
  attempt_number INTEGER NOT NULL CHECK (attempt_number BETWEEN 1 AND 3),
  status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
  started_at TIMESTAMP NOT NULL,
  finished_at TIMESTAMP,
  failure_code TEXT CHECK (failure_code IS NULL OR length(failure_code) <= 64),
  failure_reason TEXT CHECK (failure_reason IS NULL OR length(failure_reason) <= 160),
  UNIQUE (delivery_id, attempt_number),
  FOREIGN KEY (delivery_id) REFERENCES membership_reminder_deliveries (id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reminder_attempts_delivery_started
  ON membership_reminder_delivery_attempts (delivery_id, started_at);

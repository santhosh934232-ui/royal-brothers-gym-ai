-- ============================================
-- Royal Brothers Fitness Gym - Schema Updates (SQLite)
-- Legacy SQL reference for an existing royal_brothers_gym.db that is
-- missing the email verification + login lockout columns/table.
-- Preferred operation is the backup-first, idempotent runner:
--   python scripts/migrate_db.py --check
--   python scripts/migrate_db.py
-- Do not blindly execute this file more than once: SQLite's ALTER TABLE
-- ADD COLUMN statements are not idempotent. The migration runner reads
-- these statements and applies only the columns that are missing.
--
-- For a brand new database, use schema/schema.sql instead -- it
-- already includes these columns/table from the start.
--
-- Note: SQLite only allows one ADD COLUMN per ALTER TABLE statement
-- (MySQL allowed chaining several in one statement), so these are
-- split into separate statements below.
-- ============================================

PRAGMA foreign_keys = ON;

-- ---------- USERS: email verification + lockout tracking ----------
ALTER TABLE users ADD COLUMN is_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN lockout_until DATETIME DEFAULT NULL;

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

-- ---------- Grandfather in existing real accounts ----------
-- Without this, every account that existed before this migration
-- would suddenly be unverified and locked out of login. Uncomment if
-- you have real existing members using the site:
-- UPDATE users SET is_verified = 1;

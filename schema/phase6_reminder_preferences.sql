-- ============================================
-- Phase 6 migration: Smart Reminder preferences
-- Additive and safe to re-run. Does not change membership/user records.
-- Apply to an existing DB via scripts/migrate_db.py.
-- ============================================
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

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

COMMIT;

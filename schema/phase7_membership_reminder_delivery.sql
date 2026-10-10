-- ============================================
-- Phase 7 migration: reminder delivery ledger
-- Additive, repeatable, and transactional. Does not alter existing rows.
-- ============================================
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;

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

COMMIT;

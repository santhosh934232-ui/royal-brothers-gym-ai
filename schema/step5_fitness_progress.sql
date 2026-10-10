-- ============================================
-- Step 5 migration: Fitness Progress Tracking
-- For an EXISTING database (apply with scripts/migrate_db.py, or run
-- directly: sqlite3 royal_brothers_gym.db < schema/step5_fitness_progress.sql).
-- Safe to re-run. Adds one new table; nothing existing is altered.
-- ============================================
PRAGMA foreign_keys = ON;

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

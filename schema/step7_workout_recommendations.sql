-- ============================================
-- Step 7 migration: Smart Workout Recommendations
-- For an EXISTING database (apply with scripts/migrate_db.py, or run
-- directly: sqlite3 royal_brothers_gym.db < schema/step7_workout_recommendations.sql).
-- Safe to re-run. Adds one new table; nothing existing is altered.
-- ============================================
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workout_recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  recommendation_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

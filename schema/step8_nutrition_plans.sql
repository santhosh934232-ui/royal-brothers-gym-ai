-- ============================================
-- Step 8 migration: AI Nutrition Planner
-- For an EXISTING database (apply with scripts/migrate_db.py, or run
-- directly: sqlite3 royal_brothers_gym.db < schema/step8_nutrition_plans.sql).
-- Safe to re-run. Adds one new table; nothing existing is altered.
-- ============================================
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS nutrition_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

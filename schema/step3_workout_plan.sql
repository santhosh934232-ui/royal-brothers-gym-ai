-- ============================================
-- Step 3 migration: AI Workout Plan
-- Run ONCE against an EXISTING database (after Step 2's migration):
--   sqlite3 royal_brothers_gym.db < schema/step3_workout_plan.sql
-- Safe to re-run. Adds one new table; nothing existing is altered.
-- ============================================
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS workout_plans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL UNIQUE,
  plan_json TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- ============================================
-- Step 2 migration: Fitness Profile
-- Run ONCE against an EXISTING royal_brothers_gym.db:
--   sqlite3 royal_brothers_gym.db < schema/step2_fitness_profile.sql
-- Safe to re-run (IF NOT EXISTS). New databases built from
-- schema/schema.sql already include this table.
-- Adds one new table only; no existing table is altered.
-- ============================================
PRAGMA foreign_keys = ON;

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

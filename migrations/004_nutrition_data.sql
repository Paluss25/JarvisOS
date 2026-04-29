-- Migration 003: nutrition_data database and schema
-- Created: 2026-04-21
-- Purpose: NutritionDirector agent database on postgres-shared (10.10.200.139)

CREATE DATABASE nutrition_data;
\c nutrition_data

CREATE TABLE meals (
    meal_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    timestamp           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meal_type           TEXT CHECK (meal_type IN ('breakfast','lunch','dinner','snack','other')),
    source_type         TEXT CHECK (source_type IN ('image','barcode','text','image_plus_text','mixed')),
    total_calories      NUMERIC(7,1),
    total_protein       NUMERIC(6,1),
    total_carbs         NUMERIC(6,1),
    total_fat           NUMERIC(6,1),
    confidence          NUMERIC(3,2) CHECK (confidence BETWEEN 0 AND 1),
    confirmation_status TEXT CHECK (confirmation_status IN (
        'confirmed_by_user','exact_barcode_match',
        'estimated_high_confidence','estimated_moderate_confidence',
        'corrected_after_prompt'
    )),
    needs_confirmation  BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE meal_items (
    item_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meal_id             UUID REFERENCES meals(meal_id) ON DELETE CASCADE,
    food_name           TEXT NOT NULL,
    canonical_name      TEXT,
    source_database     TEXT CHECK (source_database IN ('fatsecret','openfoodfacts','usda','manual')),
    portion_g           NUMERIC(7,1),
    calories            NUMERIC(7,1),
    protein             NUMERIC(6,1),
    carbs               NUMERIC(6,1),
    fat                 NUMERIC(6,1),
    match_confidence    NUMERIC(3,2),
    barcode             TEXT,
    image_hash          TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE food_library (
    food_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL UNIQUE,
    brand               TEXT,
    default_portion_g   NUMERIC(7,1),
    calories_per_100g   NUMERIC(6,1),
    protein_per_100g    NUMERIC(5,1),
    carbs_per_100g      NUMERIC(5,1),
    fat_per_100g        NUMERIC(5,1),
    source              TEXT,
    barcode             TEXT,
    last_used           TIMESTAMPTZ,
    use_count           INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE daily_summaries (
    date                DATE PRIMARY KEY,
    total_calories      NUMERIC(7,1),
    total_protein       NUMERIC(6,1),
    total_carbs         NUMERIC(6,1),
    total_fat           NUMERIC(6,1),
    meals_logged        INTEGER DEFAULT 0,
    training_day        BOOLEAN DEFAULT FALSE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE user_corrections (
    correction_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    meal_id             UUID REFERENCES meals(meal_id),
    original_food       TEXT NOT NULL,
    corrected_food      TEXT NOT NULL,
    original_portion_g  NUMERIC(7,1),
    corrected_portion_g NUMERIC(7,1),
    image_hash          TEXT,
    similarity_key      TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE nutrition_goals (
    goal_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_calories     NUMERIC(7,1),
    target_protein      NUMERIC(6,1),
    target_carbs        NUMERIC(6,1),
    target_fat          NUMERIC(6,1),
    goal_type           TEXT CHECK (goal_type IN ('cut','bulk','maintain','recomp')),
    active_from         DATE NOT NULL DEFAULT CURRENT_DATE,
    active_to           DATE,
    notes               TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_meals_timestamp ON meals(timestamp);
CREATE INDEX idx_meals_meal_type ON meals(meal_type);
CREATE INDEX idx_meal_items_meal_id ON meal_items(meal_id);
CREATE INDEX idx_food_library_barcode ON food_library(barcode);
CREATE INDEX idx_daily_summaries_date ON daily_summaries(date);
CREATE INDEX idx_user_corrections_image_hash ON user_corrections(image_hash);
CREATE INDEX idx_user_corrections_similarity ON user_corrections(similarity_key);

-- Role: nutrition_director (full access)
CREATE ROLE nutrition_director WITH LOGIN PASSWORD 'CHANGE_ME';
GRANT ALL PRIVILEGES ON DATABASE nutrition_data TO nutrition_director;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO nutrition_director;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nutrition_director;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO nutrition_director;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE ON SEQUENCES TO nutrition_director;

-- Role: drhouse (read-only on nutrition_data)
CREATE ROLE drhouse WITH LOGIN PASSWORD 'CHANGE_ME';
GRANT CONNECT ON DATABASE nutrition_data TO drhouse;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO drhouse;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO drhouse;

-- Cross-database grant: drhouse read access on sport_metrics
-- Run separately: \c sport_metrics
-- GRANT CONNECT ON DATABASE sport_metrics TO drhouse;
-- GRANT SELECT ON ALL TABLES IN SCHEMA public TO drhouse;
-- ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO drhouse;

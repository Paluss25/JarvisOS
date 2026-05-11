-- Migration 005: replace empty daily_summaries table with a meal-derived view.
-- The original table had no producer and stayed empty while meals accumulated.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public'
          AND c.relname = 'daily_summaries'
          AND c.relkind = 'r'
    ) AND to_regclass('public.daily_summaries_legacy') IS NULL THEN
        ALTER TABLE daily_summaries RENAME TO daily_summaries_legacy;
    END IF;
END $$;

CREATE OR REPLACE VIEW daily_summaries AS
SELECT
    m.date,
    m.user_id,
    COALESCE(SUM(m.calories_est), 0)::numeric(7,1) AS total_calories,
    COALESCE(SUM(m.protein_g), 0)::numeric(6,1) AS total_protein,
    COALESCE(SUM(m.carbs_g), 0)::numeric(6,1) AS total_carbs,
    COALESCE(SUM(m.fat_g), 0)::numeric(6,1) AS total_fat,
    COUNT(*)::integer AS n_meals,
    COUNT(*)::integer AS meals_logged,
    FALSE AS training_day,
    NULL::text AS notes,
    MIN(m.created_at) AS created_at,
    MAX(m.created_at) AS updated_at
FROM meals m
GROUP BY m.date, m.user_id;

GRANT SELECT ON daily_summaries TO drhouse;
GRANT SELECT ON daily_summaries TO nutrition;

COMMIT;

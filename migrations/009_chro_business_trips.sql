-- Migration 009: chro.business_trips table for multi-day business trips
-- Created: 2026-04-30
-- Purpose: Separate parent table for business trips (trasferte) with optional
--          1→N link to chro.expense_items. Single expense_items rows stay
--          atomic; trips carry destination, period, project, aircraft, etc.

CREATE TABLE IF NOT EXISTS chro.business_trips (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_from     DATE NOT NULL,
    period_to       DATE NOT NULL,
    destination     TEXT,
    country         TEXT,
    project         TEXT,
    aircraft        TEXT,
    purpose         TEXT,
    notes           TEXT,
    raw_json        JSONB,
    source_file     TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (period_to >= period_from)
);

CREATE INDEX IF NOT EXISTS idx_business_trips_period_from
    ON chro.business_trips(period_from DESC);

CREATE INDEX IF NOT EXISTS idx_business_trips_project
    ON chro.business_trips(project)
    WHERE project IS NOT NULL;

-- Optional FK from expense_items to a parent trip (nullable: most expenses
-- are not trip-related). ON DELETE SET NULL preserves expense rows if a trip
-- is deleted — audit trail wins over referential cleanup here.
ALTER TABLE chro.expense_items
    ADD COLUMN IF NOT EXISTS trip_id UUID
    REFERENCES chro.business_trips(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_expense_items_trip
    ON chro.expense_items(trip_id)
    WHERE trip_id IS NOT NULL;

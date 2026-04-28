-- Migration 005: chro schema on postgres-shared
-- Created: 2026-04-22
-- Purpose: CHRO agent — payroll, leave, pension, expenses, audit log

CREATE SCHEMA IF NOT EXISTS chro;

CREATE TABLE IF NOT EXISTS chro.payslips (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    period_from         DATE NOT NULL,
    period_to           DATE NOT NULL,
    employer            TEXT,
    gross_pay           NUMERIC(10,2),
    net_pay             NUMERIC(10,2),
    inps_employee       NUMERIC(10,2),
    irpef_withheld      NUMERIC(10,2),
    tfr_accrued         NUMERIC(10,2),
    leave_residual_days NUMERIC(6,2),
    rol_residual_hours  NUMERIC(6,2),
    raw_json            JSONB,
    source_file         TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chro.leave_snapshots (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_date    DATE NOT NULL,
    ferie_accrued    NUMERIC(6,2),
    ferie_used       NUMERIC(6,2),
    ferie_remaining  NUMERIC(6,2),
    rol_accrued      NUMERIC(7,2),
    rol_used         NUMERIC(7,2),
    rol_remaining    NUMERIC(7,2),
    payslip_id       UUID REFERENCES chro.payslips(id) ON DELETE SET NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chro.pension_extracts (
    id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_date             DATE NOT NULL,
    contribution_period       TEXT,
    total_contributions       NUMERIC(12,2),
    projected_pension_age     INTEGER,
    projected_monthly_pension NUMERIC(10,2),
    raw_json                  JSONB,
    source_file               TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chro.expense_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    expense_date        DATE NOT NULL,
    category            TEXT,
    amount_eur          NUMERIC(10,2),
    reimbursed          BOOLEAN DEFAULT FALSE,
    employer_reference  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chro.hr_audit_log (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id                 UUID NOT NULL,
    agent_id                TEXT NOT NULL,
    action                  TEXT NOT NULL,
    input_hash              TEXT,
    output_schema_version   TEXT,
    confidence              NUMERIC(4,3),
    escalation              BOOLEAN DEFAULT FALSE,
    ts                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- hr_audit_log is append-only: block UPDATE, DELETE, and TRUNCATE
REVOKE UPDATE, DELETE, TRUNCATE ON chro.hr_audit_log FROM PUBLIC;

CREATE OR REPLACE FUNCTION chro_audit_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'chro.hr_audit_log is append-only: % not allowed', TG_OP;
END $$;

CREATE TRIGGER hr_audit_no_update
  BEFORE UPDATE ON chro.hr_audit_log
  FOR EACH ROW EXECUTE FUNCTION chro_audit_immutable();

CREATE TRIGGER hr_audit_no_delete
  BEFORE DELETE ON chro.hr_audit_log
  FOR EACH ROW EXECUTE FUNCTION chro_audit_immutable();

CREATE OR REPLACE FUNCTION chro_audit_no_truncate()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'chro.hr_audit_log is append-only: TRUNCATE not allowed';
END $$;

CREATE TRIGGER hr_audit_no_truncate
  BEFORE TRUNCATE ON chro.hr_audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION chro_audit_no_truncate();

-- 001_brokers_and_carriers_rls.sql
--
-- Proof-of-concept for our core multi-tenancy guarantee:
-- tenant isolation enforced by Postgres itself (Row-Level Security),
-- not by application code remembering to filter correctly.
--
-- Run as a role that OWNS these tables (e.g. the migration/admin role).
-- The runtime app role must be a DIFFERENT, non-owning role -- see
-- roles.sql. Table owners bypass RLS by default, so this separation
-- is what makes the guarantee real.

CREATE TABLE IF NOT EXISTS brokers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS carriers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_id   UUID NOT NULL REFERENCES brokers(id),
    name        TEXT NOT NULL,
    mc_number   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_carriers_broker_id ON carriers(broker_id);

-- Enable RLS. We deliberately do NOT set FORCE ROW LEVEL SECURITY:
-- FORCE applies the policy even to the table owner, which would also
-- block our own trusted admin/migration tooling (which legitimately
-- needs to see/seed data across all tenants). The owner (app_migrator)
-- is never used to serve tenant HTTP traffic, so it bypassing RLS is
-- not a security gap -- the guarantee that matters is that app_runtime,
-- a non-owner, is unconditionally subject to this policy.
ALTER TABLE carriers ENABLE ROW LEVEL SECURITY;

-- USING governs which existing rows are visible (SELECT/UPDATE/DELETE).
-- WITH CHECK governs which rows can be written (INSERT/UPDATE).
-- current_setting(..., true) with missing_ok=true returns NULL instead of
-- erroring when unset -- and broker_id = NULL is never true, so an
-- unset session variable means "see nothing," not "see everything."
CREATE POLICY carrier_isolation ON carriers
    USING (broker_id = current_setting('app.current_broker_id', true)::uuid)
    WITH CHECK (broker_id = current_setting('app.current_broker_id', true)::uuid);

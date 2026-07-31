-- 002_ingestion_schema.sql
--
-- Extends carriers (001 only had enough for the RLS proof-of-concept) and
-- adds customers/loads/stops/rate_line_items -- the full set of tables the
-- adapter -> ingestion pipeline writes into.
--
-- Every new table follows the exact same tenant-isolation pattern as 001:
-- a broker_id column, RLS enabled (not FORCED, for the same reason as
-- 001 -- app_migrator is trusted admin tooling, not tenant traffic), and
-- a USING/WITH CHECK policy against the session's tenant context. No new
-- grants are needed: 001's ALTER DEFAULT PRIVILEGES already covers any
-- table app_migrator creates from here on.

-- ---------------------------------------------------------------------------
-- carriers: extend with the fields the canonical Carrier model actually has
-- ---------------------------------------------------------------------------
ALTER TABLE carriers
    ADD COLUMN IF NOT EXISTS source_system      TEXT,
    ADD COLUMN IF NOT EXISTS source_native_id   TEXT,
    ADD COLUMN IF NOT EXISTS dot_number         TEXT,
    ADD COLUMN IF NOT EXISTS phone              TEXT,
    ADD COLUMN IF NOT EXISTS home_city          TEXT,
    ADD COLUMN IF NOT EXISTS home_state         TEXT,
    ADD COLUMN IF NOT EXISTS updated_at         TIMESTAMPTZ NOT NULL DEFAULT now();

-- Backfill-safe: only enforce NOT NULL / uniqueness after the columns
-- above actually have values in every row. Since 001's carriers table has
-- never been used to store real data (it only ever held test rows we
-- cleaned up), we can tighten these immediately rather than write a
-- separate backfill step.
ALTER TABLE carriers
    ALTER COLUMN source_system SET NOT NULL,
    ALTER COLUMN source_native_id SET NOT NULL;

ALTER TABLE carriers
    ADD CONSTRAINT carriers_source_system_check
        CHECK (source_system IN ('FREIGHTFLOW', 'HAULDESK', 'BROKEROS'));

ALTER TABLE carriers
    ADD CONSTRAINT carriers_broker_source_unique
        UNIQUE (broker_id, source_system, source_native_id);

-- ---------------------------------------------------------------------------
-- customers
-- ---------------------------------------------------------------------------
CREATE TABLE customers (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_id           UUID NOT NULL REFERENCES brokers(id),
    source_system       TEXT NOT NULL CHECK (source_system IN ('FREIGHTFLOW', 'HAULDESK', 'BROKEROS')),
    source_native_id    TEXT NOT NULL,
    name                TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (broker_id, source_system, source_native_id)
);

CREATE INDEX idx_customers_broker_id ON customers(broker_id);

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
CREATE POLICY customer_isolation ON customers
    USING (broker_id = current_setting('app.current_broker_id', true)::uuid)
    WITH CHECK (broker_id = current_setting('app.current_broker_id', true)::uuid);

-- ---------------------------------------------------------------------------
-- loads: the mutable core entity. Everything except identity/audit fields
-- can change between syncs -- see canonical Load model for why each field
-- means what it means.
-- ---------------------------------------------------------------------------
CREATE TABLE loads (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_id                   UUID NOT NULL REFERENCES brokers(id),
    source_system               TEXT NOT NULL CHECK (source_system IN ('FREIGHTFLOW', 'HAULDESK', 'BROKEROS')),
    source_native_id            TEXT NOT NULL,
    source_native_number        TEXT,

    status                      TEXT NOT NULL CHECK (
                                     status IN ('PLANNED', 'ACTIVE', 'COVERED', 'IN_TRANSIT', 'DELIVERED', 'COMPLETED')
                                 ),
    source_status_raw           TEXT NOT NULL,

    customer_id                 UUID NOT NULL REFERENCES customers(id),
    carrier_id                  UUID REFERENCES carriers(id),  -- null until covered

    equipment_type              TEXT NOT NULL CHECK (
                                     equipment_type IN ('DRY_VAN', 'REEFER', 'FLATBED', 'UNKNOWN')
                                 ),
    distance_miles              NUMERIC(10, 1),
    weight_lbs                  NUMERIC(10, 1),

    -- Authoritative for FreightFlow/BrokerOS; NULL for HaulDesk, whose
    -- true total is SUM(rate_line_items) computed at read time -- see the
    -- canonical Load model's docstring for the full reasoning.
    customer_rate_total_usd     NUMERIC(12, 2),
    carrier_rate_total_usd      NUMERIC(12, 2),

    source_created_at           TIMESTAMPTZ NOT NULL,
    source_last_modified_at     TIMESTAMPTZ NOT NULL,

    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (broker_id, source_system, source_native_id)
);

CREATE INDEX idx_loads_broker_id ON loads(broker_id);
CREATE INDEX idx_loads_broker_status ON loads(broker_id, status);
CREATE INDEX idx_loads_customer_id ON loads(customer_id);
CREATE INDEX idx_loads_carrier_id ON loads(carrier_id);

ALTER TABLE loads ENABLE ROW LEVEL SECURITY;
CREATE POLICY load_isolation ON loads
    USING (broker_id = current_setting('app.current_broker_id', true)::uuid)
    WITH CHECK (broker_id = current_setting('app.current_broker_id', true)::uuid);

-- ---------------------------------------------------------------------------
-- stops: no source gives a stable per-stop identifier, so these are
-- wholesale-replaced (delete + reinsert) on every sync rather than
-- upserted row-by-row. broker_id is denormalized here (derivable via a
-- join to loads) purely so every table's RLS policy stays identical and
-- simple, matching the rest of this schema.
-- ---------------------------------------------------------------------------
CREATE TABLE stops (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_id                   UUID NOT NULL REFERENCES brokers(id),
    load_id                     UUID NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    sequence                    INT NOT NULL,
    is_pickup                   BOOLEAN NOT NULL,
    is_dropoff                  BOOLEAN NOT NULL,
    city                        TEXT NOT NULL,
    state                       TEXT NOT NULL,
    zip_code                    TEXT,
    scheduled_date               DATE,
    scheduled_window_start      TIMESTAMPTZ,
    scheduled_window_end        TIMESTAMPTZ,
    actual_arrival_at           TIMESTAMPTZ,
    actual_departure_at         TIMESTAMPTZ,
    UNIQUE (load_id, sequence)
);

CREATE INDEX idx_stops_broker_id ON stops(broker_id);
CREATE INDEX idx_stops_load_id ON stops(load_id);

ALTER TABLE stops ENABLE ROW LEVEL SECURITY;
CREATE POLICY stop_isolation ON stops
    USING (broker_id = current_setting('app.current_broker_id', true)::uuid)
    WITH CHECK (broker_id = current_setting('app.current_broker_id', true)::uuid);

-- ---------------------------------------------------------------------------
-- rate_line_items: append-only. Sources that give us line-item detail
-- (HaulDesk) never edit or delete a row once created, only add new ones --
-- source_native_id is what makes re-ingesting the same file idempotent
-- (ON CONFLICT DO NOTHING at the application layer, not DO UPDATE: an
-- existing line item is never supposed to change).
-- ---------------------------------------------------------------------------
CREATE TABLE rate_line_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker_id           UUID NOT NULL REFERENCES brokers(id),
    load_id             UUID NOT NULL REFERENCES loads(id) ON DELETE CASCADE,
    source_system       TEXT NOT NULL CHECK (source_system IN ('FREIGHTFLOW', 'HAULDESK', 'BROKEROS')),
    source_native_id    TEXT NOT NULL,
    side                TEXT NOT NULL CHECK (side IN ('BILL', 'PAY')),
    code                TEXT NOT NULL,
    amount_usd          NUMERIC(12, 2) NOT NULL,
    source_created_at   TIMESTAMPTZ NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (broker_id, source_system, source_native_id)
);

CREATE INDEX idx_rate_line_items_broker_id ON rate_line_items(broker_id);
CREATE INDEX idx_rate_line_items_load_id ON rate_line_items(load_id);

ALTER TABLE rate_line_items ENABLE ROW LEVEL SECURITY;
CREATE POLICY rate_line_item_isolation ON rate_line_items
    USING (broker_id = current_setting('app.current_broker_id', true)::uuid)
    WITH CHECK (broker_id = current_setting('app.current_broker_id', true)::uuid);

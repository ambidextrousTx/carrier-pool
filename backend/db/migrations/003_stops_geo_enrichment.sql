-- 003_stops_geo_enrichment.sql
--
-- Adds market_area/latitude/longitude to stops, populated at ingestion
-- time (see persistence/ingest.py) from the static zip reference table
-- in carrier_recs.geo.reference_data. That table is deliberately NOT a
-- database table itself: it's small, static, shared by both ingestion
-- and the synthetic data generator, and denormalizing its output onto
-- stops here is what lets lane-matching be a plain indexed WHERE/GROUP BY
-- instead of a join (or worse, a geospatial computation) on every query.

ALTER TABLE stops
    ADD COLUMN market_area TEXT,
    ADD COLUMN latitude    NUMERIC(9, 6),
    ADD COLUMN longitude   NUMERIC(9, 6);

-- Composite, not standalone: every real query is already scoped to one
-- broker via RLS, so broker_id is the natural leading column.
CREATE INDEX idx_stops_broker_market_area ON stops(broker_id, market_area);

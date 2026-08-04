# Architecture

Plain-text diagrams, kept in the repo instead of image files so they stay
readable in a terminal, a diff, or a plain-text editor, and so they get
updated in the same PR as the code they describe instead of drifting out
of sync with it.

Two kinds, per how the system actually behaves:

- **Structure** -- the modules, in the order data passes through them.
- **Flow** -- two separate diagrams, because there genuinely are two
  separate flows at two different times: an offline batch flow (sync
  files into Postgres) and an online request flow (an API call into a
  recommendation). Trying to cram both into one diagram made neither
  one readable.

---

## 1. Structure

```
+----------------------------------------------------------------------------+
| SYNTHETIC DATA GENERATION  (offline, deterministic, gitignored output)     |
| ----------------------------------------------------------------------     |
| synthetic/world.py          event-stream world model, per broker, seeded       |
| synthetic/export.py         world -> native TMS JSON, one file per sync window |
| scripts/generate.py                                                   |
|     writes data/<broker>/sync/day01_sync01.json ... day11_sync04.json      |
|     run once per clone: uv run python -m scripts.generate                  |
+----------------------------------------------------------------------------+
                                       v
+-----------------------------------------------------------------------+
| ADAPTERS  (pure functions -- no DB access, no side effects)           |
| -----------------------------------------------------------           |
| adapters/freightflow.py | adapters/hauldesk.py | adapters/brokeros.py |
|     raw TMS-native JSON -> list[AdapterResult]                        |
| shared helpers: timeutils.py, units.py, numeric.py                    |
+-----------------------------------------------------------------------+
                                    |  AdapterResult(load, customer, carrier)
                                    v
+--------------------------------------------------------------------------+
| CANONICAL MODELS                                                         |
| ----------------                                                         |
| canonical/models.py    Load, Stop, Carrier, Customer, RateLineItem       |
| canonical/enums.py     LoadStatus, EquipmentType, SourceSystem, RateSide |
+--------------------------------------------------------------------------+
                                      v
+--------------------------------------------------------------------------+
| PERSISTENCE / INGESTION                                                  |
| -----------------------                                                  |
| persistence/ingestion.py :: ingest_sync(conn, broker_id, results)        |
|     one Postgres transaction per file, all-or-nothing, idempotent upsert |
| persistence/db.py :: set_tenant_context(cur, broker_id)                  |
| scripts/seed_data.py drives this: one sync file at a time,               |
|     in chronological order (day01_sync01 ... day11_sync04)               |
+--------------------------------------------------------------------------+
                                      v
+--------------------------------------------------------------------------+
| POSTGRES  (single schema, Row-Level Security)  [docker: postgres]        |
| -----------------------------------------------------------------        |
| app_migrator  owns tables, runs migrations, bypasses RLS (admin only)    |
| app_runtime   NOBYPASSRLS -- RLS always applies; this is what every      |
|               app connection actually uses                               |
|                                                                          |
| tables: brokers | carriers | customers | loads | stops | rate_line_items |
| every tenant table: broker_id + policy scoped to                         |
|     current_setting('app.current_broker_id')  -- unset = 0 rows,         |
|     fails closed, not open                                               |
+--------------------------------------------------------------------------+
                                      v
+------------------------------------------------------------------------+
| RECOMMEND ENGINE  (read-only, direct SQL, no separate scoring service) |
| ---------------------------------------------------------------------- |
| recommendation/engine.py                                               |
|     rank_carriers(cur, load_id)  -> list[CarrierRecommendation]        |
|     predict_rate(cur, load_id)   -> RatePrediction                     |
|                                     (always returned, never a bare     |
|                                      None -- carries a reason when     |
|                                      data is insufficient)             |
+------------------------------------------------------------------------+
                                     v
+-----------------------------------------------------------------+
| API  (FastAPI, synchronous, read-only)  [docker: api]           |
| -----------------------------------------------------           |
| GET /brokers                                                    |
| GET /brokers/{broker_id}/loads[?status=]                        |
| GET /brokers/{broker_id}/loads/{load_id}                        |
| GET /brokers/{broker_id}/loads/{load_id}/recommendation         |
|                                                                 |
| every broker-scoped route depends on get_broker_connection:     |
|     404 if broker_id doesn't exist, else set_tenant_context     |
|     then yield the connection -- structurally impossible to add |
|     a route later that forgets tenant scoping                   |
+-----------------------------------------------------------------+
                                 v
+-----------------------------------------------------------------+
| FRONTEND  (Vite + TypeScript + React + Tailwind)                |
| -------------------------------------------------------         |
| consumes the API above; visual polish explicitly not a priority |
+-----------------------------------------------------------------+
```

**Not shown above, deliberately kept out of the vertical pipeline:**
`geo/` (fuzzy lane matching -- `reference_data.py`, `lookup.py`,
`distance.py`, `lanes.py`) is pure, in-memory Python, not a Postgres
table. It's a shared dependency of two different stages, not a stage of
its own: `synthetic/world.py` uses it to generate realistic lanes, and
`persistence/ingestion.py` uses it to enrich `stops.market_area` /
`latitude` / `longitude` at insert time (migration 003). Runtime queries
never join against a reference table for this -- the enrichment already
happened once, at ingestion.

**Multi-tenancy** runs through every layer above the API, not just one
box: each of the 3 demo brokers (`lone-star-freight`,
`crossroads-logistics`, `summit-brokerage`) has its own TMS format, its
own sync files, and its own isolated rows in every tenant table --
enforced by Postgres RLS (see the POSTGRES box), not by application code
remembering to filter. The API's `get_broker_connection` dependency is
what carries that guarantee into every request (see the recommendation
flow below).

---

## 2. Flow -- ingestion (offline, batch)

```
STEP 1 -- generate (once per clone, or whenever you want fresh data)

  $ uv run python -m scripts.generate
        |
        v
  synthetic/world.py builds one 11-day event history per broker
  (seeds 101 / 202 / 303 -- same seed always reproduces the same world)
        |
        v
  synthetic/export.py slices it into per-sync-window native JSON,
  one file per (day, sync) pair that actually had activity
        |
        v
  data/<broker>/sync/day01_sync01.json
  data/<broker>/sync/day01_sync02.json
  ...
  data/<broker>/sync/day11_sync04.json     (44 files max per broker,
                                             gitignored, regenerated)


STEP 2 -- seed (loads the files above into Postgres)

  $ uv run python -m scripts.seed_data

  for each broker (lone-star-freight, crossroads-logistics,
                   summit-brokerage -- fully isolated from each other):

      get_or_create_broker(name)          -- via app_migrator
        |
        v
      for each sync file, in chronological order:
        |
        |   day01_sync01.json  -->  day01_sync02.json  -->  ...  -->
        |   day10_sync04.json  -->  day11_sync01.json  -->  ...  -->  day11_sync04.json
        |
        v
      raw = json.loads(path.read_text())
        |
        v
      results = adapters.parse_<tms>_sync(raw)      -- pure function,
                                                        no DB access
        |
        v
+------------------------------------------------------------------+
| ingest_sync(app_runtime_conn, broker_id, results)                |
| -------------------------------------------------                |
| one Postgres transaction, all-or-nothing:                        |
|                                                                  |
|   UPSERT customers, carriers    (ON CONFLICT DO UPDATE)          |
|   UPSERT loads                  (carrier_id can gain a value,    |
|                                   never regress back to NULL)    |
|   REPLACE stops                 (DELETE + re-INSERT -- no source |
|                                   gives a stable per-stop id)    |
|   INSERT rate_line_items        (ON CONFLICT DO NOTHING --       |
|                                   append-only, matches HaulDesk) |
+------------------------------------------------------------------+
                                  |  repeat for every remaining file, same broker
                                  v

                        [ next sync file in this broker's list ]

A load can reappear in a later file with a corrected rate, a
reassigned carrier, or a status change -- ingest_sync doesn't need
to know it's a "correction" versus normal progress, it just upserts
whatever the new current state is. By day11_sync04, every broker has
10 full days of real history in Postgres, plus a batch of brand-new
ACTIVE, uncovered loads with no history of their own -- exactly what
the recommend engine (next diagram) needs to answer for.
```

---

## 3. Flow -- recommendation request (online, per-request)

```
Frontend / any HTTP client
  |
  |  GET /brokers/{broker_id}/loads/{load_id}/recommendation
  v
api/routes.py :: get_recommendation(load_id)
  |
  |  Depends(get_broker_connection)
  v
+--------------------------------------------------------------------+
| api/deps.py :: get_broker_connection(broker_id)                    |
| -----------------------------------------------                    |
| 1. SELECT 1 FROM brokers WHERE id = broker_id                      |
|      not found?  -->  404, request stops here, no engine code runs |
| 2. set_tenant_context(cur, broker_id)                              |
|      SET LOCAL app.current_broker_id  -- this transaction only,    |
|      safe even though the connection came from a pool and will be  |
|      reused by a different broker's request later                 |
+--------------------------------------------------------------------+
                                   |  yields a tenant-scoped connection -- RLS is now active
                                   v

with conn.cursor() as cur:      # both calls share one cursor, run in sequence

+--------------------------------------------------------------+
| recommendations = rank_carriers(cur, load_id)                |
| ---------------------------------------------                |
| 1. load context: lane, equipment, distance, pickup coords    |
|      (load not found, or belongs to another broker --        |
|       RLS makes those indistinguishable -- raises, caught    |
|       by the route as a 404)                                 |
| 2. candidate carriers: broker's carriers, excluding anyone   |
|      currently COVERED / IN_TRANSIT elsewhere (busy truck),  |
|      filtered by equipment history (auto-relaxed if <3 left) |
| 3. per candidate: lane_match_score (30/90/365-day recency-   |
|      weighted) and deadhead_miles (haversine from their most |
|      recent COMPLETED delivery to this load's pickup)        |
| 4. sort: hauled-this-lane first, then score, then deadhead   |
| 5. justification text built from those same raw facts        |
+--------------------------------------------------------------+
                                v
+-----------------------------------------------------------------+
| rate = predict_rate(cur, load_id)                               |
| ---------------------------------                               |
| 1. comps: this broker's COMPLETED loads, same lane +            |
|      equipment, last 90 days                                    |
| 2. <5 comps?  broaden to same equipment, any lane               |
| 3. <3 comps even after broadening?                              |
|      is_available=False, explanation says how many comps        |
|      were found and why that wasn't enough -- never a bare None |
| 4. else: median $/mile x distance = predicted total,            |
|      25th/75th percentile = range, explanation cites the        |
|      comp count, scope, and window used                         |
+-----------------------------------------------------------------+
                                 v

api/routes.py composes RecommendationOut:
  - carrier_recommendations: [...]  (or [] + a plain-English note
      if the broker has no carriers available right now)
  - rate_prediction: {...}  (predicted_total_usd etc. serialized as
      STRINGS, not floats -- Decimal precision, not re-broken at
      the last step after being carefully preserved everywhere else)
        |
        v
  200 OK, JSON body -- both required answers, both explained
```

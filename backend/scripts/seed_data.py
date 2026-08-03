"""Loads each broker's generated sync-file stream (data/*/sync/*.json)
into Postgres, one file at a time, in chronological order -- exactly as
the real scheduled syncs would have arrived, not as one big batch.

You must run `uv run python -m scripts.generate_data` first -- sync files
are gitignored, not committed (see data/.gitignore); 3 brokers x 11 days
x 4 syncs is a lot of files to carry in the repo for something fully
reproducible from a fixed seed. Requires the Postgres container from
`docker compose up` to be running.

Idempotent in the same sense generate_data.py's output is deterministic:
re-running this against the same generated files is a safe no-op
(broker lookup is by name, ingestion upserts). If you regenerate with a
different seed in between, re-seeding reflects the new data, same as a
real re-sync would.
"""

import json
import os
from pathlib import Path

import psycopg

from adapters.brokeros import parse_brokeros_sync
from adapters.freightflow import parse_freightflow_sync
from adapters.hauldesk import parse_hauldesk_sync
from persistence.ingestion import ingest_sync
from scripts.shared import BROKERS, DATA_DIR

_PARSERS = {
    "freightflow": parse_freightflow_sync,
    "hauldesk": parse_hauldesk_sync,
    "brokeros": parse_brokeros_sync,
}

DB_HOST = os.environ.get("PGHOST", "localhost")
DB_NAME = os.environ.get("PGDATABASE", "carrier_recs")
MIGRATOR_DSN = f"host={DB_HOST} dbname={DB_NAME} user=app_migrator password={os.environ.get('APP_MIGRATOR_PASSWORD', 'migrator_dev_pw')}"
RUNTIME_DSN = f"host={DB_HOST} dbname={DB_NAME} user=app_runtime password={os.environ.get('APP_RUNTIME_PASSWORD', 'runtime_dev_pw')}"


def get_or_create_broker(cur, name: str) -> str:
    cur.execute("SELECT id FROM brokers WHERE name = %s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("INSERT INTO brokers (name) VALUES (%s) RETURNING id", (name,))
    return cur.fetchone()[0]


def sync_files_in_order(broker_slug: str) -> list[Path]:
    sync_dir = DATA_DIR / broker_slug / "sync"
    if not sync_dir.exists() or not any(sync_dir.glob("day*_sync*.json")):
        raise FileNotFoundError(
            f"{sync_dir} not found or empty. Sync files are generated locally, not committed -- "
            "run `uv run python -m scripts.generate_data` first."
        )
    # Zero-padded day/sync numbers in the filename make plain lexicographic
    # sort exactly equal to chronological sort: day01_sync01, day01_sync02,
    # ..., day10_sync04, day11_sync01, ..., day11_sync04.
    return sorted(sync_dir.glob("day*_sync*.json"))


def main() -> None:
    admin_conn = psycopg.connect(MIGRATOR_DSN, autocommit=True)
    runtime_conn = psycopg.connect(RUNTIME_DSN, autocommit=True)

    for broker in BROKERS:
        print(f"=== {broker.name} ({broker.tms}) ===")
        with admin_conn.cursor() as cur:
            broker_id = get_or_create_broker(cur, broker.name)
        print(f"  broker_id: {broker_id}")

        files = sync_files_in_order(broker.slug)
        total_touches = 0
        for path in files:
            raw = json.loads(path.read_text())
            results = _PARSERS[broker.tms](raw)
            if not results:
                print(f"  {path.name}: 0 loads (skipped)")
                continue
            # One ingest_sync call per file == one transaction per file,
            # all-or-nothing, same guarantee as before -- there's just 44
            # of these now per broker instead of 1. set_tenant_context
            # happens inside ingest_sync per call, scoped to broker_id.
            load_ids = ingest_sync(runtime_conn, broker_id, results)
            total_touches += len(load_ids)
            print(f"  {path.name}: {len(load_ids)} loads touched")

        print(f"  processed {len(files)} sync files, {total_touches} load-touches total for {broker.name}")

    admin_conn.close()
    runtime_conn.close()
    print("done")


if __name__ == "__main__":
    main()

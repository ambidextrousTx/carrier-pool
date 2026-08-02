"""Loads the committed synthetic data (data/*/current.json) into Postgres.

This is the script a fresh clone of the repo should run -- it does NOT
regenerate anything, it just reads the JSON files already committed and
ingests them via the real adapters, exactly as if they'd arrived from
each broker's actual TMS. Requires the Postgres container from
`docker compose up` to be running.

Idempotent: safe to re-run (broker lookup is by name, ingestion upserts).
"""

import json
import os

import psycopg

from adapters.brokeros import parse_brokeros_sync
from adapters.freightflow import parse_freightflow_sync
from adapters.hauldesk import parse_hauldesk_sync
from persistence.ingest import ingest_sync
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


def main() -> None:
    admin_conn = psycopg.connect(MIGRATOR_DSN, autocommit=True)
    runtime_conn = psycopg.connect(RUNTIME_DSN, autocommit=True)

    for broker in BROKERS:
        path = DATA_DIR / broker.slug / "current.json"
        if not path.exists():
            raise FileNotFoundError(
                f"{path} not found. This should be committed to the repo -- "
                "if it's genuinely missing, run generate_data.py first."
            )

        print(f"=== {broker.name} ({broker.tms}) ===")
        raw = json.loads(path.read_text())
        results = _PARSERS[broker.tms](raw)

        with admin_conn.cursor() as cur:
            broker_id = get_or_create_broker(cur, broker.name)
        print(f"  broker_id: {broker_id}")

        load_ids = ingest_sync(runtime_conn, broker_id, results)
        print(f"  ingested {len(load_ids)} loads")

    admin_conn.close()
    runtime_conn.close()
    print("done")


if __name__ == "__main__":
    main()

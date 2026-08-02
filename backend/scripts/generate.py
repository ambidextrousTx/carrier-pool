"""Generates synthetic worlds for our three demo brokers and writes each
to disk in its native TMS format.

You do NOT need to run this after cloning the repo -- its output is
already committed under data/. Only re-run it if you want to regenerate
the data (e.g. after changing WorldConfig parameters or a serializer).
After regenerating, run seed_data.py to load the new files into Postgres.
"""

import json
from datetime import date

from synthetic.export import export_brokeros, export_freightflow, export_hauldesk
from synthetic.world import WorldConfig, generate_world
from scripts.shared import BROKERS, DATA_DIR

TODAY = date(2026, 7, 31)

_EXPORTERS = {
    "freightflow": export_freightflow,
    "hauldesk": export_hauldesk,
    "brokeros": export_brokeros,
}


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    for broker in BROKERS:
        print(f"=== {broker.name} ({broker.tms}) ===")
        world = generate_world(
            WorldConfig(broker_slug=broker.slug, broker_name=broker.name, seed=broker.seed, today=TODAY)
        )
        raw = _EXPORTERS[broker.tms](world)

        out_dir = DATA_DIR / broker.slug
        out_dir.mkdir(exist_ok=True)
        out_path = out_dir / "current.json"
        out_path.write_text(json.dumps(raw, indent=2, default=str))
        print(f"  wrote {out_path} ({out_path.stat().st_size:,} bytes)")

    print("done -- now run scripts/seed_data.py to load this into Postgres")


if __name__ == "__main__":
    main()

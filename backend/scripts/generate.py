"""Generates synthetic sync-file streams for our three demo brokers and
writes each broker's TMS-native files to disk.

Produces ~44 small files
per broker: 10 history days x 4 syncs, plus day 11 x 4 syncs carrying
that broker's fresh, uncovered loads. Each file is exactly what an
incremental TMS sync would have delivered for that window -- only loads
with activity in that window appear, and they appear as their full
current state as of that window's end (a "changed record" delta, not a
field-level diff -- this is also why a restated total looks "silent",
same as the real TMS quirk it's modeling).

You DO need to run this after cloning the repo now -- sync file output
is gitignored (data/*/sync/), not committed, since 3 brokers x 11 days x
4 syncs is a lot of files to carry in the repo for something fully
reproducible from a fixed seed. Safe to re-run: deterministic per broker,
and always wipes+rewrites that broker's sync/ directory first.

After this, run seed_data.py to load the generated files into Postgres,
in the same chronological order they were written.
"""

import json
import shutil
from collections import Counter
from datetime import date

from canonical.enums import LoadStatus
from scripts.shared import BROKERS, DATA_DIR
from synthetic.export import export_brokeros_sync, export_freightflow_sync, export_hauldesk_sync, new_export_state
from synthetic.world import SYNCS_PER_DAY, WorldConfig, generate_world, sync_window_bounds

# Day 11 -- "today" for every broker. Keep this in sync with whatever
# `today` the recommendation engine/demo is run against; day 1 is always
# 10 days before this, regardless of when generate_data.py is actually
# executed.
TODAY = date(2026, 8, 2)

_EXPORTERS = {
    "freightflow": export_freightflow_sync,
    "hauldesk": export_hauldesk_sync,
    "brokeros": export_brokeros_sync,
}

_TX_TRIANGLE_MARKET_AREAS = {"Dallas-Fort Worth Metro", "Houston Metro", "San Antonio Metro", "Austin Metro"}


def _print_verification_stats(world) -> None:
    """Prints real numbers rather than asserting the generator "should"
    behave a certain way -- matches this project's existing practice of
    verifying synthetic data directly rather than trusting the generator
    blindly (see Gotcha #10 in the handoff)."""
    history = [l for l in world.loads if l.created_day <= 10]
    day11 = [l for l in world.loads if l.created_day == 11]

    status_counts = Counter(l.final_status for l in history)
    tx_internal = sum(
        1 for l in world.loads
        if l.lane.origin_market_area in _TX_TRIANGLE_MARKET_AREAS and l.lane.destination_market_area in _TX_TRIANGLE_MARKET_AREAS
    )
    busy_carriers = sum(
        1 for c in world.carriers
        if any(
            l.assigned_carrier_id == c.id and l.final_status in (LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED)
            for l in history
        )
    )
    per_carrier = Counter(l.assigned_carrier_id for l in history if l.assigned_carrier_id)
    loads_per_carrier = sorted(per_carrier.values()) or [0]
    per_lane = Counter(l.lane for l in history)
    thin_lanes = sum(1 for c in per_lane.values() if c <= 2)
    money_corrections = sum(
        1 for l in history for i in range(1, len(l.events)) if l.events[i].status == l.events[i - 1].status
    )
    reassignments = sum(
        1 for l in history
        if len({e.carrier_id for e in l.events if e.status == LoadStatus.COVERED and e.carrier_id}) > 1
    )
    field_corrections = sum(1 for l in history if l.corrections)

    print(f"  {len(world.loads)} loads total ({len(history)} history, {len(day11)} day-11 fresh)")
    print(f"  history status mix: {dict(status_counts)}")
    print(f"  TX Triangle-internal lanes: {tx_internal}/{len(world.loads)} ({tx_internal / len(world.loads):.0%})")
    print(f"  carriers currently busy (in-flight) as of day 11: {busy_carriers}")
    print(
        f"  loads/carrier: min={loads_per_carrier[0]}, "
        f"median={loads_per_carrier[len(loads_per_carrier) // 2]}, max={loads_per_carrier[-1]}, "
        f"{len(loads_per_carrier)}/{len(world.carriers)} carriers used"
    )
    print(f"  lanes with <=2 loads (thin): {thin_lanes}/{len(per_lane)}")
    print(f"  money corrections: {money_corrections}, carrier reassignments: {reassignments}, field corrections: {field_corrections}")


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    for broker in BROKERS:
        print(f"=== {broker.name} ({broker.tms}) ===")
        world = generate_world(
            WorldConfig(broker_slug=broker.slug, broker_name=broker.name, seed=broker.seed, today=TODAY)
        )
        _print_verification_stats(world)

        sync_dir = DATA_DIR / broker.slug / "sync"
        if sync_dir.exists():
            shutil.rmtree(sync_dir)
        sync_dir.mkdir(parents=True)

        exporter = _EXPORTERS[broker.tms]
        state = new_export_state()
        written, skipped = 0, 0
        for day in range(1, 12):
            for sync_num in range(1, SYNCS_PER_DAY + 1):
                window_start, window_end = sync_window_bounds(world, day, sync_num)
                payload = exporter(world, window_start, window_end, state)
                if payload is None:
                    skipped += 1
                    continue
                out_path = sync_dir / f"day{day:02d}_sync{sync_num:02d}.json"
                out_path.write_text(json.dumps(payload, indent=2, default=str))
                written += 1

        print(f"  wrote {written} sync files to {sync_dir} ({skipped}/44 windows had no activity, correctly skipped)")

    print("done -- now run `uv run python -m scripts.seed_data` to load this into Postgres")


if __name__ == "__main__":
    main()

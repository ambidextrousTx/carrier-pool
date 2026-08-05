from datetime import date

import pytest

from adapters.brokeros import parse_brokeros_sync
from adapters.freightflow import parse_freightflow_sync
from adapters.hauldesk import parse_hauldesk_sync
from canonical.enums import LoadStatus
from synthetic.export import export_brokeros_sync, export_freightflow_sync, export_hauldesk_sync, new_export_state
from synthetic.world import SYNCS_PER_DAY, WorldConfig, generate_world, sync_window_bounds


@pytest.fixture(scope="module")
def small_world():
    config = WorldConfig(
        broker_slug="test-broker", broker_name="Test Broker", seed=555, today=date(2026, 7, 31),
        num_history_days=10, target_history_loads=60, num_new_loads_day11=10,
        num_primary_lanes=6, num_carriers=12, num_customers=8,
    )
    return generate_world(config)


def _replay(world, exporter, parser):
    """Walks every sync window in chronological order and returns
    (occurrences, latest_by_native_id) -- occurrences is every parsed
    AdapterResult in the order it was synced (so a load that gets
    corrected shows up more than once, earlier value first); latest_by_
    native_id keeps only the most recent, mirroring what Postgres would
    hold after a full seed run's upserts."""
    state = new_export_state()
    occurrences = []
    latest_by_native_id = {}
    for day in range(1, 12):
        for sync_num in range(1, SYNCS_PER_DAY + 1):
            window_start, window_end = sync_window_bounds(world, day, sync_num)
            raw = exporter(world, window_start, window_end, state)
            if raw is None:
                continue
            for r in parser(raw):
                occurrences.append(r)
                latest_by_native_id[r.load.source_native_id] = r
    return occurrences, latest_by_native_id


class TestFreightFlowRoundTrip:
    def test_every_load_appears_at_least_once_across_the_full_replay(self, small_world):
        _, latest = _replay(small_world, export_freightflow_sync, parse_freightflow_sync)
        assert len(latest) == len(small_world.loads)

    def test_day11_load_has_no_carrier_and_history_completed_load_does(self, small_world):
        _, latest = _replay(small_world, export_freightflow_sync, parse_freightflow_sync)
        day11_world_loads = [ld for ld in small_world.loads if ld.created_day == 11]
        completed_world_loads = [ld for ld in small_world.loads if ld.final_status == LoadStatus.COMPLETED]
        assert day11_world_loads and completed_world_loads

        # Match by rate value since shipmentId is reassigned during export
        sample_day11 = day11_world_loads[0]
        matched = next(
            r for r in latest.values()
            if r.load.customer_rate_total_usd is not None
            and float(r.load.customer_rate_total_usd) == float(sample_day11.events[-1].customer_rate_usd)
        )
        assert matched.load.status == LoadStatus.ACTIVE
        assert matched.carrier is None

        sample_completed = completed_world_loads[0]
        matched_completed = next(
            r for r in latest.values()
            if r.load.carrier_rate_total_usd is not None
            and float(r.load.carrier_rate_total_usd) == float(sample_completed.events[-1].carrier_rate_usd)
        )
        assert matched_completed.load.status == LoadStatus.COMPLETED
        assert matched_completed.carrier is not None

    def test_a_corrected_load_parses_differently_in_an_earlier_sync_than_its_latest(self, small_world):
        # Proves the delta/windowed design actually round-trips a
        # correction -- not just that the final state is right, but that
        # an earlier sync genuinely showed the pre-correction value. Checks
        # either rate side, since a money correction has ~60% odds of
        # landing on carrier_rate rather than customer_rate.
        corrected = next(
            (ld for ld in small_world.loads if ld.created_day <= 10
             and (len({e.customer_rate_usd for e in ld.events if e.customer_rate_usd is not None}) > 1
                  or len({e.carrier_rate_usd for e in ld.events if e.carrier_rate_usd is not None}) > 1)),
            None,
        )
        assert corrected is not None, "fixture seed produced no money-corrected load to test against"

        occurrences, latest = _replay(small_world, export_freightflow_sync, parse_freightflow_sync)
        native_id = next(
            r.load.source_native_id for r in latest.values()
            if r.load.weight_lbs == corrected.weight_lbs and r.load.distance_miles == corrected.distance_miles
        )
        all_for_load = [r for r in occurrences if r.load.source_native_id == native_id]
        distinct_rates = {(r.load.customer_rate_total_usd, r.load.carrier_rate_total_usd) for r in all_for_load}
        assert len(distinct_rates) > 1


class TestHaulDeskRoundTrip:
    def test_every_load_appears_at_least_once_across_the_full_replay(self, small_world):
        _, latest = _replay(small_world, export_hauldesk_sync, parse_hauldesk_sync)
        assert len(latest) == len(small_world.loads)

    def test_rate_line_items_present_for_covered_or_later_loads(self, small_world):
        occurrences, _ = _replay(small_world, export_hauldesk_sync, parse_hauldesk_sync)
        by_native_id: dict = {}
        for r in occurrences:
            by_native_id.setdefault(r.load.source_native_id, []).extend(r.load.rate_line_items)

        world_by_id = {ld.id.upper(): ld for ld in small_world.loads}
        covered_or_later_ids = [
            nid for nid, ld in world_by_id.items()
            if ld.final_status not in (LoadStatus.PLANNED, LoadStatus.ACTIVE)
        ]
        assert covered_or_later_ids
        for nid in covered_or_later_ids:
            sides = {item.side.value for item in by_native_id.get(nid, [])}
            assert "PAY" in sides and "BILL" in sides

    def test_rate_line_item_deltas_sum_to_the_true_final_amount(self, small_world):
        # The whole point of the append-only/delta design: SUM(amount_usd)
        # must reconstruct the real final total, including for loads that
        # got a mid-stream correction or a carrier reassignment.
        occurrences, _ = _replay(small_world, export_hauldesk_sync, parse_hauldesk_sync)
        bill_sum: dict = {}
        pay_sum: dict = {}
        for r in occurrences:
            for item in r.load.rate_line_items:
                d = bill_sum if item.side == item.side.BILL else pay_sum
                d[r.load.source_native_id] = d.get(r.load.source_native_id, 0) + item.amount_usd

        checked = 0
        for ld in small_world.loads:
            native_id = ld.id.upper()
            true_customer = ld.customer_rate_as_of(ld.events[-1].timestamp)
            true_carrier = ld.carrier_rate_as_of(ld.events[-1].timestamp)
            if true_customer is not None:
                checked += 1
                assert abs(bill_sum.get(native_id, 0) - true_customer) < 1
            if true_carrier is not None:
                checked += 1
                assert abs(pay_sum.get(native_id, 0) - true_carrier) < 1
        assert checked > 0

    def test_carrier_not_redefined_in_a_later_file_still_carries_its_native_id(self, small_world):
        # The documented HaulDesk quirk: once a carrier's been sent once,
        # later files reference it by carrier_ref without redefining it --
        # the adapter result for those loads has carrier=None but still
        # carries carrier_source_native_id for ingestion to resolve by
        # lookup.
        occurrences, _ = _replay(small_world, export_hauldesk_sync, parse_hauldesk_sync)
        omitted = [
            r for r in occurrences
            if r.load.carrier_source_native_id is not None and r.carrier is None
        ]
        assert len(omitted) > 0

    def test_unit_conversion_round_trips_within_rounding_tolerance(self, small_world):
        _, latest = _replay(small_world, export_hauldesk_sync, parse_hauldesk_sync)
        by_native_id = {r.load.source_native_id: r for r in latest.values()}
        for load in small_world.loads:
            parsed = by_native_id[load.id.upper()]
            true_weight = load.weight_lbs_as_of(load.events[-1].timestamp)
            # lbs -> kg -> lbs round trip is lossy at the margins (two
            # separate roundings); tolerance reflects that, not a bug.
            assert abs(float(parsed.load.weight_lbs) - float(true_weight)) < 1.0
            assert abs(float(parsed.load.distance_miles) - float(load.distance_miles)) < 1.0


class TestBrokerOSRoundTrip:
    def test_every_load_appears_at_least_once_across_the_full_replay(self, small_world):
        _, latest = _replay(small_world, export_brokeros_sync, parse_brokeros_sync)
        assert len(latest) == len(small_world.loads)

    def test_carriers_get_mc_dot_via_our_documented_assumption(self, small_world):
        _, latest = _replay(small_world, export_brokeros_sync, parse_brokeros_sync)
        with_carrier = [r for r in latest.values() if r.carrier is not None]
        assert with_carrier
        for r in with_carrier:
            assert r.carrier.mc_number is not None
            assert r.carrier.dot_number is not None

    def test_locations_deduped_across_the_whole_sync_stream(self, small_world):
        # Not just within one file anymore -- ExportState.bos_location_ids
        # persists across all 44 calls, so a zip seen on day 1 must reuse
        # the same referenced_records id on day 9, not re-mint one.
        state = new_export_state()
        all_location_ids: set[str] = set()
        distinct_zips = {ld.origin_zip for ld in small_world.loads} | {ld.destination_zip for ld in small_world.loads}
        for day in range(1, 12):
            for sync_num in range(1, SYNCS_PER_DAY + 1):
                window_start, window_end = sync_window_bounds(small_world, day, sync_num)
                raw = export_brokeros_sync(small_world, window_start, window_end, state)
                if raw is None:
                    continue
                all_location_ids |= {
                    ref_id for ref_id, rec in raw["referenced_records"].items() if rec["type"] == "Location"
                }
        assert len(all_location_ids) == len(distinct_zips)

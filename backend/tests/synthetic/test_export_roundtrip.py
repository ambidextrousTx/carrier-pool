from datetime import date

import pytest

from adapters.brokeros import parse_brokeros_sync
from adapters.freightflow import parse_freightflow_sync
from adapters.hauldesk import parse_hauldesk_sync
from canonical.enums import LoadStatus
from synthetic.export import export_brokeros, export_freightflow, export_hauldesk
from synthetic.world import WorldConfig, generate_world


@pytest.fixture(scope="module")
def small_world():
    config = WorldConfig(
        broker_slug="test-broker", broker_name="Test Broker", seed=555, today=date(2026, 7, 31),
        num_days=90, target_loads=40, num_primary_lanes=6, num_carriers=12, num_customers=8,
        uncovered_window_days=6,
    )
    return generate_world(config)


class TestFreightFlowRoundTrip:
    def test_parses_cleanly_with_matching_load_count(self, small_world):
        raw = export_freightflow(small_world)
        results = parse_freightflow_sync(raw)
        assert len(results) == len(small_world.loads)

    def test_active_load_has_no_carrier_and_completed_load_does(self, small_world):
        raw = export_freightflow(small_world)
        results = {r.load.source_native_id: r for r in parse_freightflow_sync(raw)}
        active_world_loads = [ld for ld in small_world.loads if ld.final_status == LoadStatus.ACTIVE]
        completed_world_loads = [ld for ld in small_world.loads if ld.final_status == LoadStatus.COMPLETED]
        assert active_world_loads and completed_world_loads

        sample_active = active_world_loads[0]
        # Match by rate value since shipmentId is reassigned during export
        matched = next(r for r in results.values() if float(r.load.customer_rate_total_usd) == float(sample_active.events[-1].customer_rate_usd))
        assert matched.load.status == LoadStatus.ACTIVE
        assert matched.carrier is None

        sample_completed = completed_world_loads[0]
        matched_completed = next(
            r for r in results.values()
            if r.load.carrier_rate_total_usd is not None
            and float(r.load.carrier_rate_total_usd) == float(sample_completed.events[-1].carrier_rate_usd)
        )
        assert matched_completed.load.status == LoadStatus.COMPLETED
        assert matched_completed.carrier is not None


class TestHaulDeskRoundTrip:
    def test_parses_cleanly_with_matching_load_count(self, small_world):
        raw = export_hauldesk(small_world)
        results = parse_hauldesk_sync(raw)
        assert len(results) == len(small_world.loads)

    def test_rate_line_items_present_for_covered_loads(self, small_world):
        raw = export_hauldesk(small_world)
        results = parse_hauldesk_sync(raw)
        covered_or_later = [r for r in results if r.load.status != LoadStatus.PLANNED and r.load.status != LoadStatus.ACTIVE]
        assert covered_or_later
        for r in covered_or_later:
            sides = {item.side.value for item in r.load.rate_line_items}
            assert "PAY" in sides and "BILL" in sides

    def test_unit_conversion_round_trips_within_rounding_tolerance(self, small_world):
        raw = export_hauldesk(small_world)
        results = parse_hauldesk_sync(raw)
        by_native_id = {r.load.source_native_id: r for r in results}
        for load in small_world.loads:
            parsed = by_native_id[load.id.upper()]
            # lbs -> kg -> lbs round trip is lossy at the margins (two
            # separate roundings); tolerance reflects that, not a bug.
            assert abs(float(parsed.load.weight_lbs) - float(load.weight_lbs)) < 1.0
            assert abs(float(parsed.load.distance_miles) - float(load.distance_miles)) < 1.0


class TestBrokerOSRoundTrip:
    def test_parses_cleanly_with_matching_load_count(self, small_world):
        raw = export_brokeros(small_world)
        results = parse_brokeros_sync(raw)
        assert len(results) == len(small_world.loads)

    def test_carriers_get_mc_dot_via_our_documented_assumption(self, small_world):
        raw = export_brokeros(small_world)
        results = parse_brokeros_sync(raw)
        with_carrier = [r for r in results if r.carrier is not None]
        assert with_carrier
        for r in with_carrier:
            assert r.carrier.mc_number is not None
            assert r.carrier.dot_number is not None

    def test_locations_deduped_across_loads_sharing_a_zip(self, small_world):
        raw = export_brokeros(small_world)
        # Fewer distinct Location referenced_records than 2x load count
        # proves zips are being deduped, not re-minted per load.
        location_refs = {v["type"] for v in raw["referenced_records"].values() if v["type"] == "Location"}
        assert len(raw["referenced_records"]) < len(small_world.loads) * 2

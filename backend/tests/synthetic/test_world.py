import statistics
from collections import Counter
from datetime import date, timedelta

import pytest

from canonical.enums import LoadStatus
from geo.lookup import resolve_zip
from synthetic.world import World, WorldConfig, generate_world

_TODAY = date(2026, 7, 31)  # day 11 -- the day fresh, uncovered loads appear

_TX_TRIANGLE_MARKET_AREAS = {"Dallas-Fort Worth Metro", "Houston Metro", "San Antonio Metro", "Austin Metro"}
_LIFECYCLE_ORDER = [
    LoadStatus.PLANNED, LoadStatus.ACTIVE, LoadStatus.COVERED,
    LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED,
]


def _default_config(**overrides) -> WorldConfig:
    base = dict(broker_slug="acme", broker_name="Acme Freight", seed=42, today=_TODAY)
    base.update(overrides)
    return WorldConfig(**base)


@pytest.fixture(scope="module")
def world() -> World:
    return generate_world(_default_config())


class TestWorldStructure:
    def test_load_count_matches_config_exactly(self, world):
        # History and day-11 counts are now both exact loop counts, not
        # rounded fractions of a single target -- no "close to" slack needed.
        cfg = _default_config()
        assert len(world.loads) == cfg.target_history_loads + cfg.num_new_loads_day11

    def test_customer_count_matches_config(self, world):
        assert len(world.customers) == 20

    def test_carrier_count_matches_config(self, world):
        assert len(world.carriers) == 30

    def test_primary_lane_count_matches_config(self, world):
        assert len(world.primary_lanes) == 8

    def test_sparse_lane_not_in_primary_lanes(self, world):
        assert world.sparse_lane not in world.primary_lanes

    def test_customers_are_reused_across_loads(self, world):
        used_customer_ids = {ld.customer_id for ld in world.loads}
        assert len(used_customer_ids) <= 20
        assert len(used_customer_ids) > 1


class TestTexasTriangleBias:
    def test_all_primary_lanes_are_texas_triangle_internal(self, world):
        for lane in world.primary_lanes:
            assert lane.origin_market_area in _TX_TRIANGLE_MARKET_AREAS
            assert lane.destination_market_area in _TX_TRIANGLE_MARKET_AREAS

    def test_sparse_lane_is_texas_triangle_internal(self, world):
        assert world.sparse_lane.origin_market_area in _TX_TRIANGLE_MARKET_AREAS
        assert world.sparse_lane.destination_market_area in _TX_TRIANGLE_MARKET_AREAS

    def test_majority_of_loads_move_within_the_triangle(self, world):
        tx_internal = sum(
            1 for ld in world.loads
            if ld.lane.origin_market_area in _TX_TRIANGLE_MARKET_AREAS
            and ld.lane.destination_market_area in _TX_TRIANGLE_MARKET_AREAS
        )
        assert tx_internal / len(world.loads) > 0.60

    def test_a_genuine_non_texas_tail_still_exists(self):
        # "Covering more than the Triangle is fine" -- confirm that's
        # actually true of the generated data, not squeezed out entirely
        # by the primary-lane bias. Uses the smaller round-trip world
        # fixture-scale config isn't needed here -- module-scoped `world`
        # already has a real tail pool.
        w = generate_world(_default_config())
        non_tx = [
            ld for ld in w.loads
            if ld.lane.origin_market_area not in _TX_TRIANGLE_MARKET_AREAS
            or ld.lane.destination_market_area not in _TX_TRIANGLE_MARKET_AREAS
        ]
        assert len(non_tx) > 0


class TestCarrierTiers:
    def test_regular_occasional_split_matches_config(self, world):
        counts = Counter(c.tier for c in world.carriers)
        assert counts["regular"] == 12  # round(30 * 0.4)
        assert counts["occasional"] == 18

    def test_regular_carriers_have_preferred_lanes_from_primary_set(self, world):
        regular = [c for c in world.carriers if c.tier == "regular"]
        assert all(len(c.preferred_lanes) >= 1 for c in regular)
        for c in regular:
            assert all(lane in world.primary_lanes for lane in c.preferred_lanes)

    def test_occasional_carriers_have_no_preferred_lanes(self, world):
        occasional = [c for c in world.carriers if c.tier == "occasional"]
        assert all(c.preferred_lanes == () for c in occasional)

    def test_carrier_mc_and_dot_numbers_are_unique(self, world):
        mc_numbers = [c.mc_number for c in world.carriers]
        dot_numbers = [c.dot_number for c in world.carriers]
        assert len(mc_numbers) == len(set(mc_numbers))
        assert len(dot_numbers) == len(set(dot_numbers))

    def test_regular_carriers_win_their_preferred_lanes_more_than_chance(self, world):
        # The actual signal the recommendation engine's lane-history
        # ranking depends on -- prove it's real, not just configured and
        # silently doing nothing. Uses assigned_carrier_id, which is set
        # as soon as a load reaches COVERED regardless of whether it goes
        # on to complete or stays in-flight -- both are real evidence of
        # who got picked.
        historical = [ld for ld in world.loads if ld.assigned_carrier_id is not None]
        by_id = {c.id: c for c in world.carriers}

        wins = 0
        opportunities = 0
        for ld in historical:
            eligible_regulars = [
                c for c in world.carriers if c.tier == "regular" and ld.lane in c.preferred_lanes
            ]
            if not eligible_regulars:
                continue
            opportunities += 1
            assigned = by_id[ld.assigned_carrier_id]
            if assigned in eligible_regulars:
                wins += 1

        assert opportunities >= 20
        win_rate = wins / opportunities
        assert win_rate > 0.35


class TestLaneDistribution:
    def test_sparse_lane_has_exactly_two_loads(self, world):
        sparse_loads = [ld for ld in world.loads if ld.lane == world.sparse_lane]
        assert len(sparse_loads) == 2

    def test_most_loads_land_on_primary_lanes(self, world):
        on_primary = sum(1 for ld in world.loads if ld.lane in world.primary_lanes)
        assert on_primary / len(world.loads) > 0.60

    def test_primary_lanes_see_meaningfully_repeated_volume(self, world):
        counts = Counter(ld.lane for ld in world.loads if ld.lane in world.primary_lanes)
        assert min(counts.values()) >= 5

    def test_a_real_tail_of_one_off_lanes_exists(self, world):
        tail_loads = [ld for ld in world.loads if ld.lane not in world.primary_lanes and ld.lane != world.sparse_lane]
        assert len(tail_loads) > 0
        counts = Counter(ld.lane for ld in tail_loads)
        assert statistics.median(counts.values()) <= 2


class TestHistoryVsDay11:
    """Replaces the old TestUncoveredWindow -- the model no longer splits
    loads by "created recently vs. long ago" within one flat window; it's
    day 1-10 history (a real mix of completed and in-flight, by
    truncation) vs. day 11 (always fresh PLANNED->ACTIVE, never further)."""

    def test_day11_loads_stop_at_active_with_no_carrier(self, world):
        day11 = [ld for ld in world.loads if ld.created_day == 11]
        assert len(day11) == _default_config().num_new_loads_day11
        for ld in day11:
            assert ld.final_status == LoadStatus.ACTIVE
            assert ld.assigned_carrier_id is None

    def test_history_loads_show_a_realistic_status_mix(self, world):
        # Not just COMPLETED -- truncation should produce genuine
        # in-flight loads too (this is what makes the busy-carrier
        # exclusion in rank_carriers testable against real data).
        history = [ld for ld in world.loads if ld.created_day <= 10]
        statuses = {ld.final_status for ld in history}
        assert LoadStatus.COMPLETED in statuses
        assert statuses & {LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED}

    def test_majority_of_history_loads_reach_completed(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        completed = sum(1 for ld in history if ld.final_status == LoadStatus.COMPLETED)
        assert completed / len(history) > 0.5

    def test_every_history_day_has_at_least_one_new_load(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        days_seen = {ld.created_day for ld in history}
        assert days_seen == set(range(1, 11))

    def test_no_history_event_reaches_day_11(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        for ld in history:
            for e in ld.events:
                assert e.timestamp < world.history_cutoff, f"{ld.id} has a history event on/after day 11: {e}"

    def test_day11_events_are_on_day_11(self, world):
        day11 = [ld for ld in world.loads if ld.created_day == 11]
        for ld in day11:
            for e in ld.events:
                assert e.timestamp.date() == world.day11_date


class TestEventTimelineIntegrity:
    def test_events_are_chronologically_non_decreasing(self, world):
        for ld in world.loads:
            timestamps = [e.timestamp for e in ld.events]
            assert timestamps == sorted(timestamps)

    def test_no_event_occurs_after_today(self, world):
        for ld in world.loads:
            for e in ld.events:
                assert e.timestamp.date() <= _TODAY, f"{ld.id} has an event after 'today': {e}"

    def test_completed_loads_visit_every_lifecycle_stage_in_order(self, world):
        # Was an exact-sequence-equality check in the old model. Can't be
        # anymore -- a correction or reassignment legitimately appends an
        # extra event that repeats an already-visited status (e.g. a
        # second COVERED event with a reassigned carrier, or a second
        # COMPLETED event with a restated rate). What must still hold:
        # status never regresses, and every one of the 6 stages was
        # genuinely visited at least once.
        completed = [ld for ld in world.loads if ld.final_status == LoadStatus.COMPLETED]
        assert len(completed) > 0
        for ld in completed:
            indices = [_LIFECYCLE_ORDER.index(e.status) for e in ld.events]
            assert indices == sorted(indices), f"{ld.id} status went backward: {[e.status for e in ld.events]}"
            assert set(indices) == set(range(len(_LIFECYCLE_ORDER))), f"{ld.id} skipped a stage"

    def test_carrier_only_assigned_from_covered_onward(self, world):
        for ld in world.loads:
            for e in ld.events:
                if e.status in (LoadStatus.PLANNED, LoadStatus.ACTIVE):
                    assert e.carrier_id is None
                else:
                    assert e.carrier_id is not None

    def test_carrier_rate_only_set_from_covered_onward(self, world):
        for ld in world.loads:
            for e in ld.events:
                if e.status == LoadStatus.PLANNED:
                    assert e.carrier_rate_usd is None
                if e.status not in (LoadStatus.PLANNED, LoadStatus.ACTIVE):
                    assert e.carrier_rate_usd is not None

    def test_customer_rate_set_from_active_onward(self, world):
        for ld in world.loads:
            for e in ld.events:
                if e.status != LoadStatus.PLANNED:
                    assert e.customer_rate_usd is not None


class TestCorrectionsAndReassignment:
    """New behaviors that didn't exist in the old model at all."""

    def test_some_history_loads_have_a_repeated_status_event(self, world):
        # A money correction always reuses the load's current status on a
        # later timestamp -- so a load with one is identifiable by a
        # repeated status value in its own event list.
        history = [ld for ld in world.loads if ld.created_day <= 10]
        with_repeat = [ld for ld in history if len({e.status for e in ld.events}) < len(ld.events)]
        assert len(with_repeat) > 0

    def test_some_history_loads_have_a_carrier_reassignment(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        reassigned = [
            ld for ld in history
            if len({e.carrier_id for e in ld.events if e.status == LoadStatus.COVERED and e.carrier_id}) > 1
        ]
        assert len(reassigned) > 0

    def test_some_history_loads_have_a_field_correction(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        assert any(ld.corrections for ld in history)

    def test_field_correction_timestamps_never_exceed_history_cutoff(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        for ld in history:
            for c in ld.corrections:
                assert c.timestamp < world.history_cutoff

    def test_weight_correction_changes_the_effective_value(self, world):
        history = [ld for ld in world.loads if ld.created_day <= 10]
        weight_corrected = [ld for ld in history if any(c.field == "weight_lbs" for c in ld.corrections)]
        assert len(weight_corrected) > 0
        ld = weight_corrected[0]
        cutoff_before = min(c.timestamp for c in ld.corrections if c.field == "weight_lbs")
        assert ld.weight_lbs_as_of(cutoff_before - timedelta(seconds=1)) == ld.weight_lbs
        assert ld.weight_lbs_as_of(ld.last_modified_at) != ld.weight_lbs


class TestRateEconomics:
    def test_rate_per_mile_shows_real_variance_on_a_primary_lane(self, world):
        lane = world.primary_lanes[0]
        rates_per_mile = [
            (ld.events[-1].carrier_rate_usd / ld.distance_miles)
            for ld in world.loads
            if ld.lane == lane and ld.events[-1].carrier_rate_usd is not None
        ]
        assert len(rates_per_mile) >= 5
        assert statistics.pstdev(float(r) for r in rates_per_mile) > 0.01

    def test_at_least_one_outlier_exists_somewhere_in_the_dataset(self, world):
        by_lane: dict = {}
        for ld in world.loads:
            rate = ld.events[-1].carrier_rate_usd
            if rate is None:
                continue
            by_lane.setdefault(ld.lane, []).append(float(rate) / float(ld.distance_miles))

        found_outlier = False
        for rates in by_lane.values():
            if len(rates) < 5:
                continue
            med = statistics.median(rates)
            if any(abs(r - med) / med > 0.3 for r in rates):
                found_outlier = True
                break
        assert found_outlier

    def test_customer_rate_at_booking_exceeds_carrier_rate_at_booking(self, world):
        # Checked at the moment a carrier is first booked (the COVERED
        # event), not "wherever both are set" -- a later money correction
        # can legitimately move either side independently (that's the
        # whole point of modeling corrections as real, uncapped events),
        # so this is no longer a universal invariant across every event.
        # The margin at booking time, before any correction, always is.
        for ld in world.loads:
            covered = next((e for e in ld.events if e.status == LoadStatus.COVERED), None)
            if covered is not None:
                assert covered.customer_rate_usd > covered.carrier_rate_usd


class TestGeoConsistency:
    def test_every_load_origin_resolves_to_its_lane_origin_market(self, world):
        for ld in world.loads:
            geo = resolve_zip(ld.origin_zip)
            assert geo is not None
            assert geo.market_area == ld.lane.origin_market_area

    def test_every_load_destination_resolves_to_its_lane_destination_market(self, world):
        for ld in world.loads:
            geo = resolve_zip(ld.destination_zip)
            assert geo is not None
            assert geo.market_area == ld.lane.destination_market_area

    def test_distances_are_positive_and_plausible(self, world):
        for ld in world.loads:
            assert 0 < ld.distance_miles < 3000


class TestDeterminism:
    def test_same_seed_produces_identical_world(self):
        world_a = generate_world(_default_config(seed=99))
        world_b = generate_world(_default_config(seed=99))

        assert [c.name for c in world_a.carriers] == [c.name for c in world_b.carriers]
        assert [(ld.id, ld.origin_zip, ld.destination_zip, ld.events[-1].carrier_rate_usd) for ld in world_a.loads] == [
            (ld.id, ld.origin_zip, ld.destination_zip, ld.events[-1].carrier_rate_usd) for ld in world_b.loads
        ]

    def test_different_seeds_produce_different_worlds(self):
        world_a = generate_world(_default_config(seed=1))
        world_b = generate_world(_default_config(seed=2))
        assert [c.name for c in world_a.carriers] != [c.name for c in world_b.carriers]

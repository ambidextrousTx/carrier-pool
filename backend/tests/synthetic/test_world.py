import statistics
from collections import Counter
from datetime import date, timedelta

import pytest

from canonical.enums import LoadStatus
from geo.lookup import resolve_zip
from synthetic.world import World, WorldConfig, generate_world

_TODAY = date(2026, 7, 31)


def _default_config(**overrides) -> WorldConfig:
    base = dict(broker_slug="acme", broker_name="Acme Freight", seed=42, today=_TODAY)
    base.update(overrides)
    return WorldConfig(**base)


@pytest.fixture(scope="module")
def world() -> World:
    return generate_world(_default_config())


class TestWorldStructure:
    def test_load_count_close_to_target(self, world):
        # Rounding in the historical/current split means "close to", not
        # necessarily exact.
        assert abs(len(world.loads) - 300) <= 2

    def test_customer_count_matches_config(self, world):
        assert len(world.customers) == 20

    def test_carrier_count_matches_config(self, world):
        assert len(world.carriers) == 30

    def test_primary_lane_count_matches_config(self, world):
        assert len(world.primary_lanes) == 10

    def test_sparse_lane_not_in_primary_lanes(self, world):
        assert world.sparse_lane not in world.primary_lanes

    def test_customers_are_reused_across_loads(self, world):
        # 20 customers, ~300 loads -- customers MUST repeat.
        used_customer_ids = {ld.customer_id for ld in world.loads}
        assert len(used_customer_ids) <= 20
        assert len(used_customer_ids) > 1  # not degenerate to a single customer either


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
        # This is the actual signal the recommendation engine's lane-history
        # ranking depends on -- prove it's real, not just configured and
        # silently doing nothing.
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

        assert opportunities >= 20  # enough sample size for this to mean something
        win_rate = wins / opportunities
        # With N eligible regulars typically small (1-3) against a 30-carrier
        # pool, pure chance would be nowhere near this -- 70% preference
        # weight in the picker should show up clearly above chance.
        assert win_rate > 0.35


class TestLaneDistribution:
    def test_sparse_lane_has_exactly_two_loads(self, world):
        sparse_loads = [ld for ld in world.loads if ld.lane == world.sparse_lane]
        assert len(sparse_loads) == 2

    def test_most_loads_land_on_primary_lanes(self, world):
        on_primary = sum(1 for ld in world.loads if ld.lane in world.primary_lanes)
        # ~75% by construction, allow reasonable statistical slack
        assert on_primary / len(world.loads) > 0.60

    def test_primary_lanes_see_meaningfully_repeated_volume(self, world):
        counts = Counter(ld.lane for ld in world.loads if ld.lane in world.primary_lanes)
        # The whole point of "primary lanes" -- real repeat volume, not
        # scattered one-offs indistinguishable from the tail.
        assert min(counts.values()) >= 5

    def test_a_real_tail_of_one_off_lanes_exists(self, world):
        tail_loads = [ld for ld in world.loads if ld.lane not in world.primary_lanes and ld.lane != world.sparse_lane]
        assert len(tail_loads) > 0
        counts = Counter(ld.lane for ld in tail_loads)
        # Tail lanes should mostly NOT repeat much -- otherwise they're
        # not actually "one-off" relative to the primary lanes.
        assert statistics.median(counts.values()) <= 2


class TestUncoveredWindow:
    def _cutoff(self):
        return _TODAY - timedelta(days=6)

    def test_current_loads_stop_at_active_with_no_carrier(self, world):
        cutoff = self._cutoff()
        current = [ld for ld in world.loads if ld.created_at.date() >= cutoff]
        assert len(current) > 0
        for ld in current:
            assert ld.final_status == LoadStatus.ACTIVE
            assert ld.assigned_carrier_id is None

    def test_historical_loads_complete_with_a_carrier_assigned(self, world):
        cutoff = self._cutoff()
        historical = [ld for ld in world.loads if ld.created_at.date() < cutoff]
        assert len(historical) > 0
        for ld in historical:
            assert ld.final_status == LoadStatus.COMPLETED
            assert ld.assigned_carrier_id is not None

    def test_uncovered_loads_exist_in_a_realistic_proportion(self, world):
        cutoff = self._cutoff()
        current = [ld for ld in world.loads if ld.created_at.date() >= cutoff]
        # ~7/90 of loads by construction -- sanity check it's a plausible
        # slice, not near-zero or near-everything.
        fraction = len(current) / len(world.loads)
        assert 0.03 < fraction < 0.20


class TestEventTimelineIntegrity:
    def test_events_are_chronologically_non_decreasing(self, world):
        for ld in world.loads:
            timestamps = [e.timestamp for e in ld.events]
            assert timestamps == sorted(timestamps)

    def test_no_event_occurs_after_today(self, world):
        not_after = _TODAY
        for ld in world.loads:
            for e in ld.events:
                assert e.timestamp.date() <= not_after, f"{ld.id} has an event after 'today': {e}"

    def test_full_lifecycle_status_sequence_for_historical_loads(self, world):
        expected = [
            LoadStatus.PLANNED, LoadStatus.ACTIVE, LoadStatus.COVERED,
            LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED, LoadStatus.COMPLETED,
        ]
        historical = [ld for ld in world.loads if ld.final_status == LoadStatus.COMPLETED]
        assert len(historical) > 0
        for ld in historical:
            assert [e.status for e in ld.events] == expected

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
                if e.status in (LoadStatus.PLANNED,):
                    assert e.carrier_rate_usd is None
                if e.status not in (LoadStatus.PLANNED, LoadStatus.ACTIVE):
                    assert e.carrier_rate_usd is not None

    def test_customer_rate_set_from_active_onward(self, world):
        for ld in world.loads:
            for e in ld.events:
                if e.status != LoadStatus.PLANNED:
                    assert e.customer_rate_usd is not None


class TestRateEconomics:
    def test_customer_rate_exceeds_carrier_rate_wherever_both_are_set(self, world):
        for ld in world.loads:
            for e in ld.events:
                if e.customer_rate_usd is not None and e.carrier_rate_usd is not None:
                    assert e.customer_rate_usd > e.carrier_rate_usd

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
        # An "outlier" here: a load whose rate/mile deviates from its own
        # lane's median by a wide margin -- proves median-over-mean will
        # actually matter downstream, rather than every load hugging the
        # lane average tightly.
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

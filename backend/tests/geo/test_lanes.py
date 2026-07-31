import pytest

from canonical.models import Stop
from geo.lanes import Lane, lane_for_stops, primary_dropoff, primary_pickup


def _stop(sequence, is_pickup, is_dropoff, city, state, zip_code=None):
    return Stop(
        sequence=sequence,
        is_pickup=is_pickup,
        is_dropoff=is_dropoff,
        city=city,
        state=state,
        zip_code=zip_code,
    )


class TestPrimaryPickupAndDropoff:
    def test_simple_two_stop_load(self):
        stops = [
            _stop(1, True, False, "Grand Prairie", "TX", "75050"),
            _stop(2, False, True, "Katy", "TX", "77449"),
        ]
        assert primary_pickup(stops).city == "Grand Prairie"
        assert primary_dropoff(stops).city == "Katy"

    def test_multi_stop_ignores_middle_stops(self):
        stops = [
            _stop(1, True, False, "Grand Prairie", "TX", "75050"),
            _stop(2, False, False, "Fort Worth", "TX", "76102"),  # neither
            _stop(3, False, True, "Katy", "TX", "77449"),
        ]
        assert primary_pickup(stops).city == "Grand Prairie"
        assert primary_dropoff(stops).city == "Katy"

    def test_not_affected_by_array_order(self):
        # Same three stops as above, listed out of sequence order --
        # primary_pickup/dropoff must go by the sequence field, not
        # position in the list.
        stops = [
            _stop(3, False, True, "Katy", "TX", "77449"),
            _stop(1, True, False, "Grand Prairie", "TX", "75050"),
            _stop(2, False, False, "Fort Worth", "TX", "76102"),
        ]
        assert primary_pickup(stops).city == "Grand Prairie"
        assert primary_dropoff(stops).city == "Katy"

    def test_final_dropoff_wins_when_multiple_dropoffs_flagged(self):
        stops = [
            _stop(1, True, False, "Grand Prairie", "TX", "75050"),
            _stop(2, False, True, "Fort Worth", "TX", "76102"),  # intermediate drop
            _stop(3, False, True, "Katy", "TX", "77449"),  # final drop
        ]
        assert primary_dropoff(stops).city == "Katy"

    def test_no_pickup_raises(self):
        stops = [_stop(1, False, True, "Katy", "TX", "77449")]
        with pytest.raises(ValueError, match="no pickup stop"):
            primary_pickup(stops)

    def test_no_dropoff_raises(self):
        stops = [_stop(1, True, False, "Grand Prairie", "TX", "75050")]
        with pytest.raises(ValueError, match="no dropoff stop"):
            primary_dropoff(stops)


class TestLaneForStops:
    def test_derives_market_areas(self):
        stops = [
            _stop(1, True, False, "Grand Prairie", "TX", "75050"),
            _stop(2, False, True, "Katy", "TX", "77449"),
        ]
        assert lane_for_stops(stops) == Lane(
            origin_market_area="Dallas-Fort Worth Metro",
            destination_market_area="Houston Metro",
        )

    def test_different_cities_same_market_area_is_still_one_lane(self):
        # Dallas -> Fort Worth are different cities but the same market
        # area -- this is the actual "fuzzy" part of fuzzy lane matching.
        stops = [
            _stop(1, True, False, "Dallas", "TX", "75201"),
            _stop(2, False, True, "Fort Worth", "TX", "76102"),
        ]
        lane = lane_for_stops(stops)
        assert lane.origin_market_area == lane.destination_market_area == "Dallas-Fort Worth Metro"

    def test_unresolvable_zip_returns_none(self):
        stops = [
            _stop(1, True, False, "Nowhereville", "ZZ", "00000"),
            _stop(2, False, True, "Katy", "TX", "77449"),
        ]
        assert lane_for_stops(stops) is None

    def test_missing_zip_returns_none(self):
        stops = [
            _stop(1, True, False, "Grand Prairie", "TX", None),
            _stop(2, False, True, "Katy", "TX", "77449"),
        ]
        assert lane_for_stops(stops) is None

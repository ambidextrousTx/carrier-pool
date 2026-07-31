from geo.reference_data import GEO_ZIPS
from geo.distance import haversine_miles
from decimal import Decimal


_BY_ZIP = {z.zip_code: z for z in GEO_ZIPS}


def _dist(zip_a: str, zip_b: str) -> Decimal:
    a, b = _BY_ZIP[zip_a], _BY_ZIP[zip_b]
    return haversine_miles(a.latitude, a.longitude, b.latitude, b.longitude)


class TestHaversineMiles:
    def test_same_point_is_zero(self):
        assert _dist("75201", "75201") == Decimal("0.0")

    def test_dallas_to_houston(self):
        # Real-world straight-line distance is ~225 miles.
        assert _dist("75201", "77002") == Decimal("225.1")

    def test_los_angeles_to_nyc_cross_country(self):
        # Real-world straight-line distance is ~2450 miles -- sanity
        # check at a much larger scale than the local/regional cases.
        assert _dist("90012", "11201") == Decimal("2446.1")

    def test_symmetric(self):
        assert _dist("75201", "77002") == _dist("77002", "75201")

    def test_intra_metro_distance_is_small(self):
        # Dallas and Grand Prairie are the same market area -- should be a
        # short hop, not comparable to an interstate lane.
        assert _dist("75201", "75050") < Decimal("20.0")

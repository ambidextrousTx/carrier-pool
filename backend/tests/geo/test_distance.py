from geo.reference_data import GEO_ZIPS
from geo.distance import haversine_miles
from decimal import Decimal


class TestHaversineDistance:
    def test_known_values(self):
        by_zip = {z.zip_code: z for z in GEO_ZIPS}
        dallas = by_zip['75201']
        houston = by_zip['77002']
        la = by_zip['90012']
        nyc = by_zip['11201']
        grand_prairie = by_zip['75050']
        delta = Decimal('0.05')

        assert abs(haversine_miles(dallas.latitude, dallas.longitude, houston.latitude, houston.longitude) - Decimal(225.1)) <= delta
        assert abs(haversine_miles(la.latitude, la.longitude, nyc.latitude, nyc.longitude) - Decimal(2446.1)) <= delta
        assert abs(haversine_miles(dallas.latitude, dallas.longitude, dallas.latitude, dallas.longitude) - Decimal(0.0)) <= delta
        assert abs(haversine_miles(dallas.latitude, dallas.longitude, grand_prairie.latitude, grand_prairie.longitude) - Decimal(12.9)) <= delta

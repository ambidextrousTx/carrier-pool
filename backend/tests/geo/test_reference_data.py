from geo.reference_data import GEO_ZIPS


class TestReferenceDataIntegrity:
    def test_no_duplicate_zip_codes(self):
        zips = [z.zip_code for z in GEO_ZIPS]
        assert len(zips) == len(set(zips))

    def test_all_coordinates_in_valid_range(self):
        for z in GEO_ZIPS:
            assert -90.0 <= z.latitude <= 90.0, z
            assert -180.0 <= z.longitude <= 180.0, z

    def test_all_zips_are_five_digits(self):
        for z in GEO_ZIPS:
            assert len(z.zip_code) == 5 and z.zip_code.isdigit(), z

    def test_at_least_fifteen_distinct_market_areas(self):
        # The whole point of this table is repeat lanes -- too few market
        # areas and every load looks unique; too many and nothing repeats.
        assert len({z.market_area for z in GEO_ZIPS}) >= 15

    def test_every_market_area_has_at_least_two_cities(self):
        # A market area with only one city can never produce an
        # intra-market "same lane" match with a DIFFERENT city, which
        # undersells the "fuzzy" part of fuzzy lane matching.
        from collections import Counter

        counts = Counter(z.market_area for z in GEO_ZIPS)
        for market_area, count in counts.items():
            assert count >= 2, f"{market_area} has only {count} cities"


class TestRealFixtureZipsResolve:
    """Every zip that appears in the real TMS fixtures we were given must
    resolve here, or ingesting that real sample data would fail."""

    def _lookup(self, zip_code: str):
        return next(z for z in GEO_ZIPS if z.zip_code == zip_code)

    def test_grand_prairie(self):
        z = self._lookup("75050")
        assert z.city == "Grand Prairie" and z.state == "TX"

    def test_katy(self):
        z = self._lookup("77449")
        assert z.city == "Katy" and z.state == "TX"

    def test_new_braunfels(self):
        z = self._lookup("78130")
        assert z.city == "New Braunfels" and z.state == "TX"

    def test_pasadena(self):
        z = self._lookup("77502")
        assert z.city == "Pasadena" and z.state == "TX"

    def test_sugar_land(self):
        z = self._lookup("77478")
        assert z.city == "Sugar Land" and z.state == "TX"

    def test_schertz(self):
        z = self._lookup("78154")
        assert z.city == "Schertz" and z.state == "TX"

    def test_grand_prairie_and_katy_are_different_market_areas(self):
        # Sanity check on the corridor these fixtures represent: DFW -> Houston
        # is a real, different-market-area lane, not an intra-market hop.
        assert self._lookup("75050").market_area != self._lookup("77449").market_area

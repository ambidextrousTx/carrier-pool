from decimal import Decimal

from adapters.units import kg_to_lbs, km_to_miles


class TestKgToLbs:
    def test_known_conversion(self):
        assert kg_to_lbs(Decimal("10886.2")) == Decimal("24000.0")

    def test_rounds_to_one_decimal_place(self):
        # 1 kg = 2.2046226218... lbs -- exercise actual rounding, not just
        # a value that happens to land on a clean number.
        assert kg_to_lbs(Decimal("1")) == Decimal("2.2")


class TestKmToMiles:
    def test_known_conversion(self):
        assert km_to_miles(Decimal("389.6")) == Decimal("242.1")

    def test_rounds_to_one_decimal_place(self):
        # 1 km = 0.62137... miles
        assert km_to_miles(Decimal("1")) == Decimal("0.6")

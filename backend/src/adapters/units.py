from decimal import ROUND_HALF_UP, Decimal

# Exact conversion factors (international pound/mile definitions)
_KG_TO_LB = Decimal(1) / Decimal("0.45359237")
_KM_TO_MI = Decimal(1) / Decimal("1.609344")

_ONE_DECIMAL_PLACE = Decimal("0.1")


def kg_to_lbs(value: Decimal) -> Decimal:
    return (value * _KG_TO_LB).quantize(_ONE_DECIMAL_PLACE, rounding=ROUND_HALF_UP)


def km_to_miles(value: Decimal) -> Decimal:
    return (value * _KM_TO_MI).quantize(_ONE_DECIMAL_PLACE, rounding=ROUND_HALF_UP)

from decimal import Decimal


def to_decimal(value: float | int | str | None) -> Decimal | None:
    """Converts a JSON-parsed number to Decimal via str(), not Decimal(value)
    directly -- going through str() uses Python's shortest-round-trip float
    repr, avoiding binary floating point artifacts (e.g. Decimal(1450.0)
    is exact, but plenty of legitimate values like Decimal(0.1) are not)."""
    if value is None:
        return None
    return Decimal(str(value))

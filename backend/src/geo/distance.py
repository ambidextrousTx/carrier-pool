import math
from decimal import ROUND_HALF_UP, Decimal

_EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> Decimal:
    """Great-circle distance between two points, in miles. This is a
    straight-line ("as the crow flies") distance, not a road-network
    routing distance -- appropriate for ranking/comparing carrier
    deadhead positions relative to each other, not for a precise mileage
    quote."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    miles = _EARTH_RADIUS_MILES * c

    return Decimal(str(miles)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

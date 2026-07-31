from dataclasses import dataclass

from canonical.models import Stop
from geo.lookup import resolve_zip


@dataclass(frozen=True)
class Lane:
    origin_market_area: str
    destination_market_area: str


def primary_pickup(stops: list[Stop]) -> Stop:
    """The earliest-sequence stop flagged as a pickup -- not just stops[0],
    since a multi-stop load's array order isn't guaranteed to put the
    pickup first (see BrokerOS's adapter, which explicitly sorts by
    sequence rather than trusting array order)."""
    pickups = [s for s in stops if s.is_pickup]
    if not pickups:
        raise ValueError("no pickup stop found")
    return min(pickups, key=lambda s: s.sequence)


def primary_dropoff(stops: list[Stop]) -> Stop:
    """The latest-sequence stop flagged as a dropoff -- the FINAL
    destination for a multi-stop load, not the first dropoff encountered."""
    dropoffs = [s for s in stops if s.is_dropoff]
    if not dropoffs:
        raise ValueError("no dropoff stop found")
    return max(dropoffs, key=lambda s: s.sequence)


def lane_for_stops(stops: list[Stop]) -> Lane | None:
    """Derives the lane (origin/destination market area) from a load's
    full stop list. Returns None if either endpoint's zip doesn't resolve
    against our reference data -- callers decide how strict to be about
    that (ingestion likely treats it as a data problem; exploratory code
    may want to just skip loads with an unresolvable lane)."""
    pickup = primary_pickup(stops)
    dropoff = primary_dropoff(stops)

    origin = resolve_zip(pickup.zip_code) if pickup.zip_code else None
    destination = resolve_zip(dropoff.zip_code) if dropoff.zip_code else None
    if origin is None or destination is None:
        return None

    return Lane(origin_market_area=origin.market_area, destination_market_area=destination.market_area)

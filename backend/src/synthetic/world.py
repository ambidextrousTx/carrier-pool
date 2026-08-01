import random
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from canonical.enums import EquipmentType, LoadStatus
from geo.distance import haversine_miles
from geo.lanes import Lane
from geo.reference_data import GEO_ZIPS, GeoZip
from synthetic.names import (
    generate_carrier_names,
    generate_customer_names,
    generate_phone_number,
    generate_unique_number,
)

_MARKET_AREAS: list[str] = sorted({z.market_area for z in GEO_ZIPS})

_ZIPS_BY_MARKET_AREA: dict[str, list[GeoZip]] = {}
for _z in GEO_ZIPS:
    _ZIPS_BY_MARKET_AREA.setdefault(_z.market_area, []).append(_z)

_EQUIPMENT_WEIGHTS: list[tuple[EquipmentType, float]] = [
    (EquipmentType.DRY_VAN, 0.55),
    (EquipmentType.REEFER, 0.25),
    (EquipmentType.FLATBED, 0.20),
]

# "Primary" (repeat) lanes are drawn only from pairs under this distance --
# realistic for a broker's core repeat-lane portfolio, which is
# overwhelmingly regional/multi-state rather than consistently
# coast-to-coast. Long-haul pairs can still appear as one-off tail lanes.
_MAX_PRIMARY_LANE_DISTANCE_MILES = Decimal("1500")

_FORCED_SPARSE_LANE_LOAD_COUNT = 2


@dataclass(frozen=True)
class WorldConfig:
    broker_slug: str
    broker_name: str
    seed: int
    today: date
    num_days: int = 90
    target_loads: int = 300
    num_primary_lanes: int = 10
    num_carriers: int = 30
    regular_carrier_fraction: float = 0.4
    num_customers: int = 20
    uncovered_window_days: int = 6


@dataclass(frozen=True)
class CarrierProfile:
    id: str
    name: str
    mc_number: str
    dot_number: str
    phone: str
    home_city: str
    home_state: str
    home_zip: str
    home_market_area: str
    tier: str  # "regular" | "occasional"
    preferred_lanes: tuple[Lane, ...]


@dataclass(frozen=True)
class CustomerProfile:
    id: str
    name: str


@dataclass(frozen=True)
class LoadEvent:
    timestamp: datetime
    status: LoadStatus
    carrier_id: str | None
    customer_rate_usd: Decimal | None
    carrier_rate_usd: Decimal | None


@dataclass(frozen=True)
class WorldLoad:
    id: str
    customer_id: str
    lane: Lane
    origin_zip: str
    origin_city: str
    origin_state: str
    destination_zip: str
    destination_city: str
    destination_state: str
    equipment_type: EquipmentType
    weight_lbs: Decimal
    distance_miles: Decimal
    pickup_date: date
    delivery_date: date
    events: tuple[LoadEvent, ...]

    @property
    def created_at(self) -> datetime:
        return self.events[0].timestamp

    @property
    def last_modified_at(self) -> datetime:
        return self.events[-1].timestamp

    @property
    def final_status(self) -> LoadStatus:
        return self.events[-1].status

    @property
    def assigned_carrier_id(self) -> str | None:
        return self.events[-1].carrier_id


@dataclass(frozen=True)
class World:
    broker_slug: str
    broker_name: str
    carriers: tuple[CarrierProfile, ...]
    customers: tuple[CustomerProfile, ...]
    loads: tuple[WorldLoad, ...]
    primary_lanes: tuple[Lane, ...]
    sparse_lane: Lane


def _all_possible_lanes() -> list[Lane]:
    return [
        Lane(origin_market_area=origin, destination_market_area=dest)
        for origin in _MARKET_AREAS
        for dest in _MARKET_AREAS
        if origin != dest
    ]


def _market_area_centroid(market_area: str) -> tuple[float, float]:
    entries = _ZIPS_BY_MARKET_AREA[market_area]
    return (
        sum(e.latitude for e in entries) / len(entries),
        sum(e.longitude for e in entries) / len(entries),
    )


_MARKET_AREA_CENTROIDS = {ma: _market_area_centroid(ma) for ma in _MARKET_AREAS}


def _lane_representative_distance(lane: Lane) -> Decimal:
    olat, olon = _MARKET_AREA_CENTROIDS[lane.origin_market_area]
    dlat, dlon = _MARKET_AREA_CENTROIDS[lane.destination_market_area]
    return haversine_miles(olat, olon, dlat, dlon)


def _pick_zip_in_market_area(rng: random.Random, market_area: str) -> GeoZip:
    return rng.choice(_ZIPS_BY_MARKET_AREA[market_area])


def _weighted_choice(rng: random.Random, weighted_options: list[tuple[EquipmentType, float]]) -> EquipmentType:
    total = sum(w for _, w in weighted_options)
    r = rng.uniform(0, total)
    upto = 0.0
    for option, w in weighted_options:
        upto += w
        if upto >= r:
            return option
    return weighted_options[-1][0]


def _draw_lane(rng: random.Random, primary_lanes: list[Lane], tail_pool: list[Lane]) -> Lane:
    return rng.choice(primary_lanes) if rng.random() < 0.75 else rng.choice(tail_pool)


def _pick_carrier_for_lane(rng: random.Random, lane: Lane, carriers: list[CarrierProfile]) -> CarrierProfile:
    preferred = [c for c in carriers if lane in c.preferred_lanes]
    if preferred and rng.random() < 0.70:
        return rng.choice(preferred)
    # Regular carriers are still more likely to get picked up off their
    # preferred lanes than occasional ones (a broker's go-to carriers get
    # called more often generally), but nothing is ever off-limits --
    # this is part of what creates organic lane-history/deadhead tension.
    weights = [3.0 if c.tier == "regular" else 1.0 for c in carriers]
    return rng.choices(carriers, weights=weights, k=1)[0]


def _end_of_day_utc(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


def _random_time_on(rng: random.Random, d: date) -> datetime:
    return datetime(d.year, d.month, d.day, rng.randint(6, 22), rng.randint(0, 59), rng.randint(0, 59), tzinfo=timezone.utc)


def _clamped_advance(dt: datetime, delta: timedelta, not_after: datetime) -> datetime:
    """Advances dt by delta, but never past `not_after`. Since every call
    site only ever advances forward from an already-clamped dt, repeated
    clamping keeps the whole sequence non-decreasing even in worst-case
    random draws -- this is what guarantees a historical load's lifecycle
    can never appear to complete in the future relative to `today`,
    without having to hand-tune every random range's bounds to avoid it."""
    return min(dt + delta, not_after)


def _generate_load(
    rng: random.Random,
    load_index: int,
    config: WorldConfig,
    lane: Lane,
    created_date: date,
    is_current: bool,
    customers: list[CustomerProfile],
    carriers: list[CarrierProfile],
    lane_base_rate: dict[Lane, Decimal],
) -> WorldLoad:
    origin = _pick_zip_in_market_area(rng, lane.origin_market_area)
    destination = _pick_zip_in_market_area(rng, lane.destination_market_area)
    distance = haversine_miles(origin.latitude, origin.longitude, destination.latitude, destination.longitude)

    equipment = _weighted_choice(rng, _EQUIPMENT_WEIGHTS)
    weight = Decimal(rng.randint(8000, 45000))
    customer = rng.choice(customers)

    base_rate = lane_base_rate.get(lane) or Decimal(str(round(rng.uniform(1.80, 2.80), 2)))
    noise = rng.gauss(1.0, 0.08)
    if rng.random() < 0.05:  # deliberate outlier -- rush premium or distressed/backhaul discount
        noise *= rng.uniform(1.4, 1.8) if rng.random() < 0.5 else rng.uniform(0.5, 0.7)
    noise = max(noise, 0.4)

    carrier_rate_per_mile = (base_rate * Decimal(str(round(noise, 4)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    carrier_rate_total = (carrier_rate_per_mile * distance).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    margin_multiplier = Decimal(str(round(rng.uniform(1.12, 1.25), 3)))
    customer_rate_total = (carrier_rate_total * margin_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    not_after = _end_of_day_utc(config.today)
    events: list[LoadEvent] = []

    created_dt = min(_random_time_on(rng, created_date), not_after)
    events.append(
        LoadEvent(timestamp=created_dt, status=LoadStatus.PLANNED, carrier_id=None, customer_rate_usd=None, carrier_rate_usd=None)
    )

    active_dt = _clamped_advance(created_dt, timedelta(hours=rng.uniform(1, 12)), not_after)
    events.append(
        LoadEvent(
            timestamp=active_dt, status=LoadStatus.ACTIVE, carrier_id=None,
            customer_rate_usd=customer_rate_total, carrier_rate_usd=None,
        )
    )

    if is_current:
        pickup_date = created_date + timedelta(days=rng.randint(1, 3))
        delivery_date = pickup_date + timedelta(days=max(1, int(distance / 500) + rng.randint(0, 2)))
        return WorldLoad(
            id=f"{config.broker_slug}-load-{load_index:05d}",
            customer_id=customer.id,
            lane=lane,
            origin_zip=origin.zip_code, origin_city=origin.city, origin_state=origin.state,
            destination_zip=destination.zip_code, destination_city=destination.city, destination_state=destination.state,
            equipment_type=equipment,
            weight_lbs=weight,
            distance_miles=distance,
            pickup_date=pickup_date,
            delivery_date=delivery_date,
            events=tuple(events),
        )

    carrier = _pick_carrier_for_lane(rng, lane, carriers)

    covered_dt = _clamped_advance(active_dt, timedelta(hours=rng.uniform(2, 40)), not_after)
    events.append(
        LoadEvent(
            timestamp=covered_dt, status=LoadStatus.COVERED, carrier_id=carrier.id,
            customer_rate_usd=customer_rate_total, carrier_rate_usd=carrier_rate_total,
        )
    )

    pickup_dt = _clamped_advance(covered_dt, timedelta(hours=rng.uniform(6, 40)), not_after)
    events.append(
        LoadEvent(
            timestamp=pickup_dt, status=LoadStatus.IN_TRANSIT, carrier_id=carrier.id,
            customer_rate_usd=customer_rate_total, carrier_rate_usd=carrier_rate_total,
        )
    )

    avg_speed_mph = rng.uniform(38, 55)
    transit_hours = float(distance) / avg_speed_mph + rng.uniform(2, 8)
    delivered_dt = _clamped_advance(pickup_dt, timedelta(hours=transit_hours), not_after)
    events.append(
        LoadEvent(
            timestamp=delivered_dt, status=LoadStatus.DELIVERED, carrier_id=carrier.id,
            customer_rate_usd=customer_rate_total, carrier_rate_usd=carrier_rate_total,
        )
    )

    completed_dt = _clamped_advance(delivered_dt, timedelta(days=rng.uniform(2, 6)), not_after)
    events.append(
        LoadEvent(
            timestamp=completed_dt, status=LoadStatus.COMPLETED, carrier_id=carrier.id,
            customer_rate_usd=customer_rate_total, carrier_rate_usd=carrier_rate_total,
        )
    )

    return WorldLoad(
        id=f"{config.broker_slug}-load-{load_index:05d}",
        customer_id=customer.id,
        lane=lane,
        origin_zip=origin.zip_code, origin_city=origin.city, origin_state=origin.state,
        destination_zip=destination.zip_code, destination_city=destination.city, destination_state=destination.state,
        equipment_type=equipment,
        weight_lbs=weight,
        distance_miles=distance,
        pickup_date=pickup_dt.date(),
        delivery_date=delivered_dt.date(),
        events=tuple(events),
    )


def generate_world(config: WorldConfig) -> World:
    rng = random.Random(config.seed)

    all_lanes = _all_possible_lanes()
    regional_lanes = [lane for lane in all_lanes if _lane_representative_distance(lane) <= _MAX_PRIMARY_LANE_DISTANCE_MILES]
    if len(regional_lanes) < config.num_primary_lanes + 1:
        raise ValueError(
            f"only {len(regional_lanes)} regional lane candidates available, "
            f"need {config.num_primary_lanes + 1} (primary + sparse) -- add more market areas or relax the distance cap"
        )
    rng.shuffle(regional_lanes)
    primary_lanes = regional_lanes[: config.num_primary_lanes]
    sparse_lane = regional_lanes[config.num_primary_lanes]
    chosen = set(primary_lanes) | {sparse_lane}
    tail_pool = [lane for lane in all_lanes if lane not in chosen]

    customer_names = generate_customer_names(rng, config.num_customers)
    customers = [
        CustomerProfile(id=f"{config.broker_slug}-cust-{i + 1:03d}", name=name)
        for i, name in enumerate(customer_names)
    ]

    num_regular = round(config.num_carriers * config.regular_carrier_fraction)
    carrier_names = generate_carrier_names(rng, config.num_carriers)
    used_mc: set[str] = set()
    used_dot: set[str] = set()
    carriers: list[CarrierProfile] = []
    for i, name in enumerate(carrier_names):
        tier = "regular" if i < num_regular else "occasional"
        home_market = rng.choice(_MARKET_AREAS)
        home_zip = _pick_zip_in_market_area(rng, home_market)
        preferred: tuple[Lane, ...] = ()
        if tier == "regular":
            k = min(rng.randint(1, 3), len(primary_lanes))
            preferred = tuple(rng.sample(primary_lanes, k=k))
        carriers.append(
            CarrierProfile(
                id=f"{config.broker_slug}-carrier-{i + 1:03d}",
                name=name,
                mc_number=generate_unique_number(rng, used_mc, 100000, 9999999),
                dot_number=generate_unique_number(rng, used_dot, 1000000, 9999999),
                phone=generate_phone_number(rng),
                home_city=home_zip.city,
                home_state=home_zip.state,
                home_zip=home_zip.zip_code,
                home_market_area=home_market,
                tier=tier,
                preferred_lanes=preferred,
            )
        )

    lane_base_rate: dict[Lane, Decimal] = {
        lane: Decimal(str(round(rng.uniform(1.80, 2.80), 2))) for lane in [*primary_lanes, sparse_lane]
    }

    cutoff_date = config.today - timedelta(days=config.uncovered_window_days)
    earliest_date = config.today - timedelta(days=config.num_days)

    num_remaining = config.target_loads - _FORCED_SPARSE_LANE_LOAD_COUNT
    num_current = round(num_remaining * ((config.uncovered_window_days + 1) / config.num_days))
    num_historical = num_remaining - num_current

    loads: list[WorldLoad] = []
    load_index = 0

    for _ in range(num_historical):
        load_index += 1
        created = date.fromordinal(rng.randint(earliest_date.toordinal(), (cutoff_date - timedelta(days=1)).toordinal()))
        lane = _draw_lane(rng, primary_lanes, tail_pool)
        loads.append(_generate_load(rng, load_index, config, lane, created, False, customers, carriers, lane_base_rate))

    for _ in range(num_current):
        load_index += 1
        created = date.fromordinal(rng.randint(cutoff_date.toordinal(), config.today.toordinal()))
        lane = _draw_lane(rng, primary_lanes, tail_pool)
        loads.append(_generate_load(rng, load_index, config, lane, created, True, customers, carriers, lane_base_rate))

    for _ in range(_FORCED_SPARSE_LANE_LOAD_COUNT):
        load_index += 1
        created = date.fromordinal(rng.randint(earliest_date.toordinal(), (cutoff_date - timedelta(days=1)).toordinal()))
        loads.append(_generate_load(rng, load_index, config, sparse_lane, created, False, customers, carriers, lane_base_rate))

    return World(
        broker_slug=config.broker_slug,
        broker_name=config.broker_name,
        carriers=tuple(carriers),
        customers=tuple(customers),
        loads=tuple(loads),
        primary_lanes=tuple(primary_lanes),
        sparse_lane=sparse_lane,
    )

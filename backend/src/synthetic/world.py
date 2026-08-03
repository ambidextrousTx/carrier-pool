import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from canonical.enums import EquipmentType, LoadStatus
from geo.distance import haversine_miles
from geo.lanes import Lane
from geo.reference_data import GEO_ZIPS, GeoZip, TEXAS_TRIANGLE_MARKET_AREAS
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

_MAX_PRIMARY_LANE_DISTANCE_MILES = Decimal("1500")
_FORCED_SPARSE_LANE_LOAD_COUNT = 2

# Real syncs happen on a schedule, not continuously. Four a day is enough
# to spread a load's lifecycle across several files without needing an
# absurd file count. Both generate_data.py and export.py key off this
# same constant so the window math can't drift between the two.
SYNCS_PER_DAY = 4


@dataclass(frozen=True)
class WorldConfig:
    broker_slug: str
    broker_name: str
    seed: int
    today: date  # day 11 -- the day fresh, uncovered loads appear
    num_history_days: int = 10  # days 1..10, all synced incrementally
    target_history_loads: int = 150
    num_new_loads_day11: int = 22
    num_primary_lanes: int = 8
    num_carriers: int = 30
    regular_carrier_fraction: float = 0.4
    num_customers: int = 20
    # Probabilities are evaluated independently per load and can stack
    # (a load can get a reassignment AND a later money correction) --
    # that's realistic, corrections aren't mutually exclusive events.
    money_correction_probability: float = 0.15
    reassignment_probability: float = 0.06
    field_correction_probability: float = 0.10


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
class FieldCorrection:
    """A data-entry fix to a field that isn't part of the status/money
    lifecycle -- weight, equipment, or a rescheduled date. Modeled
    separately from LoadEvent because these aren't business events with
    their own status, they're patches applied on top of whatever the
    load's status already is."""

    timestamp: datetime
    field: str  # "weight_lbs" | "equipment_type" | "pickup_date" | "delivery_date"
    new_value: Any


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
    created_day: int  # 1..11, which day this load first appeared
    events: tuple[LoadEvent, ...]
    corrections: tuple[FieldCorrection, ...] = ()

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

    def latest_event_as_of(self, cutoff: datetime) -> LoadEvent | None:
        matching = [e for e in self.events if e.timestamp <= cutoff]
        return matching[-1] if matching else None

    def status_as_of(self, cutoff: datetime) -> LoadStatus | None:
        e = self.latest_event_as_of(cutoff)
        return e.status if e else None

    def assigned_carrier_id_as_of(self, cutoff: datetime) -> str | None:
        e = self.latest_event_as_of(cutoff)
        return e.carrier_id if e else None

    def customer_rate_as_of(self, cutoff: datetime) -> Decimal | None:
        e = self.latest_event_as_of(cutoff)
        return e.customer_rate_usd if e else None

    def carrier_rate_as_of(self, cutoff: datetime) -> Decimal | None:
        e = self.latest_event_as_of(cutoff)
        return e.carrier_rate_usd if e else None

    def has_activity_in_window(self, window_start: datetime, window_end: datetime) -> bool:
        event_hit = any(window_start <= e.timestamp < window_end for e in self.events)
        correction_hit = any(window_start <= c.timestamp < window_end for c in self.corrections)
        return event_hit or correction_hit

    def _field_as_of(self, field: str, cutoff: datetime, base: Any) -> Any:
        applicable = [c for c in self.corrections if c.field == field and c.timestamp <= cutoff]
        if not applicable:
            return base
        return max(applicable, key=lambda c: c.timestamp).new_value

    def weight_lbs_as_of(self, cutoff: datetime) -> Decimal:
        return self._field_as_of("weight_lbs", cutoff, self.weight_lbs)

    def equipment_type_as_of(self, cutoff: datetime) -> EquipmentType:
        return self._field_as_of("equipment_type", cutoff, self.equipment_type)

    def pickup_date_as_of(self, cutoff: datetime) -> date:
        return self._field_as_of("pickup_date", cutoff, self.pickup_date)

    def delivery_date_as_of(self, cutoff: datetime) -> date:
        return self._field_as_of("delivery_date", cutoff, self.delivery_date)


@dataclass(frozen=True)
class World:
    broker_slug: str
    broker_name: str
    carriers: tuple[CarrierProfile, ...]
    customers: tuple[CustomerProfile, ...]
    loads: tuple[WorldLoad, ...]  # days 1-10 history + day-11 fresh loads, all together
    primary_lanes: tuple[Lane, ...]
    sparse_lane: Lane
    history_start_date: date  # day 1
    history_end_date: date  # day 10
    history_cutoff: datetime  # start of day 11, UTC -- exclusive upper bound for history events
    day11_date: date  # config.today


def sync_window_bounds(world: World, day_number: int, sync_number: int) -> tuple[datetime, datetime]:
    """1-indexed day_number (1..11) and sync_number (1..SYNCS_PER_DAY) ->
    half-open [window_start, window_end) as UTC datetimes. Day 11's
    windows fall out of the same formula as days 1-10 -- no special
    casing needed, which is also what keeps world.history_cutoff (start
    of day 11) exactly equal to sync_window_bounds(11, 1)[0]."""
    day_date = world.history_start_date + timedelta(days=day_number - 1)
    day_start = datetime.combine(day_date, time.min, tzinfo=timezone.utc)
    hours_per_sync = 24 // SYNCS_PER_DAY
    window_start = day_start + timedelta(hours=hours_per_sync * (sync_number - 1))
    window_end = day_start + timedelta(hours=hours_per_sync * sync_number)
    return window_start, window_end


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
    weights = [3.0 if c.tier == "regular" else 1.0 for c in carriers]
    return rng.choices(carriers, weights=weights, k=1)[0]


def _random_time_on(rng: random.Random, d: date) -> datetime:
    return datetime(d.year, d.month, d.day, rng.randint(0, 23), rng.randint(0, 59), rng.randint(0, 59), tzinfo=timezone.utc)


def _price_load(rng: random.Random, lane: Lane, distance: Decimal, lane_base_rate: dict[Lane, Decimal]) -> tuple[Decimal, Decimal]:
    """Returns (carrier_rate_total, customer_rate_total). Pulled out of
    _generate_load so carrier reassignment can reuse it to reprice the
    load for the new carrier."""
    base_rate = lane_base_rate.get(lane) or Decimal(str(round(rng.uniform(1.80, 2.80), 2)))
    noise = rng.gauss(1.0, 0.08)
    if rng.random() < 0.05:
        noise *= rng.uniform(1.4, 1.8) if rng.random() < 0.5 else rng.uniform(0.5, 0.7)
    noise = max(noise, 0.4)
    carrier_rate_per_mile = (base_rate * Decimal(str(round(noise, 4)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    carrier_rate_total = (carrier_rate_per_mile * distance).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    margin_multiplier = Decimal(str(round(rng.uniform(1.12, 1.25), 3)))
    customer_rate_total = (carrier_rate_total * margin_multiplier).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return carrier_rate_total, customer_rate_total


def _generate_natural_lifecycle(
    rng: random.Random,
    created_dt: datetime,
    carrier: CarrierProfile,
    customer_rate_total: Decimal,
    carrier_rate_total: Decimal,
    distance: Decimal,
) -> list[LoadEvent]:
    """The load's full, un-truncated story -- every load gets this whether
    or not it'll end up fitting inside the history window. Truncation
    (not clamping) is applied by the caller afterward."""
    events = [LoadEvent(created_dt, LoadStatus.PLANNED, None, None, None)]

    active_dt = created_dt + timedelta(hours=rng.uniform(1, 12))
    events.append(LoadEvent(active_dt, LoadStatus.ACTIVE, None, customer_rate_total, None))

    covered_dt = active_dt + timedelta(hours=rng.uniform(2, 40))
    events.append(LoadEvent(covered_dt, LoadStatus.COVERED, carrier.id, customer_rate_total, carrier_rate_total))

    pickup_dt = covered_dt + timedelta(hours=rng.uniform(6, 40))
    events.append(LoadEvent(pickup_dt, LoadStatus.IN_TRANSIT, carrier.id, customer_rate_total, carrier_rate_total))

    avg_speed_mph = rng.uniform(38, 55)
    transit_hours = float(distance) / avg_speed_mph + rng.uniform(2, 8)
    delivered_dt = pickup_dt + timedelta(hours=transit_hours)
    events.append(LoadEvent(delivered_dt, LoadStatus.DELIVERED, carrier.id, customer_rate_total, carrier_rate_total))

    # Tightened from the original 2-6 day invoicing lag to 1-4 days --
    # otherwise almost nothing created after day ~4 would have a
    # realistic chance of reaching COMPLETED inside a 10-day window, and
    # "completed" would stop being a meaningful majority case.
    completed_dt = delivered_dt + timedelta(days=rng.uniform(1, 4))
    events.append(LoadEvent(completed_dt, LoadStatus.COMPLETED, carrier.id, customer_rate_total, carrier_rate_total))

    return events


def _maybe_append_reassignment(
    rng: random.Random,
    events: list[LoadEvent],
    lane: Lane,
    distance: Decimal,
    lane_base_rate: dict[Lane, Decimal],
    carriers: list[CarrierProfile],
    probability: float,
) -> tuple[list[LoadEvent], CarrierProfile | None]:
    """Swaps the carrier on a load that's still COVERED (pre-pickup) --
    the original carrier fell through and a different one got booked.
    Only fires against the natural (un-truncated) chain; whether the
    resulting event survives truncation is decided later. Returns the new
    carrier if a swap happened, so the caller can keep using it for the
    rest of the natural chain."""
    covered_idx = next((i for i, e in enumerate(events) if e.status == LoadStatus.COVERED), None)
    if covered_idx is None or rng.random() >= probability:
        return events, None

    original = events[covered_idx]
    candidates = [c for c in carriers if c.id != original.carrier_id]
    if not candidates:
        return events, None
    new_carrier = _pick_carrier_for_lane(rng, lane, candidates)
    new_carrier_rate, _ = _price_load(rng, lane, distance, lane_base_rate)

    reassign_ts = original.timestamp + timedelta(hours=rng.uniform(2, 20))
    reassignment_event = LoadEvent(
        timestamp=reassign_ts, status=LoadStatus.COVERED, carrier_id=new_carrier.id,
        customer_rate_usd=original.customer_rate_usd, carrier_rate_usd=new_carrier_rate,
    )
    # Insert right after the original COVERED event, before IN_TRANSIT
    # onward, and re-timestamp everything downstream to stay after it --
    # the shift is small (a few hours) so it doesn't meaningfully change
    # when the load reaches later stages.
    shift = reassign_ts - original.timestamp
    rest = [
        LoadEvent(e.timestamp + shift, e.status, new_carrier.id, e.customer_rate_usd, e.carrier_rate_usd)
        for e in events[covered_idx + 1 :]
    ]
    new_events = [*events[: covered_idx + 1], reassignment_event, *rest]
    return new_events, new_carrier


def _maybe_append_money_correction(rng: random.Random, events: list[LoadEvent], probability: float) -> list[LoadEvent]:
    """A later sync restates an already-recorded total -- matches
    FreightFlow/BrokerOS's documented 'silently restated' totals. Always
    appended after whatever the current last event is, so it always lands
    chronologically last regardless of what else has already happened."""
    if rng.random() >= probability:
        return events
    last = events[-1]
    if last.status == LoadStatus.PLANNED:
        return events  # nothing priced yet to correct

    correct_carrier_side = last.carrier_rate_usd is not None and rng.random() < 0.6
    new_customer_rate, new_carrier_rate = last.customer_rate_usd, last.carrier_rate_usd
    if correct_carrier_side:
        adj = Decimal(str(round(rng.uniform(0.85, 1.15), 4)))
        new_carrier_rate = (last.carrier_rate_usd * adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        adj = Decimal(str(round(rng.uniform(0.90, 1.10), 4)))
        new_customer_rate = (last.customer_rate_usd * adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    correction_ts = last.timestamp + timedelta(hours=rng.uniform(4, 48))
    return [*events, LoadEvent(correction_ts, last.status, last.carrier_id, new_customer_rate, new_carrier_rate)]


def _maybe_field_corrections(
    rng: random.Random, created_dt: datetime, weight: Decimal, probability: float
) -> tuple[FieldCorrection, ...]:
    if rng.random() >= probability:
        return ()
    field = rng.choice(["weight_lbs", "equipment_type", "pickup_date"])
    ts = created_dt + timedelta(hours=rng.uniform(2, 30))
    if field == "weight_lbs":
        # A mis-keyed weight corrected after the fact -- kept in the same
        # plausible range as the original, not a wild swing.
        new_value: Any = Decimal(rng.randint(8000, 45000))
    elif field == "equipment_type":
        new_value = _weighted_choice(rng, _EQUIPMENT_WEIGHTS)
    else:
        new_value = None  # filled in by caller, which knows the load's pickup_date
    return (FieldCorrection(ts, field, new_value),)


def generate_world(config: WorldConfig) -> World:
    rng = random.Random(config.seed)

    history_start_date = config.today - timedelta(days=config.num_history_days)
    history_end_date = config.today - timedelta(days=1)
    history_cutoff = datetime.combine(config.today, time.min, tzinfo=timezone.utc)

    all_lanes = _all_possible_lanes()

    # Primary (repeat) lanes are drawn ONLY from Texas Triangle-internal
    # pairs -- this is what actually makes "loads move within the Texas
    # Triangle" true of the generated data, not just true of the zip
    # table. Non-TX lanes are still reachable, but only via the one-off
    # tail pool, same as any other out-of-territory booking a real broker
    # occasionally takes.
    tx_lanes = [
        lane for lane in all_lanes
        if lane.origin_market_area in TEXAS_TRIANGLE_MARKET_AREAS
        and lane.destination_market_area in TEXAS_TRIANGLE_MARKET_AREAS
    ]
    if len(tx_lanes) < config.num_primary_lanes + 1:
        raise ValueError(
            f"only {len(tx_lanes)} Texas Triangle-internal lane candidates available, "
            f"need {config.num_primary_lanes + 1} (primary + sparse) -- add more TX market areas "
            f"or lower num_primary_lanes"
        )
    rng.shuffle(tx_lanes)
    primary_lanes = tx_lanes[: config.num_primary_lanes]
    sparse_lane = tx_lanes[config.num_primary_lanes]
    chosen = set(primary_lanes) | {sparse_lane}
    # Deliberately NOT capped at _MAX_PRIMARY_LANE_DISTANCE_MILES -- the
    # tail pool is where the occasional genuine long-haul one-off lives,
    # and it also picks up any leftover TX-internal pairs that didn't get
    # promoted to primary/sparse, so "thin" lanes come in both TX and
    # non-TX flavors.
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

    def build_historical_load(load_index: int, lane: Lane, forced_created_date: date | None = None) -> WorldLoad:
        origin = _pick_zip_in_market_area(rng, lane.origin_market_area)
        destination = _pick_zip_in_market_area(rng, lane.destination_market_area)
        distance = haversine_miles(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        equipment = _weighted_choice(rng, _EQUIPMENT_WEIGHTS)
        weight = Decimal(rng.randint(8000, 45000))
        customer = rng.choice(customers)

        if forced_created_date is not None:
            created_date = forced_created_date
        else:
            # Skewed toward the earlier days on purpose: a load created on
            # day 9 or 10 has almost no realistic chance of reaching
            # COMPLETED before the day-11 cutoff (worst case alone is
            # close to a week), so a uniform draw would leave
            # predict_rate's comp pool thinner than it should be.
            # triangular(...) has zero density right at the far endpoint
            # though, which is why every day's floor is force-seeded
            # separately below rather than relied on from this draw.
            day_offset = int(rng.triangular(0, config.num_history_days - 1, 2))
            created_date = history_start_date + timedelta(days=day_offset)
        created_dt = _random_time_on(rng, created_date)

        carrier = _pick_carrier_for_lane(rng, lane, carriers)
        carrier_rate_total, customer_rate_total = _price_load(rng, lane, distance, lane_base_rate)

        events = _generate_natural_lifecycle(rng, created_dt, carrier, customer_rate_total, carrier_rate_total, distance)
        events, reassigned_to = _maybe_append_reassignment(
            rng, events, lane, distance, lane_base_rate, carriers, config.reassignment_probability
        )
        final_carrier = reassigned_to or carrier
        events = _maybe_append_money_correction(rng, events, config.money_correction_probability)

        # Scheduled pickup/delivery dates are known at booking time, from
        # the natural (un-truncated) chain -- a load that's still just
        # COVERED as of the cutoff still has a real scheduled pickup date,
        # it just hasn't happened yet.
        in_transit_event = next(e for e in events if e.status == LoadStatus.IN_TRANSIT)
        delivered_event = next(e for e in events if e.status == LoadStatus.DELIVERED)
        pickup_date = in_transit_event.timestamp.date()
        delivery_date = delivered_event.timestamp.date()

        corrections = _maybe_field_corrections(rng, created_dt, weight, config.field_correction_probability)
        corrections = tuple(
            c if c.field != "pickup_date" else FieldCorrection(c.timestamp, c.field, pickup_date + timedelta(days=rng.choice([-1, 1, 2])))
            for c in corrections
        )

        # Truncate -- this is what turns "the load's whole future" into
        # "what a sync running through day 10 would actually have seen."
        truncated_events = tuple(e for e in events if e.timestamp < history_cutoff) or (events[0],)
        truncated_corrections = tuple(c for c in corrections if c.timestamp < history_cutoff)

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
            created_day=(created_date - history_start_date).days + 1,
            events=truncated_events,
            corrections=truncated_corrections,
        )

    loads: list[WorldLoad] = []
    load_index = 0

    num_remaining = config.target_history_loads - _FORCED_SPARSE_LANE_LOAD_COUNT

    # Guarantee every one of the 10 history days gets at least one
    # genuinely new load (original requirement #7: "each day, each broker
    # gets new loads") -- the skewed draw below is realistic for volume
    # but its density is ~0 right at day 10, so day coverage can't be left
    # to chance.
    for day_offset in range(config.num_history_days):
        load_index += 1
        forced_date = history_start_date + timedelta(days=day_offset)
        lane = _draw_lane(rng, primary_lanes, tail_pool)
        loads.append(build_historical_load(load_index, lane, forced_created_date=forced_date))

    for _ in range(num_remaining - config.num_history_days):
        load_index += 1
        lane = _draw_lane(rng, primary_lanes, tail_pool)
        loads.append(build_historical_load(load_index, lane))
    for _ in range(_FORCED_SPARSE_LANE_LOAD_COUNT):
        load_index += 1
        loads.append(build_historical_load(load_index, sparse_lane))

    # Identify carriers genuinely still busy as of the history cutoff --
    # used below to deliberately place at least one day-11 load where the
    # busy-carrier exclusion in rank_carriers has something real to do.
    busy_regular_carrier = next(
        (
            c for c in carriers
            if c.tier == "regular" and c.preferred_lanes
            and any(
                ld.assigned_carrier_id == c.id
                and ld.final_status in (LoadStatus.COVERED, LoadStatus.IN_TRANSIT, LoadStatus.DELIVERED)
                for ld in loads
            )
        ),
        None,
    )

    for day11_idx in range(config.num_new_loads_day11):
        load_index += 1
        if day11_idx == 0 and busy_regular_carrier is not None:
            lane = rng.choice(busy_regular_carrier.preferred_lanes)
        else:
            lane = _draw_lane(rng, primary_lanes, tail_pool)

        origin = _pick_zip_in_market_area(rng, lane.origin_market_area)
        destination = _pick_zip_in_market_area(rng, lane.destination_market_area)
        distance = haversine_miles(origin.latitude, origin.longitude, destination.latitude, destination.longitude)
        equipment = _weighted_choice(rng, _EQUIPMENT_WEIGHTS)
        weight = Decimal(rng.randint(8000, 45000))
        customer = rng.choice(customers)

        created_dt = _random_time_on(rng, config.today)
        _, customer_rate_total = _price_load(rng, lane, distance, lane_base_rate)

        pickup_date = config.today + timedelta(days=rng.randint(1, 3))
        delivery_date = pickup_date + timedelta(days=max(1, int(distance / 500) + rng.randint(0, 2)))

        events = (
            LoadEvent(created_dt, LoadStatus.PLANNED, None, None, None),
            LoadEvent(created_dt + timedelta(hours=rng.uniform(1, 4)), LoadStatus.ACTIVE, None, customer_rate_total, None),
        )

        loads.append(
            WorldLoad(
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
                created_day=config.num_history_days + 1,
                events=events,
            )
        )

    return World(
        broker_slug=config.broker_slug,
        broker_name=config.broker_name,
        carriers=tuple(carriers),
        customers=tuple(customers),
        loads=tuple(loads),
        primary_lanes=tuple(primary_lanes),
        sparse_lane=sparse_lane,
        history_start_date=history_start_date,
        history_end_date=history_end_date,
        history_cutoff=history_cutoff,
        day11_date=config.today,
    )

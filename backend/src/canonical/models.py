from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from canonical.enums import EquipmentType, LoadStatus, RateSide, SourceSystem


class Stop(BaseModel):
    sequence: int  # 1-based order along the route
    is_pickup: bool
    is_dropoff: bool
    city: str
    state: str
    zip_code: str | None = None

    # Date-level granularity, populated for every source regardless of
    # whether they give us a finer window (lets "loads picking up on date
    # X" queries work uniformly across sources).
    scheduled_date: date | None = None

    # True time-of-day window, only populated when the source actually
    # provides one (FreightFlow only, as of the schemas we've seen).
    scheduled_window_start: datetime | None = None
    scheduled_window_end: datetime | None = None

    # Sources track different actual-time semantics per stop -- FreightFlow
    # gives departure only, HaulDesk gives departure-from-pickup and
    # arrival-at-delivery (not symmetric), BrokerOS gives arrival only.
    # Both fields are here so each adapter populates whichever it actually has.
    actual_arrival_at: datetime | None = None
    actual_departure_at: datetime | None = None


class RateLineItem(BaseModel):
    source_native_id: str  # stable ID from the source; makes append-only ingestion idempotent
    side: RateSide
    code: str
    amount_usd: Decimal  # can be negative (correction/credit)
    source_created_at: datetime


class Carrier(BaseModel):
    source_system: SourceSystem
    source_native_id: str
    name: str
    mc_number: str | None = None
    dot_number: str | None = None
    phone: str | None = None
    home_city: str | None = None
    home_state: str | None = None


class Customer(BaseModel):
    source_system: SourceSystem
    source_native_id: str
    name: str


class Load(BaseModel):
    source_system: SourceSystem
    source_native_id: str  # stable, unique within this source
    source_native_number: str | None = None  # human-readable label, if distinct from the id

    status: LoadStatus
    source_status_raw: str  # original status text/code, preserved for audit

    customer_source_native_id: str
    carrier_source_native_id: str | None = None  # null until a carrier is booked

    equipment_type: EquipmentType
    distance_miles: Decimal | None = None
    weight_lbs: Decimal | None = None

    # The current, authoritative totals -- directly copied from sources
    # that expose a mutable total (FreightFlow, BrokerOS). Left as None
    # for sources with no single authoritative total field (HaulDesk):
    # there, the true total is SUM(rate_line_items) across every synced
    # file that has ever mentioned this load, which this adapter -- given
    # only one file at a time -- cannot know. Computing that running total
    # is the ingestion/persistence layer's job, not the adapter's.
    customer_rate_total_usd: Decimal | None = None
    carrier_rate_total_usd: Decimal | None = None

    # Whatever NEW rate line items this file contributes for this load.
    # Empty for sources that don't expose line-item detail.
    rate_line_items: list[RateLineItem] = []

    stops: list[Stop]

    source_created_at: datetime
    source_last_modified_at: datetime


class AdapterResult(BaseModel):
    """What one raw load record from a sync file normalizes into. `carrier`
    is None either because no carrier is booked yet, or because this file
    references a carrier by id without including that carrier's details
    (HaulDesk only redefines a carrier row when it's new or changed) -- in
    the latter case `load.carrier_source_native_id` is still set, it's just
    that this file has nothing new to say about the carrier itself."""

    load: Load
    customer: Customer
    carrier: Carrier | None = None

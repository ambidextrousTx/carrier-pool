from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from adapters.units import lbs_to_kg, miles_to_km
from canonical.enums import EquipmentType, LoadStatus
from synthetic.world import CarrierProfile, CustomerProfile, World, WorldLoad

_CENTRAL = ZoneInfo("America/Chicago")


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _naive_central(dt: datetime) -> str:
    return dt.astimezone(_CENTRAL).strftime("%Y-%m-%d %H:%M:%S")


def _first_timestamp_for_status_as_of(load: WorldLoad, status: LoadStatus, as_of: datetime) -> datetime | None:
    """The first time a load genuinely reached `status` (i.e. the real
    physical event, not a later correction that happens to reuse the same
    status label), as observed as of `as_of`."""
    return next((e.timestamp for e in load.events if e.status == status and e.timestamp <= as_of), None)


class _SequentialIds:
    """Assigns stable sequential numeric-looking ids to world string ids,
    in first-appearance order. Must live in ExportState (not be
    recreated per sync call) so the same entity gets the same id in every
    file it appears in across a broker's whole sync history."""

    def __init__(self, start: int):
        self._next = start
        self._assigned: dict[str, int] = {}

    def get(self, world_id: str) -> int:
        if world_id not in self._assigned:
            self._assigned[world_id] = self._next
            self._next += 1
        return self._assigned[world_id]


@dataclass
class ExportState:
    """Cross-sync-call state for one broker's export stream. Threaded
    through every export_*_sync call for that broker, in chronological
    order, so id numbering stays stable across files and so HaulDesk's
    'carrier only redefined when new' behavior is real rather than
    accidental. Each broker gets its own fresh ExportState -- never share
    one across brokers."""

    ff_shipment_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(127_000_000))
    ff_customer_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(880_000))
    ff_carrier_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(830_000))

    hd_customer_codes: _SequentialIds = field(default_factory=lambda: _SequentialIds(1))
    hd_carrier_refs: _SequentialIds = field(default_factory=lambda: _SequentialIds(66_000))
    hd_rate_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(910_000))
    hd_carriers_sent: set[str] = field(default_factory=set)

    bos_load_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(1))
    bos_account_ids: _SequentialIds = field(default_factory=lambda: _SequentialIds(1))
    bos_location_ids: dict[str, str] = field(default_factory=dict)


def new_export_state() -> ExportState:
    return ExportState()


# =============================================================================
# FreightFlow
# =============================================================================

_FF_STATUS = {
    LoadStatus.PLANNED: "Quoting",
    LoadStatus.ACTIVE: "Booking",
    LoadStatus.COVERED: "Dispatched",
    LoadStatus.IN_TRANSIT: "En Route",
    LoadStatus.DELIVERED: "Delivered",
    LoadStatus.COMPLETED: "Completed",
}
_FF_EQUIPMENT = {
    EquipmentType.DRY_VAN: "53 ft Van | Dry",
    EquipmentType.REEFER: "53 ft Van | Reefer",
    EquipmentType.FLATBED: "48 ft Flatbed",
}


def _ff_stop(city: str, state: str, zip_code: str, on_date, stop_type: str, actual_departure) -> dict:
    ready = datetime(on_date.year, on_date.month, on_date.day, 8, 0, 0, tzinfo=timezone.utc)
    close = datetime(on_date.year, on_date.month, on_date.day, 16, 0, 0, tzinfo=timezone.utc)
    return {
        "stopType": stop_type,
        "city": city,
        "state": state,
        "zipCode": zip_code,
        "estimatedReadyDateTime": _utc_iso(ready),
        "estimatedCloseDateTime": _utc_iso(close),
        "actualDepartureDateTime": _utc_iso(actual_departure) if actual_departure else None,
    }


def export_freightflow_sync(world: World, window_start: datetime, window_end: datetime, state: ExportState) -> dict | None:
    carrier_by_id = {c.id: c for c in world.carriers}
    customer_by_id = {c.id: c for c in world.customers}
    as_of = window_end

    loads_out = []
    for load in world.loads:
        if not load.has_activity_in_window(window_start, window_end):
            continue
        status = load.status_as_of(as_of)
        if status is None:
            continue

        carrier_id = load.assigned_carrier_id_as_of(as_of)
        carrier: CarrierProfile | None = carrier_by_id.get(carrier_id) if carrier_id else None
        customer = customer_by_id[load.customer_id]

        pickup_departure = _first_timestamp_for_status_as_of(load, LoadStatus.IN_TRANSIT, as_of)
        weight = load.weight_lbs_as_of(as_of)
        equipment = load.equipment_type_as_of(as_of)
        pickup_date = load.pickup_date_as_of(as_of)
        delivery_date = load.delivery_date_as_of(as_of)
        customer_rate = load.customer_rate_as_of(as_of)
        carrier_rate = load.carrier_rate_as_of(as_of)

        loads_out.append(
            {
                "shipmentId": state.ff_shipment_ids.get(load.id),
                "status": _FF_STATUS[status],
                "mileage": float(load.distance_miles),
                "totalSell": float(customer_rate) if customer_rate is not None else None,
                "totalBuy": float(carrier_rate) if carrier_rate is not None else None,
                "customer": {"customerId": state.ff_customer_ids.get(customer.id), "name": customer.name},
                "carrier": None
                if carrier is None
                else {
                    "carrierMasterId": state.ff_carrier_ids.get(carrier.id),
                    "name": carrier.name,
                    "mcNumber": carrier.mc_number,
                    "dotNumber": carrier.dot_number,
                    "phoneNumber": f"+1{carrier.phone}",
                },
                "equipment": _FF_EQUIPMENT[equipment],
                "weightTotal": float(weight),
                "stops": [
                    _ff_stop(load.origin_city, load.origin_state, load.origin_zip, pickup_date, "First Pickup", pickup_departure),
                    _ff_stop(load.destination_city, load.destination_state, load.destination_zip, delivery_date, "Last Drop", None),
                ],
                "createdDate": _utc_iso(load.created_at),
                "lastModifiedDate": _utc_iso(load.latest_event_as_of(as_of).timestamp),
            }
        )

    if not loads_out:
        return None
    return {"syncedAt": _utc_iso(window_end), "loads": loads_out}


# =============================================================================
# HaulDesk
# =============================================================================

_HD_STATUS = {
    LoadStatus.PLANNED: 10,
    LoadStatus.ACTIVE: 20,
    LoadStatus.COVERED: 30,
    LoadStatus.IN_TRANSIT: 40,
    LoadStatus.DELIVERED: 50,
    LoadStatus.COMPLETED: 90,
}
_HD_EQUIPMENT = {EquipmentType.DRY_VAN: "V", EquipmentType.REEFER: "R", EquipmentType.FLATBED: "F"}


def _hd_rate_line_items(load: WorldLoad) -> list[tuple[datetime, str, Decimal]]:
    """(timestamp, side, delta_amount) for every event that introduces or
    changes a rate side, walked once against the load's full (already
    history-truncated) event chain. 'bill' first appears at ACTIVE; 'pay'
    first appears at COVERED. A later correction or reassignment that
    changes either side contributes another delta line item -- append-
    only, matching HaulDesk's real contract; corrections show up as a
    second (possibly negative) line item, never a rewrite of the first."""
    items: list[tuple[datetime, str, Decimal]] = []
    last_bill: Decimal | None = None
    last_pay: Decimal | None = None
    for e in load.events:
        if e.customer_rate_usd is not None and e.customer_rate_usd != last_bill:
            delta = e.customer_rate_usd if last_bill is None else (e.customer_rate_usd - last_bill)
            items.append((e.timestamp, "bill", delta))
            last_bill = e.customer_rate_usd
        if e.carrier_rate_usd is not None and e.carrier_rate_usd != last_pay:
            delta = e.carrier_rate_usd if last_pay is None else (e.carrier_rate_usd - last_pay)
            items.append((e.timestamp, "pay", delta))
            last_pay = e.carrier_rate_usd
    return items


def export_hauldesk_sync(world: World, window_start: datetime, window_end: datetime, state: ExportState) -> dict | None:
    carrier_by_id = {c.id: c for c in world.carriers}
    customer_by_id = {c.id: c for c in world.customers}
    as_of = window_end

    loads_out = []
    new_carriers = []
    rates_out = []

    for load in world.loads:
        if not load.has_activity_in_window(window_start, window_end):
            continue
        status = load.status_as_of(as_of)
        if status is None:
            continue

        carrier_id = load.assigned_carrier_id_as_of(as_of)
        carrier: CarrierProfile | None = carrier_by_id.get(carrier_id) if carrier_id else None
        customer = customer_by_id[load.customer_id]

        pickup_departure = _first_timestamp_for_status_as_of(load, LoadStatus.IN_TRANSIT, as_of)
        delivery_arrival = _first_timestamp_for_status_as_of(load, LoadStatus.DELIVERED, as_of)
        weight = load.weight_lbs_as_of(as_of)
        equipment = load.equipment_type_as_of(as_of)
        pickup_date = load.pickup_date_as_of(as_of)
        delivery_date = load.delivery_date_as_of(as_of)

        loads_out.append(
            {
                "load_num": load.id.upper(),
                "status_code": _HD_STATUS[status],
                "customer_code": f"C-{state.hd_customer_codes.get(customer.id):04d}",
                "customer_name": customer.name,
                "carrier_ref": state.hd_carrier_refs.get(carrier.id) if carrier else None,
                "equip": _HD_EQUIPMENT[equipment],
                "weight_kg": float(lbs_to_kg(weight)),
                "dist_km": float(miles_to_km(load.distance_miles)),
                "pu_city": load.origin_city, "pu_state": load.origin_state, "pu_zip": load.origin_zip,
                "pu_date": pickup_date.isoformat(),
                "pu_departed_at": _naive_central(pickup_departure) if pickup_departure else None,
                "del_city": load.destination_city, "del_state": load.destination_state, "del_zip": load.destination_zip,
                "del_date": delivery_date.isoformat(),
                "del_arrived_at": _naive_central(delivery_arrival) if delivery_arrival else None,
                "entered_at": _naive_central(load.created_at),
                "updated_at": _naive_central(load.latest_event_as_of(as_of).timestamp),
            }
        )

        # Real HaulDesk only redefines a carrier in the `carriers` array
        # the first time it's referenced, or when something about it
        # changes -- since our carriers never change fields after
        # creation, "first time referenced, ever" is the whole rule.
        if carrier is not None and carrier.id not in state.hd_carriers_sent:
            state.hd_carriers_sent.add(carrier.id)
            new_carriers.append(
                {
                    "carrier_id": state.hd_carrier_refs.get(carrier.id),
                    "carrier_name": carrier.name,
                    "mc_no": carrier.mc_number,
                    "dot_no": carrier.dot_number,
                    "home_city": carrier.home_city,
                    "home_state": carrier.home_state,
                    "phone": carrier.phone,
                }
            )

        for ts, side, delta in _hd_rate_line_items(load):
            if window_start <= ts < window_end:
                rates_out.append(
                    {
                        "rate_id": state.hd_rate_ids.get(f"{load.id}-{side}-{ts.isoformat()}"),
                        "load_num": load.id.upper(),
                        "side": side,
                        "code": "LINEHAUL",
                        "amount_usd": float(delta),
                        "created_at": _naive_central(ts),
                    }
                )

    if not loads_out:
        return None
    return {
        "synced_at": _naive_central(window_end),
        "loads": loads_out,
        "carriers": new_carriers,
        "rates": rates_out,
    }


# =============================================================================
# BrokerOS
# =============================================================================

_BOS_STATUS = {
    LoadStatus.PLANNED: "Quotes Requested",
    LoadStatus.ACTIVE: "Ready to Book",
    LoadStatus.COVERED: "Booked",
    LoadStatus.IN_TRANSIT: "In Transit",
    LoadStatus.DELIVERED: "Delivered",
    LoadStatus.COMPLETED: "Paid",
}
_BOS_EQUIPMENT = {EquipmentType.DRY_VAN: "Dry Van", EquipmentType.REEFER: "Reefer", EquipmentType.FLATBED: "Flatbed"}


def export_brokeros_sync(world: World, window_start: datetime, window_end: datetime, state: ExportState) -> dict | None:
    carrier_by_id = {c.id: c for c in world.carriers}
    customer_by_id = {c.id: c for c in world.customers}
    as_of = window_end

    referenced_records: dict = {}
    records = []

    def location_ref(zip_code: str, city: str, state_abbr: str) -> str:
        if zip_code not in state.bos_location_ids:
            state.bos_location_ids[zip_code] = f"LOC{len(state.bos_location_ids) + 1:015d}"
        ref_id = state.bos_location_ids[zip_code]
        referenced_records[ref_id] = {
            "type": "Location", "Name": f"{city} Hub",
            "bos__City__c": city, "bos__State__c": state_abbr, "bos__Postal_Code__c": zip_code,
        }
        return ref_id

    def account_ref(entity_id: str, kind: str, customer: CustomerProfile | None = None, carrier: CarrierProfile | None = None) -> str:
        key = f"{kind}:{entity_id}"
        ref_id = f"ACC{state.bos_account_ids.get(key):015d}"
        if customer is not None:
            referenced_records[ref_id] = {"type": "Account", "record_type": "Customer", "Name": customer.name}
        else:
            referenced_records[ref_id] = {
                "type": "Account", "record_type": "Carrier", "Name": carrier.name,
                "bos__MC_Number__c": carrier.mc_number, "bos__DOT_Number__c": carrier.dot_number,
                "bos__Phone__c": carrier.phone, "bos__City__c": carrier.home_city, "bos__State__c": carrier.home_state,
            }
        return ref_id

    for load in world.loads:
        if not load.has_activity_in_window(window_start, window_end):
            continue
        status = load.status_as_of(as_of)
        if status is None:
            continue

        carrier_id = load.assigned_carrier_id_as_of(as_of)
        carrier: CarrierProfile | None = carrier_by_id.get(carrier_id) if carrier_id else None
        customer = customer_by_id[load.customer_id]

        customer_ref = account_ref(customer.id, "cust", customer=customer)
        carrier_ref = account_ref(carrier.id, "carrier", carrier=carrier) if carrier else None

        weight = load.weight_lbs_as_of(as_of)
        equipment = load.equipment_type_as_of(as_of)
        pickup_date = load.pickup_date_as_of(as_of)
        delivery_date = load.delivery_date_as_of(as_of)
        customer_rate = load.customer_rate_as_of(as_of)
        carrier_rate = load.carrier_rate_as_of(as_of)

        origin_loc = location_ref(load.origin_zip, load.origin_city, load.origin_state)
        dest_loc = location_ref(load.destination_zip, load.destination_city, load.destination_state)

        pickup_arrival = _first_timestamp_for_status_as_of(load, LoadStatus.IN_TRANSIT, as_of)
        delivery_arrival = _first_timestamp_for_status_as_of(load, LoadStatus.DELIVERED, as_of)

        seq = state.bos_load_ids.get(load.id)
        records.append(
            {
                "Id": f"LOAD{seq:014d}",
                "Name": f"SHP{seq:07d}",
                "bos__Load_Status__c": _BOS_STATUS[status],
                "bos__Distance_Miles__c": float(load.distance_miles),
                "bos__Customer__c": customer_ref,
                "bos__Carrier__c": carrier_ref,
                "bos__Equipment_Type__c": _BOS_EQUIPMENT[equipment],
                "bos__Customer_Rate__c": float(customer_rate) if customer_rate is not None else None,
                "bos__Carrier_Rate__c": float(carrier_rate) if carrier_rate is not None else None,
                "bos__Stops__r": [
                    {
                        "bos__Number__c": 1.0, "bos__Is_Pickup__c": True, "bos__Is_Dropoff__c": False,
                        "bos__Location__c": origin_loc, "bos__Scheduled_Date__c": pickup_date.isoformat(),
                        "bos__Arrival_Time__c": _utc_iso(pickup_arrival) if pickup_arrival else None,
                    },
                    {
                        "bos__Number__c": 2.0, "bos__Is_Pickup__c": False, "bos__Is_Dropoff__c": True,
                        "bos__Location__c": dest_loc, "bos__Scheduled_Date__c": delivery_date.isoformat(),
                        "bos__Arrival_Time__c": _utc_iso(delivery_arrival) if delivery_arrival else None,
                    },
                ],
                "bos__Line_Items__r": [
                    {
                        "bos__Commodity__c": "General Freight",
                        "bos__Weight__c": float(weight),
                        "bos__Weight_Units__c": "lbs",
                        "bos__Pallet_Count__c": float(max(1, round(float(weight) / 1200))),
                    }
                ],
                "CreatedDate": _utc_iso(load.created_at),
                "LastModifiedDate": _utc_iso(load.latest_event_as_of(as_of).timestamp),
            }
        )

    if not records:
        return None
    return {"synced_at": _utc_iso(window_end), "records": records, "referenced_records": referenced_records}

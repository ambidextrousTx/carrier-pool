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


def _event_for(load: WorldLoad, status: LoadStatus):
    return next((e for e in load.events if e.status == status), None)


def _has_reached(load: WorldLoad, status: LoadStatus) -> bool:
    order = list(LoadStatus)
    return order.index(load.final_status) >= order.index(status)


class _SequentialIds:
    """Assigns stable sequential numeric-looking ids to world string ids,
    in first-appearance order -- deterministic given the world's own
    (seeded, reproducible) load ordering."""

    def __init__(self, start: int):
        self._next = start
        self._assigned: dict[str, int] = {}

    def get(self, world_id: str) -> int:
        if world_id not in self._assigned:
            self._assigned[world_id] = self._next
            self._next += 1
        return self._assigned[world_id]


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


def export_freightflow(world: World) -> dict:
    shipment_ids = _SequentialIds(start=127_000_000)
    customer_ids = _SequentialIds(start=880_000)
    carrier_ids = _SequentialIds(start=830_000)

    loads = []
    for load in world.loads:
        customer = next(c for c in world.customers if c.id == load.customer_id)
        carrier: CarrierProfile | None = None
        if load.assigned_carrier_id:
            carrier = next(c for c in world.carriers if c.id == load.assigned_carrier_id)

        pickup_departure = _event_for(load, LoadStatus.IN_TRANSIT).timestamp if _has_reached(load, LoadStatus.IN_TRANSIT) else None

        loads.append(
            {
                "shipmentId": shipment_ids.get(load.id),
                "status": _FF_STATUS[load.final_status],
                "mileage": float(load.distance_miles),
                "totalSell": float(_event_for(load, LoadStatus.ACTIVE).customer_rate_usd),
                "totalBuy": float(carrier_rate) if (carrier_rate := load.events[-1].carrier_rate_usd) is not None else None,
                "customer": {"customerId": customer_ids.get(customer.id), "name": customer.name},
                "carrier": None
                if carrier is None
                else {
                    "carrierMasterId": carrier_ids.get(carrier.id),
                    "name": carrier.name,
                    "mcNumber": carrier.mc_number,
                    "dotNumber": carrier.dot_number,
                    "phoneNumber": f"+1{carrier.phone}",
                },
                "equipment": _FF_EQUIPMENT[load.equipment_type],
                "weightTotal": float(load.weight_lbs),
                "stops": [
                    _ff_stop(load.origin_city, load.origin_state, load.origin_zip, load.pickup_date, "First Pickup", pickup_departure),
                    _ff_stop(load.destination_city, load.destination_state, load.destination_zip, load.delivery_date, "Last Drop", None),
                ],
                "createdDate": _utc_iso(load.created_at),
                "lastModifiedDate": _utc_iso(load.last_modified_at),
            }
        )

    return {"syncedAt": _utc_iso(world.loads[0].created_at if world.loads else datetime.now(timezone.utc)), "loads": loads}


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


def export_hauldesk(world: World) -> dict:
    customer_codes = _SequentialIds(start=1)
    carrier_refs = _SequentialIds(start=66_000)
    rate_ids = _SequentialIds(start=910_000)

    loads = []
    carriers_seen: dict[str, CarrierProfile] = {}
    rates = []

    for load in world.loads:
        customer = next(c for c in world.customers if c.id == load.customer_id)
        carrier: CarrierProfile | None = None
        if load.assigned_carrier_id:
            carrier = next(c for c in world.carriers if c.id == load.assigned_carrier_id)
            carriers_seen[carrier.id] = carrier

        pickup_departure = _event_for(load, LoadStatus.IN_TRANSIT).timestamp if _has_reached(load, LoadStatus.IN_TRANSIT) else None
        delivery_arrival = _event_for(load, LoadStatus.DELIVERED).timestamp if _has_reached(load, LoadStatus.DELIVERED) else None

        loads.append(
            {
                "load_num": load.id.upper(),
                "status_code": _HD_STATUS[load.final_status],
                "customer_code": f"C-{customer_codes.get(customer.id):04d}",
                "customer_name": customer.name,
                "carrier_ref": carrier_refs.get(carrier.id) if carrier else None,
                "equip": _HD_EQUIPMENT[load.equipment_type],
                "weight_kg": float(lbs_to_kg(load.weight_lbs)),
                "dist_km": float(miles_to_km(load.distance_miles)),
                "pu_city": load.origin_city, "pu_state": load.origin_state, "pu_zip": load.origin_zip,
                "pu_date": load.pickup_date.isoformat(),
                "pu_departed_at": _naive_central(pickup_departure) if pickup_departure else None,
                "del_city": load.destination_city, "del_state": load.destination_state, "del_zip": load.destination_zip,
                "del_date": load.delivery_date.isoformat(),
                "del_arrived_at": _naive_central(delivery_arrival) if delivery_arrival else None,
                "entered_at": _naive_central(load.created_at),
                "updated_at": _naive_central(load.last_modified_at),
            }
        )

        # BILL side is set as soon as a customer rate exists (from ACTIVE
        # onward); PAY side only once a carrier is actually booked --
        # matches real HaulDesk's "line items, not a total field" model.
        active_event = _event_for(load, LoadStatus.ACTIVE)
        rates.append(
            {
                "rate_id": rate_ids.get(f"{load.id}-bill"),
                "load_num": load.id.upper(),
                "side": "bill",
                "code": "LINEHAUL",
                "amount_usd": float(active_event.customer_rate_usd),
                "created_at": _naive_central(active_event.timestamp),
            }
        )
        covered_event = _event_for(load, LoadStatus.COVERED)
        if covered_event is not None:
            rates.append(
                {
                    "rate_id": rate_ids.get(f"{load.id}-pay"),
                    "load_num": load.id.upper(),
                    "side": "pay",
                    "code": "LINEHAUL",
                    "amount_usd": float(covered_event.carrier_rate_usd),
                    "created_at": _naive_central(covered_event.timestamp),
                }
            )

    carriers = [
        {
            "carrier_id": carrier_refs.get(c.id),
            "carrier_name": c.name,
            "mc_no": c.mc_number,
            "dot_no": c.dot_number,
            "home_city": c.home_city,
            "home_state": c.home_state,
            "phone": c.phone,
        }
        for c in carriers_seen.values()
    ]

    return {
        "synced_at": _naive_central(world.loads[0].created_at if world.loads else datetime.now(timezone.utc)),
        "loads": loads,
        "carriers": carriers,
        "rates": rates,
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


def export_brokeros(world: World) -> dict:
    load_ids = _SequentialIds(start=1)
    account_ids = _SequentialIds(start=1)
    location_ids: dict[str, str] = {}  # zip -> referenced_records id, deduped

    def location_ref(zip_code: str, city: str, state: str, referenced: dict) -> str:
        if zip_code not in location_ids:
            ref_id = f"LOC{len(location_ids) + 1:015d}"
            location_ids[zip_code] = ref_id
            referenced[ref_id] = {"type": "Location", "Name": f"{city} Hub", "bos__City__c": city, "bos__State__c": state, "bos__Postal_Code__c": zip_code}
        return location_ids[zip_code]

    def account_ref(entity_id: str, kind: str, referenced: dict, customer: CustomerProfile | None = None, carrier: CarrierProfile | None = None) -> str:
        key = f"{kind}:{entity_id}"
        ref_id = f"ACC{account_ids.get(key):015d}"
        if ref_id not in referenced:
            if customer is not None:
                referenced[ref_id] = {"type": "Account", "record_type": "Customer", "Name": customer.name}
            else:
                referenced[ref_id] = {
                    "type": "Account", "record_type": "Carrier", "Name": carrier.name,
                    "bos__MC_Number__c": carrier.mc_number, "bos__DOT_Number__c": carrier.dot_number,
                    "bos__Phone__c": carrier.phone, "bos__City__c": carrier.home_city, "bos__State__c": carrier.home_state,
                }
        return ref_id

    referenced_records: dict = {}
    records = []

    for load in world.loads:
        customer = next(c for c in world.customers if c.id == load.customer_id)
        carrier: CarrierProfile | None = None
        if load.assigned_carrier_id:
            carrier = next(c for c in world.carriers if c.id == load.assigned_carrier_id)

        customer_ref = account_ref(customer.id, "cust", referenced_records, customer=customer)
        carrier_ref = account_ref(carrier.id, "carrier", referenced_records, carrier=carrier) if carrier else None

        origin_loc = location_ref(load.origin_zip, load.origin_city, load.origin_state, referenced_records)
        dest_loc = location_ref(load.destination_zip, load.destination_city, load.destination_state, referenced_records)

        pickup_arrival = _event_for(load, LoadStatus.IN_TRANSIT).timestamp if _has_reached(load, LoadStatus.IN_TRANSIT) else None
        delivery_arrival = _event_for(load, LoadStatus.DELIVERED).timestamp if _has_reached(load, LoadStatus.DELIVERED) else None

        seq = load_ids.get(load.id)
        records.append(
            {
                "Id": f"LOAD{seq:014d}",
                "Name": f"SHP{seq:07d}",
                "bos__Load_Status__c": _BOS_STATUS[load.final_status],
                "bos__Distance_Miles__c": float(load.distance_miles),
                "bos__Customer__c": customer_ref,
                "bos__Carrier__c": carrier_ref,
                "bos__Equipment_Type__c": _BOS_EQUIPMENT[load.equipment_type],
                "bos__Customer_Rate__c": float(_event_for(load, LoadStatus.ACTIVE).customer_rate_usd),
                "bos__Carrier_Rate__c": float(cr) if (cr := load.events[-1].carrier_rate_usd) is not None else None,
                "bos__Stops__r": [
                    {
                        "bos__Number__c": 1.0, "bos__Is_Pickup__c": True, "bos__Is_Dropoff__c": False,
                        "bos__Location__c": origin_loc, "bos__Scheduled_Date__c": load.pickup_date.isoformat(),
                        "bos__Arrival_Time__c": _utc_iso(pickup_arrival) if pickup_arrival else None,
                    },
                    {
                        "bos__Number__c": 2.0, "bos__Is_Pickup__c": False, "bos__Is_Dropoff__c": True,
                        "bos__Location__c": dest_loc, "bos__Scheduled_Date__c": load.delivery_date.isoformat(),
                        "bos__Arrival_Time__c": _utc_iso(delivery_arrival) if delivery_arrival else None,
                    },
                ],
                "bos__Line_Items__r": [
                    {
                        "bos__Commodity__c": "General Freight",
                        "bos__Weight__c": float(load.weight_lbs),
                        "bos__Weight_Units__c": "lbs",
                        "bos__Pallet_Count__c": float(max(1, round(float(load.weight_lbs) / 1200))),
                    }
                ],
                "CreatedDate": _utc_iso(load.created_at),
                "LastModifiedDate": _utc_iso(load.last_modified_at),
            }
        )

    return {
        "synced_at": _utc_iso(world.loads[0].created_at if world.loads else datetime.now(timezone.utc)),
        "records": records,
        "referenced_records": referenced_records,
    }

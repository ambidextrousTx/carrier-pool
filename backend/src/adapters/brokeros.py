from decimal import Decimal

from adapters.numeric import to_decimal
from adapters.timeutils import parse_date_only, parse_offset_aware_iso
from adapters.units import kg_to_lbs
from canonical.enums import EquipmentType, LoadStatus, SourceSystem
from canonical.models import AdapterResult, Carrier, Customer, Load, Stop

_STATUS_MAP: dict[str, LoadStatus] = {
    "Quotes Requested": LoadStatus.PLANNED,
    "Ready to Book": LoadStatus.ACTIVE,
    "Booked": LoadStatus.COVERED,
    "In Transit": LoadStatus.IN_TRANSIT,
    "Delivered": LoadStatus.DELIVERED,
    "Invoiced": LoadStatus.DELIVERED,  # collapsed -- see canonical model discussion
    "Paid": LoadStatus.COMPLETED,
}

_EQUIPMENT_MAP: dict[str, EquipmentType] = {
    "Dry Van": EquipmentType.DRY_VAN,
    "Reefer": EquipmentType.REEFER,
    "Flatbed": EquipmentType.FLATBED,
}

# Weight can be recorded per line item in a unit other than lbs -- convert
# each line item using its OWN unit before summing, per the source's "usually
# lbs -- but check per record" warning.
_WEIGHT_CONVERTERS = {
    "lbs": lambda d: d,
    "kg": kg_to_lbs,
}


def _map_status(raw: str) -> LoadStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"BrokerOS: unrecognized bos__Load_Status__c {raw!r}") from None


def _map_equipment(raw: str | None) -> EquipmentType:
    if raw is None:
        return EquipmentType.UNKNOWN
    return _EQUIPMENT_MAP.get(raw, EquipmentType.UNKNOWN)


def _resolve(referenced_records: dict, record_id: str) -> dict:
    try:
        return referenced_records[record_id]
    except KeyError:
        raise ValueError(f"BrokerOS: referenced_records missing entry for {record_id!r}") from None


def _parse_stop(raw: dict, referenced_records: dict) -> Stop:
    location = _resolve(referenced_records, raw["bos__Location__c"])
    arrival = raw.get("bos__Arrival_Time__c")
    return Stop(
        sequence=int(raw["bos__Number__c"]),
        is_pickup=raw["bos__Is_Pickup__c"],
        is_dropoff=raw["bos__Is_Dropoff__c"],
        city=location["bos__City__c"],
        state=location["bos__State__c"],
        zip_code=location.get("bos__Postal_Code__c"),
        scheduled_date=parse_date_only(raw["bos__Scheduled_Date__c"]),
        actual_arrival_at=parse_offset_aware_iso(arrival) if arrival else None,
    )


def _parse_stops(raw_stops: list[dict], referenced_records: dict) -> list[Stop]:
    if not raw_stops:
        raise ValueError("BrokerOS: load has no stops")
    # Source's own comment: "order by bos__Number__c" -- array order is not
    # guaranteed to already be sorted.
    ordered = sorted(raw_stops, key=lambda s: s["bos__Number__c"])
    return [_parse_stop(s, referenced_records) for s in ordered]


def _total_weight_lbs(line_items: list[dict]) -> Decimal | None:
    if not line_items:
        return None
    total = Decimal("0")
    for item in line_items:
        unit = item.get("bos__Weight_Units__c") or "lbs"
        try:
            convert = _WEIGHT_CONVERTERS[unit]
        except KeyError:
            raise ValueError(f"BrokerOS: unrecognized bos__Weight_Units__c {unit!r}") from None
        total += convert(to_decimal(item["bos__Weight__c"]))
    return total


def _parse_customer(customer_id: str, referenced_records: dict) -> Customer:
    account = _resolve(referenced_records, customer_id)
    return Customer(
        source_system=SourceSystem.BROKEROS,
        source_native_id=customer_id,
        name=account["Name"],
    )


def _parse_carrier(carrier_id: str | None, referenced_records: dict) -> Carrier | None:
    if carrier_id is None:
        return None
    account = _resolve(referenced_records, carrier_id)
    return Carrier(
        source_system=SourceSystem.BROKEROS,
        source_native_id=carrier_id,
        name=account["Name"],
        # ASSUMPTION, not confirmed against real BrokerOS data: neither
        # sample load we were given had a carrier booked, so we've never
        # seen a real Account record for one. These field names follow
        # BrokerOS's established bos__X__c convention. Our synthetic data
        # generator should populate them consistently; revisit if/when
        # real data shows different field names.
        mc_number=account.get("bos__MC_Number__c"),
        dot_number=account.get("bos__DOT_Number__c"),
        phone=account.get("bos__Phone__c"),
        home_city=account.get("bos__City__c"),
        home_state=account.get("bos__State__c"),
    )


def _parse_load(raw: dict, referenced_records: dict) -> AdapterResult:
    customer = _parse_customer(raw["bos__Customer__c"], referenced_records)
    carrier = _parse_carrier(raw.get("bos__Carrier__c"), referenced_records)

    load = Load(
        source_system=SourceSystem.BROKEROS,
        source_native_id=raw["Id"],
        source_native_number=raw.get("Name"),
        status=_map_status(raw["bos__Load_Status__c"]),
        source_status_raw=raw["bos__Load_Status__c"],
        customer_source_native_id=customer.source_native_id,
        carrier_source_native_id=carrier.source_native_id if carrier else None,
        equipment_type=_map_equipment(raw.get("bos__Equipment_Type__c")),
        distance_miles=to_decimal(raw.get("bos__Distance_Miles__c")),
        weight_lbs=_total_weight_lbs(raw.get("bos__Line_Items__r", [])),
        customer_rate_total_usd=to_decimal(raw.get("bos__Customer_Rate__c")),
        carrier_rate_total_usd=to_decimal(raw.get("bos__Carrier_Rate__c")),
        stops=_parse_stops(raw["bos__Stops__r"], referenced_records),
        source_created_at=parse_offset_aware_iso(raw["CreatedDate"]),
        source_last_modified_at=parse_offset_aware_iso(raw["LastModifiedDate"]),
    )
    return AdapterResult(load=load, customer=customer, carrier=carrier)


def parse_brokeros_sync(raw: dict) -> list[AdapterResult]:
    referenced_records = raw.get("referenced_records", {})
    return [_parse_load(r, referenced_records) for r in raw["records"]]

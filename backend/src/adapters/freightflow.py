from adapters.numeric import to_decimal
from adapters.timeutils import parse_offset_aware_iso
from canonical.enums import EquipmentType, LoadStatus, SourceSystem
from canonical.models import AdapterResult, Carrier, Customer, Load, Stop

_STATUS_MAP: dict[str, LoadStatus] = {
    "Quoting": LoadStatus.PLANNED,
    "Booking": LoadStatus.ACTIVE,
    "Dispatched": LoadStatus.COVERED,
    "At Shipper": LoadStatus.COVERED,
    "En Route": LoadStatus.IN_TRANSIT,
    "At Receiver": LoadStatus.IN_TRANSIT,
    "Delivered": LoadStatus.DELIVERED,
    "Completed": LoadStatus.COMPLETED,
}


def _map_status(raw: str) -> LoadStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"FreightFlow: unrecognized status {raw!r}") from None


def _map_equipment(raw: str | None) -> EquipmentType:
    if not raw:
        return EquipmentType.UNKNOWN
    lowered = raw.lower()
    if "flatbed" in lowered:
        return EquipmentType.FLATBED
    if "reefer" in lowered:
        return EquipmentType.REEFER
    if "dry" in lowered:
        return EquipmentType.DRY_VAN
    return EquipmentType.UNKNOWN


def _parse_stop(raw: dict, *, sequence: int, is_pickup: bool, is_dropoff: bool) -> Stop:
    window_start = parse_offset_aware_iso(raw["estimatedReadyDateTime"])
    window_end = (
        parse_offset_aware_iso(raw["estimatedCloseDateTime"])
        if raw.get("estimatedCloseDateTime")
        else None
    )
    actual_departure = (
        parse_offset_aware_iso(raw["actualDepartureDateTime"])
        if raw.get("actualDepartureDateTime")
        else None
    )
    return Stop(
        sequence=sequence,
        is_pickup=is_pickup,
        is_dropoff=is_dropoff,
        city=raw["city"],
        state=raw["state"],
        zip_code=raw.get("zipCode"),
        scheduled_date=window_start.date(),
        scheduled_window_start=window_start,
        scheduled_window_end=window_end,
        actual_departure_at=actual_departure,
    )


def _parse_stops(raw_stops: list[dict]) -> list[Stop]:
    if not raw_stops:
        raise ValueError("FreightFlow: load has no stops")
    last_index = len(raw_stops) - 1
    return [
        _parse_stop(raw, sequence=i + 1, is_pickup=(i == 0), is_dropoff=(i == last_index))
        for i, raw in enumerate(raw_stops)
    ]


def _parse_carrier(raw: dict | None) -> Carrier | None:
    if raw is None:
        return None
    return Carrier(
        source_system=SourceSystem.FREIGHTFLOW,
        source_native_id=str(raw["carrierMasterId"]),
        name=raw["name"],
        mc_number=raw.get("mcNumber"),
        dot_number=raw.get("dotNumber"),
        phone=raw.get("phoneNumber"),
    )


def _parse_load(raw: dict) -> AdapterResult:
    customer = Customer(
        source_system=SourceSystem.FREIGHTFLOW,
        source_native_id=str(raw["customer"]["customerId"]),
        name=raw["customer"]["name"],
    )
    carrier = _parse_carrier(raw.get("carrier"))

    load = Load(
        source_system=SourceSystem.FREIGHTFLOW,
        source_native_id=str(raw["shipmentId"]),
        status=_map_status(raw["status"]),
        source_status_raw=raw["status"],
        customer_source_native_id=customer.source_native_id,
        carrier_source_native_id=carrier.source_native_id if carrier else None,
        equipment_type=_map_equipment(raw.get("equipment")),
        distance_miles=to_decimal(raw.get("mileage")),
        weight_lbs=to_decimal(raw.get("weightTotal")),
        customer_rate_total_usd=to_decimal(raw.get("totalSell")),
        carrier_rate_total_usd=to_decimal(raw.get("totalBuy")),
        stops=_parse_stops(raw["stops"]),
        source_created_at=parse_offset_aware_iso(raw["createdDate"]),
        source_last_modified_at=parse_offset_aware_iso(raw["lastModifiedDate"]),
    )
    return AdapterResult(load=load, customer=customer, carrier=carrier)


def parse_freightflow_sync(raw: dict) -> list[AdapterResult]:
    return [_parse_load(raw_load) for raw_load in raw["loads"]]

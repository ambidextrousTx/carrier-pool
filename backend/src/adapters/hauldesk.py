from adapters.numeric import to_decimal
from adapters.timeutils import parse_date_only, parse_naive_central
from adapters.units import kg_to_lbs, km_to_miles
from canonical.enums import EquipmentType, LoadStatus, RateSide, SourceSystem
from canonical.models import AdapterResult, Carrier, Customer, Load, RateLineItem, Stop

_STATUS_MAP: dict[int, LoadStatus] = {
    10: LoadStatus.PLANNED,
    20: LoadStatus.ACTIVE,
    30: LoadStatus.COVERED,
    40: LoadStatus.IN_TRANSIT,
    50: LoadStatus.DELIVERED,
    90: LoadStatus.COMPLETED,
}

_EQUIPMENT_MAP: dict[str, EquipmentType] = {
    "V": EquipmentType.DRY_VAN,
    "R": EquipmentType.REEFER,
    "F": EquipmentType.FLATBED,
}

_RATE_SIDE_MAP: dict[str, RateSide] = {
    "bill": RateSide.BILL,
    "pay": RateSide.PAY,
}


def _map_status(raw: int) -> LoadStatus:
    try:
        return _STATUS_MAP[raw]
    except KeyError:
        raise ValueError(f"HaulDesk: unrecognized status_code {raw!r}") from None


def _map_equipment(raw: str | None) -> EquipmentType:
    if raw is None:
        return EquipmentType.UNKNOWN
    return _EQUIPMENT_MAP.get(raw, EquipmentType.UNKNOWN)


def _map_rate_side(raw: str) -> RateSide:
    try:
        return _RATE_SIDE_MAP[raw]
    except KeyError:
        raise ValueError(f"HaulDesk: unrecognized rate side {raw!r}") from None


def _parse_pickup_stop(raw_load: dict) -> Stop:
    departed = raw_load.get("pu_departed_at")
    return Stop(
        sequence=1,
        is_pickup=True,
        is_dropoff=False,
        city=raw_load["pu_city"],
        state=raw_load["pu_state"],
        zip_code=raw_load.get("pu_zip"),
        scheduled_date=parse_date_only(raw_load["pu_date"]),
        actual_departure_at=parse_naive_central(departed) if departed else None,
    )


def _parse_delivery_stop(raw_load: dict) -> Stop:
    arrived = raw_load.get("del_arrived_at")
    return Stop(
        sequence=2,
        is_pickup=False,
        is_dropoff=True,
        city=raw_load["del_city"],
        state=raw_load["del_state"],
        zip_code=raw_load.get("del_zip"),
        scheduled_date=parse_date_only(raw_load["del_date"]),
        actual_arrival_at=parse_naive_central(arrived) if arrived else None,
    )


def _parse_carrier(raw: dict) -> Carrier:
    return Carrier(
        source_system=SourceSystem.HAULDESK,
        source_native_id=str(raw["carrier_id"]),
        name=raw["carrier_name"],
        mc_number=raw.get("mc_no"),
        dot_number=raw.get("dot_no"),
        phone=raw.get("phone"),
        home_city=raw.get("home_city"),
        home_state=raw.get("home_state"),
    )


def _parse_rate_line_item(raw: dict) -> RateLineItem:
    return RateLineItem(
        source_native_id=str(raw["rate_id"]),
        side=_map_rate_side(raw["side"]),
        code=raw["code"],
        amount_usd=to_decimal(raw["amount_usd"]),
        source_created_at=parse_naive_central(raw["created_at"]),
    )


def parse_hauldesk_sync(raw: dict) -> list[AdapterResult]:
    # Carriers/rates are separate tables in this file, joined by reference.
    # A carrier_ref on a load may point to a carrier NOT present in this
    # particular file's "carriers" array -- HaulDesk only re-includes a
    # carrier row when it's new or changed, per the source's own comment.
    # When that happens we still set the load's carrier_source_native_id
    # (the relationship is real), but AdapterResult.carrier is None: this
    # file has nothing new to say about that carrier's details.
    carriers_by_id = {str(c["carrier_id"]): _parse_carrier(c) for c in raw.get("carriers", [])}

    rates_by_load_num: dict[str, list[dict]] = {}
    for rate in raw.get("rates", []):
        rates_by_load_num.setdefault(rate["load_num"], []).append(rate)

    results = []
    for raw_load in raw["loads"]:
        load_num = raw_load["load_num"]

        customer = Customer(
            source_system=SourceSystem.HAULDESK,
            source_native_id=raw_load["customer_code"],
            name=raw_load["customer_name"],
        )

        carrier_ref = raw_load.get("carrier_ref")
        carrier_source_id = str(carrier_ref) if carrier_ref is not None else None
        carrier = carriers_by_id.get(carrier_source_id) if carrier_source_id else None

        rate_line_items = [_parse_rate_line_item(r) for r in rates_by_load_num.get(load_num, [])]

        dist_km = to_decimal(raw_load.get("dist_km"))
        weight_kg = to_decimal(raw_load.get("weight_kg"))

        load = Load(
            source_system=SourceSystem.HAULDESK,
            source_native_id=load_num,
            status=_map_status(raw_load["status_code"]),
            source_status_raw=str(raw_load["status_code"]),
            customer_source_native_id=customer.source_native_id,
            carrier_source_native_id=carrier_source_id,
            equipment_type=_map_equipment(raw_load.get("equip")),
            distance_miles=km_to_miles(dist_km) if dist_km is not None else None,
            weight_lbs=kg_to_lbs(weight_kg) if weight_kg is not None else None,
            # No single-file authoritative total for HaulDesk -- see the
            # Load model's docstring. The real total is SUM(rate_line_items)
            # across every file that has ever mentioned this load, which
            # the persistence layer computes, not this adapter.
            customer_rate_total_usd=None,
            carrier_rate_total_usd=None,
            rate_line_items=rate_line_items,
            stops=[_parse_pickup_stop(raw_load), _parse_delivery_stop(raw_load)],
            source_created_at=parse_naive_central(raw_load["entered_at"]),
            source_last_modified_at=parse_naive_central(raw_load["updated_at"]),
        )
        results.append(AdapterResult(load=load, customer=customer, carrier=carrier))

    return results

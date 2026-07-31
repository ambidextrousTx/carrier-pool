from canonical.enums import SourceSystem
from canonical.models import AdapterResult, Carrier, Customer, Load, RateLineItem, Stop
from geo.lookup import resolve_zip
from persistence.db import set_tenant_context


def _upsert_customer(cur, broker_id: str, customer: Customer) -> str:
    cur.execute(
        """
        INSERT INTO customers (broker_id, source_system, source_native_id, name)
        VALUES (%(broker_id)s, %(source_system)s, %(source_native_id)s, %(name)s)
        ON CONFLICT (broker_id, source_system, source_native_id) DO UPDATE SET
            name = EXCLUDED.name,
            updated_at = now()
        RETURNING id
        """,
        {
            "broker_id": broker_id,
            "source_system": customer.source_system.value,
            "source_native_id": customer.source_native_id,
            "name": customer.name,
        },
    )
    return cur.fetchone()[0]


def _upsert_carrier(cur, broker_id: str, carrier: Carrier) -> str:
    cur.execute(
        """
        INSERT INTO carriers (
            broker_id, source_system, source_native_id, name,
            mc_number, dot_number, phone, home_city, home_state
        ) VALUES (
            %(broker_id)s, %(source_system)s, %(source_native_id)s, %(name)s,
            %(mc_number)s, %(dot_number)s, %(phone)s, %(home_city)s, %(home_state)s
        )
        ON CONFLICT (broker_id, source_system, source_native_id) DO UPDATE SET
            name = EXCLUDED.name,
            mc_number = EXCLUDED.mc_number,
            dot_number = EXCLUDED.dot_number,
            phone = EXCLUDED.phone,
            home_city = EXCLUDED.home_city,
            home_state = EXCLUDED.home_state,
            updated_at = now()
        RETURNING id
        """,
        {
            "broker_id": broker_id,
            "source_system": carrier.source_system.value,
            "source_native_id": carrier.source_native_id,
            "name": carrier.name,
            "mc_number": carrier.mc_number,
            "dot_number": carrier.dot_number,
            "phone": carrier.phone,
            "home_city": carrier.home_city,
            "home_state": carrier.home_state,
        },
    )
    return cur.fetchone()[0]


def _lookup_carrier_id(
    cur, broker_id: str, source_system: SourceSystem, source_native_id: str
) -> str | None:
    cur.execute(
        "SELECT id FROM carriers WHERE broker_id = %s AND source_system = %s AND source_native_id = %s",
        (broker_id, source_system.value, source_native_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _resolve_carrier_id(cur, broker_id: str, result: AdapterResult) -> str | None:
    if result.carrier is not None:
        return _upsert_carrier(cur, broker_id, result.carrier)

    # No carrier details in THIS file, but the load still references one
    # by native id (HaulDesk: "not redefined this sync" case -- see the
    # adapter's own comment). Resolve against what we already have.
    native_id = result.load.carrier_source_native_id
    if native_id is None:
        return None

    carrier_id = _lookup_carrier_id(cur, broker_id, result.load.source_system, native_id)
    if carrier_id is None:
        raise ValueError(
            f"{result.load.source_system.value}: load {result.load.source_native_id} references "
            f"carrier {native_id!r}, which has never been seen in any prior sync -- cannot resolve"
        )
    return carrier_id


def _upsert_load(cur, broker_id: str, load: Load, customer_id: str, carrier_id: str | None) -> str:
    cur.execute(
        """
        INSERT INTO loads (
            broker_id, source_system, source_native_id, source_native_number,
            status, source_status_raw,
            customer_id, carrier_id,
            equipment_type, distance_miles, weight_lbs,
            customer_rate_total_usd, carrier_rate_total_usd,
            source_created_at, source_last_modified_at
        ) VALUES (
            %(broker_id)s, %(source_system)s, %(source_native_id)s, %(source_native_number)s,
            %(status)s, %(source_status_raw)s,
            %(customer_id)s, %(carrier_id)s,
            %(equipment_type)s, %(distance_miles)s, %(weight_lbs)s,
            %(customer_rate_total_usd)s, %(carrier_rate_total_usd)s,
            %(source_created_at)s, %(source_last_modified_at)s
        )
        ON CONFLICT (broker_id, source_system, source_native_id) DO UPDATE SET
            source_native_number = EXCLUDED.source_native_number,
            status = EXCLUDED.status,
            source_status_raw = EXCLUDED.source_status_raw,
            customer_id = EXCLUDED.customer_id,
            -- Never let a load regress from "has a carrier" to "has no
            -- carrier" -- every source keeps carrier_ref/carrier once set,
            -- but this is a cheap, defensible guard against a source ever
            -- omitting it in some update payload.
            carrier_id = COALESCE(EXCLUDED.carrier_id, loads.carrier_id),
            equipment_type = EXCLUDED.equipment_type,
            distance_miles = EXCLUDED.distance_miles,
            weight_lbs = EXCLUDED.weight_lbs,
            customer_rate_total_usd = EXCLUDED.customer_rate_total_usd,
            carrier_rate_total_usd = EXCLUDED.carrier_rate_total_usd,
            -- source_created_at intentionally NOT updated -- it's when the
            -- load was first created at the source, immutable thereafter.
            source_last_modified_at = EXCLUDED.source_last_modified_at,
            updated_at = now()
        RETURNING id
        """,
        {
            "broker_id": broker_id,
            "source_system": load.source_system.value,
            "source_native_id": load.source_native_id,
            "source_native_number": load.source_native_number,
            "status": load.status.value,
            "source_status_raw": load.source_status_raw,
            "customer_id": customer_id,
            "carrier_id": carrier_id,
            "equipment_type": load.equipment_type.value,
            "distance_miles": load.distance_miles,
            "weight_lbs": load.weight_lbs,
            "customer_rate_total_usd": load.customer_rate_total_usd,
            "carrier_rate_total_usd": load.carrier_rate_total_usd,
            "source_created_at": load.source_created_at,
            "source_last_modified_at": load.source_last_modified_at,
        },
    )
    return cur.fetchone()[0]


def _resolve_stop_geo(stop: Stop) -> tuple[str | None, float | None, float | None]:
    """Returns (market_area, latitude, longitude) for a stop's zip code.
    A missing zip_code is a known, legitimate state (some sources allow
    it) and resolves to (None, None, None). A PRESENT zip that doesn't
    match anything in our reference data is a data integrity problem --
    we control the entire zip universe this system deals with (real
    fixtures plus our own synthetic generator), so an unresolvable zip
    means something has drifted out of sync and should fail loudly
    rather than silently ingest a geo-less stop."""
    if stop.zip_code is None:
        return None, None, None
    geo = resolve_zip(stop.zip_code)
    if geo is None:
        raise ValueError(f"unresolvable zip code {stop.zip_code!r} for stop in {stop.city}, {stop.state}")
    return geo.market_area, geo.latitude, geo.longitude


def _replace_stops(cur, broker_id: str, load_id: str, stops: list[Stop]) -> None:
    # No source gives a stable per-stop identifier, so stops are always
    # wholesale-replaced rather than upserted individually.
    cur.execute("DELETE FROM stops WHERE load_id = %s", (load_id,))
    for stop in stops:
        market_area, latitude, longitude = _resolve_stop_geo(stop)
        cur.execute(
            """
            INSERT INTO stops (
                broker_id, load_id, sequence, is_pickup, is_dropoff,
                city, state, zip_code,
                scheduled_date, scheduled_window_start, scheduled_window_end,
                actual_arrival_at, actual_departure_at,
                market_area, latitude, longitude
            ) VALUES (
                %(broker_id)s, %(load_id)s, %(sequence)s, %(is_pickup)s, %(is_dropoff)s,
                %(city)s, %(state)s, %(zip_code)s,
                %(scheduled_date)s, %(scheduled_window_start)s, %(scheduled_window_end)s,
                %(actual_arrival_at)s, %(actual_departure_at)s,
                %(market_area)s, %(latitude)s, %(longitude)s
            )
            """,
            {
                "broker_id": broker_id,
                "load_id": load_id,
                "sequence": stop.sequence,
                "is_pickup": stop.is_pickup,
                "is_dropoff": stop.is_dropoff,
                "city": stop.city,
                "state": stop.state,
                "zip_code": stop.zip_code,
                "scheduled_date": stop.scheduled_date,
                "scheduled_window_start": stop.scheduled_window_start,
                "scheduled_window_end": stop.scheduled_window_end,
                "actual_arrival_at": stop.actual_arrival_at,
                "actual_departure_at": stop.actual_departure_at,
                "market_area": market_area,
                "latitude": latitude,
                "longitude": longitude,
            },
        )


def _insert_rate_line_items(
    cur, broker_id: str, load_id: str, source_system: SourceSystem, items: list[RateLineItem]
) -> None:
    for item in items:
        cur.execute(
            """
            INSERT INTO rate_line_items (
                broker_id, load_id, source_system, source_native_id, side, code, amount_usd, source_created_at
            ) VALUES (
                %(broker_id)s, %(load_id)s, %(source_system)s, %(source_native_id)s,
                %(side)s, %(code)s, %(amount_usd)s, %(source_created_at)s
            )
            -- Append-only: an existing line item is never supposed to
            -- change, so a repeat sighting is silently ignored, not updated.
            ON CONFLICT (broker_id, source_system, source_native_id) DO NOTHING
            """,
            {
                "broker_id": broker_id,
                "load_id": load_id,
                "source_system": source_system.value,
                "source_native_id": item.source_native_id,
                "side": item.side.value,
                "code": item.code,
                "amount_usd": item.amount_usd,
                "source_created_at": item.source_created_at,
            },
        )


def ingest_result(cur, broker_id: str, result: AdapterResult) -> str:
    """Ingests one AdapterResult using an already-open cursor (caller owns
    the transaction and tenant context). Returns the load's surrogate id."""
    customer_id = _upsert_customer(cur, broker_id, result.customer)
    carrier_id = _resolve_carrier_id(cur, broker_id, result)
    load_id = _upsert_load(cur, broker_id, result.load, customer_id, carrier_id)
    _replace_stops(cur, broker_id, load_id, result.load.stops)
    _insert_rate_line_items(cur, broker_id, load_id, result.load.source_system, result.load.rate_line_items)
    return load_id


def ingest_sync(conn, broker_id: str, results: list[AdapterResult]) -> list[str]:
    """Ingests an entire sync file's worth of AdapterResults as one
    all-or-nothing transaction: either the whole file lands, or none of it
    does. Safe to call more than once with the same file (idempotent)."""
    with conn.transaction():
        with conn.cursor() as cur:
            set_tenant_context(cur, broker_id)
            return [ingest_result(cur, broker_id, r) for r in results]

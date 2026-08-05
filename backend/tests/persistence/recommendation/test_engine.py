import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from geo.distance import haversine_miles
from geo.lookup import resolve_zip
from recommendation.engine import predict_rate, rank_carriers

# Real zips from our reference data.
DFW_A, DFW_B = "75050", "75201"  # Grand Prairie, Dallas -- same market area
HOUSTON_A, HOUSTON_B = "77002", "77449"  # Houston, Katy -- same market area
SAN_ANTONIO = "78205"


def _insert_customer(cur, broker_id: str) -> str:
    cur.execute(
        "INSERT INTO customers (broker_id, source_system, source_native_id, name) VALUES (%s, 'FREIGHTFLOW', %s, %s) RETURNING id",
        (broker_id, str(uuid.uuid4()), "Test Customer"),
    )
    return cur.fetchone()[0]


def _insert_carrier(cur, broker_id: str, name: str) -> str:
    cur.execute(
        """INSERT INTO carriers (broker_id, source_system, source_native_id, name, mc_number, dot_number)
           VALUES (%s, 'FREIGHTFLOW', %s, %s, '100000', '1000000') RETURNING id""",
        (broker_id, str(uuid.uuid4()), name),
    )
    return cur.fetchone()[0]


def _insert_load(
    cur, broker_id, customer_id, carrier_id, status, equipment_type, origin_zip, destination_zip,
    *, created_days_ago=100, carrier_rate=None, customer_rate=Decimal("1200.00"),
    dropoff_arrival_days_ago=None,
):
    origin = resolve_zip(origin_zip)
    destination = resolve_zip(destination_zip)
    created_at = datetime.now(timezone.utc) - timedelta(days=created_days_ago)
    distance = haversine_miles(origin.latitude, origin.longitude, destination.latitude, destination.longitude)

    cur.execute(
        """
        INSERT INTO loads (
            broker_id, source_system, source_native_id, status, source_status_raw,
            customer_id, carrier_id, equipment_type, distance_miles, weight_lbs,
            customer_rate_total_usd, carrier_rate_total_usd, source_created_at, source_last_modified_at
        ) VALUES (
            %(broker_id)s, 'FREIGHTFLOW', %(native_id)s, %(status)s, %(status)s,
            %(customer_id)s, %(carrier_id)s, %(equipment_type)s, %(distance)s, 20000,
            %(customer_rate)s, %(carrier_rate)s, %(created_at)s, %(created_at)s
        ) RETURNING id
        """,
        {
            "broker_id": broker_id, "native_id": str(uuid.uuid4()), "status": status,
            "customer_id": customer_id, "carrier_id": carrier_id, "equipment_type": equipment_type,
            "distance": distance, "customer_rate": customer_rate, "carrier_rate": carrier_rate,
            "created_at": created_at,
        },
    )
    load_id = cur.fetchone()[0]

    dropoff_arrival = datetime.now(timezone.utc) - timedelta(days=dropoff_arrival_days_ago) if dropoff_arrival_days_ago is not None else None
    pickup_date = created_at.date() + timedelta(days=1)

    for seq, is_pickup, is_dropoff, geo, sched_date, arrival in [
        (1, True, False, origin, pickup_date, None),
        (2, False, True, destination, pickup_date + timedelta(days=1), dropoff_arrival),
    ]:
        cur.execute(
            """
            INSERT INTO stops (broker_id, load_id, sequence, is_pickup, is_dropoff, city, state, zip_code,
                                scheduled_date, actual_arrival_at, market_area, latitude, longitude)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (broker_id, load_id, seq, is_pickup, is_dropoff, geo.city, geo.state, geo.zip_code,
             sched_date, arrival, geo.market_area, geo.latitude, geo.longitude),
        )
    return load_id


def _insert_rate_line_item(cur, broker_id, load_id, native_id, side, amount, created_at):
    cur.execute(
        """INSERT INTO rate_line_items (broker_id, load_id, source_system, source_native_id, side, code, amount_usd, source_created_at)
           VALUES (%s, %s, 'HAULDESK', %s, %s, 'LINEHAUL', %s, %s)""",
        (broker_id, load_id, native_id, side, amount, created_at),
    )


@pytest.fixture
def broker_id(admin_conn, two_brokers):
    return two_brokers[0]


class TestRankCarriers:
    def test_lane_history_beats_no_history_regardless_of_deadhead(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)

        carrier_with_history = _insert_carrier(cur, broker_id, "Has Lane History")
        _insert_load(
            cur, broker_id, customer_id, carrier_with_history, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A,
            created_days_ago=10, carrier_rate=Decimal("900"), dropoff_arrival_days_ago=60,  # far from new pickup
        )

        carrier_no_history_close = _insert_carrier(cur, broker_id, "No History But Close")
        _insert_load(
            cur, broker_id, customer_id, carrier_no_history_close, "COMPLETED", "DRY_VAN", SAN_ANTONIO, DFW_B,
            created_days_ago=5, carrier_rate=Decimal("500"), dropoff_arrival_days_ago=1,  # very close to new pickup
        )

        # The new ACTIVE load: DFW -> Houston
        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        results = rank_carriers(cur, target)
        assert results[0].carrier_id == carrier_with_history
        assert results[0].has_hauled_this_lane is True
        assert "hauled this lane" in results[0].justification

    def test_recency_weighting_prefers_more_recent_lane_activity(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)

        recent_carrier = _insert_carrier(cur, broker_id, "Recent")
        _insert_load(cur, broker_id, customer_id, recent_carrier, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=10, dropoff_arrival_days_ago=10)

        stale_carrier = _insert_carrier(cur, broker_id, "Stale")
        _insert_load(cur, broker_id, customer_id, stale_carrier, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=300, dropoff_arrival_days_ago=300)

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        results = rank_carriers(cur, target)
        recent_rank = next(i for i, r in enumerate(results) if r.carrier_id == recent_carrier)
        stale_rank = next(i for i, r in enumerate(results) if r.carrier_id == stale_carrier)
        assert recent_rank < stale_rank

    def test_busy_carrier_is_excluded_entirely(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)

        busy_carrier = _insert_carrier(cur, broker_id, "Currently Busy")
        _insert_load(cur, broker_id, customer_id, busy_carrier, "IN_TRANSIT", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=1, carrier_rate=Decimal("900"))

        free_carrier = _insert_carrier(cur, broker_id, "Available")
        _insert_load(cur, broker_id, customer_id, free_carrier, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=10, dropoff_arrival_days_ago=10)

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        results = rank_carriers(cur, target)
        assert busy_carrier not in [r.carrier_id for r in results]
        assert free_carrier in [r.carrier_id for r in results]

    def test_equipment_filter_relaxes_when_too_few_matches(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)

        # Only carriers with REEFER history exist -- none have hauled DRY_VAN
        reefer_carrier = _insert_carrier(cur, broker_id, "Reefer Only")
        _insert_load(cur, broker_id, customer_id, reefer_carrier, "COMPLETED", "REEFER", DFW_A, HOUSTON_A, created_days_ago=10, dropoff_arrival_days_ago=10)

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        results = rank_carriers(cur, target)
        assert len(results) > 0
        assert results[0].equipment_filter_relaxed is True

    def test_lane_match_does_not_count_wrong_equipment_type(self, admin_conn, broker_id):
        # Regression: a carrier who hauled this exact lane many times in a
        # DIFFERENT trailer type must not get "knows this lane" credit for
        # the wrong equipment -- caught by comparing against real seeded
        # data, where ranking and rate prediction disagreed on this exact
        # scenario before the fix.
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)

        carrier_id = _insert_carrier(cur, broker_id, "Dry Van Specialist")
        for _ in range(5):
            _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=10, dropoff_arrival_days_ago=10)

        # New load is REEFER on the same lane -- the carrier's dry van
        # history there must not count.
        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "REEFER", DFW_B, HOUSTON_B, created_days_ago=0)

        results = rank_carriers(cur, target)
        matched = next(r for r in results if r.carrier_id == carrier_id)
        assert matched.has_hauled_this_lane is False
        assert matched.lane_match_count == 0


class TestPredictRate:
    def test_median_over_comparable_loads(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)
        carrier_id = _insert_carrier(cur, broker_id, "Carrier")

        # 5 comps on the same lane, distances ~225mi (DFW -> Houston), rates chosen for a clean median
        for rate in [Decimal("400"), Decimal("450"), Decimal("500"), Decimal("550"), Decimal("2000")]:  # outlier included
            _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=30, carrier_rate=rate)

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        prediction = predict_rate(cur, target)
        assert prediction.is_available is True
        assert prediction.comparable_load_count == 5
        assert prediction.is_low_confidence is False
        # Median rate (500) shouldn't be dragged by the 2000 outlier the
        # way a mean would be.
        assert prediction.predicted_total_usd < Decimal("700")

    def test_falls_back_to_broad_market_when_lane_is_sparse(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)
        carrier_id = _insert_carrier(cur, broker_id, "Carrier")

        # Only 2 comps on the specific lane (below min_comps=5)
        _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=10, carrier_rate=Decimal("500"))
        _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=20, carrier_rate=Decimal("520"))
        # But several DRY_VAN comps on OTHER lanes
        for rate in [Decimal("300"), Decimal("310"), Decimal("320")]:
            _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, SAN_ANTONIO, created_days_ago=15, carrier_rate=rate)

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        prediction = predict_rate(cur, target)
        assert prediction.is_available is True
        assert prediction.is_low_confidence is True
        assert "Low confidence" in prediction.explanation
        assert prediction.comparable_load_count == 5  # 2 same-lane + 3 other-lane

    def test_unavailable_when_truly_insufficient_data(self, admin_conn, broker_id):
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)
        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "FLATBED", DFW_B, HOUSTON_B, created_days_ago=0)

        prediction = predict_rate(cur, target)
        # No bare None -- the caller still needs to know *why* there's no
        # number, same as a real answer needs to be explained.
        assert prediction.is_available is False
        assert prediction.predicted_total_usd is None
        assert prediction.low_usd is None
        assert prediction.high_usd is None
        assert prediction.comparable_load_count == 0
        assert "Not enough data" in prediction.explanation

    def test_uses_summed_rate_line_items_when_no_single_total(self, admin_conn, broker_id):
        """The deferred HaulDesk piece: a load with carrier_rate_total_usd
        IS NULL but has rate_line_items must still contribute to the
        comparable set via effective_carrier_rate."""
        cur = admin_conn.cursor()
        customer_id = _insert_customer(cur, broker_id)
        carrier_id = _insert_carrier(cur, broker_id, "Carrier")

        for rate in [Decimal("400"), Decimal("450"), Decimal("500"), Decimal("550")]:
            _insert_load(cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A, created_days_ago=10, carrier_rate=rate)

        # A 5th load with NO carrier_rate_total_usd, only line items summing to 600
        line_item_load = _insert_load(
            cur, broker_id, customer_id, carrier_id, "COMPLETED", "DRY_VAN", DFW_A, HOUSTON_A,
            created_days_ago=10, carrier_rate=None,
        )
        _insert_rate_line_item(cur, broker_id, line_item_load, "rate-1", "PAY", Decimal("400.00"), datetime.now(timezone.utc))
        _insert_rate_line_item(cur, broker_id, line_item_load, "rate-2", "PAY", Decimal("200.00"), datetime.now(timezone.utc))

        target = _insert_load(cur, broker_id, customer_id, None, "ACTIVE", "DRY_VAN", DFW_B, HOUSTON_B, created_days_ago=0)

        prediction = predict_rate(cur, target)
        assert prediction.is_available is True
        assert prediction.comparable_load_count == 5  # the line-item load counted

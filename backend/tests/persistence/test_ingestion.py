import copy

import psycopg
import pytest

from adapters.brokeros import parse_brokeros_sync
from adapters.freightflow import parse_freightflow_sync
from adapters.hauldesk import parse_hauldesk_sync
from persistence.ingestion import ingest_sync
from tms_fixtures import (
    BROKEROS_SYNC,
    FREIGHTFLOW_SYNC_BOOKED,
    FREIGHTFLOW_SYNC_UNBOOKED,
    HAULDESK_SYNC,
)


def _fetch_load(admin_conn, broker_id, source_system, source_native_id):
    with admin_conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM loads WHERE broker_id = %s AND source_system = %s AND source_native_id = %s",
            (broker_id, source_system, source_native_id),
        )
        columns = [d[0] for d in cur.description]
        row = cur.fetchone()
        return dict(zip(columns, row)) if row else None


def _count(admin_conn, table, **where):
    clause = " AND ".join(f"{k} = %s" for k in where)
    with admin_conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table} WHERE {clause}", tuple(where.values()))
        return cur.fetchone()[0]


class TestBasicIngestion:
    def test_ingests_load_customer_and_stops(self, bare_runtime_conn, two_brokers, admin_conn):
        broker_a, _ = two_brokers
        results = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)

        load_ids = ingest_sync(bare_runtime_conn, broker_a, results)
        assert len(load_ids) == 1

        load = _fetch_load(admin_conn, broker_a, "FREIGHTFLOW", "127472397")
        assert load is not None
        assert load["id"] == load_ids[0]
        assert load["status"] == "ACTIVE"
        assert load["carrier_id"] is None
        assert str(load["distance_miles"]) == "242.1"

        assert _count(admin_conn, "customers", broker_id=broker_a) == 1
        assert _count(admin_conn, "stops", load_id=load["id"]) == 2


class TestIdempotency:
    def test_reingesting_same_file_does_not_duplicate(self, bare_runtime_conn, two_brokers, admin_conn):
        broker_a, _ = two_brokers
        results = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)

        ids_first = ingest_sync(bare_runtime_conn, broker_a, results)
        ids_second = ingest_sync(bare_runtime_conn, broker_a, results)

        assert ids_first == ids_second
        assert _count(admin_conn, "loads", broker_id=broker_a) == 1
        assert _count(admin_conn, "customers", broker_id=broker_a) == 1


class TestUpdateOnConflict:
    def test_booking_updates_same_load_row_and_creates_carrier(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, _ = two_brokers
        ingest_sync(bare_runtime_conn, broker_a, parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED))
        before = _fetch_load(admin_conn, broker_a, "FREIGHTFLOW", "127472397")

        ingest_sync(bare_runtime_conn, broker_a, parse_freightflow_sync(FREIGHTFLOW_SYNC_BOOKED))
        after = _fetch_load(admin_conn, broker_a, "FREIGHTFLOW", "127472397")

        assert after["id"] == before["id"]  # same row, not a new one
        assert after["status"] == "COVERED"
        assert after["carrier_id"] is not None
        assert str(after["carrier_rate_total_usd"]) == "1180.00"
        assert _count(admin_conn, "loads", broker_id=broker_a) == 1  # still just one load

        with admin_conn.cursor() as cur:
            cur.execute("SELECT name, mc_number, dot_number FROM carriers WHERE id = %s", (after["carrier_id"],))
            name, mc, dot = cur.fetchone()
        assert name == "IBRAHIM TRANSPORT INC"
        assert mc == "1346382"
        assert dot == "3771394"

    def test_stops_are_replaced_not_appended(self, bare_runtime_conn, two_brokers, admin_conn):
        broker_a, _ = two_brokers
        ingest_sync(bare_runtime_conn, broker_a, parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED))

        modified = copy.deepcopy(FREIGHTFLOW_SYNC_UNBOOKED)
        modified["loads"][0]["stops"].append(copy.deepcopy(modified["loads"][0]["stops"][0]))
        modified["loads"][0]["stops"][-1]["city"] = "AUSTIN"
        modified["loads"][0]["lastModifiedDate"] = "2026-07-06T11:00:00-05:00"

        ingest_sync(bare_runtime_conn, broker_a, parse_freightflow_sync(modified))

        load = _fetch_load(admin_conn, broker_a, "FREIGHTFLOW", "127472397")
        assert _count(admin_conn, "stops", load_id=load["id"]) == 3  # replaced, not 2+3=5


class TestMultiTenantIsolation:
    def test_same_native_id_creates_separate_rows_per_broker(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, broker_b = two_brokers
        results = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)  # shipmentId 127472397 for both

        ingest_sync(bare_runtime_conn, broker_a, results)
        ingest_sync(bare_runtime_conn, broker_b, results)

        load_a = _fetch_load(admin_conn, broker_a, "FREIGHTFLOW", "127472397")
        load_b = _fetch_load(admin_conn, broker_b, "FREIGHTFLOW", "127472397")
        assert load_a["id"] != load_b["id"]

    def test_runtime_connection_only_sees_its_own_broker_after_ingestion(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, broker_b = two_brokers
        results = parse_freightflow_sync(FREIGHTFLOW_SYNC_UNBOOKED)
        ingest_sync(bare_runtime_conn, broker_a, results)
        ingest_sync(bare_runtime_conn, broker_b, results)

        conn_a = psycopg.connect(
            "host=localhost dbname=carrier_recs user=app_runtime password=runtime_dev_pw", autocommit=True
        )
        with conn_a.cursor() as cur:
            cur.execute("SELECT set_config('app.current_broker_id', %s, false)", (str(broker_a),))
            cur.execute("SELECT count(*) FROM loads")
            visible_count = cur.fetchone()[0]
        conn_a.close()

        assert visible_count == 1  # only broker_a's load, not both


class TestRateLineItems:
    def test_line_items_ingested_and_idempotent(self, bare_runtime_conn, two_brokers, admin_conn):
        broker_a, _ = two_brokers
        results = parse_hauldesk_sync(HAULDESK_SYNC)

        ingest_sync(bare_runtime_conn, broker_a, results)
        load = _fetch_load(admin_conn, broker_a, "HAULDESK", "HD-2026-004417")
        assert _count(admin_conn, "rate_line_items", load_id=load["id"]) == 2

        ingest_sync(bare_runtime_conn, broker_a, results)  # re-ingest same file
        assert _count(admin_conn, "rate_line_items", load_id=load["id"]) == 2  # not 4

    def test_new_line_item_appends_without_touching_existing_ones(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, _ = two_brokers
        ingest_sync(bare_runtime_conn, broker_a, parse_hauldesk_sync(HAULDESK_SYNC))
        load = _fetch_load(admin_conn, broker_a, "HAULDESK", "HD-2026-004417")

        with_adjustment = copy.deepcopy(HAULDESK_SYNC)
        with_adjustment["rates"].append(
            {
                "rate_id": 910299,
                "load_num": "HD-2026-004417",
                "side": "pay",
                "code": "ADJUSTMENT",
                "amount_usd": -75.00,
                "created_at": "2026-07-06 09:00:00",
            }
        )
        ingest_sync(bare_runtime_conn, broker_a, parse_hauldesk_sync(with_adjustment))

        assert _count(admin_conn, "rate_line_items", load_id=load["id"]) == 3
        with admin_conn.cursor() as cur:
            cur.execute(
                "SELECT amount_usd FROM rate_line_items WHERE load_id = %s AND code = 'LINEHAUL' AND side = 'PAY'",
                (load["id"],),
            )
            (original_amount,) = cur.fetchone()
        assert str(original_amount) == "1035.00"  # untouched


class TestCarrierResolution:
    def test_carrier_not_redefined_in_later_sync_still_resolves(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, _ = two_brokers
        ingest_sync(bare_runtime_conn, broker_a, parse_hauldesk_sync(HAULDESK_SYNC))

        later_sync = copy.deepcopy(HAULDESK_SYNC)
        later_sync["carriers"] = []  # carrier not redefined, but carrier_ref still present
        later_sync["loads"][0]["status_code"] = 40
        later_sync["loads"][0]["updated_at"] = "2026-07-06 10:00:00"

        ingest_sync(bare_runtime_conn, broker_a, parse_hauldesk_sync(later_sync))

        load = _fetch_load(admin_conn, broker_a, "HAULDESK", "HD-2026-004417")
        assert load["status"] == "IN_TRANSIT"
        assert load["carrier_id"] is not None  # still resolved, not wiped to null

    def test_carrier_never_seen_before_raises_and_rolls_back_whole_sync(
        self, bare_runtime_conn, two_brokers, admin_conn
    ):
        broker_a, _ = two_brokers
        raw = copy.deepcopy(HAULDESK_SYNC)
        raw["carriers"] = []  # carrier_ref 66861 resolves to nothing anywhere

        with pytest.raises(ValueError, match="never been seen"):
            ingest_sync(bare_runtime_conn, broker_a, parse_hauldesk_sync(raw))

        # Nothing from this sync should have landed -- all-or-nothing.
        assert _fetch_load(admin_conn, broker_a, "HAULDESK", "HD-2026-004417") is None
        assert _count(admin_conn, "customers", broker_id=broker_a) == 0


class TestBrokerOSIngestion:
    def test_full_pipeline_happy_path(self, bare_runtime_conn, two_brokers, admin_conn):
        broker_a, _ = two_brokers
        ingest_sync(bare_runtime_conn, broker_a, parse_brokeros_sync(BROKEROS_SYNC))

        load = _fetch_load(admin_conn, broker_a, "BROKEROS", "a0jO900000YgsYJIAZ")
        assert load is not None
        assert load["status"] == "ACTIVE"
        assert str(load["weight_lbs"]) == "14440.0"
        assert _count(admin_conn, "stops", load_id=load["id"]) == 2

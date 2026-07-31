import psycopg
import pytest


def _seed_one_carrier_per_broker(admin_conn, broker_a, broker_b):
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO carriers (broker_id, source_system, source_native_id, name) VALUES (%s, %s, %s, %s)",
            (broker_a, "FREIGHTFLOW", "1001", "A Trucking"),
        )
        cur.execute(
            "INSERT INTO carriers (broker_id, source_system, source_native_id, name) VALUES (%s, %s, %s, %s)",
            (broker_b, "FREIGHTFLOW", "1002", "B Trucking"),
        )


def test_broker_sees_only_its_own_carriers(admin_conn, two_brokers, runtime_conn):
    broker_a, broker_b = two_brokers
    _seed_one_carrier_per_broker(admin_conn, broker_a, broker_b)

    conn_a = runtime_conn(broker_a)
    with conn_a.cursor() as cur:
        cur.execute("SELECT name FROM carriers")
        names = [row[0] for row in cur.fetchall()]

    assert names == ["A Trucking"]


def test_two_tenants_get_independent_views_simultaneously(
    admin_conn, two_brokers, runtime_conn
):
    broker_a, broker_b = two_brokers
    _seed_one_carrier_per_broker(admin_conn, broker_a, broker_b)

    conn_a = runtime_conn(broker_a)
    conn_b = runtime_conn(broker_b)

    with conn_a.cursor() as cur:
        cur.execute("SELECT name FROM carriers")
        names_a = [row[0] for row in cur.fetchall()]

    with conn_b.cursor() as cur:
        cur.execute("SELECT name FROM carriers")
        names_b = [row[0] for row in cur.fetchall()]

    assert names_a == ["A Trucking"]
    assert names_b == ["B Trucking"]


def test_unset_tenant_context_returns_nothing_not_everything(
    admin_conn, two_brokers, runtime_conn
):
    """The property that matters most: a bug that forgets to set the
    tenant context must fail CLOSED (see nothing), not fail OPEN
    (see every tenant's data)."""
    broker_a, broker_b = two_brokers
    _seed_one_carrier_per_broker(admin_conn, broker_a, broker_b)

    conn_no_context = runtime_conn(None)
    with conn_no_context.cursor() as cur:
        cur.execute("SELECT name FROM carriers")
        rows = cur.fetchall()

    assert rows == []


def test_cannot_write_a_row_into_another_tenant(admin_conn, two_brokers, runtime_conn):
    """WITH CHECK should block inserting a row tagged with a different
    tenant's broker_id, even from a connection that IS authenticated
    (as broker A) -- e.g. if a broker_id value got mixed up somewhere
    upstream in application code."""
    broker_a, broker_b = two_brokers
    conn_a = runtime_conn(broker_a)

    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with conn_a.cursor() as cur:
            cur.execute(
                "INSERT INTO carriers (broker_id, source_system, source_native_id, name) VALUES (%s, %s, %s, %s)",
                (broker_b, "FREIGHTFLOW", "9999", "Sneaky Trucking"),
            )


def test_runtime_role_cannot_bypass_rls_via_raw_sql(
    admin_conn, two_brokers, runtime_conn
):
    """Guards against a regression where app_runtime is accidentally
    granted ownership or BYPASSRLS in a future migration."""
    broker_a, broker_b = two_brokers
    _seed_one_carrier_per_broker(admin_conn, broker_a, broker_b)

    conn_a = runtime_conn(broker_a)
    with conn_a.cursor() as cur:
        cur.execute("SELECT count(*) FROM carriers")
        (total_visible,) = cur.fetchone()

    # Two carriers exist in the table, but broker A must only ever see 1.
    assert total_visible == 1

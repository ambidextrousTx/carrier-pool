import psycopg
import pytest

import os


DB_HOST = os.environ.get("TEST_DB_HOST", "localhost")
DB_NAME = os.environ.get("TEST_DB_NAME", "carrier_recs")

# app_migrator owns the tables and bypasses RLS -- used ONLY for test
# setup/teardown, never to exercise the isolation guarantee itself.
MIGRATOR_DSN = f"host={DB_HOST} dbname={DB_NAME} user=app_migrator password=migrator_dev_pw"

# app_runtime is the weak, non-owning role the real backend connects as.
# This is the role RLS actually restricts.
RUNTIME_DSN = f"host={DB_HOST} dbname={DB_NAME} user=app_runtime password=runtime_dev_pw"


@pytest.fixture
def admin_conn():
    conn = psycopg.connect(MIGRATOR_DSN, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def bare_runtime_conn():
    """A plain app_runtime connection with NO tenant context pre-set --
    unlike the top-level `runtime_conn` fixture. Ingestion code is
    responsible for setting its own context; this fixture makes sure our
    tests actually prove that, rather than piggybacking on scaffolding."""
    conn = psycopg.connect(RUNTIME_DSN, autocommit=True)
    yield conn
    conn.close()


@pytest.fixture
def two_brokers(admin_conn):
    """Creates two tenant brokers for a test and cleans up after."""
    with admin_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO brokers (name) VALUES (%s), (%s) RETURNING id",
            ("Acme Freight", "Big Rig Logistics"),
        )
        ids = [row[0] for row in cur.fetchall()]
    yield ids
    with admin_conn.cursor() as cur:
        # stops and rate_line_items cascade automatically via ON DELETE
        # CASCADE from loads. loads references customers and carriers, so
        # it must go first; customers/carriers reference brokers, so they
        # go before brokers.
        cur.execute("DELETE FROM loads WHERE broker_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM customers WHERE broker_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM carriers WHERE broker_id = ANY(%s)", (ids,))
        cur.execute("DELETE FROM brokers WHERE id = ANY(%s)", (ids,))


@pytest.fixture
def runtime_conn():
    """Factory fixture. Call with a broker_id to get an app_runtime
    connection scoped to that tenant (mirrors what the backend will do
    once per request). Call with None to simulate a bug where the tenant
    context was never set. All opened connections are closed after the test.
    """
    opened = []

    def _make(broker_id):
        conn = psycopg.connect(RUNTIME_DSN, autocommit=True)
        if broker_id is not None:
            with conn.cursor() as cur:
                # SET does not accept bind parameters (Postgres limitation).
                # set_config() is a normal function call, so it does --
                # this is the safe way to assign a session GUC from a
                # runtime value.
                cur.execute(
                    "SELECT set_config('app.current_broker_id', %s, false)",
                    (str(broker_id),),
                )
        opened.append(conn)
        return conn

    yield _make
    for conn in opened:
        conn.close()

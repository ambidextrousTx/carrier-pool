from collections.abc import Iterator

import psycopg
from fastapi import Depends, HTTPException, Request
from psycopg_pool import ConnectionPool

from persistence.db import set_tenant_context


def get_pool(request: Request) -> ConnectionPool:
    return request.app.state.pool


def get_broker_connection(broker_id: str, pool: ConnectionPool = Depends(get_pool)) -> Iterator[psycopg.Connection]:
    """The one dependency every broker-scoped route uses. Deliberately
    structured so a route physically cannot query tenant data without
    going through this -- there's no other way to get a connection out of
    the pool in this module.

    Does two things inside a single checked-out connection/transaction:
    1. Confirms `broker_id` actually exists -- a syntactically valid but
       nonexistent id should 404 up front, not silently return empty
       results from every query a route runs afterward.
    2. Calls set_tenant_context, which uses SET LOCAL under the hood --
       scoped to this transaction only, so it's safe even though this
       connection came from a pool and will be reused by a different
       request (for a different broker) later.

    `brokers` itself has no RLS policy (it's the tenant directory, not
    tenant data), so this lookup is safe to run as app_runtime before
    tenant context is set -- no chicken-and-egg problem.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM brokers WHERE id = %(broker_id)s", {"broker_id": broker_id})
            if cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"broker not found: {broker_id}")
            set_tenant_context(cur, broker_id)
        yield conn

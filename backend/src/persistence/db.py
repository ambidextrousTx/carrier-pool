def set_tenant_context(cur, broker_id: str) -> None:
    """Scopes RLS to the given broker for the remainder of the CURRENT
    transaction only (is_local=true, i.e. SET LOCAL semantics) -- safe
    even if this connection is later reused, e.g. via a pool, for a
    different tenant's request. Must be called inside the same
    transaction as the queries it's meant to scope."""
    cur.execute("SELECT set_config('app.current_broker_id', %s, true)",
                (str(broker_id),))

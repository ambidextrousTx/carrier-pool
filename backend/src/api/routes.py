import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg_pool import ConnectionPool

from recommendation.engine import predict_rate, rank_carriers

from .deps import get_broker_connection, get_pool
from .schemas import (
    BrokerOut,
    CarrierRecommendationOut,
    LoadDetailOut,
    LoadStatusStr,
    LoadSummaryOut,
    RatePredictionOut,
    RecommendationOut,
)

router = APIRouter()


@router.get("/brokers", response_model=list[BrokerOut])
def list_brokers(pool: ConnectionPool = Depends(get_pool)):
    # No tenant scoping here on purpose -- `brokers` is the tenant
    # directory, not tenant data, and there's nothing to scope to yet
    # (this is how a client discovers valid broker_ids in the first
    # place, given there's no real login/auth in front of this demo).
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, name FROM brokers ORDER BY name")
        return [BrokerOut(id=str(row[0]), name=row[1]) for row in cur.fetchall()]


# Every column here is one engine.py's own queries already rely on
# (_load_context, _available_candidates, rank_carriers' last-delivery
# query) -- deliberately not guessing at weight/customer/rate column
# names that engine.py never touches. "We don't have to expose much"
# applies here too.
_LOAD_QUERY_SQL = """
    SELECT l.id, l.status, l.equipment_type, l.distance_miles, l.carrier_id,
           pu.market_area, pu.city, pu.state, pu.scheduled_date,
           do_.market_area, do_.city, do_.state, do_.scheduled_date
    FROM loads l
    JOIN stops pu ON pu.load_id = l.id AND pu.is_pickup
    JOIN stops do_ ON do_.load_id = l.id AND do_.is_dropoff
"""


def _row_to_load_detail(row) -> LoadDetailOut:
    (
        load_id, status, equipment_type, distance_miles, carrier_id,
        origin_market, origin_city, origin_state, pickup_date,
        dest_market, dest_city, dest_state, delivery_date,
    ) = row
    return LoadDetailOut(
        id=str(load_id), status=status, equipment_type=equipment_type,
        origin_market_area=origin_market, destination_market_area=dest_market,
        origin_city=origin_city, origin_state=origin_state,
        destination_city=dest_city, destination_state=dest_state,
        pickup_date=pickup_date, delivery_date=delivery_date,
        distance_miles=float(distance_miles), carrier_id=str(carrier_id) if carrier_id is not None else None,
    )


@router.get("/brokers/{broker_id}/loads", response_model=list[LoadSummaryOut])
def list_loads(
    status: LoadStatusStr | None = Query(default=None, description="Filter by load status, e.g. ACTIVE"),
    conn: psycopg.Connection = Depends(get_broker_connection),
):
    # No broker_id filter here -- RLS already scopes every query on this
    # connection to the broker set_tenant_context was called with. Adding
    # "AND l.broker_id = ..." here would be redundant at best and a false
    # sense of security at worst (the real guarantee is the database
    # policy, not this line of application code).
    query = _LOAD_QUERY_SQL + " WHERE 1=1"
    params: dict = {}
    if status is not None:
        query += " AND l.status = %(status)s"
        params["status"] = status
    query += " ORDER BY pu.scheduled_date"

    with conn.cursor() as cur:
        cur.execute(query, params)
        rows = cur.fetchall()
    # LoadDetailOut is a superset of LoadSummaryOut -- FastAPI's
    # response_model filters it down to LoadSummaryOut's fields on the
    # way out, so one row-mapping function covers both endpoints.
    return [_row_to_load_detail(row) for row in rows]


@router.get("/brokers/{broker_id}/loads/{load_id}", response_model=LoadDetailOut)
def get_load(load_id: str, conn: psycopg.Connection = Depends(get_broker_connection)):
    with conn.cursor() as cur:
        cur.execute(_LOAD_QUERY_SQL + " WHERE l.id = %(load_id)s", {"load_id": load_id})
        row = cur.fetchone()
    if row is None:
        # Covers both "genuinely doesn't exist" and "exists but belongs to
        # a different broker" -- RLS makes those indistinguishable at this
        # layer, which is exactly the point: a cross-tenant probe gets a
        # plain 404, not a "found but not yours" 403 that would confirm
        # the id is real.
        raise HTTPException(status_code=404, detail=f"load not found: {load_id}")
    return _row_to_load_detail(row)


@router.get("/brokers/{broker_id}/loads/{load_id}/recommendation", response_model=RecommendationOut)
def get_recommendation(load_id: str, conn: psycopg.Connection = Depends(get_broker_connection)):
    # Works for a load in any status, not just ACTIVE -- deliberately not
    # restricted, so the same endpoint doubles as a validation tool: point
    # it at a COMPLETED load and compare what the engine would have said
    # against what actually happened.
    with conn.cursor() as cur:
        try:
            recommendations = rank_carriers(cur, load_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"load not found: {load_id}")
        rate = predict_rate(cur, load_id)

    note = None
    if not recommendations:
        note = "No carriers are currently available for this broker right now (all are booked on other loads)."

    return RecommendationOut(
        load_id=load_id,
        carrier_recommendations=[
            CarrierRecommendationOut(
                carrier_id=str(r.carrier_id),
                carrier_name=r.carrier_name,
                mc_number=r.mc_number,
                dot_number=r.dot_number,
                has_hauled_this_lane=r.has_hauled_this_lane,
                lane_match_count=r.lane_match_count,
                deadhead_miles=float(r.deadhead_miles) if r.deadhead_miles is not None else None,
                justification=r.justification,
                equipment_filter_relaxed=r.equipment_filter_relaxed,
            )
            for r in recommendations
        ],
        carrier_recommendations_note=note,
        rate_prediction=RatePredictionOut.from_engine(rate),
    )

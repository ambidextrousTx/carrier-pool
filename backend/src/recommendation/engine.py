import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from geo.distance import haversine_miles

# HaulDesk loads have no single authoritative carrier_rate_total_usd --
# the real total is SUM(rate_line_items WHERE side='PAY'). This fragment
# is the one place that reads a carrier rate, used everywhere below, so
# every query is correct for all three sources without needing to know
# which source a given load came from.
_EFFECTIVE_CARRIER_RATE_SQL = """
    COALESCE(
        l.carrier_rate_total_usd,
        (SELECT SUM(amount_usd) FROM rate_line_items WHERE load_id = l.id AND side = 'PAY')
    )
"""

_LANE_RECENCY_WEIGHTS_SQL = """
    SUM(
        CASE
            WHEN pu.scheduled_date >= %(d30)s THEN 3
            WHEN pu.scheduled_date >= %(d90)s THEN 2
            WHEN pu.scheduled_date >= %(d365)s THEN 1
            ELSE 0
        END
    )
"""


@dataclass(frozen=True)
class LoadContext:
    broker_id: str
    equipment_type: str
    origin_market_area: str
    destination_market_area: str
    distance_miles: Decimal
    pickup_lat: float
    pickup_lon: float


@dataclass(frozen=True)
class CarrierRecommendation:
    carrier_id: str
    carrier_name: str
    mc_number: str | None
    dot_number: str | None
    has_hauled_this_lane: bool
    lane_match_count: int
    deadhead_miles: Decimal | None
    justification: str
    equipment_filter_relaxed: bool


@dataclass(frozen=True)
class RatePrediction:
    is_available: bool
    predicted_total_usd: Decimal | None
    low_usd: Decimal | None
    high_usd: Decimal | None
    comparable_load_count: int
    is_low_confidence: bool
    explanation: str


def _load_context(cur, load_id: str) -> LoadContext:
    cur.execute(
        """
        SELECT l.broker_id, l.equipment_type, l.distance_miles,
               pu.market_area, pu.latitude, pu.longitude, do_.market_area
        FROM loads l
        JOIN stops pu ON pu.load_id = l.id AND pu.is_pickup
        JOIN stops do_ ON do_.load_id = l.id AND do_.is_dropoff
        WHERE l.id = %(load_id)s
        """,
        {"load_id": load_id},
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"load {load_id!r} not found")
    broker_id, equipment_type, distance_miles, origin_market, pu_lat, pu_lon, dest_market = row
    return LoadContext(
        broker_id=broker_id, equipment_type=equipment_type, distance_miles=distance_miles,
        origin_market_area=origin_market, destination_market_area=dest_market,
        pickup_lat=float(pu_lat), pickup_lon=float(pu_lon),
    )


def _available_candidates(cur, broker_id: str, equipment_type: str, require_equipment_history: bool) -> list[dict]:
    cur.execute(
        f"""
        SELECT c.id, c.name, c.mc_number, c.dot_number
        FROM carriers c
        WHERE c.broker_id = %(broker_id)s
          -- exclude carriers currently committed to another load --
          -- a busy truck is not a useful recommendation
          AND NOT EXISTS (
              SELECT 1 FROM loads l2
              WHERE l2.carrier_id = c.id AND l2.status IN ('COVERED', 'IN_TRANSIT')
          )
          AND (
              %(skip_equipment_filter)s
              OR EXISTS (
                  SELECT 1 FROM loads l3
                  WHERE l3.carrier_id = c.id AND l3.equipment_type = %(equipment_type)s AND l3.status = 'COMPLETED'
              )
          )
        """,
        {
            "broker_id": broker_id,
            "equipment_type": equipment_type,
            "skip_equipment_filter": not require_equipment_history,
        },
    )
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def rank_carriers(cur, load_id: str, top_n: int = 5) -> list[CarrierRecommendation]:
    ctx = _load_context(cur, load_id)

    candidates = _available_candidates(cur, ctx.broker_id, ctx.equipment_type, require_equipment_history=True)
    equipment_filter_relaxed = False
    if len(candidates) < 3:
        candidates = _available_candidates(cur, ctx.broker_id, ctx.equipment_type, require_equipment_history=False)
        equipment_filter_relaxed = True

    if not candidates:
        return []

    candidate_ids = [c["id"] for c in candidates]
    today = date.today()

    cur.execute(
        f"""
        SELECT l.carrier_id, {_LANE_RECENCY_WEIGHTS_SQL} AS lane_score, count(*) AS lane_count
        FROM loads l
        JOIN stops pu ON pu.load_id = l.id AND pu.is_pickup
        JOIN stops do_ ON do_.load_id = l.id AND do_.is_dropoff
        WHERE l.broker_id = %(broker_id)s
          AND l.status = 'COMPLETED'
          AND l.carrier_id = ANY(%(candidate_ids)s)
          AND l.equipment_type = %(equipment_type)s
          AND pu.market_area = %(origin_market)s
          AND do_.market_area = %(destination_market)s
        GROUP BY l.carrier_id
        """,
        {
            "broker_id": ctx.broker_id, "candidate_ids": candidate_ids, "equipment_type": ctx.equipment_type,
            "origin_market": ctx.origin_market_area, "destination_market": ctx.destination_market_area,
            "d30": today - timedelta(days=30), "d90": today - timedelta(days=90), "d365": today - timedelta(days=365),
        },
    )
    lane_stats = {row[0]: {"score": row[1], "count": row[2]} for row in cur.fetchall()}

    cur.execute(
        """
        SELECT DISTINCT ON (l.carrier_id) l.carrier_id, do_.latitude, do_.longitude, do_.city, do_.state
        FROM loads l
        JOIN stops do_ ON do_.load_id = l.id AND do_.is_dropoff
        WHERE l.broker_id = %(broker_id)s AND l.status = 'COMPLETED' AND l.carrier_id = ANY(%(candidate_ids)s)
        ORDER BY l.carrier_id, do_.actual_arrival_at DESC NULLS LAST, l.source_last_modified_at DESC
        """,
        {"broker_id": ctx.broker_id, "candidate_ids": candidate_ids},
    )
    last_delivery = {row[0]: {"lat": float(row[1]), "lon": float(row[2]), "city": row[3], "state": row[4]} for row in cur.fetchall()}

    recommendations = []
    for c in candidates:
        stats = lane_stats.get(c["id"], {"score": 0, "count": 0})
        delivery = last_delivery.get(c["id"])
        deadhead = (
            haversine_miles(delivery["lat"], delivery["lon"], ctx.pickup_lat, ctx.pickup_lon)
            if delivery is not None
            else None
        )

        parts = []
        if stats["count"] > 0:
            parts.append(f"hauled this lane {stats['count']} time{'s' if stats['count'] != 1 else ''} recently")
        else:
            parts.append("no history on this exact lane")
        if delivery is not None:
            parts.append(f"last delivered {deadhead} mi away in {delivery['city']}, {delivery['state']}")
        else:
            parts.append("no delivery history to estimate current position")

        recommendations.append(
            CarrierRecommendation(
                carrier_id=c["id"], carrier_name=c["name"], mc_number=c["mc_number"], dot_number=c["dot_number"],
                has_hauled_this_lane=stats["count"] > 0,
                lane_match_count=stats["count"],
                deadhead_miles=deadhead,
                justification="; ".join(parts),
                equipment_filter_relaxed=equipment_filter_relaxed,
            )
        )

    recommendations.sort(
        key=lambda r: (
            not r.has_hauled_this_lane,  # False (hauled) sorts before True (hasn't)
            -lane_stats.get(r.carrier_id, {"score": 0})["score"],
            r.deadhead_miles if r.deadhead_miles is not None else Decimal("999999"),
        )
    )
    return recommendations[:top_n]


def predict_rate(cur, load_id: str, min_comps: int = 5, absolute_min_comps: int = 3, window_days: int = 90) -> RatePrediction:
    ctx = _load_context(cur, load_id)
    window_start = date.today() - timedelta(days=window_days)

    def _fetch_comps(same_lane: bool) -> list[tuple[Decimal, Decimal]]:
        lane_clause = "AND pu.market_area = %(origin_market)s AND do_.market_area = %(destination_market)s" if same_lane else ""
        cur.execute(
            f"""
            SELECT l.distance_miles, {_EFFECTIVE_CARRIER_RATE_SQL} AS carrier_rate
            FROM loads l
            JOIN stops pu ON pu.load_id = l.id AND pu.is_pickup
            JOIN stops do_ ON do_.load_id = l.id AND do_.is_dropoff
            WHERE l.broker_id = %(broker_id)s
              AND l.status = 'COMPLETED'
              AND l.equipment_type = %(equipment_type)s
              AND l.source_created_at >= %(window_start)s
              {lane_clause}
            """,
            {
                "broker_id": ctx.broker_id, "equipment_type": ctx.equipment_type,
                "origin_market": ctx.origin_market_area, "destination_market": ctx.destination_market_area,
                "window_start": window_start,
            },
        )
        return [(row[0], row[1]) for row in cur.fetchall() if row[1] is not None]

    comps = _fetch_comps(same_lane=True)
    is_low_confidence = False
    scope_desc = f"the {ctx.origin_market_area} -> {ctx.destination_market_area} lane"

    if len(comps) < min_comps:
        comps = _fetch_comps(same_lane=False)
        is_low_confidence = True
        scope_desc = f"{ctx.equipment_type} loads broker-wide (not enough same-lane history)"

    if len(comps) < absolute_min_comps:
        explanation = (
            f"Not enough data to predict a rate: found only {len(comps)} completed comparable "
            f"load{'s' if len(comps) != 1 else ''} ({scope_desc}, last {window_days} days) -- need at least "
            f"{absolute_min_comps} even after broadening beyond the exact lane."
        )
        return RatePrediction(
            is_available=False, predicted_total_usd=None, low_usd=None, high_usd=None,
            comparable_load_count=len(comps), is_low_confidence=True, explanation=explanation,
        )

    rates_per_mile = [float(rate) / float(miles) for miles, rate in comps]
    median_rpm = statistics.median(rates_per_mile)
    quantiles = statistics.quantiles(rates_per_mile, n=4) if len(rates_per_mile) >= 4 else [min(rates_per_mile), median_rpm, max(rates_per_mile)]
    p25, p75 = quantiles[0], quantiles[-1]

    distance = float(ctx.distance_miles)
    predicted = Decimal(str(round(median_rpm * distance, 2)))
    low = Decimal(str(round(p25 * distance, 2)))
    high = Decimal(str(round(p75 * distance, 2)))

    explanation = (
        f"Median of {len(comps)} comparable completed loads over {scope_desc} in the last {window_days} days: "
        f"${median_rpm:.2f}/mi x {distance:.0f} mi = ${predicted}. Typical range ${low}-${high}."
    )
    if is_low_confidence:
        explanation += " Low confidence -- based on broad market data, not this specific lane."

    return RatePrediction(
        is_available=True, predicted_total_usd=predicted, low_usd=low, high_usd=high,
        comparable_load_count=len(comps), is_low_confidence=is_low_confidence, explanation=explanation,
    )

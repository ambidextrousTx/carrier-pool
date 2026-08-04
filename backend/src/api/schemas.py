from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

LoadStatusStr = Literal["PLANNED", "ACTIVE", "COVERED", "IN_TRANSIT", "DELIVERED", "COMPLETED"]


class BrokerOut(BaseModel):
    id: str
    name: str


class LoadSummaryOut(BaseModel):
    id: str
    status: LoadStatusStr
    equipment_type: str
    origin_market_area: str
    destination_market_area: str
    origin_city: str
    origin_state: str
    destination_city: str
    destination_state: str
    pickup_date: date | None
    distance_miles: float


class LoadDetailOut(LoadSummaryOut):
    delivery_date: date | None
    carrier_id: str | None


class CarrierRecommendationOut(BaseModel):
    carrier_id: str
    carrier_name: str
    mc_number: str | None
    dot_number: str | None
    has_hauled_this_lane: bool
    lane_match_count: int
    deadhead_miles: float | None
    justification: str
    equipment_filter_relaxed: bool


class RatePredictionOut(BaseModel):
    is_available: bool
    # Money fields are strings, not floats -- deliberately. Everything
    # upstream of this response goes out of its way to keep money exact
    # (Decimal(str(x)), never Decimal(x) -- see the project's own Gotcha
    # #7); serializing as float here would silently undo that at the very
    # last step, right before it reaches whoever's reading the number.
    predicted_total_usd: str | None
    low_usd: str | None
    high_usd: str | None
    comparable_load_count: int
    is_low_confidence: bool
    explanation: str

    @classmethod
    def from_engine(cls, rate) -> "RatePredictionOut":
        def money(v: Decimal | None) -> str | None:
            return str(v) if v is not None else None

        return cls(
            is_available=rate.is_available,
            predicted_total_usd=money(rate.predicted_total_usd),
            low_usd=money(rate.low_usd),
            high_usd=money(rate.high_usd),
            comparable_load_count=rate.comparable_load_count,
            is_low_confidence=rate.is_low_confidence,
            explanation=rate.explanation,
        )


class RecommendationOut(BaseModel):
    load_id: str
    carrier_recommendations: list[CarrierRecommendationOut]
    # Populated only when carrier_recommendations is empty -- an empty
    # list is not self-explanatory on its own (out of carriers entirely?
    # a bug? no data seeded?), and "must be able to see why" applies just
    # as much to zero recommendations as it does to a missing rate.
    carrier_recommendations_note: str | None
    rate_prediction: RatePredictionOut

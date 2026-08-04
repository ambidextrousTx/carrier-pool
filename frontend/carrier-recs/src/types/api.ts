// src/types/api.ts

export type LoadStatus =
  | 'PLANNED'
  | 'ACTIVE'
  | 'COVERED'
  | 'IN_TRANSIT'
  | 'DELIVERED'
  | 'COMPLETED';

export interface BrokerOut {
  id: string;
  name: string;
  // Note: if slug isn't on BrokerOut, id will be used as the URL slug/identifier
}

export interface LoadSummaryOut {
  id: string;
  status: LoadStatus;
  equipment_type: string;
  origin_market_area: string;
  destination_market_area: string;
  origin_city: string;
  origin_state: string;
  destination_city: string;
  destination_state: string;
  pickup_date: string | null; // YYYY-MM-DD
  distance_miles: number;
}

export interface LoadDetailOut extends LoadSummaryOut {
  delivery_date: string | null; // YYYY-MM-DD
  carrier_id: string | null;
}

export interface CarrierRecommendationOut {
  carrier_id: string;
  carrier_name: string;
  mc_number: string | null;
  dot_number: string | null;
  has_hauled_this_lane: boolean;
  lane_match_count: number;
  deadhead_miles: number | null;
  justification: string;
  equipment_filter_relaxed: boolean;
}

export interface RatePredictionOut {
  is_available: boolean;
  predicted_total_usd: string | null; // Decimal as string e.g. "1550.00"
  low_usd: string | null;
  high_usd: string | null;
  comparable_load_count: number;
  is_low_confidence: boolean;
  explanation: string;
}

export interface RecommendationOut {
  load_id: string;
  carrier_recommendations: CarrierRecommendationOut[];
  carrier_recommendations_note: string | null;
  rate_prediction: RatePredictionOut;
}

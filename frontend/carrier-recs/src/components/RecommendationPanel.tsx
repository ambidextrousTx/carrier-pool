import React, { useEffect, useState } from 'react';
import type { RecommendationOut } from '../types/api';
import { useBroker } from '../context/BrokerContext';
import { formatUSD } from '../utils/formatters';

interface RecommendationPanelProps {
  loadId: string | null;
  fetchRecommendationFn?: (brokerId: string, loadId: string) => Promise<RecommendationOut>;
}

export const RecommendationPanel: React.FC<RecommendationPanelProps> = ({
  loadId,
  fetchRecommendationFn,
}) => {
  const { activeBrokerSlug } = useBroker();
  const [recommendation, setRecommendation] = useState<RecommendationOut | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeBrokerSlug || !loadId) {
      setRecommendation(null);
      return;
    }

    let isMounted = true;
    const getRecommendation = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const fetcher = fetchRecommendationFn || (async (bId: string, lId: string) => {
          const res = await fetch(`/brokers/${bId}/loads/${lId}/recommendation`);
          if (!res.ok) throw new Error('Failed to fetch carrier recommendations');
          return res.json();
        });

        const data = await fetcher(activeBrokerSlug, loadId);
        if (isMounted) {
          setRecommendation(data);
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Error fetching recommendations');
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    getRecommendation();

    return () => {
      isMounted = false;
    };
  }, [activeBrokerSlug, loadId, fetchRecommendationFn]);

  if (!loadId) {
    return (
      <div className="h-full flex items-center justify-center p-8 text-gray-400 border border-dashed rounded-lg bg-gray-50">
        Select an active load from the left to view price estimates and ranked carriers.
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="p-8 text-center text-gray-500 border rounded-lg bg-white shadow-sm" data-testid="recommendation-loading">
        Analyzing historical lane data and ranking carriers...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-red-50 text-red-700 rounded-md border border-red-200">
        {error}
      </div>
    );
  }

  if (!recommendation) return null;

  const { rate_prediction, carrier_recommendations, carrier_recommendations_note } = recommendation;

  return (
    <div className="space-y-6" data-testid="recommendation-panel">
      {/* RATE PREDICTION SECTION */}
      <div className="bg-white border rounded-lg p-5 shadow-sm">
        <div className="flex items-center justify-between pb-3 border-b mb-4">
          <h3 className="text-lg font-bold text-gray-800">Carrier Rate Prediction</h3>
          {rate_prediction.is_low_confidence && (
            <span className="px-2.5 py-1 text-xs font-semibold rounded bg-amber-100 text-amber-800 border border-amber-200">
              ⚠️ Low Confidence Prediction
            </span>
          )}
        </div>

        {rate_prediction.is_available ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
            <div className="p-3 bg-blue-50/70 rounded-lg border border-blue-100">
              <span className="text-xs uppercase tracking-wider text-blue-700 font-bold block mb-1">
                Target Rate
              </span>
              <span className="text-2xl font-extrabold text-blue-900">
                {formatUSD(rate_prediction.predicted_total_usd)}
              </span>
            </div>

            <div className="p-3 bg-gray-50 rounded-lg border">
              <span className="text-xs uppercase tracking-wider text-gray-500 font-medium block mb-1">
                Expected Range
              </span>
              <span className="text-lg font-bold text-gray-700">
                {formatUSD(rate_prediction.low_usd)} – {formatUSD(rate_prediction.high_usd)}
              </span>
            </div>

            <div className="p-3 bg-gray-50 rounded-lg border">
              <span className="text-xs uppercase tracking-wider text-gray-500 font-medium block mb-1">
                Comps Used
              </span>
              <span className="text-lg font-bold text-gray-700">
                {rate_prediction.comparable_load_count} historical loads
              </span>
            </div>
          </div>
        ) : (
          <div className="p-4 bg-gray-50 text-gray-600 rounded text-sm italic mb-4">
            Insufficient historical lane data to generate a rate prediction.
          </div>
        )}

        <p className="text-xs text-gray-600 bg-gray-50 p-3 rounded border border-gray-100">
          <strong className="text-gray-700">Model Explanation:</strong> {rate_prediction.explanation}
        </p>
      </div>

      {/* CARRIER RANKINGS SECTION */}
      <div className="bg-white border rounded-lg p-5 shadow-sm">
        <div className="flex items-center justify-between pb-3 border-b mb-4">
          <h3 className="text-lg font-bold text-gray-800">
            Recommended Carriers{' '}
            <span className="text-sm font-normal text-gray-500">
              ({carrier_recommendations.length})
            </span>
          </h3>
        </div>

        {/* Empty Carrier List State (Rule 11/12) */}
        {carrier_recommendations.length === 0 ? (
          <div className="p-4 bg-amber-50 text-amber-900 border border-amber-200 rounded-lg text-sm">
            <p className="font-semibold mb-1">No Carrier Matches Found</p>
            <p>{carrier_recommendations_note || 'No matching carriers available for this load criteria.'}</p>
          </div>
        ) : (
          <div className="space-y-4">
            {carrier_recommendations.map((carrier, idx) => (
              <div
                key={carrier.carrier_id}
                className="p-4 border rounded-lg hover:border-blue-300 transition-colors bg-white shadow-2xs"
                data-testid={`carrier-card-${carrier.carrier_id}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-2 mb-2">
                  <div className="flex items-center space-x-3">
                    <span className="flex items-center justify-center w-6 h-6 rounded-full bg-blue-600 text-white text-xs font-bold">
                      #{idx + 1}
                    </span>
                    <div>
                      <h4 className="font-bold text-gray-900 text-base">{carrier.carrier_name}</h4>
                      <div className="text-xs text-gray-500 space-x-2">
                        {carrier.mc_number && <span>MC: {carrier.mc_number}</span>}
                        {carrier.dot_number && <span>DOT: {carrier.dot_number}</span>}
                      </div>
                    </div>
                  </div>

                  {/* Feature Badges */}
                  <div className="flex flex-wrap gap-1.5 text-xs font-medium">
                    {carrier.has_hauled_this_lane && (
                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200">
                        {carrier.lane_match_count}x Lane Match
                      </span>
                    )}
                    {carrier.deadhead_miles !== null && (
                      <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-800 border">
                        {carrier.deadhead_miles} mi deadhead
                      </span>
                    )}
                    {carrier.equipment_filter_relaxed && (
                      <span className="px-2 py-0.5 rounded bg-amber-100 text-amber-800 border border-amber-200">
                        Equipment Relaxed
                      </span>
                    )}
                  </div>
                </div>

                <p className="mt-3 text-sm text-gray-700 bg-gray-50 p-2.5 rounded border border-gray-100">
                  <span className="font-semibold text-gray-900">Justification: </span>
                  {carrier.justification}
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

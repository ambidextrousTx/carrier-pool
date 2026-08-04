import React, { useEffect, useState } from 'react';
import type { LoadSummaryOut } from '../types/api';
import { useBroker } from '../context/BrokerContext';
import { formatLocation } from '../utils/formatters';

interface LoadListProps {
  selectedLoadId: string | null;
  onSelectLoad: (loadId: string) => void;
  fetchLoadsFn?: (brokerId: string) => Promise<LoadSummaryOut[]>; // For test injection
}

export const LoadList: React.FC<LoadListProps> = ({
  selectedLoadId,
  onSelectLoad,
  fetchLoadsFn,
}) => {
  const { activeBrokerSlug } = useBroker();
  const [loads, setLoads] = useState<LoadSummaryOut[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!activeBrokerSlug) return;

    let isMounted = true;
    const getLoads = async () => {
      try {
        setIsLoading(true);
        setError(null);

        const fetcher = fetchLoadsFn || (async (brokerId: string) => {
          const res = await fetch(`/brokers/${brokerId}/loads?status=ACTIVE`);
          if (!res.ok) throw new Error('Failed to load active shipments');
          return res.json();
        });

        const data = await fetcher(activeBrokerSlug);
        if (isMounted) {
          setLoads(data);
          // Auto-select the first load if none selected
          if (data.length > 0 && !selectedLoadId) {
            onSelectLoad(data[0].id);
          }
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Error loading shipments');
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    };

    getLoads();

    return () => {
      isMounted = false;
    };
  }, [activeBrokerSlug, fetchLoadsFn]);

  if (!activeBrokerSlug) {
    return <div className="p-4 text-gray-500">Select a broker to view loads.</div>;
  }

  if (isLoading) {
    return (
      <div className="p-6 text-center text-gray-500" data-testid="load-list-spinner">
        Loading active loads...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 m-4 bg-red-50 text-red-700 rounded-md border border-red-200">
        {error}
      </div>
    );
  }

  if (loads.length === 0) {
    return (
      <div className="p-6 text-center text-gray-500 border rounded-lg bg-gray-50">
        No active loads found for this broker.
      </div>
    );
  }

  return (
    <div className="border rounded-lg bg-white shadow-sm overflow-hidden">
      <div className="p-4 bg-gray-50 border-b flex justify-between items-center">
        <h2 className="text-lg font-semibold text-gray-800">
          Active Loads <span className="text-sm font-normal text-gray-500">({loads.length})</span>
        </h2>
      </div>

      <div className="divide-y divide-gray-200 max-h-[70vh] overflow-y-auto">
        {loads.map((load) => {
          const isSelected = load.id === selectedLoadId;
          return (
            <div
              key={load.id}
              onClick={() => onSelectLoad(load.id)}
              className={`p-4 cursor-pointer transition-colors hover:bg-blue-50/50 ${
                isSelected ? 'bg-blue-50 border-l-4 border-blue-600' : ''
              }`}
              data-testid={`load-item-${load.id}`}
            >
              <div className="flex justify-between items-start mb-2">
                <span className="font-mono text-sm font-bold text-gray-900">
                  {load.id}
                </span>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800">
                  {load.equipment_type}
                </span>
              </div>

              <div className="text-sm font-medium text-gray-800">
                {formatLocation(load.origin_city, load.origin_state, load.origin_market_area)}
                <span className="mx-2 text-gray-400">➔</span>
                {formatLocation(load.destination_city, load.destination_state, load.destination_market_area)}
              </div>

              <div className="mt-2 flex items-center justify-between text-xs text-gray-500">
                <span>Pickup: {load.pickup_date || 'TBD'}</span>
                <span>{load.distance_miles.toLocaleString()} mi</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

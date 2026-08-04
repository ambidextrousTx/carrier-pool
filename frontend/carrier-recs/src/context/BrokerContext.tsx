import React, { createContext, useContext, useState, useEffect } from 'react';
import { Broker } from '../types/api';

interface BrokerContextType {
  activeBrokerSlug: string | null;
  brokers: Broker[];
  setActiveBrokerSlug: (slug: string) => void;
  isLoadingBrokers: boolean;
  error: string | null;
}

const BrokerContext = createContext<BrokerContextType | undefined>(undefined);

export const BrokerProvider: React.FC<{
  children: React.ReactNode;
  fetchBrokersFn?: () => Promise<Broker[]>; // Dependency injection for easier testing
}> = ({ children, fetchBrokersFn }) => {
  const [brokers, setBrokers] = useState<Broker[]>([]);
  const [activeBrokerSlug, setActiveBrokerSlug] = useState<string | null>(null);
  const [isLoadingBrokers, setIsLoadingBrokers] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;
    
    const loadBrokers = async () => {
      try {
        setIsLoadingBrokers(true);
        // Default fetch mechanism if no mock/custom fetch provided
        const fetchFn = fetchBrokersFn || (async () => {
          const res = await fetch('/brokers');
          if (!res.ok) throw new Error('Failed to fetch brokers');
          return res.json();
        });

        const data = await fetchFn();
        if (isMounted) {
          setBrokers(data);
          if (data.length > 0 && !activeBrokerSlug) {
            const defaultId = data[0].slug || data[0].id; // <--- Handles both slug and id!
            setActiveBrokerSlug(defaultId);
          }
        }
      } catch (err: any) {
        if (isMounted) {
          setError(err.message || 'Unknown error');
        }
      } finally {
        if (isMounted) setIsLoadingBrokers(false);
      }
    };

    loadBrokers();

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <BrokerContext.Provider
      value={{
        activeBrokerSlug,
        brokers,
        setActiveBrokerSlug,
        isLoadingBrokers,
        error,
      }}
    >
      {children}
    </BrokerContext.Provider>
  );
};

export const useBroker = (): BrokerContextType => {
  const context = useContext(BrokerContext);
  if (!context) {
    throw new Error('useBroker must be used within a BrokerProvider');
  }
  return context;
};

import React, { useState } from 'react';
import { BrokerProvider, useBroker } from './context/BrokerContext';
import { LoadList } from './components/LoadList';
import { RecommendationPanel } from './components/RecommendationPanel';

const HeaderBar: React.FC = () => {
  const { activeBrokerSlug, brokers, setActiveBrokerSlug, isLoadingBrokers } = useBroker();

  return (
    <header className="bg-slate-900 text-white px-6 py-4 shadow-md flex justify-between items-center">
      <div className="flex items-center space-x-3">
        <span className="text-xl">🚛</span>
        <div>
          <h1 className="text-lg font-bold leading-tight">Carrier Match Engine</h1>
          <p className="text-xs text-slate-400">Multi-Tenant Freight Recommendation System</p>
        </div>
      </div>

      {/* Tenant Switcher Dropdown (Rule 9 / 17) */}
      <div className="flex items-center space-x-3">
        <label htmlFor="broker-select" className="text-xs text-slate-300 font-medium">
          Active Broker Tenant:
        </label>
        {isLoadingBrokers ? (
          <span className="text-xs text-slate-400">Loading tenants...</span>
        ) : (
            <select
              id="broker-select"
              value={activeBrokerSlug || ''}
              onChange={(e) => setActiveBrokerSlug(e.target.value)}
              className="bg-slate-800 border border-slate-700 text-slate-100 text-sm rounded-md px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 font-medium"
              data-testid="tenant-switcher"
            >
              {brokers.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.id})
                </option>
              ))}
            </select>
          )}
      </div>
    </header>
  );
};

const Workspace: React.FC = () => {
  const [selectedLoadId, setSelectedLoadId] = useState<string | null>(null);
  const { activeBrokerSlug } = useBroker();

  // Reset selected load when tenant switches
  React.useEffect(() => {
    setSelectedLoadId(null);
  }, [activeBrokerSlug]);

  return (
    <div className="min-h-screen bg-slate-100 flex flex-col font-sans">
      <HeaderBar />
      <main className="flex-1 p-6 max-w-[1400px] mx-auto w-full">
        {/* Header Title Banner */}
        <div className="mb-6 flex flex-col md:flex-row md:items-center md:justify-between gap-2 border-b border-slate-200 pb-4">
          <div>
            <h2 className="text-2xl font-bold text-slate-900 tracking-tight">Load Matching Workspace</h2>
            <p className="text-sm text-slate-500">
              Active load dispatch recommendations, rate predictions, and carrier lane analytics.
            </p>
          </div>
        </div>

        {/* Split Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
          {/* Left Column: Fixed height scrolling list */}
          <div className="lg:col-span-5 xl:col-span-4 sticky top-6">
            <LoadList
              selectedLoadId={selectedLoadId}
              onSelectLoad={(loadId) => setSelectedLoadId(loadId)}
            />
          </div>

          {/* Right Column: Detailed Recommendations */}
          <div className="lg:col-span-7 xl:col-span-8">
            <RecommendationPanel loadId={selectedLoadId} />
          </div>
        </div>
      </main>

    </div>
  );
};

export function App() {
  return (
    <BrokerProvider>
      <Workspace />
    </BrokerProvider>
  );
}

export default App;

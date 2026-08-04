import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { RecommendationPanel } from '../RecommendationPanel';
import { BrokerProvider } from '../../context/BrokerContext';
import type { RecommendationOut } from '../../types/api';

const mockRecommendation: RecommendationOut = {
  load_id: 'LOAD-101',
  carrier_recommendations: [
    {
      carrier_id: 'CARR-1',
      carrier_name: 'Swift Hauling LLC',
      mc_number: 'MC123456',
      dot_number: 'DOT98765',
      has_hauled_this_lane: true,
      lane_match_count: 5,
      deadhead_miles: 14.2,
      justification: 'Completed 5 loads on this exact lane in last 60 days.',
      equipment_filter_relaxed: false,
    },
  ],
  carrier_recommendations_note: null,
  rate_prediction: {
    is_available: true,
    predicted_total_usd: '1850.00',
    low_usd: '1700.00',
    high_usd: '2000.00',
    comparable_load_count: 12,
    is_low_confidence: false,
    explanation: 'Based on 12 recent loads in Chicago -> Dallas corridor.',
  },
};

const renderWithBroker = (ui: React.ReactNode) => {
  return render(
    <BrokerProvider fetchBrokersFn={async () => [{ id: 'broker-1', name: 'Acme Freight', slug: 'broker-1' }]}>
      {ui}
    </BrokerProvider>
  );
};

describe('RecommendationPanel', () => {
  it('renders target rate and ranked carriers when data is returned', async () => {
    const mockFetcher = vi.fn().mockResolvedValue(mockRecommendation);

    renderWithBroker(<RecommendationPanel loadId="LOAD-101" fetchRecommendationFn={mockFetcher} />);

    // Wait for panel to load
    const panel = await screen.findByTestId('recommendation-panel');
    expect(panel).toBeInTheDocument();

    // Check rate prediction
    expect(screen.getByText('$1,850.00')).toBeInTheDocument();
    expect(screen.getByText('$1,700.00 – $2,000.00')).toBeInTheDocument();

    // Check carrier details
    expect(screen.getByText('Swift Hauling LLC')).toBeInTheDocument();
    expect(screen.getByText('5x Lane Match')).toBeInTheDocument();
    expect(screen.getByText('14.2 mi deadhead')).toBeInTheDocument();
    expect(screen.getByText(/Completed 5 loads on this exact lane/i)).toBeInTheDocument();
  });

  it('renders carrier recommendations note when carrier array is empty', async () => {
    const emptyRec: RecommendationOut = {
      ...mockRecommendation,
      carrier_recommendations: [],
      carrier_recommendations_note: 'No carriers within 50 mile deadhead radius.',
    };

    const mockFetcher = vi.fn().mockResolvedValue(emptyRec);

    renderWithBroker(<RecommendationPanel loadId="LOAD-101" fetchRecommendationFn={mockFetcher} />);

    await screen.findByTestId('recommendation-panel');

    expect(screen.getByText('No Carrier Matches Found')).toBeInTheDocument();
    expect(screen.getByText('No carriers within 50 mile deadhead radius.')).toBeInTheDocument();
  });
});

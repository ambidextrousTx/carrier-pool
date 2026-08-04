// src/components/__tests__/LoadList.test.tsx

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { LoadList } from '../LoadList';
import { BrokerProvider } from '../../context/BrokerContext';
import type { LoadSummaryOut } from '../../types/api';

const mockLoads: LoadSummaryOut[] = [
  {
    id: 'LOAD-101',
    status: 'ACTIVE',
    equipment_type: 'REEFER',
    origin_market_area: 'Chicago Market',
    destination_market_area: 'Dallas Market',
    origin_city: 'Chicago',
    origin_state: 'IL',
    destination_city: 'Dallas',
    destination_state: 'TX',
    pickup_date: '2026-08-10',
    distance_miles: 925,
  },
  {
    id: 'LOAD-102',
    status: 'ACTIVE',
    equipment_type: 'DRY_VAN',
    origin_market_area: 'Atlanta Market',
    destination_market_area: 'Miami Market',
    origin_city: 'Atlanta',
    origin_state: 'GA',
    destination_city: 'Miami',
    destination_state: 'FL',
    pickup_date: '2026-08-11',
    distance_miles: 660,
  },
];

const renderWithBroker = (ui: React.ReactNode) => {
  return render(
    <BrokerProvider 
      fetchBrokersFn={async () => [{ id: 'broker-1', name: 'Acme Logistics', slug: 'broker-1' }]}
    >
      {ui}
    </BrokerProvider>
  );
};

describe('LoadList', () => {
  it('renders list of active loads and calls onSelectLoad when clicked', async () => {
    const handleSelect = vi.fn();
    const mockFetchLoads = vi.fn().mockResolvedValue(mockLoads);

    renderWithBroker(
      <LoadList selectedLoadId="LOAD-101" onSelectLoad={handleSelect} fetchLoadsFn={mockFetchLoads} />
    );

    // Wait until testid appears in DOM
    const loadItem1 = await screen.findByTestId('load-item-LOAD-101');
    expect(loadItem1).toBeInTheDocument();

    const loadItem2 = await screen.findByTestId('load-item-LOAD-102');
    expect(loadItem2).toBeInTheDocument();

    // Verify text within the load item
    expect(loadItem1).toHaveTextContent('LOAD-101');
    expect(loadItem1).toHaveTextContent('Chicago, IL (Chicago Market)');

    // Click second load item
    fireEvent.click(loadItem2);
    expect(handleSelect).toHaveBeenCalledWith('LOAD-102');
  });
});

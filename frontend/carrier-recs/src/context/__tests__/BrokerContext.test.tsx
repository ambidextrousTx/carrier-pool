import { render, screen, act } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import React from 'react';
import { BrokerProvider, useBroker } from '../BrokerContext';

const TestComponent = () => {
  const { activeBrokerSlug, brokers, setActiveBrokerSlug, isLoadingBrokers } = useBroker();

  if (isLoadingBrokers) return <div>Loading...</div>;

  return (
    <div>
      <span data-testid="active-slug">{activeBrokerSlug}</span>
      <ul>
        {brokers.map((b) => (
          <li key={b.slug} onClick={() => setActiveBrokerSlug(b.slug)}>
            {b.name}
          </li>
        ))}
      </ul>
    </div>
  );
};

describe('BrokerContext', () => {
  const mockBrokers = [
    { slug: 'acme-freight', name: 'Acme Freight' },
    { slug: 'apex-logistics', name: 'Apex Logistics' },
  ];

  it('loads brokers and sets the first broker as active by default', async () => {
    const mockFetch = async () => mockBrokers;

    render(
      <BrokerProvider fetchBrokersFn={mockFetch}>
        <TestComponent />
      </BrokerProvider>
    );

    // Verify initial load state
    expect(screen.getByText('Loading...')).toBeInTheDocument();

    // Verify loaded active broker
    const activeSlug = await screen.findByTestId('active-slug');
    expect(activeSlug).toHaveTextContent('acme-freight');
  });

  it('allows switching active broker', async () => {
    const mockFetch = async () => mockBrokers;

    render(
      <BrokerProvider fetchBrokersFn={mockFetch}>
        <TestComponent />
      </BrokerProvider>
    );

    await screen.findByTestId('active-slug');

    // Click second broker
    const secondBrokerItem = screen.getByText('Apex Logistics');
    act(() => {
      secondBrokerItem.click();
    });

    expect(screen.getByTestId('active-slug')).toHaveTextContent('apex-logistics');
  });
});

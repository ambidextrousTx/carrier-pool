import { describe, it, expect } from 'vitest';
import { formatUSD, formatLocation } from '../formatters';

describe('formatUSD', () => {
  it('formats valid string decimal into USD currency', () => {
    expect(formatUSD('1450.50')).toBe('$1,450.50');
    expect(formatUSD('2000')).toBe('$2,000.00');
    expect(formatUSD('1234.5')).toBe('$1,234.50');
  });

  it('handles null, undefined, or invalid inputs gracefully', () => {
    expect(formatUSD(null)).toBe('N/A');
    expect(formatUSD(undefined)).toBe('N/A');
    expect(formatUSD('invalid')).toBe('N/A');
  });
});

describe('formatLocation', () => {
  it('formats city and state correctly', () => {
    expect(formatLocation('Chicago', 'IL')).toBe('Chicago, IL');
  });

  it('includes market area if distinct', () => {
    expect(formatLocation('Joliet', 'IL', 'Chicago Market Area')).toBe('Joliet, IL (Chicago Market Area)');
  });
});

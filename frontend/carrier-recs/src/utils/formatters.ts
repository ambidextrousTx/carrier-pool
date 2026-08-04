// src/utils/formatters.ts

/**
 * Formats stringified decimal numbers as USD currency ($1,234.50)
 */
export const formatUSD = (amountStr: string | null | undefined): string => {
  if (!amountStr) return 'N/A';
  const val = parseFloat(amountStr);
  if (isNaN(val)) return 'N/A';

  const formatted = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    roundingPriority: "lessPrecision"
  }).format(val);

  // Normalize any non-breaking space quirks across Node environments
  return formatted.replace(/\u00A0/g, ' ');
};

/**
 * Formats market area/city display
 */
export const formatLocation = (city: string, state: string, marketArea?: string): string => {
  const cityState = `${city}, ${state}`;
  if (marketArea && marketArea.toLowerCase() !== `${city.toLowerCase()}, ${state.toLowerCase()}`) {
    return `${cityState} (${marketArea})`;
  }
  return cityState;
};

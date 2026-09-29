/** Trims float noise: 0.05000000000000001 -> "0.05", 2 -> "2". */
function plain(value: number): string {
  return String(Number(value.toFixed(6)))
}

export const formatPercent = (value: number) => `${value.toFixed(2)}%`

/** A denom in cents, as the game shows it: 200 -> "200c". */
export const formatDenom = (cents: number) => `${plain(cents)}c`

/** What one credit is worth at a denom in cents: 200 -> "2", 1 -> "0.01". */
export const formatPerCredit = (cents: number) => plain(cents / 100)

/** Supported denoms are shown as the log writes them: "1.000, 2.000". */
export const formatDenomList = (denoms: number[]) => denoms.map((d) => d.toFixed(3)).join(', ')

export const formatWeight = (weight: number) => weight.toLocaleString('en-US')

/**
 * "4.61% (1 in 22)". Two significant digits at least, so a rare outcome is not shown as 0.00%:
 * 0.20%, 0.040%, 0.000040%.
 */
export function formatProbability(probability: number): string {
  if (probability <= 0) return '0%'
  const percent = probability * 100
  const decimals = percent >= 0.1 ? 2 : Math.min(6, 1 - Math.floor(Math.log10(percent)))
  const odds = Math.round(1 / probability)
  // Thousands separators only from five digits up, so "1 in 2500" stays as compact as the game's.
  const grouped = new Intl.NumberFormat('en-US', { useGrouping: 'min2' }).format(odds)
  return `${percent.toFixed(decimals)}% (1 in ${grouped})`
}

/** A payout multiplier; whole numbers without a decimal point. */
export const formatPayout = (value: number) => plain(value)

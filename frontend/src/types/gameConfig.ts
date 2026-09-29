import type { GameMode } from '@/types/gameContext'

export interface CurrentPaytable {
  game: string
  mode: GameMode
  /** Null when the game has no log for this mode. */
  log_path: string | null
  /** The log is configured but could not be opened or read. */
  log_unreadable: boolean
  /** Null until the log has reported one. */
  paytable_id: string | null
  /** Cents, as written in the log. */
  denom: number | null
  supported_denoms: number[]
}

export interface PaytableList {
  game: string
  mode: GameMode
  directory: string
  paytables: string[]
}

export type SymbolKind = 'regular' | 'wild' | 'scatter'

export interface SymbolInfo {
  code: string
  name: string
  kind: SymbolKind
}

export interface PaytableSummary {
  display_name: string | null
  return_pct: number | null
  base_return_pct: number | null
  lines: number | null
  min_total_bet: number | null
  max_bets: number[]
}

export interface PaylineSet {
  id: number
  /** lines[n][reel] is the row line n crosses on that reel; 0 is the top row. */
  lines: number[][]
}

export interface WinGeometry {
  file: string
  reels: number
  rows: number
  /** The set this paytable plays, if the file has it. */
  active_set: number | null
  sets: PaylineSet[]
}

export interface PaylineComboRow {
  /** Symbols that pay exactly the same. */
  symbols: string[]
  /** payouts[i] is for a run of `PaylineCombos.lengths[i]`; null when it pays nothing. */
  payouts: (number | null)[]
}

export interface PaylineCombos {
  /** Run lengths present, longest first. */
  lengths: number[]
  rows: PaylineComboRow[]
}

export interface ReelStrip {
  id: string
  stops: string[]
  /** One per stop, in the same order. */
  weights: number[]
}

export interface ReelStripSet {
  id: string
  label: string | null
  visible_rows: number
  /** One per reel; ids may repeat. */
  strip_ids: string[]
}

export interface OrbValue {
  label: string
  jackpot: boolean
  weight: number
  probability: number
}

export interface OrbTable {
  title: string
  table: string
  bet: number
  total_weight: number
  values: OrbValue[]
}

export interface PaytableConfig {
  game: string
  mode: GameMode
  paytable_id: string
  summary: PaytableSummary
  symbols: SymbolInfo[]
  win_geometry: WinGeometry | null
  payline_combos: PaylineCombos | null
  default_reel_strip_set: string | null
  reel_strip_sets: ReelStripSet[]
  reel_strips: ReelStrip[]
  orb_tables: OrbTable[]
  /** Sections that could not be built, and why. */
  warnings: string[]
}

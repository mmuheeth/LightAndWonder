import type { PayKind } from '@/types/gameConfig'
import type { GameMode } from '@/types/gameContext'
import type { RoiImage } from '@/types/roi'

/** What was read in one grid position. Both indexes start at 0; `column` is the reel. */
export interface PaylineCell {
  row: number
  column: number
  /** The symbol; null when the classifier was under the confidence floor, so the tile counts as unread. */
  code: string | null
  /** The classifier's best guess, however unsure it was. */
  guess: string
  name: string | null
  /** Percent (0-100). */
  confidence: number
}

/**
 * One reel's symbol on a line against the next reel's. same: the same symbol; wild: a wild stands in
 * for the other; different: the run ends here; unknown: one of the two was unread.
 */
export type StepRelation = 'same' | 'wild' | 'different' | 'unknown'

export interface PaylineStep {
  relation: StepRelation
  /** Whether the step decided the run: its matches, and the step that ended it. Later steps only show how the tiles compare. */
  counted: boolean
}

/** The bet the awards were worked out for, from the game log. */
export interface PaylineBet {
  /** Cents, as written in the log. */
  denom: number
  /** Cents bet on each line (each way): the credits times the denom. */
  bets_per_unit: number
  /** Credits bet on each line (way): what a combo's value is multiplied by. */
  credits_per_unit: number
  /** Credits bet on the spin. */
  total_bet: number
}

/** The payline combo a line was paid by. */
export interface PaidCombo {
  /** The ComboID in math.xml. */
  id: number | null
  /** One entry per reel: the run, then ANY for the reels that do not matter. */
  pattern: string[]
  value: number
}

export interface PaylineOutcome {
  /** 1-based: the first line of the set is line 1. */
  number: number
  /** One per reel, left to right: the positions the line crosses. */
  cells: PaylineCell[]
  /** Between neighbouring cells, so one fewer than the cells. */
  steps: PaylineStep[]
  /** What the run is of (the paying combo's symbol, if it paid); null when the first cell was unread. */
  symbol: string | null
  symbol_name: string | null
  /** Reels in the run from the left, wilds included. */
  matches: number
  combo: PaidCombo | null
  /** What the combo pays for one credit bet on the line. */
  pays: number
  /** What the line pays at the bet that was played: `pays` times the credits bet on each line. */
  credits: number
  /** A run of two or more of a symbol the paytable pays for other run lengths, but not this one. */
  unpaid: boolean
  /** An unread tile on the line could make it pay, or pay more, than it does here. */
  uncertain: boolean
}

/** One symbol of a ways paytable: the run it makes over neighbouring reels from the left, on any rows. */
export interface WayOutcome {
  symbol: string
  symbol_name: string | null
  /** One entry per reel counted, left to right: the cells that show the symbol or a wild standing in for it. */
  reels: PaylineCell[][]
  /** Reels counted: the paying combo's length, or the whole run when nothing paid. */
  matches: number
  /** The routes over those reels: the matching cells multiplied reel by reel. */
  ways: number
  combo: PaidCombo | null
  /** The combo's value for each way, times the ways: what the symbol pays for one credit bet on each way. */
  pays: number
  /** What the symbol pays at the bet that was played: `pays` times the credits bet on each way. */
  credits: number
  /** A run of two or more reels that the paytable pays for other run lengths, but not this one. */
  unpaid: boolean
  /** An unread tile could make the symbol pay, or pay more, than it does here. */
  uncertain: boolean
  /** The unread tiles that could change this outcome; empty unless it is uncertain. */
  unread: PaylineCell[]
}

export interface PaylineResult {
  /** The symbol reading (and ROI record) that was scored. */
  reading_id: string
  created_at: string
  game: string
  mode: GameMode
  paytable_id: string
  /** log: the paytable the game log reported last; request: the one asked for. */
  paytable_source: 'log' | 'request'
  /** Whether the paytable pays along lines (`lines` is filled) or by ways (`ways` is). */
  kind: PayKind
  /** The number of lines of the win geometry set that was used; for ways, the ways the grid holds. */
  line_set: number
  /** Percent a tile had to reach to be read. */
  min_confidence: number
  rows: number
  columns: number
  /** The reel grid as cut from the screenshot, for drawing the lines on. */
  reels: RoiImage | null
  /** Row by row, left to right. */
  tiles: PaylineCell[]
  lines: PaylineOutcome[]
  /** Filled for a ways paytable, whose `lines` are empty. */
  ways: WayOutcome[]
  /** Null when the log has reported no bet (or denom) yet: the awards are then for one credit on each line. */
  bet: PaylineBet | null
  /** The credits of every line (or symbol, for ways) added up: the pays times the credits bet on each line. */
  total_credits: number
  /** False when an unread tile could change the total, which is then the least it can be. */
  complete: boolean
}

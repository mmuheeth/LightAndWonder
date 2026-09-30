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
  pays: number
  /** A run of two or more of a symbol the paytable pays for other run lengths, but not this one. */
  unpaid: boolean
  /** An unread tile on the line could make it pay, or pay more, than it does here. */
  uncertain: boolean
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
  /** The number of lines of the win geometry set that was used. */
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
  /** The pays of every line added up, for a credit bet on each line. */
  total_credits: number
  /** False when an unread tile could change the total, which is then the least it can be. */
  complete: boolean
}

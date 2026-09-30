import type { GameMode } from '@/types/gameContext'
import type { RoiImage } from '@/types/roi'

/** A trained classifier, as it was when training finished. */
export interface SymbolModelInfo {
  architecture: string
  trained_at: string
  /** Symbol codes it can name. */
  classes: string[]
  image_count: number
  epochs: number
  /** Percent of the held-out artwork named correctly; null when no symbol had images to hold out. */
  accuracy: number | null
  /** The same for its worst symbol. */
  floor: number | null
  /** Symbols with too few images to check; they are not part of the figures above. */
  unchecked: string[]
}

export interface TrainingProgress {
  epoch: number
  epochs: number
  loss: number | null
}

export type SymbolModelState = 'untrained' | 'training' | 'ready' | 'failed'

export interface SymbolModelStatus {
  game: string
  state: SymbolModelState
  /** Artwork found for the game: a folder per symbol code. */
  dataset_classes: number
  dataset_images: number
  /** Percent a tile must reach to be named; the starting value of the threshold. */
  min_confidence: number
  /** The last finished model, also while another is training. */
  model: SymbolModelInfo | null
  progress: TrainingProgress | null
  error: string | null
}

/** What the classifier read in one grid position. Both indexes start at 0. */
export interface SymbolTile {
  row: number
  column: number
  /** Its best guess, however unsure it was. */
  code: string
  /** The code's name in the game config; null when the config does not name it. */
  name: string | null
  /** Percent (0-100) the classifier puts on `code`. */
  confidence: number
}

export interface SymbolReading {
  /** The id of the ROI record (screenshot and tiles) that was read. */
  id: string
  created_at: string
  game: string
  mode: GameMode
  rows: number
  columns: number
  /** The reel grid as cut from the screenshot; null in readings saved before it was kept. */
  reels: RoiImage | null
  model: SymbolModelInfo
  /** Row by row, left to right. */
  tiles: SymbolTile[]
}

import type { GameMode } from '@/types/gameContext'
import type { ObsScreenshot } from '@/types/obs'

export interface RoiImage {
  /** Path relative to the API base URL. */
  url: string
  width: number
  height: number
}

/** One region of the game config, cut out of the screenshot. */
export interface RoiCrop extends RoiImage {
  /** The game config key: "reels" (the whole grid), "cash_meter", "cyclic_message", ... */
  name: string
  /** Where it was cut: [left, top, right, bottom] as fractions of the screenshot. */
  roi: number[]
}

/** One symbol position of the grid. Both indexes start at 0. */
export interface RoiTile extends RoiImage {
  row: number
  column: number
}

export interface RoiRecord {
  id: string
  created_at: string
  game: string
  mode: GameMode
  screenshot: ObsScreenshot
  crops: RoiCrop[]
  /** 0 when the game has no "reels" region or no reel bounds; `tiles` is then empty. */
  rows: number
  columns: number
  /** Row by row, left to right. */
  tiles: RoiTile[]
}

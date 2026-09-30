import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContext } from '@/types/gameContext'
import type { SymbolModelStatus, SymbolReading } from '@/types/symbols'

// Screenshot, cutting the tiles, and the classifier; the first reading after the backend starts also
// loads the network, which takes a while on a busy machine.
const IDENTIFY_TIMEOUT_MS = 90_000

export function fetchSymbolModel(game: string): Promise<SymbolModelStatus> {
  return unwrap(apiClient.get<ApiResponse<SymbolModelStatus>>('/symbols/model', { params: { game } }))
}

/** Returns at once, with the status showing training; the backend trains in the background. */
export function trainSymbolModel(game: string): Promise<SymbolModelStatus> {
  return unwrap(apiClient.post<ApiResponse<SymbolModelStatus>>('/symbols/model/train', null, { params: { game } }))
}

// The game and mode are always sent, so the reading is for what was on screen when the button was
// pressed even if the selection changes while the request is on its way.
export function identifySymbols({ game, mode }: GameContext): Promise<SymbolReading> {
  return unwrap(
    apiClient.post<ApiResponse<SymbolReading>>('/symbols/identify', null, {
      params: { game, mode },
      timeout: IDENTIFY_TIMEOUT_MS,
    }),
  )
}

/** Newest first; kept on the backend, so it is the same after a page refresh. */
export function fetchSymbolReadings(limit: number): Promise<SymbolReading[]> {
  return unwrap(apiClient.get<ApiResponse<SymbolReading[]>>('/symbols/readings', { params: { limit } }))
}

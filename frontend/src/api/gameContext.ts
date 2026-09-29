import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContextResponse, GameContextUpdate } from '@/types/gameContext'

export function fetchGameContext(): Promise<GameContextResponse> {
  return unwrap(apiClient.get<ApiResponse<GameContextResponse>>('/game-context'))
}

export function updateGameContext(update: GameContextUpdate): Promise<GameContextResponse> {
  return unwrap(apiClient.patch<ApiResponse<GameContextResponse>>('/game-context', update))
}

import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { CyclicRound, CyclicStatus } from '@/types/cyclic'
import type { GameContext } from '@/types/gameContext'

export function fetchCyclicStatus(): Promise<CyclicStatus> {
  return unwrap(apiClient.get<ApiResponse<CyclicStatus>>('/cyclic/status'))
}

// The game and mode are always sent, so what is tracked is what was selected when the button was pressed.
export function startCyclicTracking({ game, mode }: GameContext): Promise<CyclicStatus> {
  return unwrap(apiClient.post<ApiResponse<CyclicStatus>>('/cyclic/tracking/start', null, { params: { game, mode } }))
}

export function stopCyclicTracking(): Promise<CyclicStatus> {
  return unwrap(apiClient.post<ApiResponse<CyclicStatus>>('/cyclic/tracking/stop'))
}

/** Newest first, the round being captured included; kept on the backend, so it is the same after a refresh. */
export function fetchCyclicRounds(limit: number): Promise<CyclicRound[]> {
  return unwrap(apiClient.get<ApiResponse<CyclicRound[]>>('/cyclic/rounds', { params: { limit } }))
}

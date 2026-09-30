import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContext } from '@/types/gameContext'
import type { PaylineResult } from '@/types/paylines'

// Screenshot, cutting the tiles, the classifier and the paytable; the first reading after the backend
// starts also loads the network, which takes a while on a busy machine.
const EVALUATE_TIMEOUT_MS = 90_000

// The game and mode are always sent, so the result is for what was on screen when the button was
// pressed even if the selection changes while the request is on its way. The paytable is the one the
// game log reported last.
export function evaluatePaylines({ game, mode }: GameContext, minConfidence: number): Promise<PaylineResult> {
  return unwrap(
    apiClient.post<ApiResponse<PaylineResult>>('/paylines/evaluate', null, {
      params: { game, mode, min_confidence: minConfidence },
      timeout: EVALUATE_TIMEOUT_MS,
    }),
  )
}

/** Scores a symbol reading that was made before, without a new screenshot. */
export function fetchPaylineScore(reading: string, minConfidence: number): Promise<PaylineResult> {
  return unwrap(
    apiClient.get<ApiResponse<PaylineResult>>('/paylines/score', {
      params: { reading, min_confidence: minConfidence },
    }),
  )
}

import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { CurrentPaytable, PaytableConfig, PaytableList } from '@/types/gameConfig'
import type { GameContext } from '@/types/gameContext'

export function fetchCurrentPaytable(): Promise<CurrentPaytable> {
  return unwrap(apiClient.get<ApiResponse<CurrentPaytable>>('/game-config/current'))
}

// The game and mode are always sent: the selection can change while a request is on its way,
// and what comes back is cached under the game and mode it was asked for.

export function fetchPaytableList({ game, mode }: GameContext): Promise<PaytableList> {
  return unwrap(
    apiClient.get<ApiResponse<PaytableList>>('/game-config/paytables', { params: { game, mode } }),
  )
}

export function fetchPaytableConfig(
  { game, mode }: GameContext,
  paytableId: string,
): Promise<PaytableConfig> {
  return unwrap(
    apiClient.get<ApiResponse<PaytableConfig>>(
      `/game-config/paytables/${encodeURIComponent(paytableId)}`,
      { params: { game, mode } },
    ),
  )
}

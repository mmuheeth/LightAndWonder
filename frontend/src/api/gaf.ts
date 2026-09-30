import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContext } from '@/types/gameContext'
import type { GafActionInfo, GafActionInputs, GafActionResult, GafStatus } from '@/types/gaf'

// The backend gives its status probe 4s, and NRobot can stall for 10-20s when the game drops its link,
// so the poll is answered (as "not reachable, reconnecting") well inside this. The client's default of
// 10s is too tight for a slow machine.
const STATUS_TIMEOUT_MS = 20_000
// Connecting retries while a freshly launched game starts accepting, and can take a while.
const CONNECT_TIMEOUT_MS = 90_000
// A spin is answered once it has settled, and a bonus can keep it playing for as long as the
// backend's settle timeout (2 minutes by default).
const ACTION_TIMEOUT_MS = 150_000

// The game and mode are always sent, so the answer is for what the caller was showing even if the
// selection is still being saved on the backend when the request arrives.

export function fetchGafStatus({ game, mode }: GameContext): Promise<GafStatus> {
  return unwrap(
    apiClient.get<ApiResponse<GafStatus>>('/gaf/status', {
      params: { game, mode },
      timeout: STATUS_TIMEOUT_MS,
    }),
  )
}

export function connectGaf({ game, mode }: GameContext): Promise<GafStatus> {
  return unwrap(
    apiClient.post<ApiResponse<GafStatus>>('/gaf/connect', null, {
      params: { game, mode },
      timeout: CONNECT_TIMEOUT_MS,
    }),
  )
}

export function disconnectGaf({ game, mode }: GameContext): Promise<GafStatus> {
  // Tearing the session down calls NRobot too, so it can meet the same stall as a connect.
  return unwrap(
    apiClient.post<ApiResponse<GafStatus>>('/gaf/disconnect', null, {
      params: { game, mode },
      timeout: CONNECT_TIMEOUT_MS,
    }),
  )
}

export function fetchGafActions({ game, mode }: GameContext): Promise<GafActionInfo[]> {
  return unwrap(apiClient.get<ApiResponse<GafActionInfo[]>>('/gaf/actions', { params: { game, mode } }))
}

export function runGafAction(
  { game, mode }: GameContext,
  actionId: string,
  inputs: GafActionInputs = {},
): Promise<GafActionResult> {
  return unwrap(
    apiClient.post<ApiResponse<GafActionResult>>(
      `/gaf/actions/${encodeURIComponent(actionId)}`,
      Object.keys(inputs).length > 0 ? { params: inputs } : null,
      { params: { game, mode }, timeout: ACTION_TIMEOUT_MS },
    ),
  )
}

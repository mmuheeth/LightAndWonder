import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContext } from '@/types/gameContext'
import type { RoiImage, RoiRecord } from '@/types/roi'

// The backend takes the screenshot and then cuts the images, which takes longer than a query.
const EXTRACT_TIMEOUT_MS = 30_000

// The game and mode are always sent, so the record is for what was on screen when the button
// was pressed even if the selection changes while the request is on its way.
export function extractRoi({ game, mode }: GameContext): Promise<RoiRecord> {
  return unwrap(
    apiClient.post<ApiResponse<RoiRecord>>('/roi/records', null, {
      params: { game, mode },
      timeout: EXTRACT_TIMEOUT_MS,
    }),
  )
}

export function fetchRoiRecords(limit: number): Promise<RoiRecord[]> {
  return unwrap(apiClient.get<ApiResponse<RoiRecord[]>>('/roi/records', { params: { limit } }))
}

/** Absolute URL of a cut-out image, for use in <img src>. */
export function roiImageSrc(image: RoiImage): string {
  return `${apiClient.defaults.baseURL ?? ''}${image.url}`
}

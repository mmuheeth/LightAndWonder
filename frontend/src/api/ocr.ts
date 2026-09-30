import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { GameContext } from '@/types/gameContext'
import type { OcrEngineStatus, OcrRecord } from '@/types/ocr'

// Two screenshots with the meter toggled through GAF in between (and back), then the cutting.
const EXTRACT_TIMEOUT_MS = 60_000
// The first read after the backend starts loads the OCR models (~30-60 s on a busy machine); after that
// reading everything takes 10-15 s.
const READ_TIMEOUT_MS = 300_000

/** Starts loading the OCR models on the backend and returns at once. */
export function warmUpOcr(): Promise<OcrEngineStatus> {
  return unwrap(apiClient.post<ApiResponse<OcrEngineStatus>>('/ocr/engine/warmup'))
}

// The game and mode are always sent, so the record is for what was on screen when the button was pressed
// even if the selection changes while the request is on its way.
export function extractOcr({ game, mode }: GameContext): Promise<OcrRecord> {
  return unwrap(
    apiClient.post<ApiResponse<OcrRecord>>('/ocr/records', null, {
      params: { game, mode },
      timeout: EXTRACT_TIMEOUT_MS,
    }),
  )
}

/** Runs the OCR on a record's images; the record comes back with its readings. */
export function readOcrRecord(recordId: string): Promise<OcrRecord> {
  return unwrap(
    apiClient.post<ApiResponse<OcrRecord>>(`/ocr/records/${recordId}/read`, null, { timeout: READ_TIMEOUT_MS }),
  )
}

/** Newest first; kept on the backend, so it is the same after a page refresh. */
export function fetchOcrRecords(limit: number): Promise<OcrRecord[]> {
  return unwrap(apiClient.get<ApiResponse<OcrRecord[]>>('/ocr/records', { params: { limit } }))
}

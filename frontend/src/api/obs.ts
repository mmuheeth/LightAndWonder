import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type {
  ObsCaptureSetup,
  ObsConfig,
  ObsScreenshot,
  ObsStatus,
  ObsWindow,
} from '@/types/obs'

// Connecting may have to launch OBS and wait for it to start, so it gets a longer timeout.
const CONNECT_TIMEOUT_MS = 60_000

export function fetchObsStatus(): Promise<ObsStatus> {
  return unwrap(apiClient.get<ApiResponse<ObsStatus>>('/obs/status'))
}

export function connectObs(): Promise<ObsStatus> {
  return unwrap(
    apiClient.post<ApiResponse<ObsStatus>>('/obs/connect', null, { timeout: CONNECT_TIMEOUT_MS }),
  )
}

export function disconnectObs(): Promise<ObsStatus> {
  return unwrap(apiClient.post<ApiResponse<ObsStatus>>('/obs/disconnect'))
}

export function takeObsScreenshot(): Promise<ObsScreenshot> {
  return unwrap(apiClient.post<ApiResponse<ObsScreenshot>>('/obs/screenshots'))
}

export function fetchObsScreenshots(limit: number): Promise<ObsScreenshot[]> {
  return unwrap(apiClient.get<ApiResponse<ObsScreenshot[]>>('/obs/screenshots', { params: { limit } }))
}

export function fetchObsConfig(): Promise<ObsConfig> {
  return unwrap(apiClient.get<ApiResponse<ObsConfig>>('/obs/config'))
}

export function updateObsConfig(config: ObsConfig): Promise<ObsConfig> {
  return unwrap(apiClient.put<ApiResponse<ObsConfig>>('/obs/config', config))
}

export function fetchObsWindows(): Promise<ObsWindow[]> {
  return unwrap(apiClient.get<ApiResponse<ObsWindow[]>>('/obs/windows'))
}

export function fetchObsCaptureSetup(): Promise<ObsCaptureSetup> {
  return unwrap(apiClient.get<ApiResponse<ObsCaptureSetup>>('/obs/window'))
}

export function selectObsWindow(window: ObsWindow): Promise<ObsCaptureSetup> {
  return unwrap(apiClient.put<ApiResponse<ObsCaptureSetup>>('/obs/window', window))
}

/** Absolute URL of a screenshot image, for use in <img src>. */
export function obsScreenshotSrc(screenshot: ObsScreenshot): string {
  return `${apiClient.defaults.baseURL ?? ''}${screenshot.url}`
}

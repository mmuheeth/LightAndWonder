export interface ObsStatus {
  obs_running: boolean
  connected: boolean
  recording: boolean
  recording_path: string | null
}

export interface ObsScreenshot {
  filename: string
  created_at: string
  size_bytes: number
  /** Path relative to the API base URL. */
  url: string
}

export interface ObsConfig {
  host: string
  port: number
}

export interface ObsWindow {
  /** OBS's identifier for the window; sent back unchanged to select it. */
  value: string
  name: string
}

export interface ObsCaptureSetup {
  window: ObsWindow | null
  canvas_width: number | null
  canvas_height: number | null
  /** False when the saved window could not be applied; see `warning`. */
  applied: boolean
  warning: string | null
}

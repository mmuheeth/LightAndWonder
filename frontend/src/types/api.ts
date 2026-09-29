export interface ApiError {
  code: string
  message: string
  details?: Record<string, unknown> | null
}

export interface ApiResponseMeta {
  timestamp: string
  path?: string | null
}

export interface ApiResponse<T> {
  success: boolean
  data: T | null
  error: ApiError | null
  meta: ApiResponseMeta
}

import axios, { AxiosError } from 'axios'

import type { ApiError, ApiResponse } from '@/types/api'

export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 10_000,
  headers: {
    'Content-Type': 'application/json',
  },
})

export class ApiRequestError extends Error {
  code: string
  details?: Record<string, unknown> | null
  status?: number

  constructor(error: ApiError, status?: number) {
    super(error.message)
    this.name = 'ApiRequestError'
    this.code = error.code
    this.details = error.details
    this.status = status
  }
}

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<ApiResponse<unknown>>) => {
    const payload = error.response?.data

    if (payload?.error) {
      return Promise.reject(new ApiRequestError(payload.error, error.response?.status))
    }

    return Promise.reject(
      new ApiRequestError(
        { code: 'NETWORK_ERROR', message: error.message },
        error.response?.status,
      ),
    )
  },
)

export async function unwrap<T>(promise: Promise<{ data: ApiResponse<T> }>): Promise<T> {
  const response = await promise
  if (!response.data.success || response.data.data === null) {
    throw new ApiRequestError(
      response.data.error ?? { code: 'UNKNOWN_ERROR', message: 'Unknown API error' },
    )
  }
  return response.data.data
}

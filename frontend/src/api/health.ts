import { apiClient, unwrap } from '@/api/client'
import type { ApiResponse } from '@/types/api'
import type { HealthCheck } from '@/types/health'

export function fetchHealth(): Promise<HealthCheck> {
  return unwrap(apiClient.get<ApiResponse<HealthCheck>>('/health'))
}

import { useQuery } from '@tanstack/react-query'

import { fetchHealth } from '@/api/health'

export function useHealthCheck() {
  return useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 15_000,
    retry: 1,
  })
}

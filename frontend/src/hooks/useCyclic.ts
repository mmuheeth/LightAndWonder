import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchCyclicRounds, fetchCyclicStatus, startCyclicTracking, stopCyclicTracking } from '@/api/cyclic'
import type { CyclicRound, CyclicStatus } from '@/types/cyclic'

/** How many rounds the tab lists. */
const ROUNDS_SHOWN = 20

const STATUS_KEY = ['cyclic', 'status']
const ROUNDS_KEY = ['cyclic', 'rounds']

/** Polled: where the spin is changes every second or so while tracking. */
export function useCyclicStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: fetchCyclicStatus,
    refetchInterval: (query) => (query.state.data?.tracking ? 1_000 : 3_000),
    retry: false,
  })
}

const isUnread = (round: CyclicRound) =>
  round.regions.some((region) => region.messages.some((m) => m.text === null && m.read_error === null))

/**
 * The rounds are files the backend keeps adding to, so they are polled while tracking, and for as long as a message
 * is still waiting to be read (the OCR goes on after tracking is stopped).
 */
export function useCyclicRounds(tracking: boolean) {
  return useQuery({
    queryKey: ROUNDS_KEY,
    queryFn: () => fetchCyclicRounds(ROUNDS_SHOWN),
    refetchInterval: (query) => (tracking || query.state.data?.some(isUnread) ? 1_000 : false),
  })
}

/** Mutations that return the new status write it straight into the status query. */
function useStatusMutation<T>(mutationFn: (variables: T) => Promise<CyclicStatus>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (status) => {
      queryClient.setQueryData(STATUS_KEY, status)
      void queryClient.invalidateQueries({ queryKey: ROUNDS_KEY })
    },
  })
}

export const useStartCyclicTracking = () => useStatusMutation(startCyclicTracking)
export const useStopCyclicTracking = () => useStatusMutation(() => stopCyclicTracking())

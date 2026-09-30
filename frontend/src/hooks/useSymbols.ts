import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchSymbolModel, fetchSymbolReadings, identifySymbols, trainSymbolModel } from '@/api/symbols'
import type { SymbolModelStatus, SymbolReading } from '@/types/symbols'

/** How often the model's status is asked for while it trains. */
const TRAINING_POLL_MS = 2_000

const modelKey = (game: string | undefined) => ['symbols', 'model', game]
export const READINGS_KEY = ['symbols', 'readings']

/** The game's classifier; while it trains, it is polled until it is done. */
export function useSymbolModel(game: string | undefined) {
  return useQuery({
    queryKey: modelKey(game),
    queryFn: () => fetchSymbolModel(game as string),
    enabled: Boolean(game),
    refetchInterval: (query) => (query.state.data?.state === 'training' ? TRAINING_POLL_MS : false),
  })
}

/** Starts training; the status it answers with (training) goes straight into the cache, which starts the polling. */
export function useTrainSymbolModel() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: trainSymbolModel,
    onSuccess: (status) => queryClient.setQueryData<SymbolModelStatus>(modelKey(status.game), status),
  })
}

/** The newest reading only; it is the one the tab shows. */
export function useLatestSymbolReading() {
  return useQuery({
    queryKey: READINGS_KEY,
    queryFn: () => fetchSymbolReadings(1),
    select: (readings) => readings[0] ?? null,
  })
}

export function useIdentifySymbols() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: identifySymbols,
    onSuccess: (reading) => queryClient.setQueryData<SymbolReading[]>(READINGS_KEY, [reading]),
  })
}

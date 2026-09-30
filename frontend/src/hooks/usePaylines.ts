import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { evaluatePaylines, fetchPaylineScore } from '@/api/paylines'
import { READINGS_KEY } from '@/hooks/useSymbols'
import type { GameContext } from '@/types/gameContext'

const scoreKey = (reading: string | undefined, minConfidence: number) => ['paylines', 'score', reading, minConfidence]

/**
 * What a symbol reading pays. It depends only on the reading, the confidence floor and the paytable the
 * log reports, so a new floor is scored again on the backend without a new screenshot; the previous
 * answer stays on screen until it arrives.
 */
export function usePaylineScore(reading: string | undefined, minConfidence: number) {
  return useQuery({
    queryKey: scoreKey(reading, minConfidence),
    queryFn: () => fetchPaylineScore(reading as string, minConfidence),
    enabled: Boolean(reading),
    placeholderData: keepPreviousData,
    retry: false,
  })
}

/** Takes the screenshot, reads it and scores it. The reading it makes is the Symbol tab's latest too. */
export function useEvaluatePaylines() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ context, minConfidence }: { context: GameContext; minConfidence: number }) =>
      evaluatePaylines(context, minConfidence),
    onSuccess: (result) => {
      queryClient.setQueryData(scoreKey(result.reading_id, result.min_confidence), result)
      return queryClient.invalidateQueries({ queryKey: READINGS_KEY })
    },
  })
}

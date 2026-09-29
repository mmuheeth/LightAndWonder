import { keepPreviousData, useQuery } from '@tanstack/react-query'

import { fetchCurrentPaytable, fetchPaytableConfig, fetchPaytableList } from '@/api/gameConfig'
import type { GameContext } from '@/types/gameContext'

/** How often the backend is asked which paytable the game log reported last. */
const CURRENT_POLL_MS = 1_000

const gameConfigKey =(context: GameContext) => ['game-config', context.game, context.mode]

/**
 * The paytable in play, as last seen in the game log. The backend answers from memory, so this
 * is polled; every other query here only changes when the paytable does.
 */
export function useCurrentPaytable() {
  return useQuery({
    queryKey: ['game-config', 'current'],
    queryFn: fetchCurrentPaytable,
    refetchInterval: CURRENT_POLL_MS,
    retry: false,
  })
}

export function usePaytableList(context: GameContext) {
  return useQuery({
    queryKey: [...gameConfigKey(context), 'paytables'],
    queryFn: () => fetchPaytableList(context),
    staleTime: 60_000,
    retry: false,
  })
}

/**
 * What a paytable contains. It cannot change unless its files do, so it is kept until the page
 * is refreshed; the previous paytable stays on screen while the next one loads.
 */
export function usePaytableConfig(context: GameContext, paytableId: string | null) {
  return useQuery({
    queryKey: [...gameConfigKey(context), 'paytable', paytableId],
    queryFn: () => fetchPaytableConfig(context, paytableId as string),
    enabled: paytableId !== null,
    staleTime: Infinity,
    placeholderData: keepPreviousData,
    retry: false,
  })
}

import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'

import { fetchGameContext, updateGameContext } from '@/api/gameContext'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { GameContextUpdate } from '@/types/gameContext'

/**
 * Loads the game/mode selection from the backend into the store. Mount once,
 * near the root; other components read the store directly.
 */
export function useGameContextSync() {
  const hydrate = useGameContextStore((state) => state.hydrate)
  const query = useQuery({
    queryKey: ['game-context'],
    queryFn: fetchGameContext,
    refetchOnWindowFocus: true,
  })

  useEffect(() => {
    if (query.data) hydrate(query.data)
  }, [query.data, hydrate])

  return query
}

/** Changes game and/or mode: updates the UI immediately, then the backend. */
export function useUpdateGameContext() {
  const { setContext, hydrate } = useGameContextStore.getState()

  return useMutation({
    mutationFn: (update: GameContextUpdate) => updateGameContext(update),
    onMutate: (update) => {
      const previous = useGameContextStore.getState().context
      if (previous) setContext({ ...previous, ...update })
      return { previous }
    },
    onSuccess: hydrate,
    onError: (_error, _update, mutationContext) => {
      if (mutationContext?.previous) setContext(mutationContext.previous)
    },
  })
}

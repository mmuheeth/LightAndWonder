import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { connectGaf, disconnectGaf, fetchGafActions, fetchGafStatus, runGafAction } from '@/api/gaf'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { GameContext } from '@/types/gameContext'
import type { GafActionInputs, GafStatus } from '@/types/gaf'

// Every request names its game and mode, and so does its key: changing the selection fetches the
// new game's answer at once, and an answer can never be cached under the other game's key.
const STATUS_KEYS = ['gaf', 'status']
const statusKey = (game?: string, mode?: string) => [...STATUS_KEYS, game, mode]

/** Polled, so the UI notices the game or NRobot going away. */
export function useGafStatus() {
  const context = useGameContextStore((state) => state.context)
  return useQuery({
    queryKey: statusKey(context?.game, context?.mode),
    queryFn: () => fetchGafStatus(context as GameContext), // only runs once `enabled`
    enabled: context !== null,
    refetchInterval: 3_000,
    retry: false,
  })
}

/** The actions of the selected game: the common ones, then the ones its config lists. */
export function useGafActions() {
  const context = useGameContextStore((state) => state.context)
  return useQuery({
    queryKey: ['gaf', 'actions', context?.game, context?.mode],
    queryFn: () => fetchGafActions(context as GameContext), // only runs once `enabled`
    enabled: context !== null,
    retry: false,
  })
}

/** Mutations that return the new status write it straight into the status query. */
function useStatusMutation(mutationFn: (context: GameContext) => Promise<GafStatus>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (status) => queryClient.setQueryData(statusKey(status.game, status.mode), status),
  })
}

export const useConnectGaf = () => useStatusMutation(connectGaf)
export const useDisconnectGaf = () => useStatusMutation(disconnectGaf)

/** An action can change the game's state, so the status is refreshed once it is done. */
export function useRunGafAction() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      context,
      actionId,
      inputs,
    }: {
      context: GameContext
      actionId: string
      inputs?: GafActionInputs
    }) => runGafAction(context, actionId, inputs),
    onSettled: () => queryClient.invalidateQueries({ queryKey: STATUS_KEYS }),
  })
}

import { create } from 'zustand'

import type { GameContext, GameContextOptions, GameContextResponse } from '@/types/gameContext'

interface GameContextState {
  context: GameContext | null
  options: GameContextOptions
  hydrate: (response: GameContextResponse) => void
  /** Optimistic local change; the backend remains the source of truth. */
  setContext: (context: GameContext) => void
}

export const useGameContextStore = create<GameContextState>((set) => ({
  context: null,
  options: { games: [], modes: [] },
  hydrate: ({ context, options }) => set({ context, options }),
  setContext: (context) => set({ context }),
}))

import { create } from 'zustand'

interface ConnectionState {
  lastCheckedAt: string | null
  isBackendReachable: boolean
  setStatus: (isBackendReachable: boolean) => void
}

export const useConnectionStore = create<ConnectionState>((set) => ({
  lastCheckedAt: null,
  isBackendReachable: false,
  setStatus: (isBackendReachable) =>
    set({ isBackendReachable, lastCheckedAt: new Date().toISOString() }),
}))

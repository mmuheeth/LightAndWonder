import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  connectObs,
  disconnectObs,
  fetchObsCaptureSetup,
  fetchObsConfig,
  fetchObsScreenshots,
  fetchObsStatus,
  fetchObsWindows,
  selectObsWindow,
  takeObsScreenshot,
  updateObsConfig,
} from '@/api/obs'
import type { ObsStatus } from '@/types/obs'

/** How many recent screenshots the OBS tab shows. */
const RECENT_SCREENSHOT_COUNT = 5

const STATUS_KEY = ['obs', 'status']
const CONFIG_KEY = ['obs', 'config']
const SCREENSHOTS_KEY = ['obs', 'screenshots']
// Prefix of the window queries below, so one invalidation refreshes both.
const WINDOW_KEYS = ['obs', 'window']

/** Polled, so the UI notices OBS being closed or a recording being stopped from OBS itself. */
export function useObsStatus() {
  return useQuery({
    queryKey: STATUS_KEY,
    queryFn: fetchObsStatus,
    refetchInterval: 3_000,
    retry: false,
  })
}

export function useRecentScreenshots() {
  return useQuery({
    queryKey: SCREENSHOTS_KEY,
    queryFn: () => fetchObsScreenshots(RECENT_SCREENSHOT_COUNT),
  })
}

/** Mutations that return the new status write it straight into the status query. */
function useStatusMutation(mutationFn: () => Promise<ObsStatus>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (status) => queryClient.setQueryData(STATUS_KEY, status),
  })
}

/** Connecting also applies the saved capture window, so the window queries are refreshed. */
export function useConnectObs() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: connectObs,
    onSuccess: (status) => {
      queryClient.setQueryData(STATUS_KEY, status)
      return queryClient.invalidateQueries({ queryKey: WINDOW_KEYS })
    },
  })
}
export const useDisconnectObs = () => useStatusMutation(disconnectObs)

export function useObsConfig() {
  return useQuery({ queryKey: CONFIG_KEY, queryFn: fetchObsConfig })
}

/** Saving a new server drops the current connection, so the status is refreshed too. */
export function useUpdateObsConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: updateObsConfig,
    onSuccess: (config) => {
      queryClient.setQueryData(CONFIG_KEY, config)
      return queryClient.invalidateQueries({ queryKey: STATUS_KEY })
    },
  })
}

export function useTakeScreenshot() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: takeObsScreenshot,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SCREENSHOTS_KEY }),
  })
}

/** Windows OBS can capture; only loaded while connected. */
export function useObsWindows(connected: boolean) {
  return useQuery({
    queryKey: [...WINDOW_KEYS, 'list'],
    queryFn: fetchObsWindows,
    enabled: connected,
    staleTime: 0,
    retry: false,
  })
}

/**
 * The selected window and canvas size. The backend keeps the canvas fitted to the window by
 * itself, so this is polled to show the size it currently has.
 */
export function useObsCaptureSetup(connected: boolean) {
  return useQuery({
    queryKey: [...WINDOW_KEYS, 'setup', connected],
    queryFn: fetchObsCaptureSetup,
    refetchInterval: connected ? 3_000 : false,
    retry: false,
  })
}

export function useSelectObsWindow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: selectObsWindow,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: WINDOW_KEYS }),
  })
}

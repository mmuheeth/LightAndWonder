import { Loader2, RefreshCw } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  useObsCaptureSetup,
  useObsWindows,
  useSelectObsWindow,
} from '@/hooks/useObs'

/** Chooses the window OBS captures. The canvas is fitted to it automatically, and stays fitted. */
export function WindowPicker({ connected }: { connected: boolean }) {
  const setup = useObsCaptureSetup(connected)
  const windows = useObsWindows(connected)
  const select = useSelectObsWindow()

  const saved = setup.data?.window ?? null
  const options = windows.data ?? []
  // The saved window stays selectable (and visible) even when it is not open right now.
  const missingSaved = saved && !options.some((window) => window.value === saved.value)

  const error = select.error ?? (windows.isError ? windows.error : null)
  const { canvas_width: width, canvas_height: height } = setup.data ?? {}

  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">Window to capture</p>
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={saved?.value ?? ''}
          onValueChange={(value) => {
            const window = options.find((option) => option.value === value)
            if (window) select.mutate(window)
          }}
          disabled={!connected || select.isPending}
        >
          <SelectTrigger aria-label="Window to capture" className="w-96 max-w-full">
            <SelectValue
              placeholder={
                !connected
                  ? 'Connect to choose a window'
                  : windows.isPending
                    ? 'Loading windows…'
                    : 'Select a window'
              }
            />
          </SelectTrigger>
          <SelectContent>
            {missingSaved ? (
              <SelectItem value={saved.value}>{saved.name || saved.value} (not open)</SelectItem>
            ) : null}
            {options.map((window) => (
              <SelectItem key={window.value} value={window.value}>
                {window.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Button
          variant="outline"
          size="icon"
          aria-label="Refresh windows"
          title="Refresh windows"
          onClick={() => windows.refetch()}
          disabled={!connected || windows.isFetching}
        >
          <RefreshCw className={windows.isFetching ? 'animate-spin' : undefined} />
        </Button>
        {select.isPending ? (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" />
            Fitting canvas…
          </span>
        ) : null}
      </div>
      {connected && width && height ? (
        <p className="text-xs text-muted-foreground">
          Canvas {width}×{height}
          {saved && setup.data?.applied ? ' · follows the window automatically' : ''}
        </p>
      ) : null}
      {setup.data?.warning ? <p className="text-sm text-amber-600">{setup.data.warning}</p> : null}
      {error ? <p className="text-sm text-destructive">{error.message}</p> : null}
    </div>
  )
}

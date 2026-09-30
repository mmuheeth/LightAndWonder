import { useState } from 'react'
import { Camera, ImageOff, Loader2, Pencil, Plug, Unplug, Video } from 'lucide-react'

import { obsScreenshotSrc } from '@/api/obs'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { WindowPicker } from '@/components/obs/WindowPicker'
import { Section } from '@/components/layout/Section'
import { Input } from '@/components/ui/input'
import { EmptyState, Notice } from '@/components/ui/notice'
import {
  useConnectObs,
  useDisconnectObs,
  useObsConfig,
  useObsStatus,
  useRecentScreenshots,
  useTakeScreenshot,
  useUpdateObsConfig,
} from '@/hooks/useObs'
import type { ObsConfig } from '@/types/obs'

function StatusBadge({ connected, recording, unreachable }: {
  connected: boolean
  recording: boolean
  unreachable: boolean
}) {
  if (unreachable) return <Badge variant="destructive">backend unreachable</Badge>
  if (recording) return <Badge variant="destructive">● recording</Badge>
  if (connected) return <Badge className="bg-green-600 text-white">connected</Badge>
  return <Badge variant="secondary">disconnected</Badge>
}

/**
 * The saved server is shown in the card header; the inputs only appear after "Change server".
 * Rendered with a `key` of the saved value, so it closes and resets when the server changes.
 */
function ServerForm({ config, connected }: { config: ObsConfig; connected: boolean }) {
  const update = useUpdateObsConfig()
  const [editing, setEditing] = useState(false)
  const [host, setHost] = useState(config.host)
  const [port, setPort] = useState(String(config.port))

  if (!editing) {
    return (
      <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
        <Pencil />
        Change server
      </Button>
    )
  }

  const trimmedHost = host.trim()
  const portNumber = Number(port)
  const valid =
    trimmedHost.length > 0 && Number.isInteger(portNumber) && portNumber >= 1 && portNumber <= 65535
  const changed = trimmedHost !== config.host || portNumber !== config.port

  return (
    <form
      className="space-y-2"
      onSubmit={(event) => {
        event.preventDefault()
        if (valid && changed) update.mutate({ host: trimmedHost, port: portNumber })
      }}
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="space-y-1 text-xs text-muted-foreground">
          Host
          <Input
            value={host}
            onChange={(event) => setHost(event.target.value)}
            className="w-48 text-foreground"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <label className="space-y-1 text-xs text-muted-foreground">
          Port
          <Input
            value={port}
            onChange={(event) => setPort(event.target.value)}
            className="w-24 text-foreground"
            inputMode="numeric"
            autoComplete="off"
          />
        </label>
        <Button type="submit" variant="outline" disabled={!valid || !changed || update.isPending}>
          {update.isPending ? <Loader2 className="animate-spin" /> : null}
          Save
        </Button>
        <Button
          type="button"
          variant="ghost"
          disabled={update.isPending}
          onClick={() => {
            setHost(config.host)
            setPort(String(config.port))
            update.reset()
            setEditing(false)
          }}
        >
          Cancel
        </Button>
      </div>
      {connected && changed && valid ? (
        <p className="text-xs text-muted-foreground">
          Saving disconnects from the current server; press Connect afterwards.
        </p>
      ) : null}
      {update.error ? <Notice tone="error">{update.error.message}</Notice> : null}
    </form>
  )
}

export function ObsPanel() {
  const status = useObsStatus()
  const config = useObsConfig()
  const screenshots = useRecentScreenshots()
  const connect = useConnectObs()
  const disconnect = useDisconnectObs()
  const screenshot = useTakeScreenshot()

  const connected = status.data?.connected ?? false
  const recording = status.data?.recording ?? false
  const obsRunning = status.data?.obs_running ?? false

  const error = connect.error ?? disconnect.error ?? screenshot.error

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <Video />
            OBS Studio
            <StatusBadge connected={connected} recording={recording} unreachable={status.isError} />
          </CardTitle>
          <CardDescription>
            {config.data ? (
              <>
                Server{' '}
                <span className="font-mono text-foreground">
                  {config.data.host}:{config.data.port}
                </span>
                {' · '}
              </>
            ) : null}
            {connected
              ? 'connected over obs-websocket.'
              : obsRunning
                ? 'OBS is running but not connected.'
                : 'OBS is not running. Connect will launch it.'}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => connect.mutate()} disabled={connected || connect.isPending}>
              {connect.isPending ? <Loader2 className="animate-spin" /> : <Plug />}
              {connect.isPending ? (obsRunning ? 'Connecting…' : 'Launching OBS…') : 'Connect'}
            </Button>
            <Button
              variant="outline"
              onClick={() => disconnect.mutate()}
              disabled={!connected || disconnect.isPending}
            >
              <Unplug />
              Disconnect
            </Button>
            <Button
              variant="secondary"
              onClick={() => screenshot.mutate()}
              disabled={!connected || screenshot.isPending}
            >
              {screenshot.isPending ? <Loader2 className="animate-spin" /> : <Camera />}
              Screenshot
            </Button>
          </div>
          {error ? <Notice tone="error">{error.message}</Notice> : null}
          <div className="border-t pt-4">
            <WindowPicker connected={connected} />
          </div>
          {config.data ? (
            <div className="border-t pt-4">
              <ServerForm
                key={`${config.data.host}:${config.data.port}`}
                config={config.data}
                connected={connected}
              />
            </div>
          ) : config.isError ? (
            <Notice tone="error">Could not load server settings: {config.error.message}</Notice>
          ) : null}
        </CardContent>
      </Card>

      <Section title="Recent screenshots">
        {screenshots.isError ? (
          <Notice tone="error">Could not load screenshots: {screenshots.error.message}</Notice>
        ) : screenshots.data?.length === 0 ? (
          <EmptyState icon={ImageOff} title="No screenshots yet">
            Connect to OBS and press Screenshot.
          </EmptyState>
        ) : (
          <Card>
            <CardContent>
              <ul className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
                {screenshots.data?.map((shot) => (
                  <li key={shot.filename} className="space-y-1">
                    <a
                      href={obsScreenshotSrc(shot)}
                      target="_blank"
                      rel="noreferrer"
                      className="block overflow-hidden rounded-lg border bg-muted shadow-card transition-shadow hover:shadow-raised"
                    >
                      {/* Natural aspect ratio, so the whole frame is visible, never cropped. */}
                      <img
                        src={obsScreenshotSrc(shot)}
                        alt={`Screenshot taken at ${new Date(shot.created_at).toLocaleTimeString()}`}
                        loading="lazy"
                        className="h-auto w-full"
                      />
                    </a>
                    <p className="truncate text-xs text-muted-foreground" title={shot.filename}>
                      {new Date(shot.created_at).toLocaleString()}
                    </p>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        )}
      </Section>
    </div>
  )
}

import { Loader2, Radio, Square } from 'lucide-react'

import { CyclicRoundView } from '@/components/cyclic/CyclicRoundView'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  useCyclicRounds,
  useCyclicStatus,
  useStartCyclicTracking,
  useStopCyclicTracking,
} from '@/hooks/useCyclic'
import { useObsStatus } from '@/hooks/useObs'
import { useWarmUpOcr } from '@/hooks/useOcr'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { TrackingPhase } from '@/types/cyclic'

function PhaseBadge({ phase }: { phase: TrackingPhase }) {
  switch (phase) {
    case 'capturing':
      return (
        <Badge className="bg-green-600 text-white">
          <Loader2 className="animate-spin" />
          capturing messages
        </Badge>
      )
    case 'spinning':
      return <Badge variant="secondary">reels spinning</Badge>
    case 'waiting':
      return <Badge variant="secondary">waiting for a spin</Badge>
    default:
      return <Badge variant="outline">not tracking</Badge>
  }
}

export function CyclicPanel() {
  const context = useGameContextStore((state) => state.context)
  const obs = useObsStatus()
  const status = useCyclicStatus()
  const tracking = status.data?.tracking ?? false
  const rounds = useCyclicRounds(tracking)
  const start = useStartCyclicTracking()
  const stop = useStopCyclicTracking()
  useWarmUpOcr()

  const connected = obs.data?.connected ?? false
  const current = status.data?.current ?? null
  // The round being captured is shown from the status, which is fresher than the list of rounds.
  const earlier = (rounds.data ?? []).filter((round) => round.id !== current?.id)
  const error = start.error ?? stop.error

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <span className="flex items-center gap-2">
              <Radio className="size-4" />
              Track cyclic messages
            </span>
            {status.data ? <PhaseBadge phase={status.data.phase} /> : null}
            {tracking && status.data ? (
              <span className="text-sm font-normal text-muted-foreground">
                {status.data.rounds} {status.data.rounds === 1 ? 'spin' : 'spins'} seen
              </span>
            ) : null}
          </CardTitle>
          <CardDescription>
            Follows the game&apos;s log
            {context ? (
              <>
                {' '}
                of <span className="font-mono text-foreground">{context.game}</span> ·{' '}
                <span className="font-mono text-foreground">{context.mode}</span>
              </>
            ) : null}
            . Spin and collect wins yourself. From the moment a spin&apos;s reels stop, the two cyclic message lines are
            screenshotted every few tenths of a second and each new message is read with OCR while the capture goes on.
            Each line is captured for one loop. The win&apos;s lines stop when the game reports the first pass over
            them is done (a win on 40 lines takes about 80 s), whether or not you have collected the win. The lower
            line only starts cycling once you collect, so the capture stays open for that (up to ten minutes) and
            finishes when it has had its loop. Starting the next spin ends it early.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {tracking ? (
            <Button variant="outline" onClick={() => stop.mutate()} disabled={stop.isPending}>
              {stop.isPending ? <Loader2 className="animate-spin" /> : <Square />}
              Stop Tracking
            </Button>
          ) : (
            <Button
              onClick={() => context && start.mutate(context)}
              disabled={!context || !connected || start.isPending}
            >
              {start.isPending ? <Loader2 className="animate-spin" /> : <Radio />}
              Track Cyclic Messages
            </Button>
          )}
          {!connected && !obs.isError && !tracking ? (
            <p className="text-xs text-muted-foreground">Connect to OBS in the OBS tab first.</p>
          ) : null}
          {tracking && status.data && !status.data.ocr_ready ? (
            <p className="text-xs text-muted-foreground">
              The OCR models are still loading (about half a minute after the backend starts), so messages are read once
              they are.
            </p>
          ) : null}
          {status.data?.log_unreadable ? (
            <p className="text-sm text-destructive">
              The game log cannot be read ({status.data.log_path}), so no spin will be noticed.
            </p>
          ) : null}
          {status.data?.problem ? <p className="text-sm text-destructive">{status.data.problem}</p> : null}
          {error ? <p className="text-sm text-destructive">{error.message}</p> : null}
          {status.isError ? (
            <p className="text-sm text-destructive">Could not load the tracking status: {status.error.message}</p>
          ) : null}
        </CardContent>
      </Card>

      {current ? (
        <section className="space-y-3">
          <h3 className="font-heading text-base font-medium">Now</h3>
          <CyclicRoundView key={current.id} round={current} live />
        </section>
      ) : null}

      {rounds.isError ? (
        <p className="text-sm text-destructive">Could not load the spins: {rounds.error.message}</p>
      ) : rounds.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the spins…</p>
      ) : earlier.length === 0 && !current ? (
        <p className="text-sm text-muted-foreground">
          No spins tracked yet. Press Track Cyclic Messages, then spin the game (from the GAF tab, or on the game itself).
        </p>
      ) : earlier.length > 0 ? (
        <section className="space-y-3">
          <h3 className="font-heading text-base font-medium">Earlier spins</h3>
          {earlier.map((round) => (
            <CyclicRoundView key={round.id} round={round} />
          ))}
        </section>
      ) : null}
    </div>
  )
}

import { History, Loader2, Radio, Square } from 'lucide-react'

import { CyclicRoundView } from '@/components/cyclic/CyclicRoundView'
import { Section } from '@/components/layout/Section'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, Notice } from '@/components/ui/notice'
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
          <CardTitle className="flex-wrap gap-x-3 gap-y-1">
            <span className="flex items-center gap-2">
              <Radio />
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
        <CardContent className="space-y-4">
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
            <Notice tone="error">
              The game log cannot be read ({status.data.log_path}), so no spin will be noticed.
            </Notice>
          ) : null}
          {status.data?.problem ? <Notice tone="error">{status.data.problem}</Notice> : null}
          {error ? <Notice tone="error">{error.message}</Notice> : null}
          {status.isError ? (
            <Notice tone="error">Could not load the tracking status: {status.error.message}</Notice>
          ) : null}
        </CardContent>
      </Card>

      {current ? (
        <Section title="Now">
          <CyclicRoundView key={current.id} round={current} live />
        </Section>
      ) : null}

      {rounds.isError ? (
        <Notice tone="error">Could not load the spins: {rounds.error.message}</Notice>
      ) : rounds.isPending ? (
        <EmptyState loading title="Loading the spins…" />
      ) : earlier.length === 0 && !current ? (
        <EmptyState icon={History} title="No spins tracked yet">
          Press Track Cyclic Messages, then spin the game (from the GAF tab, or on the game itself).
        </EmptyState>
      ) : earlier.length > 0 ? (
        <Section title="Earlier spins">
          {earlier.map((round) => (
            <CyclicRoundView key={round.id} round={round} />
          ))}
        </Section>
      ) : null}
    </div>
  )
}

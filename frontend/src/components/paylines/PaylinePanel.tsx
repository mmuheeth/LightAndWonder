import { History, Loader2, Waypoints } from 'lucide-react'

import { PaylineResultCard } from '@/components/paylines/PaylineResultCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState, Notice } from '@/components/ui/notice'
import { useMinConfidence } from '@/hooks/useMinConfidence'
import { useObsStatus } from '@/hooks/useObs'
import { useEvaluatePaylines, usePaylineScore } from '@/hooks/usePaylines'
import { useLatestSymbolReading, useSymbolModel } from '@/hooks/useSymbols'
import { cn } from '@/lib/utils'
import { useGameContextStore } from '@/store/useGameContextStore'

/**
 * Takes a screenshot, reads the symbols on it, and works out which paylines pay. What is shown is the
 * newest symbol reading (the Symbols tab's too), scored with the paytable the game log reported last.
 * A tile is read at the Symbols tab's confidence setting; this tab has none of its own.
 */
export function PaylinePanel() {
  const context = useGameContextStore((state) => state.context)
  const obs = useObsStatus()
  const model = useSymbolModel(context?.game)
  const latest = useLatestSymbolReading()
  const minConfidence = useMinConfidence(model.data?.min_confidence)
  const score = usePaylineScore(latest.data?.id, minConfidence.value)
  const evaluate = useEvaluatePaylines()

  const connected = obs.data?.connected ?? false
  const trained = model.data?.model != null
  // While a new floor is scored, the previous answer stays up, dimmed.
  const stale = score.isPlaceholderData

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>
            <Waypoints />
            Evaluate paylines
          </CardTitle>
          <CardDescription>
            Takes a screenshot of the game in OBS, reads the symbols on the reels with the trained classifier, and
            finds which paylines pay and how much
            {context ? (
              <>
                {' '}
                for <span className="font-mono text-foreground">{context.game}</span> ·{' '}
                <span className="font-mono text-foreground">{context.mode}</span>
              </>
            ) : null}
            .
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex flex-wrap items-end gap-4">
            <Button
              onClick={() => context && evaluate.mutate({ context, minConfidence: minConfidence.value })}
              disabled={!context || !connected || !trained || evaluate.isPending}
            >
              {evaluate.isPending ? <Loader2 className="animate-spin" /> : <Waypoints />}
              Evaluate
            </Button>
          </div>
          {!connected && !obs.isError ? (
            <p className="text-xs text-muted-foreground">Connect to OBS in the OBS tab first.</p>
          ) : null}
          {model.data && !trained ? (
            <p className="text-xs text-muted-foreground">
              {model.data.state === 'training'
                ? 'The symbol model is still training.'
                : 'Train the symbol model in the Symbols tab first.'}
            </p>
          ) : null}
          {evaluate.error ? <Notice tone="error">{evaluate.error.message}</Notice> : null}
        </CardContent>
      </Card>

      {latest.isError ? (
        <Notice tone="error">Could not load the last reading: {latest.error.message}</Notice>
      ) : latest.isPending ? (
        <EmptyState loading title="Loading the last reading…" />
      ) : !latest.data ? (
        <EmptyState icon={History} title="No paylines evaluated yet">
          Press Evaluate to read the reels and find the lines that pay.
        </EmptyState>
      ) : score.isError ? (
        <Notice tone="error">Could not score the paylines: {score.error.message}</Notice>
      ) : score.data ? (
        <div className={cn('transition-opacity', stale && 'pointer-events-none opacity-50')} aria-busy={stale}>
          <PaylineResultCard key={score.data.reading_id} result={score.data} />
        </div>
      ) : (
        <EmptyState loading title="Scoring the paylines…" />
      )}
    </div>
  )
}

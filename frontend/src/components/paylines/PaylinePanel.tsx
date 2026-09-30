import { Loader2, Spline } from 'lucide-react'

import { PaylineResultCard } from '@/components/paylines/PaylineResultCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useMinConfidence } from '@/hooks/useMinConfidence'
import { useObsStatus } from '@/hooks/useObs'
import { useEvaluatePaylines, usePaylineScore } from '@/hooks/usePaylines'
import { useLatestSymbolReading, useSymbolModel } from '@/hooks/useSymbols'
import { cn } from '@/lib/utils'
import { useGameContextStore } from '@/store/useGameContextStore'

/**
 * Takes a screenshot, reads the symbols on it, and works out which paylines pay. What is shown is the
 * newest symbol reading (the Symbol tab's too), scored with the paytable the game log reported last.
 * A tile is read at the Symbol tab's confidence setting; this tab has none of its own.
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
          <CardTitle className="flex items-center gap-2">
            <Spline className="size-4" />
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
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-4">
            <Button
              onClick={() => context && evaluate.mutate({ context, minConfidence: minConfidence.value })}
              disabled={!context || !connected || !trained || evaluate.isPending}
            >
              {evaluate.isPending ? <Loader2 className="animate-spin" /> : <Spline />}
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
                : 'Train the symbol model in the Symbol tab first.'}
            </p>
          ) : null}
          {evaluate.error ? <p className="text-sm text-destructive">{evaluate.error.message}</p> : null}
        </CardContent>
      </Card>

      {latest.isError ? (
        <p className="text-sm text-destructive">Could not load the last reading: {latest.error.message}</p>
      ) : latest.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the last reading…</p>
      ) : !latest.data ? (
        <p className="text-sm text-muted-foreground">No paylines evaluated yet.</p>
      ) : score.isError ? (
        <p className="text-sm text-destructive">Could not score the paylines: {score.error.message}</p>
      ) : score.data ? (
        <div className={cn('transition-opacity', stale && 'pointer-events-none opacity-50')} aria-busy={stale}>
          <PaylineResultCard key={score.data.reading_id} result={score.data} />
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">Scoring the paylines…</p>
      )}
    </div>
  )
}

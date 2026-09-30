import { Loader2, ScanSearch } from 'lucide-react'

import { MinConfidenceField } from '@/components/symbols/MinConfidenceField'
import { SymbolReadingCard } from '@/components/symbols/SymbolReadingCard'
import { SymbolTrainingCard } from '@/components/symbols/SymbolTrainingCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useMinConfidence } from '@/hooks/useMinConfidence'
import { useObsStatus } from '@/hooks/useObs'
import { useIdentifySymbols, useLatestSymbolReading, useSymbolModel } from '@/hooks/useSymbols'
import { useGameContextStore } from '@/store/useGameContextStore'

export function SymbolPanel() {
  const context = useGameContextStore((state) => state.context)
  const obs = useObsStatus()
  const model = useSymbolModel(context?.game)
  const latest = useLatestSymbolReading()
  const identify = useIdentifySymbols()
  const minConfidence = useMinConfidence(model.data?.min_confidence)

  const connected = obs.data?.connected ?? false
  const trained = model.data?.model != null

  return (
    <div className="space-y-6">
      <SymbolTrainingCard />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScanSearch className="size-4" />
            Identify symbols
          </CardTitle>
          <CardDescription>
            Takes a screenshot of the game in OBS, cuts the reel grid into tiles and names each tile&apos;s
            symbol with the trained classifier
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
              onClick={() => context && identify.mutate(context)}
              disabled={!context || !connected || !trained || identify.isPending}
            >
              {identify.isPending ? <Loader2 className="animate-spin" /> : <ScanSearch />}
              Identify
            </Button>
            <MinConfidenceField
              minConfidence={minConfidence}
              title="A tile is named only when the classifier is at least this sure of it"
            />
          </div>
          {!connected && !obs.isError ? (
            <p className="text-xs text-muted-foreground">Connect to OBS in the OBS tab first.</p>
          ) : null}
          {model.data && !trained ? (
            <p className="text-xs text-muted-foreground">
              {model.data.state === 'training' ? 'The model is still training.' : 'Train the model first.'}
            </p>
          ) : null}
          {minConfidence.invalid ? (
            <p className="text-xs text-destructive">Min confidence is a percent from 0 to 100.</p>
          ) : null}
          {identify.error ? <p className="text-sm text-destructive">{identify.error.message}</p> : null}
        </CardContent>
      </Card>

      {latest.isError ? (
        <p className="text-sm text-destructive">Could not load the last reading: {latest.error.message}</p>
      ) : latest.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the last reading…</p>
      ) : !latest.data ? (
        <p className="text-sm text-muted-foreground">No symbols read yet.</p>
      ) : (
        <SymbolReadingCard key={latest.data.id} reading={latest.data} minConfidence={minConfidence.value} />
      )}
    </div>
  )
}

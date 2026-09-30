import { useState } from 'react'
import { Loader2, ScanSearch } from 'lucide-react'

import { SymbolReadingCard } from '@/components/symbols/SymbolReadingCard'
import { SymbolTrainingCard } from '@/components/symbols/SymbolTrainingCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useObsStatus } from '@/hooks/useObs'
import { useIdentifySymbols, useLatestSymbolReading, useSymbolModel } from '@/hooks/useSymbols'
import { useGameContextStore } from '@/store/useGameContextStore'

const STORAGE_KEY = 'symbols.minConfidence'
// Only until the backend's own default (its SYMBOL_MIN_CONFIDENCE setting) has arrived.
const FALLBACK_MIN_CONFIDENCE = 90

/** A percent from 0 to 100, or null. */
function parsePercent(raw: string): number | null {
  const value = Number(raw)
  return raw.trim() !== '' && Number.isFinite(value) && value >= 0 && value <= 100 ? value : null
}

function storedMinConfidence(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw === null ? null : parsePercent(raw)
  } catch {
    return null // storage can be blocked; the threshold then just is not remembered
  }
}

/**
 * The confidence a tile must reach to be named. It starts at the backend's default, and what the user
 * sets is remembered in this browser. It applies to the reading on screen at once, without a new screenshot.
 */
function useMinConfidence(backendDefault: number | undefined) {
  const [chosen, setChosen] = useState<number | null>(storedMinConfidence)
  // What is in the field, while it is being typed: it may be unfinished, and then is not applied.
  const [draft, setDraft] = useState<string | null>(null)

  const value = chosen ?? backendDefault ?? FALLBACK_MIN_CONFIDENCE
  const invalid = draft !== null && parsePercent(draft) === null

  const change = (raw: string) => {
    setDraft(raw)
    const percent = parsePercent(raw)
    if (percent === null) return
    setChosen(percent)
    try {
      localStorage.setItem(STORAGE_KEY, String(percent))
    } catch {
      // not remembered
    }
  }

  return { value, text: draft ?? String(value), invalid, change, settle: () => setDraft(null) }
}

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
            <label
              className="space-y-1 text-xs text-muted-foreground"
              title="A tile is named only when the classifier is at least this sure of it"
            >
              Min confidence (%)
              <Input
                value={minConfidence.text}
                onChange={(event) => minConfidence.change(event.target.value)}
                onBlur={minConfidence.settle}
                inputMode="decimal"
                autoComplete="off"
                aria-invalid={minConfidence.invalid}
                className="block w-24 text-foreground"
              />
            </label>
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

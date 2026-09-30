import { Loader2, RefreshCw, ScanText } from 'lucide-react'

import { OcrRecordView } from '@/components/ocr/OcrRecordView'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useGafStatus } from '@/hooks/useGaf'
import { useObsStatus } from '@/hooks/useObs'
import { useExtractValues, useLatestOcrRecord, useReadOcrRecord, useWarmUpOcr } from '@/hooks/useOcr'
import { useGameContextStore } from '@/store/useGameContextStore'

const PHASE_LABEL = { capturing: 'Capturing…', reading: 'Reading…' } as const

export function OcrPanel() {
  const context = useGameContextStore((state) => state.context)
  const obs = useObsStatus()
  const gaf = useGafStatus()
  const latest = useLatestOcrRecord()
  const extract = useExtractValues()
  const readAgain = useReadOcrRecord()
  useWarmUpOcr()

  const connected = obs.data?.connected ?? false
  const record = latest.data
  const busy = extract.isPending || readAgain.isPending
  // The record shown is being read: by the button (once it has captured it), or by "Read again".
  const reading = extract.phase === 'reading' || readAgain.isPending
  const error = extract.error ?? readAgain.error

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <ScanText className="size-4" />
            Extract values
          </CardTitle>
          <CardDescription>
            Takes a screenshot of the game in OBS and cuts out the credit meter, the cash meter and the two cyclic
            messages, then reads them with PaddleOCR
            {context ? (
              <>
                {' '}
                for <span className="font-mono text-foreground">{context.game}</span> ·{' '}
                <span className="font-mono text-foreground">{context.mode}</span>
              </>
            ) : null}
            . The meter is switched between cash and credits through GAF to capture both, and switched back.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Button onClick={() => context && extract.mutate(context)} disabled={!context || !connected || busy}>
            {extract.isPending ? <Loader2 className="animate-spin" /> : <ScanText />}
            {extract.phase ? PHASE_LABEL[extract.phase] : 'Extract Values'}
          </Button>
          {!connected && !obs.isError ? (
            <p className="text-xs text-muted-foreground">Connect to OBS in the OBS tab first.</p>
          ) : null}
          {gaf.data && !gaf.data.connected ? (
            <p className="text-xs text-muted-foreground">
              GAF is not connected, so only the meter the game is showing is read. Connect it in the GAF tab to read
              both the credit and the cash meter.
            </p>
          ) : null}
          {reading ? (
            <p className="text-xs text-muted-foreground">
              Reading takes a few seconds; if the backend has only just started it first loads the OCR models, which
              takes about half a minute.
            </p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error.message}</p> : null}
        </CardContent>
      </Card>

      {latest.isError ? (
        <p className="text-sm text-destructive">Could not load the last capture: {latest.error.message}</p>
      ) : latest.isPending ? (
        <p className="text-sm text-muted-foreground">Loading the last capture…</p>
      ) : !record ? (
        <p className="text-sm text-muted-foreground">Nothing extracted yet.</p>
      ) : (
        <section className="space-y-3">
          <h3 className="flex flex-wrap items-center gap-x-3 gap-y-1 font-heading text-base font-medium">
            Latest capture
            <Badge variant="secondary">
              {record.game} · {record.mode}
            </Badge>
            <span className="text-sm font-normal text-muted-foreground">
              {new Date(record.created_at).toLocaleString()}
              {record.readings ? ` · read in ${record.readings.seconds} s` : ''}
            </span>
            {!reading ? (
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => readAgain.mutate(record.id)}
                title="Run the OCR on these images again"
              >
                <RefreshCw />
                {record.readings ? 'Read again' : 'Read'}
              </Button>
            ) : null}
          </h3>
          <OcrRecordView key={record.id} record={record} reading={reading} />
        </section>
      )}
    </div>
  )
}

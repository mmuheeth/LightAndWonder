import { Crop, Loader2 } from 'lucide-react'

import { RoiRecordView } from '@/components/roi/RoiRecordView'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useObsStatus } from '@/hooks/useObs'
import { useExtractRoi, useRoiRecords } from '@/hooks/useRoi'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { RoiRecord } from '@/types/roi'

const formatTime = (record: RoiRecord) => new Date(record.created_at).toLocaleString()

const summarize = (record: RoiRecord) =>
  `${record.crops.length} regions${record.tiles.length ? ` · ${record.tiles.length} tiles` : ''}`

export function RoiPanel() {
  const context = useGameContextStore((state) => state.context)
  const status = useObsStatus()
  const records = useRoiRecords()
  const extract = useExtractRoi()

  const connected = status.data?.connected ?? false
  const [latest, ...previous] = records.data ?? []

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Extract ROI</CardTitle>
          <CardDescription>
            Takes a screenshot of the game in OBS, then cuts out its regions of interest and splits
            the reel grid into tiles
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
          <Button
            onClick={() => context && extract.mutate(context)}
            disabled={!context || !connected || extract.isPending}
          >
            {extract.isPending ? <Loader2 className="animate-spin" /> : <Crop />}
            Extract ROI
          </Button>
          {!connected && !status.isError ? (
            <p className="text-xs text-muted-foreground">Connect to OBS in the OBS tab first.</p>
          ) : null}
          {extract.error ? <p className="text-sm text-destructive">{extract.error.message}</p> : null}
        </CardContent>
      </Card>

      {records.isError ? (
        <p className="text-sm text-destructive">
          Could not load earlier extractions: {records.error.message}
        </p>
      ) : records.isPending ? (
        <p className="text-sm text-muted-foreground">Loading extractions…</p>
      ) : !latest ? (
        <p className="text-sm text-muted-foreground">No extractions yet.</p>
      ) : (
        <section className="space-y-3">
          <h3 className="flex flex-wrap items-center gap-x-3 gap-y-1 font-heading text-base font-medium">
            Latest extraction
            <Badge variant="secondary">
              {latest.game} · {latest.mode}
            </Badge>
            <span className="text-sm font-normal text-muted-foreground">{formatTime(latest)}</span>
          </h3>
          <RoiRecordView key={latest.id} record={latest} />
        </section>
      )}

      {previous.length > 0 ? (
        <section className="space-y-3">
          <h3 className="font-heading text-base font-medium">Previous extractions</h3>
          <Accordion
            type="single"
            collapsible
            className="rounded-xl bg-card px-4 ring-1 ring-foreground/10"
          >
            {previous.map((record) => (
              <AccordionItem key={record.id} value={record.id}>
                <AccordionTrigger className="hover:no-underline">
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span>{formatTime(record)}</span>
                    <Badge variant="secondary">
                      {record.game} · {record.mode}
                    </Badge>
                    <span className="text-xs font-normal text-muted-foreground">
                      {summarize(record)}
                    </span>
                  </span>
                </AccordionTrigger>
                <AccordionContent>
                  <RoiRecordView record={record} />
                </AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </section>
      ) : null}
    </div>
  )
}

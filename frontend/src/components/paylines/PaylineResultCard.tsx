import { Spline, TriangleAlert } from 'lucide-react'

import { PaylineLineRow } from '@/components/paylines/PaylineLineRow'
import { PaylineOverlay } from '@/components/paylines/PaylineOverlay'
import { PayDescription, PaylineRun } from '@/components/paylines/PaylineRun'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatCredits, formatPercent, lineColor } from '@/lib/paylines'
import type { PaylineOutcome, PaylineResult } from '@/types/paylines'

function SectionLabel({ children }: { children: string }) {
  return <h4 className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">{children}</h4>
}

const lineNames = (lines: PaylineOutcome[]) => lines.map((line) => `Line ${line.number}`).join(', ')

/** A line that paid: what it read, what it matched, and what the paytable gave for it. */
function AwardedLine({ line }: { line: PaylineOutcome }) {
  return (
    <li
      className="space-y-1.5 rounded-lg border border-l-4 bg-card p-3"
      style={{ borderLeftColor: lineColor(line.number) }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <p className="flex items-center gap-2 text-sm">
          <span
            aria-hidden
            className="size-3 shrink-0 self-center rounded-full"
            style={{ backgroundColor: lineColor(line.number) }}
          />
          <span className="font-medium">Line {line.number}</span>
          <span className="text-muted-foreground">matches {line.matches}</span>
        </p>
        <p className="shrink-0 text-sm text-muted-foreground">
          pays <span className="font-semibold text-foreground tabular-nums">{formatCredits(line.pays)}</span>
        </p>
      </div>
      <PaylineRun line={line} />
      <p className="text-sm text-muted-foreground">
        <PayDescription line={line} />
      </p>
      {line.combo ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          {line.combo.pattern.join(' ')} · combo {line.combo.id ?? '—'}
        </p>
      ) : null}
    </li>
  )
}

function Caveat({ children }: { children: string }) {
  return (
    <p className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-400">
      <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
      <span>{children}</span>
    </p>
  )
}

/**
 * The paylines of one result screenshot: the lines that paid with what they paid, the total, every line
 * with the codes it was read from, and a look at any line on the reels themselves.
 */
export function PaylineResultCard({ result }: { result: PaylineResult }) {
  const awarded = result.lines.filter((line) => line.pays > 0)
  const unpaid = result.lines.filter((line) => line.unpaid)
  const uncertain = result.lines.filter((line) => line.uncertain)
  const unread = result.tiles.filter((tile) => tile.code === null).length

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Spline className="size-4" />
          Paylines
        </CardTitle>
        <CardDescription>Runs read off the picture by the classifier, awards decided by the paytable</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Badge variant="outline" className="h-6 font-mono" title="The paytable the wins are decided by">
            {result.paytable_id}
          </Badge>
          <Badge variant="secondary" className="h-6 font-mono">
            {result.line_set}-line set
          </Badge>
          <span className="text-xs text-muted-foreground">
            set chosen by game_config, paytable from {result.paytable_source === 'log' ? 'log' : 'request'}
          </span>
        </div>

        {result.reels ? (
          <PaylineOverlay
            image={result.reels}
            rows={result.rows}
            columns={result.columns}
            lines={awarded}
            fan
            fill
            alt={`The reels, with the ${awarded.length} paying lines drawn on them`}
          />
        ) : null}

        <section className="space-y-2">
          <SectionLabel>Awarded</SectionLabel>
          {awarded.length > 0 ? (
            <ul className="grid gap-3 md:grid-cols-2">
              {awarded.map((line) => (
                <AwardedLine key={line.number} line={line} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No line pays.</p>
          )}
        </section>

        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-lg border bg-muted/30 px-4 py-3">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">Total credits</span>
            <span className="text-sm text-muted-foreground">
              over {awarded.length} paying {awarded.length === 1 ? 'line' : 'lines'}
            </span>
          </p>
          <p className="text-xl font-semibold tabular-nums" aria-label="Total credits">
            {!result.complete ? (
              <span className="mr-2 text-xs font-normal text-amber-700 dark:text-amber-400">at least</span>
            ) : null}
            {formatCredits(result.total_credits)}
          </p>
        </div>

        {unpaid.length > 0 || uncertain.length > 0 || unread > 0 ? (
          <div className="space-y-1.5">
            {unpaid.length > 0 ? (
              <Caveat>{`${unpaid.length} ${unpaid.length === 1 ? 'run' : 'runs'} the paytable does not pay: ${lineNames(unpaid)}`}</Caveat>
            ) : null}
            {uncertain.length > 0 ? (
              <Caveat>{`A tile under the ${formatPercent(result.min_confidence)} floor could change ${lineNames(uncertain)}, so the total is the least it can be`}</Caveat>
            ) : unread > 0 ? (
              <Caveat>{`${unread} ${unread === 1 ? 'tile is' : 'tiles are'} under the ${formatPercent(result.min_confidence)} floor, but none of them can change a line`}</Caveat>
            ) : null}
          </div>
        ) : null}

        <Accordion type="single" collapsible className="border-t">
          <AccordionItem value="lines" className="border-b-0">
            <AccordionTrigger className="flex-row-reverse justify-end gap-2 text-sm font-normal text-muted-foreground hover:no-underline">
              <span className="flex-1">
                All {result.lines.length} lines and the codes they were read from, at confidence floor{' '}
                {formatPercent(result.min_confidence)}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <Accordion type="multiple" className="space-y-2">
                {result.lines.map((line) => (
                  <PaylineLineRow key={line.number} result={result} line={line} />
                ))}
              </Accordion>
            </AccordionContent>
          </AccordionItem>
        </Accordion>

        <p className="font-mono text-[11px] text-muted-foreground">
          split {result.reading_id} · {result.game} · {result.mode}
        </p>
      </CardContent>
    </Card>
  )
}

import { Fragment } from 'react'
import { Grid3x3 } from 'lucide-react'

import { SubHeading } from '@/components/layout/Section'
import { BetNote, Caveat } from '@/components/paylines/PaylineResultCard'
import { PaylineOverlay } from '@/components/paylines/PaylineOverlay'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cellCode, cellLabel, creditsPerUnit, formatCredits, formatPercent, isUnread } from '@/lib/paylines'
import { cn } from '@/lib/utils'
import type { PaylineCell, PaylineResult, WayOutcome } from '@/types/paylines'

const wayName = (way: WayOutcome) => way.symbol_name ?? way.symbol

const wayNames = (ways: WayOutcome[]) => ways.map(wayName).join(', ')

/** A symbol that paid: the cells that make up its run reel by reel, how many ways they make, and the pay. */
function AwardedWay({ way, perUnit }: { way: WayOutcome; perUnit: number }) {
  return (
    <li className="space-y-1.5 rounded-lg border bg-card p-3 shadow-card">
      <div className="flex items-baseline justify-between gap-3">
        <p className="flex items-center gap-2 text-sm">
          <span className="font-medium">{wayName(way)}</span>
          <span className="font-mono text-xs text-muted-foreground">{way.symbol}</span>
          <span className="text-muted-foreground">matches {way.matches}</span>
        </p>
        <p className="shrink-0 text-sm text-muted-foreground">
          pays <span className="font-semibold text-foreground tabular-nums">{formatCredits(way.credits)}</span>
        </p>
      </div>
      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-1 font-mono text-xs">
        {way.reels.map((cells, index) => (
          <Fragment key={index}>
            {index > 0 ? <span className="text-muted-foreground">×</span> : null}
            <span className="rounded border bg-muted/60 px-1.5 py-0.5" title={cells.map(cellLabel).join(', ')}>
              {cells.map(cellCode).join(' ')}
            </span>
          </Fragment>
        ))}
        <span className="text-muted-foreground">=</span>
        <span>{way.ways} ways</span>
      </p>
      {way.combo ? (
        <p className="text-sm text-muted-foreground">
          {way.ways} × <span className="font-medium text-foreground">{formatCredits(way.combo.value)}</span>
          {perUnit !== 1 ? (
            <>
              {' '}
              × <span className="font-medium text-foreground">{formatCredits(perUnit)}</span> bet
            </>
          ) : null}{' '}
          → <span className="font-medium text-foreground">{formatCredits(way.credits)}</span> credits
        </p>
      ) : null}
      {way.combo ? (
        <p className="font-mono text-[11px] text-muted-foreground">
          {way.combo.pattern.join(' ')} · combo {way.combo.id ?? '—'}
        </p>
      ) : null}
    </li>
  )
}

/** Each distinct cell once, for the frames drawn on the reels. */
function distinctCells(ways: WayOutcome[]): PaylineCell[] {
  const cells = new Map<string, PaylineCell>()
  for (const cell of ways.flatMap((way) => way.reels.flat())) cells.set(`${cell.row}-${cell.column}`, cell)
  return [...cells.values()]
}

/**
 * The result of a game that pays by ways: the symbols that paid with the cells that made their run, the
 * total, and the grid the symbols were read from. There are no lines to draw, so the cells that take part
 * are framed on the reels.
 */
export function WayResultCard({ result }: { result: PaylineResult }) {
  const awarded = result.ways.filter((way) => way.pays > 0).sort((a, b) => b.credits - a.credits)
  const unpaid = result.ways.filter((way) => way.unpaid)
  const uncertain = result.ways.filter((way) => way.uncertain)
  const unread = result.tiles.filter(isUnread)
  const floor = formatPercent(result.min_confidence)

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Grid3x3 />
          Ways
        </CardTitle>
        <CardDescription>Runs read off the picture by the classifier, awards decided by the paytable</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <Badge variant="outline" className="h-6 font-mono" title="The paytable the wins are decided by">
            {result.paytable_id}
          </Badge>
          <Badge variant="secondary" className="h-6 font-mono">
            {result.line_set} ways
          </Badge>
          <span className="text-xs text-muted-foreground">
            paytable from {result.paytable_source === 'log' ? 'log' : 'request'}
          </span>
        </div>
        <BetNote bet={result.bet} unit="way" />

        {result.reels ? (
          <PaylineOverlay
            image={result.reels}
            rows={result.rows}
            columns={result.columns}
            lines={[]}
            frames={distinctCells(awarded)}
            fill
            alt={`The reels, with the cells of the ${awarded.length} paying symbols framed`}
          />
        ) : null}

        <section className="space-y-2">
          <SubHeading>Awarded</SubHeading>
          {awarded.length > 0 ? (
            <ul className="grid gap-3 md:grid-cols-2">
              {awarded.map((way) => (
                <AwardedWay key={way.symbol} way={way} perUnit={creditsPerUnit(result)} />
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No symbol pays.</p>
          )}
        </section>

        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 rounded-lg border bg-muted/60 px-4 py-3">
          <p className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-medium">Total credits</span>
            <span className="text-sm text-muted-foreground">
              over {awarded.length} paying {awarded.length === 1 ? 'symbol' : 'symbols'}
            </span>
          </p>
          <p className="text-xl font-semibold tabular-nums" aria-label="Total credits">
            {!result.complete ? (
              <span className="mr-2 text-xs font-normal text-amber-700 dark:text-amber-400">at least</span>
            ) : null}
            {formatCredits(result.total_credits)}
          </p>
        </div>

        {unpaid.length > 0 || uncertain.length > 0 || unread.length > 0 ? (
          <div className="space-y-1.5">
            {unpaid.length > 0 ? (
              <Caveat>{`${unpaid.length} ${unpaid.length === 1 ? 'run' : 'runs'} the paytable does not pay: ${wayNames(unpaid)}`}</Caveat>
            ) : null}
            {uncertain.length > 0 ? (
              <Caveat>{`A tile under the ${floor} floor could change ${wayNames(uncertain)}, so the total is the least it can be`}</Caveat>
            ) : unread.length > 0 ? (
              <Caveat>{`${unread.length} ${unread.length === 1 ? 'tile is' : 'tiles are'} under the ${floor} floor, but none of them can change a symbol`}</Caveat>
            ) : null}
          </div>
        ) : null}

        <Accordion type="single" collapsible className="border-t">
          <AccordionItem value="grid" className="border-b-0">
            <AccordionTrigger className="flex-row-reverse justify-end gap-2 text-sm font-normal text-muted-foreground hover:no-underline">
              <span className="flex-1">
                The {result.rows} × {result.columns} grid as read, at confidence floor {floor}
              </span>
            </AccordionTrigger>
            <AccordionContent>
              <div
                className="grid gap-1.5 font-mono text-xs"
                style={{ gridTemplateColumns: `repeat(${result.columns}, minmax(0, 1fr))` }}
              >
                {result.tiles.map((tile) => (
                  <span
                    key={`${tile.row}-${tile.column}`}
                    title={`${cellLabel(tile)} · ${tile.guess} ${formatPercent(tile.confidence)}`}
                    className={cn(
                      'truncate rounded border px-2 py-1 text-center',
                      isUnread(tile) && 'border-dashed text-amber-700 dark:text-amber-400',
                    )}
                  >
                    {isUnread(tile) ? `${tile.guess}?` : tile.code}
                  </span>
                ))}
              </div>
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

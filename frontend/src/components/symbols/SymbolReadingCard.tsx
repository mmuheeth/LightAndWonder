import { Eye } from 'lucide-react'
import type { ReactNode } from 'react'

import { roiImageSrc } from '@/api/roi'
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { SymbolModelInfo, SymbolReading, SymbolTile } from '@/types/symbols'

const pad = (value: number) => String(value).padStart(2, '0')

/** Local time as 2026-09-01T00:02:31, the way a trained model is stamped. */
const formatStamp = (iso: string) => {
  const at = new Date(iso)
  return (
    `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}` +
    `T${pad(at.getHours())}:${pad(at.getMinutes())}:${pad(at.getSeconds())}`
  )
}

const formatPercent = (value: number) => `${value.toFixed(1)}%`

/** The position as the game's own 1-based row and reel: r1c1 is top left. */
const positionLabel = (tile: SymbolTile) => `r${tile.row + 1}c${tile.column + 1}`

const tileKey = (tile: SymbolTile) => `${tile.row}-${tile.column}`

/** A tile is named only when the classifier is at least this sure (percent). */
const isNamed = (tile: SymbolTile, minConfidence: number) => tile.confidence >= minConfidence

function SectionLabel({ children }: { children: ReactNode }) {
  return <h4 className="text-[11px] font-medium tracking-wider text-muted-foreground uppercase">{children}</h4>
}

/** The reel grid as cells in a bordered box; `columns` wide, filled row by row. */
function Grid({ label, columns, children }: { label: string; columns: number; children: ReactNode }) {
  return (
    <div className="space-y-1.5">
      <SectionLabel>{label}</SectionLabel>
      <div
        className="grid w-fit gap-px overflow-hidden rounded-lg border bg-border"
        style={{ gridTemplateColumns: `repeat(${columns}, auto)` }}
      >
        {children}
      </div>
    </div>
  )
}

const cellClass = 'bg-card px-3.5 py-2 text-center text-sm whitespace-nowrap'

function ModelLine({ model }: { model: SymbolModelInfo }) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <Badge variant="secondary" className="font-mono">
        {model.architecture}
      </Badge>
      <span className="text-xs text-muted-foreground">
        <span title="Accuracy on the artwork held out of training, for the symbol it names worst">
          {model.floor === null ? 'unchecked' : `floor ${formatPercent(model.floor)}`}
        </span>
        {model.floor !== null && model.unchecked.length > 0 ? (
          <span title={`Too few images to hold any out: ${model.unchecked.join(', ')}`}>
            {' '}
            · {model.unchecked.length} unchecked
          </span>
        ) : null}
        {' · '}trained {formatStamp(model.trained_at)}
      </span>
    </div>
  )
}

/**
 * The reel grid as it was captured, with the tile borders drawn over it, so each tile's reading can be
 * checked against what is on screen. Absent for a reading saved before the grid image was kept.
 */
function ReelsImage({ reading }: { reading: SymbolReading }) {
  if (!reading.reels) return null
  return (
    <section className="space-y-1.5">
      <SectionLabel>On the reels</SectionLabel>
      <a
        href={roiImageSrc(reading.reels)}
        target="_blank"
        rel="noreferrer"
        className="relative block w-fit max-w-full overflow-hidden rounded-lg border-2 border-emerald-500 bg-muted"
      >
        <img
          src={roiImageSrc(reading.reels)}
          alt={`The ${reading.rows} by ${reading.columns} reel grid that was read`}
          className="block h-auto max-h-[32rem] w-auto max-w-full"
        />
        <span
          aria-hidden
          className="pointer-events-none absolute inset-0 grid"
          style={{
            gridTemplateColumns: `repeat(${reading.columns}, minmax(0, 1fr))`,
            gridTemplateRows: `repeat(${reading.rows}, minmax(0, 1fr))`,
          }}
        >
          {reading.tiles.map((tile) => (
            <span key={tileKey(tile)} className="border border-emerald-500" />
          ))}
        </span>
      </a>
    </section>
  )
}

/**
 * Every tile's symbol, code, position and the classifier's confidence. Closed until opened; the header
 * already says how many tiles reached the threshold.
 */
function TilesTable({ reading, minConfidence }: { reading: SymbolReading; minConfidence: number }) {
  const named = reading.tiles.filter((tile) => isNamed(tile, minConfidence)).length
  return (
    <Accordion type="single" collapsible className="border-t">
      <AccordionItem value="tiles" className="border-b-0">
        <AccordionTrigger className="text-[11px] tracking-wider text-muted-foreground uppercase hover:no-underline">
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            Every tile
            <Badge variant="outline" className="font-mono tracking-normal normal-case">
              {named}/{reading.tiles.length} at or above {formatPercent(minConfidence)}
            </Badge>
          </span>
        </AccordionTrigger>
        <AccordionContent>
          <div className="overflow-hidden rounded-lg border">
            <Table className="table-fixed">
              <TableHeader className="bg-muted/30">
                <TableRow className="hover:bg-transparent">
                  <TableHead className="px-4">Symbol</TableHead>
                  <TableHead>Code</TableHead>
                  <TableHead>Position</TableHead>
                  <TableHead className="px-4 text-right">Confidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {reading.tiles.map((tile) => {
                  const sure = isNamed(tile, minConfidence)
                  return (
                    <TableRow key={tileKey(tile)} title={sure ? undefined : `Under ${minConfidence}%, so left unnamed`}>
                      <TableCell className={cn('px-4 py-2.5', !sure && 'text-muted-foreground')}>
                        {tile.name ?? tile.code}
                      </TableCell>
                      <TableCell className={cn('py-2.5 text-xs', !sure && 'text-muted-foreground')}>
                        {tile.code}
                      </TableCell>
                      <TableCell className="py-2.5 font-mono text-xs text-muted-foreground">
                        {positionLabel(tile)}
                      </TableCell>
                      <TableCell
                        className={cn(
                          'px-4 py-2.5 text-right font-mono',
                          !sure && 'font-medium text-amber-700 dark:text-amber-400',
                        )}
                      >
                        {formatPercent(tile.confidence)}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </AccordionContent>
      </AccordionItem>
    </Accordion>
  )
}

/**
 * The symbols read off one result screenshot: the classifier's codes and the names the game config gives
 * them, the grid they were read from, and a row of confidence per tile. A tile is named only when the
 * classifier is at least `minConfidence` percent sure of it; the others show "?" in the grids, and their
 * best guess stays in the table.
 */
export function SymbolReadingCard({ reading, minConfidence }: { reading: SymbolReading; minConfidence: number }) {
  const named = reading.tiles.filter((tile) => isNamed(tile, minConfidence)).length

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Eye className="size-4" />
          Symbols on the reels
        </CardTitle>
        <CardDescription>
          Read off the result screenshot by the image classifier — not from the game&apos;s log, and not by
          comparing tiles to each other
        </CardDescription>
        <CardAction>
          <Badge
            variant="outline"
            className="font-mono"
            title={`Tiles the classifier is at least ${minConfidence}% sure of`}
          >
            {named}/{reading.tiles.length} named
          </Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-5">
        <ModelLine model={reading.model} />

        <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
          <Grid label="Codes" columns={reading.columns}>
            {reading.tiles.map((tile) => {
              const sure = isNamed(tile, minConfidence)
              return (
                <span
                  key={tileKey(tile)}
                  className={cn(cellClass, !sure && 'text-muted-foreground')}
                  title={
                    sure ? undefined : `Best guess ${tile.code} at ${formatPercent(tile.confidence)}, under ${minConfidence}%`
                  }
                >
                  {sure ? tile.code : '?'}
                </span>
              )
            })}
          </Grid>
          <Grid label="Symbols" columns={reading.columns}>
            {reading.tiles.map((tile) => {
              const sure = isNamed(tile, minConfidence)
              return (
                <span key={tileKey(tile)} className={cn(cellClass, !sure && 'text-muted-foreground')}>
                  {sure ? (tile.name ?? tile.code) : '—'}
                </span>
              )
            })}
          </Grid>
        </div>

        <ReelsImage reading={reading} />

        <TilesTable reading={reading} minConfidence={minConfidence} />

        <p className="font-mono text-[11px] text-muted-foreground">
          split {reading.id} · {reading.game} · {reading.mode}
        </p>
      </CardContent>
    </Card>
  )
}

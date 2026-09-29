import { Grid3x3 } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import type { PaylineSet, PaytableSummary, WinGeometry } from '@/types/gameConfig'

/** One payline drawn on a grid of reels x rows, filled where the line passes. */
function LineGrid({ line, rows }: { line: number[]; rows: number }) {
  return (
    <div
      role="img"
      aria-label={`Rows by reel: ${line.map((row) => row + 1).join(', ')}`}
      className="grid gap-1"
      style={{ gridTemplateColumns: `repeat(${line.length}, minmax(0, 1fr))` }}
    >
      {Array.from({ length: rows }, (_, row) =>
        line.map((lineRow, reel) => (
          <span
            key={`${row}-${reel}`}
            className={cn(
              'aspect-square rounded-md',
              lineRow === row ? 'bg-foreground' : 'bg-muted',
            )}
          />
        )),
      )}
    </div>
  )
}

function SetChip({
  set,
  selected,
  inPlay,
  onSelect,
}: {
  set: PaylineSet
  selected: boolean
  inPlay: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      title={inPlay ? 'In play for this paytable' : undefined}
      onClick={onSelect}
      className={cn(
        'rounded-lg border px-2.5 py-1 font-mono text-xs font-medium transition-colors',
        selected
          ? 'border-foreground bg-foreground text-background'
          : 'bg-background hover:bg-muted',
        inPlay && !selected && 'border-foreground/60',
      )}
    >
      {set.id} · {set.lines.length}
    </button>
  )
}

interface WinGeometryCardProps {
  geometry: WinGeometry
  summary: PaytableSummary
}

/** Give it a `key` of the paytable, so the set being viewed starts over with each paytable. */
export function WinGeometryCard({ geometry, summary }: WinGeometryCardProps) {
  const [chosen, setChosen] = useState<number | null>(null)
  const shownId = chosen ?? geometry.active_set ?? geometry.sets[0]?.id ?? null
  const shown = geometry.sets.find((set) => set.id === shownId)
  const lines = summary.lines ?? geometry.active_set

  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Grid3x3 className="size-4" aria-hidden />
          Win geometry
        </CardTitle>
        <CardDescription>Which payline set is in play, and where each of its lines runs</CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-3xl font-semibold tabular-nums">{lines ?? '—'}</span>
          {lines !== null ? <Badge variant="secondary">{lines} lines</Badge> : null}
          <span className="text-sm text-muted-foreground">
            {geometry.active_set === null
              ? 'no matching set in this file'
              : "from this paytable's NumberOfLines"}
          </span>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm text-muted-foreground">Sets in this file</span>
          <div className="flex flex-wrap gap-2">
            {geometry.sets.map((set) => (
              <SetChip
                key={set.id}
                set={set}
                selected={set.id === shownId}
                inPlay={set.id === geometry.active_set}
                onSelect={() => setChosen(set.id)}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-wrap items-baseline justify-between gap-3 text-sm">
          <span className="text-muted-foreground">File</span>
          <span className="min-w-0 truncate font-mono text-xs" title={geometry.file}>
            {geometry.file}
          </span>
        </div>

        {shown ? (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-x-6 gap-y-5 border-t pt-5">
            {shown.lines.map((line, index) => (
              <li key={index} className="space-y-1.5">
                <p className="text-xs font-medium tracking-wider text-muted-foreground uppercase">
                  Line {index + 1}
                </p>
                <LineGrid line={line} rows={geometry.rows} />
                <p className="font-mono text-xs text-muted-foreground">
                  {line.map((row) => row + 1).join('')}
                </p>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  )
}

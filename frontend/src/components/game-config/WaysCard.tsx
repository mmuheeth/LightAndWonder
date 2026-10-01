import { Grid3x3 } from 'lucide-react'
import { useMemo } from 'react'

import { LineGrid } from '@/components/game-config/LineGrid'
import { SubHeading } from '@/components/layout/Section'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { PaytableSummary } from '@/types/gameConfig'

/** Drawing more routes than this would bury the page: a 4 x 5 grid holds 1024, a 5 x 5 one 3125. */
const MAX_DRAWN = 1024

/** Every way over the grid: one row picked on each reel, the last reel changing fastest. */
function enumerateWays(reels: number, rows: number): number[][] {
  return Array.from({ length: rows ** reels }, (_, index) => {
    const way = new Array<number>(reels)
    let rest = index
    for (let reel = reels - 1; reel >= 0; reel--) {
      way[reel] = rest % rows
      rest = Math.floor(rest / rows)
    }
    return way
  })
}

interface WaysCardProps {
  summary: PaytableSummary
  /** The grid the paytable is played on, from its default reel set; null when the file does not say. */
  grid: { reels: number; rows: number; source: string } | null
}

/** The ways of a paytable that pays by ways, in place of the payline sets of one that pays by lines. */
export function WaysCard({ summary, grid }: WaysCardProps) {
  const total = grid && grid.reels > 0 && grid.rows > 0 ? grid.rows ** grid.reels : null
  const ways = useMemo(
    () => (grid && total !== null && total <= MAX_DRAWN ? enumerateWays(grid.reels, grid.rows) : []),
    [grid, total],
  )
  const count = summary.lines ?? total

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Grid3x3 aria-hidden />
          Win ways
        </CardTitle>
        <CardDescription>
          This paytable pays by ways, not along lines: a symbol pays for the reels, from the first, that show it
          anywhere, and cells that match on a reel multiply the ways
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-3xl font-semibold tabular-nums">{count ?? '—'}</span>
          {count !== null ? <Badge variant="secondary">{count} ways</Badge> : null}
          <span className="text-sm text-muted-foreground">
            {summary.lines !== null ? "from this paytable's NumberOfLines" : 'from the reel set'}
            {grid ? ` · ${grid.reels} reels × ${grid.rows} rows` : ''}
          </span>
        </div>

        {grid && total !== null && count !== null && total !== count ? (
          <p className="text-sm text-amber-700 dark:text-amber-400">
            The {grid.reels} × {grid.rows} grid of {grid.source} holds {total} ways, not {count}.
          </p>
        ) : null}

        {grid && total !== null && total > MAX_DRAWN ? (
          <p className="border-t pt-5 text-sm text-muted-foreground">
            The {grid.reels} × {grid.rows} grid holds {total} ways, too many to draw.
          </p>
        ) : null}

        {grid && ways.length > 0 ? (
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(9.5rem,1fr))] gap-x-6 gap-y-5 border-t pt-5">
            {ways.map((way, index) => (
              <li key={index} className="space-y-1.5">
                <SubHeading>Way {index + 1}</SubHeading>
                <LineGrid line={way} rows={grid.rows} />
                <p className="font-mono text-xs text-muted-foreground">{way.map((row) => row + 1).join('')}</p>
              </li>
            ))}
          </ul>
        ) : null}
      </CardContent>
    </Card>
  )
}

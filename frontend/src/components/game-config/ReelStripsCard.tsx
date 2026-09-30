import { Rows3 } from 'lucide-react'
import { useMemo, useState } from 'react'

import { SymbolChip } from '@/components/game-config/SymbolChip'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatWeight } from '@/lib/gameConfigFormat'
import type { PaytableConfig, ReelStrip, SymbolInfo } from '@/types/gameConfig'

const setName = (set: { id: string; label: string | null }) =>
  set.label ? `${set.id} (${set.label})` : set.id

interface ReelStripsCardProps {
  config: PaytableConfig
  symbols: ReadonlyMap<string, SymbolInfo>
}

/** Give it a `key` of the paytable, so the set being viewed starts over with each paytable. */
export function ReelStripsCard({ config, symbols }: ReelStripsCardProps) {
  const [chosen, setChosen] = useState<string | null>(null)
  const [showWeights, setShowWeights] = useState(false)

  const strips = useMemo(
    () => new Map<string, ReelStrip>(config.reel_strips.map((strip) => [strip.id, strip])),
    [config.reel_strips],
  )
  const shown =
    config.reel_strip_sets.find((set) => set.id === (chosen ?? config.default_reel_strip_set)) ??
    config.reel_strip_sets[0]
  if (!shown) return null

  const columns = shown.strip_ids.flatMap((id) => strips.get(id) ?? [])
  const stopCount = Math.max(0, ...columns.map((strip) => strip.stops.length))
  // Worth a toggle only when some stops are likelier than others.
  const hasWeights = columns.some((strip) => strip.weights.some((w) => w !== strip.weights[0]))

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Rows3 aria-hidden />
          Reel strips
        </CardTitle>
        <CardDescription>
          {columns.length} strips in {shown.id} · up to {stopCount} stops each
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <Select value={shown.id} onValueChange={setChosen}>
            <SelectTrigger aria-label="Reel strip set" className="h-9 min-w-64 flex-1 font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper">
              {config.reel_strip_sets.map((set) => (
                <SelectItem key={set.id} value={set.id} className="font-mono">
                  {setName(set)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {hasWeights ? (
            <Button
              variant={showWeights ? 'secondary' : 'outline'}
              size="sm"
              aria-pressed={showWeights}
              onClick={() => setShowWeights((on) => !on)}
            >
              Weights
            </Button>
          ) : null}
        </div>

        <Table containerClassName="max-h-[28rem] overflow-y-auto rounded-lg border">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead className="sticky top-0 z-10 w-16 bg-muted text-right shadow-[inset_0_-1px_0_var(--border)]">
                Stop
              </TableHead>
              {columns.map((strip, reel) => (
                <TableHead
                  key={reel}
                  className="sticky top-0 z-10 border-l bg-muted tracking-normal normal-case shadow-[inset_0_-1px_0_var(--border)]"
                >
                  <div className="text-sm font-semibold text-foreground">Reel {reel + 1}</div>
                  <div className="font-mono text-[11px] font-normal">
                    {strip.id} · {strip.stops.length}
                  </div>
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: stopCount }, (_, stop) => (
              <TableRow key={stop}>
                <TableCell className="py-1.5 text-right font-mono text-muted-foreground tabular-nums">
                  {stop}
                </TableCell>
                {columns.map((strip, reel) => {
                  const code = strip.stops[stop]
                  if (code === undefined) return <TableCell key={reel} className="border-l" />
                  const symbol = symbols.get(code) ?? { code, name: code, kind: 'regular' as const }
                  return (
                    <TableCell key={reel} className="border-l py-1.5">
                      <div className="flex items-center gap-3">
                        <SymbolChip code={code} kind={symbol.kind} />
                        <span>{symbol.name}</span>
                        {showWeights ? (
                          <span className="ml-auto pl-2 font-mono text-xs text-muted-foreground tabular-nums">
                            {formatWeight(strip.weights[stop])}
                          </span>
                        ) : null}
                      </div>
                    </TableCell>
                  )
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

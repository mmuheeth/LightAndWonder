import { Coins } from 'lucide-react'
import { Fragment } from 'react'

import { SymbolChip } from '@/components/game-config/SymbolChip'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatPayout } from '@/lib/gameConfigFormat'
import type { PaylineCombos, SymbolInfo } from '@/types/gameConfig'

export function PaylineCombosCard({
  combos,
  symbols,
}: {
  combos: PaylineCombos
  symbols: ReadonlyMap<string, SymbolInfo>
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Coins aria-hidden />
          Payline combos
        </CardTitle>
        <CardDescription>What each symbol pays for a run of it, left to right along a line</CardDescription>
      </CardHeader>

      <CardContent>
        <Table containerClassName="rounded-lg border">
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>Code</TableHead>
              <TableHead>Name</TableHead>
              {combos.lengths.map((length) => (
                <TableHead key={length} className="text-right">
                  x{length}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {combos.rows.map((row) => {
              const info = row.symbols.map(
                (code) => symbols.get(code) ?? { code, name: code, kind: 'regular' as const },
              )
              return (
                <TableRow key={row.symbols.join('/')}>
                  <TableCell className="py-3">
                    <div className="flex items-center gap-2">
                      {info.map((symbol, index) => (
                        <Fragment key={symbol.code}>
                          {index > 0 ? <span className="text-muted-foreground">/</span> : null}
                          <SymbolChip code={symbol.code} kind={symbol.kind} name={symbol.name} />
                        </Fragment>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell className="font-medium">
                    {info.map((symbol) => symbol.name).join(' / ')}
                  </TableCell>
                  {row.payouts.map((payout, index) => (
                    <TableCell
                      key={combos.lengths[index]}
                      className="text-right font-mono tabular-nums"
                    >
                      {payout === null ? <span className="text-muted-foreground">—</span> : formatPayout(payout)}
                    </TableCell>
                  ))}
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

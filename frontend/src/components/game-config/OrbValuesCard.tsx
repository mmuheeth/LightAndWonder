import { Gem } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatProbability, formatWeight } from '@/lib/gameConfigFormat'
import type { OrbTable } from '@/types/gameConfig'

export function OrbValuesCard({ tables }: { tables: OrbTable[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <Gem aria-hidden />
          Orb value range
        </CardTitle>
        <CardDescription>What a landed orb can show, base game, at the minimum bet</CardDescription>
      </CardHeader>

      <CardContent className="space-y-8">
        {tables.map((table) => (
          <section key={table.table} className="space-y-2">
            <div className="flex items-baseline justify-between gap-4">
              <h3 className="font-heading text-sm font-medium">{table.title}</h3>
              <span className="text-xs text-muted-foreground">Bet {table.bet}</span>
            </div>
            <Table containerClassName="rounded-lg border">
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Value</TableHead>
                  <TableHead className="text-right">Weight</TableHead>
                  <TableHead className="text-right">Probability</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {table.values.map((value) => (
                  <TableRow key={value.label}>
                    <TableCell className="py-2.5 font-mono">{value.label}</TableCell>
                    <TableCell className="py-2.5 text-right font-mono tabular-nums">
                      {formatWeight(value.weight)}
                    </TableCell>
                    <TableCell className="py-2.5 text-right font-mono tabular-nums">
                      {formatProbability(value.probability)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        ))}
      </CardContent>
    </Card>
  )
}

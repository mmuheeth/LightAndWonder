import { CircleHelp, TriangleAlert } from 'lucide-react'

import { PayDescription, PaylineSteps } from '@/components/paylines/PaylineRun'
import { PaylineOverlay } from '@/components/paylines/PaylineOverlay'
import { AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion'
import { Badge } from '@/components/ui/badge'
import { cellCode, cellLabel, formatCredits, formatPercent, lineColor, unreadCells } from '@/lib/paylines'
import type { PaylineOutcome, PaylineResult } from '@/types/paylines'

/** What is worth saying about a line besides what it paid. */
function LineNotes({ line, minConfidence }: { line: PaylineOutcome; minConfidence: number }) {
  const unread = unreadCells(line)
  const stoppedAt = line.symbol !== null && line.matches < line.cells.length ? line.cells[line.matches] : null
  if (!stoppedAt && !line.unpaid && unread.length === 0) return null
  return (
    <div className="space-y-1 text-sm text-muted-foreground">
      {stoppedAt ? (
        <p>
          The run stopped at <span className="font-mono text-foreground">{cellLabel(stoppedAt)}</span>.
        </p>
      ) : null}
      {line.unpaid ? (
        <p className="text-amber-700 dark:text-amber-400">
          A run of {line.matches} × {line.symbol_name ?? line.symbol}, which the paytable does not pay.
        </p>
      ) : null}
      {unread.length > 0 ? (
        <p className="text-amber-700 dark:text-amber-400">
          Under the {formatPercent(minConfidence)} floor, so not read:{' '}
          {unread.map((cell) => `${cellLabel(cell)} (best guess ${cell.guess} at ${formatPercent(cell.confidence)})`).join(', ')}
          {line.uncertain ? '. The line may pay more than shown.' : '. It does not change this line.'}
        </p>
      ) : null}
    </div>
  )
}

function LineDetail({ result, line }: { result: PaylineResult; line: PaylineOutcome }) {
  return (
    <div className="space-y-3 border-t pt-3">
      {result.reels ? (
        <PaylineOverlay
          image={result.reels}
          rows={result.rows}
          columns={result.columns}
          lines={[line]}
          frames={line.cells.slice(0, line.matches)}
          alt={`The reels, with line ${line.number} drawn on them`}
          className="max-h-[22rem]"
        />
      ) : null}

      {line.combo ? (
        <div className="space-y-0.5">
          <p className="text-sm text-muted-foreground">
            <PayDescription line={line} />
          </p>
          <p className="font-mono text-[11px] text-muted-foreground">
            {line.combo.pattern.join(' ')} · combo {line.combo.id ?? '—'}
          </p>
        </div>
      ) : null}

      <PaylineSteps line={line} />

      <div className="space-y-0.5 font-mono text-[11px] text-muted-foreground">
        <p>{line.cells.map((cell) => `${cellLabel(cell)}=${cellCode(cell)}`).join(' ')}</p>
        <p className="text-muted-foreground/70">
          winGeometry: {line.cells.map((cell) => `[${cell.column},${cell.row}]`).join(' ')}
        </p>
      </div>

      <LineNotes line={line} minConfidence={result.min_confidence} />
    </div>
  )
}

/** One line of the set, closed to what it read and paid, open to why. */
export function PaylineLineRow({ result, line }: { result: PaylineResult; line: PaylineOutcome }) {
  const pays = line.pays > 0
  return (
    <AccordionItem value={String(line.number)} className="rounded-lg border bg-card px-3 last:border-b">
      <AccordionTrigger className="flex-row-reverse gap-2.5 py-2.5 hover:no-underline">
        <span className="flex min-w-0 flex-1 items-center gap-2.5">
          <span
            aria-hidden
            className="size-3 shrink-0 rounded-full"
            style={{ backgroundColor: lineColor(line.number) }}
          />
          <span className="shrink-0">Line {line.number}</span>
          {pays ? (
            <Badge
              variant="outline"
              className="border-emerald-300 bg-emerald-50 font-mono text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
            >
              matches {line.matches} · pays {formatCredits(line.pays)}
            </Badge>
          ) : (
            <Badge variant="outline" className="font-mono text-muted-foreground">
              no win
            </Badge>
          )}
          {line.unpaid ? (
            <TriangleAlert
              className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
              aria-label="The paytable does not pay this run"
            />
          ) : null}
          {line.uncertain ? (
            <CircleHelp
              className="size-4 shrink-0 text-amber-600 dark:text-amber-400"
              aria-label="A tile under the confidence floor could change this line"
            />
          ) : null}
          <span className="ml-auto truncate pl-2 font-mono text-xs font-normal text-muted-foreground">
            {line.cells.map(cellCode).join(' ')}
          </span>
        </span>
      </AccordionTrigger>
      <AccordionContent className="pb-3">
        <LineDetail result={result} line={line} />
      </AccordionContent>
    </AccordionItem>
  )
}

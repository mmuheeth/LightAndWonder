import { Ban, CircleCheck } from 'lucide-react'
import { Fragment } from 'react'

import { cellCode, cellLabel, formatCredits } from '@/lib/paylines'
import { cn } from '@/lib/utils'
import type { PaylineOutcome, StepRelation } from '@/types/paylines'

const SIGN: Record<StepRelation, { glyph: string; className: string; title: string }> = {
  same: { glyph: '=', className: 'text-emerald-600 dark:text-emerald-400', title: 'The same symbol' },
  wild: { glyph: '=', className: 'text-amber-600 dark:text-amber-400', title: 'A wild stands in' },
  different: { glyph: '≠', className: 'text-foreground', title: 'A different symbol: the run ends here' },
  unknown: { glyph: '≟', className: 'text-amber-600 dark:text-amber-400', title: 'A tile under the confidence floor' },
}

/**
 * The line's symbols in a row, each pair joined by whether they match: BB = BB = BB ≠ FF ≠ EE. What the
 * run did not reach is dimmed.
 */
export function PaylineRun({ line }: { line: PaylineOutcome }) {
  return (
    <p className="font-mono text-xs leading-relaxed">
      <span>{cellCode(line.cells[0])}</span>
      {line.steps.map((step, index) => {
        const sign = SIGN[step.relation]
        return (
          <Fragment key={index}>
            <span
              className={cn('mx-1.5', step.counted ? sign.className : 'text-muted-foreground/60')}
              title={sign.title}
            >
              {sign.glyph}
            </span>
            <span className={cn(!step.counted && 'text-muted-foreground/60')}>{cellCode(line.cells[index + 1])}</span>
          </Fragment>
        )
      })}
    </p>
  )
}

/** "5 × Pisces → 75 credits", and when more than a credit was bet on the line, "(25 × 3 bet)". */
export function PayDescription({ line, creditsPerUnit }: { line: PaylineOutcome; creditsPerUnit: number }) {
  return (
    <>
      {line.matches} × <span className="font-medium text-foreground">{line.symbol_name ?? line.symbol}</span> →{' '}
      <span className="font-medium text-foreground">{formatCredits(line.credits)}</span> credits
      {creditsPerUnit !== 1 ? (
        <>
          {' '}
          ({formatCredits(line.pays)} × {formatCredits(creditsPerUnit)} bet)
        </>
      ) : null}
    </>
  )
}

/** One row per pair of neighbouring tiles: where the run held, and where it stopped. */
export function PaylineSteps({ line }: { line: PaylineOutcome }) {
  return (
    <ul className="space-y-1 font-mono text-xs">
      {line.steps.map((step, index) => {
        const left = line.cells[index]
        const right = line.cells[index + 1]
        const held = step.counted && (step.relation === 'same' || step.relation === 'wild')
        const sign = SIGN[step.relation]
        return (
          <li
            key={index}
            className={cn(
              'grid grid-cols-[1rem_8rem_1fr] items-center gap-x-2',
              !step.counted && 'text-muted-foreground/60',
              step.counted && !held && 'font-medium',
            )}
          >
            {held ? (
              <CircleCheck className="size-3.5 text-emerald-600 dark:text-emerald-400" aria-label="Held" />
            ) : (
              <Ban className="size-3.5" aria-label={step.counted ? 'Stopped here' : 'Not reached'} />
            )}
            <span>
              {cellLabel(left)} · {cellLabel(right)}
            </span>
            <span>
              {cellCode(left)} <span className={step.counted ? sign.className : undefined}>{sign.glyph}</span>{' '}
              {cellCode(right)}
              {step.counted && step.relation === 'wild' ? (
                <span className="ml-2 font-sans text-muted-foreground">wild</span>
              ) : null}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

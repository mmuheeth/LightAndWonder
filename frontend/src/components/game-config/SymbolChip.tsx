import { cn } from '@/lib/utils'
import type { SymbolKind } from '@/types/gameConfig'

const KIND_STYLES: Record<SymbolKind, string> = {
  regular: 'border-border bg-background',
  wild: 'border-foreground/25 bg-muted font-semibold',
  scatter:
    'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200',
}

const KIND_LABELS: Record<SymbolKind, string> = {
  regular: '',
  wild: ' (wild)',
  scatter: ' (scatter)',
}

/** A symbol's two-letter code, tinted by what it does: wilds grey, scatters amber. */
export function SymbolChip({
  code,
  kind,
  name,
  className,
}: {
  code: string
  kind: SymbolKind
  name?: string
  className?: string
}) {
  return (
    <span
      title={name ? `${name}${KIND_LABELS[kind]}` : undefined}
      className={cn(
        'inline-flex min-w-9 items-center justify-center rounded-md border px-2 py-1 font-mono text-xs',
        KIND_STYLES[kind],
        className,
      )}
    >
      {code}
    </span>
  )
}

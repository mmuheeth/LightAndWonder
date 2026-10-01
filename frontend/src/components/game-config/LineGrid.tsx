import { cn } from '@/lib/utils'

/** One route across the reels drawn on a grid of reels x rows, filled where it passes: a payline, or a way. */
export function LineGrid({ line, rows }: { line: number[]; rows: number }) {
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
              'aspect-square rounded-md border',
              lineRow === row ? 'border-foreground bg-foreground' : 'border-input bg-muted',
            )}
          />
        )),
      )}
    </div>
  )
}

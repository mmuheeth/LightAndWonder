import { roiImageSrc } from '@/api/roi'
import { cn } from '@/lib/utils'
import { lineColor, lineOffset, runCells } from '@/lib/paylines'
import type { RoiImage } from '@/types/roi'
import type { PaylineCell } from '@/types/paylines'

interface OverlayLine {
  number: number
  cells: PaylineCell[]
  /** Reels in the run from the left, wilds included: the line is drawn this far and no further. */
  matches: number
}

interface PaylineOverlayProps {
  image: RoiImage
  rows: number
  columns: number
  /** Drawn through the middle of the cells of their run, each in its own colour, and stopping where it ends. */
  lines: OverlayLine[]
  /** Cells to put a frame around, e.g. the ones that make up a run. */
  frames?: PaylineCell[]
  /** Fan the lines out a little, for when several are drawn together. */
  fan?: boolean
  /** Stretch to the width available (up to a limit) rather than show the image at its own size. */
  fill?: boolean
  alt: string
  className?: string
}

/**
 * The reel grid as it was captured, with paylines drawn over it. The grid is cut into equal tiles, so a
 * tile's middle is a fixed fraction of the image whatever size it is shown at.
 */
export function PaylineOverlay({
  image,
  rows,
  columns,
  lines,
  frames = [],
  fan = false,
  fill = false,
  alt,
  className,
}: PaylineOverlayProps) {
  return (
    <div className={cn('relative max-w-full overflow-hidden rounded-lg bg-muted', fill ? 'w-full max-w-6xl' : 'w-fit')}>
      <img
        src={roiImageSrc(image)}
        alt={alt}
        className={cn('block h-auto max-w-full', fill ? 'w-full' : 'w-auto', className)}
      />
      <svg
        aria-hidden
        className="pointer-events-none absolute inset-0 size-full"
        viewBox={`0 0 ${columns} ${rows}`}
        preserveAspectRatio="none"
      >
        {frames.map((cell) => (
          <rect
            key={`${cell.row}-${cell.column}`}
            x={cell.column + 0.025}
            y={cell.row + 0.025}
            width={0.95}
            height={0.95}
            fill="none"
            className="stroke-emerald-500"
            strokeWidth={3}
            vectorEffect="non-scaling-stroke"
          />
        ))}
        {lines.map((line) => {
          const offset = fan ? lineOffset(line.number) : 0
          const run = runCells(line)
          // A run of one tile is drawn as a dot: the same point twice, which the round caps fill in.
          const drawn = run.length > 1 ? run : [run[0], run[0]]
          return (
            <polyline
              key={line.number}
              points={drawn.map((cell) => `${cell.column + 0.5},${cell.row + 0.5 + offset}`).join(' ')}
              fill="none"
              stroke={lineColor(line.number)}
              strokeWidth={3}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={0.9}
              vectorEffect="non-scaling-stroke"
            />
          )
        })}
      </svg>
    </div>
  )
}

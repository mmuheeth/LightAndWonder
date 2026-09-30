import type { PaylineCell, PaylineOutcome } from '@/types/paylines'

/** Golden-angle hues, so any two lines of a set of forty or so stay tellable apart. */
export const lineColor = (number: number) => `hsl(${Math.round((number * 137.508) % 360)} 85% 52%)`

/**
 * Where a line is drawn, in rows, away from the middle of its tiles. Lines that share tiles would
 * otherwise lie on top of each other; this fans them out by a few percent of a row.
 */
export const lineOffset = (number: number) => ((number % 7) - 3) * 0.02

/** Credits as the game shows them: whole numbers plain, thousands grouped. */
export const formatCredits = (value: number) => Number(value.toFixed(2)).toLocaleString('en-US')

export const formatPercent = (value: number) => `${value.toFixed(1)}%`

/** The position as the game's own 1-based row and reel: r1c1 is top left. */
export const cellLabel = (cell: Pick<PaylineCell, 'row' | 'column'>) => `r${cell.row + 1}c${cell.column + 1}`

/** The code of a cell that was read; "??" for one under the confidence floor. */
export const cellCode = (cell: PaylineCell) => cell.code ?? '??'

export const isUnread = (cell: PaylineCell) => cell.code === null

/** The cells of the line that are unread, which may hide a win. */
export const unreadCells = (line: PaylineOutcome) => line.cells.filter(isUnread)

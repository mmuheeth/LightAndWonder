import { Loader2 } from 'lucide-react'

import { roiImageSrc } from '@/api/roi'
import { SubHeading } from '@/components/layout/Section'
import { Badge } from '@/components/ui/badge'
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { CyclicEventType, CyclicMessage, CyclicRegion, CyclicRound, EndReason } from '@/types/cyclic'

/** A reading the recognizer was less sure of than this (percent) is shown as doubtful. */
const DOUBTFUL_BELOW = 80

const REGION_TITLES: Record<string, string> = {
  cyclic_message: 'Cyclic message 1',
  cyclic_message_2: 'Cyclic message 2',
}

const EVENT_LABELS: Record<CyclicEventType, string> = {
  result: 'result',
  first_cycle_done: 'first cycle done',
  cycle_stopped: 'cycle stopped',
  game_over: 'game over',
}

const END_LABELS: Record<EndReason, string> = {
  complete: 'first loop finished',
  next_spin: 'the next spin began',
  timeout: 'gave up waiting',
  stopped: 'tracking was stopped',
  interrupted: 'the backend stopped',
}

/** The log writes the win in the game's smallest currency unit: 400 is 4.00. */
const formatWin = (amount: number) => (amount / 100).toFixed(2)

function WinBadge({ round }: { round: CyclicRound }) {
  if (round.won === null) {
    // Tracking began after the spin, so its result line was never seen.
    return <Badge variant="secondary">{round.end_reason === null ? 'result pending' : 'result not seen'}</Badge>
  }
  if (!round.won) return <Badge variant="secondary">no win</Badge>
  return (
    <Badge className="bg-green-600 text-white" title={`${round.win_amount} in the game's smallest currency unit`}>
      won {round.win_amount === null ? '' : formatWin(round.win_amount)}
    </Badge>
  )
}

function CycleBadge({ region, live }: { region: CyclicRegion; live: boolean }) {
  if (region.cycle === 'closed') {
    return (
      <Badge className="bg-green-600 text-white" title="A message came round again, so the whole cycle was seen">
        cycle seen whole
      </Badge>
    )
  }
  if (region.cycle === 'steady') {
    const label = region.messages.length === 0 ? 'nothing shown' : 'held steady'
    return (
      <Badge variant="secondary" title="After the game went idle it kept showing the same thing">
        {label}
      </Badge>
    )
  }
  if (live) {
    return (
      <Badge variant="secondary">
        <Loader2 className="animate-spin" />
        watching
      </Badge>
    )
  }
  return (
    <Badge
      className="bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
      title="The capture ended before the cycle came round, so there may be more messages"
    >
      cycle incomplete
    </Badge>
  )
}

function Confidence({ value }: { value: number | null }) {
  if (value === null) return null
  const doubtful = value < DOUBTFUL_BELOW
  return (
    <span
      className={cn('font-mono', doubtful && 'font-medium text-amber-700 dark:text-amber-400')}
      title={doubtful ? `The recognizer was only ${value}% sure` : 'How sure the recognizer was'}
    >
      {value.toFixed(0)}%
    </span>
  )
}

/** What the OCR made of a message: its text, or that it is still reading, or why it could not. */
function Reading({ message }: { message: CyclicMessage }) {
  if (message.read_error) return <span className="text-sm text-destructive">{message.read_error}</span>
  if (message.text === null) {
    return (
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="size-4 animate-spin" />
        Reading…
      </span>
    )
  }
  if (message.text === '') return <span className="text-sm text-muted-foreground italic">(no text found)</span>
  return <span className="font-mono text-base">{message.text}</span>
}

/** Crops wider than this are already big, as from a large display, and are shown at their own size. */
const ENLARGE_BELOW_PX = 300

/** The cut-out message, enlarged when it is small (never stretched beyond its cell); clicking opens the file. */
function MessageImage({ message, title }: { message: CyclicMessage; title: string }) {
  const scale = message.width < ENLARGE_BELOW_PX ? 2 : 1
  return (
    <a
      href={roiImageSrc(message)}
      target="_blank"
      rel="noreferrer"
      className="block w-fit max-w-full overflow-hidden rounded-md border bg-muted"
    >
      <img
        src={roiImageSrc(message)}
        alt={`${title}, message ${message.index + 1}, as cut from the screenshot`}
        width={message.width * scale}
        height={message.height * scale}
        className="block h-auto max-w-full [image-rendering:pixelated]"
      />
    </a>
  )
}

function RegionView({ region, live }: { region: CyclicRegion; live: boolean }) {
  const title = REGION_TITLES[region.name] ?? region.name
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <SubHeading>{title}</SubHeading>
        <CycleBadge region={region} live={live} />
      </div>
      {region.messages.length === 0 ? (
        <p className="text-sm text-muted-foreground italic">{live ? 'Nothing shown yet.' : 'Nothing was shown here.'}</p>
      ) : (
        <Table containerClassName="rounded-lg border">
          <TableHeader>
            <TableRow>
              <TableHead className="w-0">#</TableHead>
              <TableHead>Message</TableHead>
              <TableHead>Read as</TableHead>
              <TableHead className="text-right">Sure</TableHead>
              <TableHead className="text-right" title="Seconds after the reels stopped">
                First seen
              </TableHead>
              <TableHead className="text-right">Shown</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {region.messages.map((message) => (
              <TableRow key={message.index}>
                <TableCell className="font-mono text-muted-foreground">{message.index + 1}</TableCell>
                <TableCell>
                  <MessageImage message={message} title={title} />
                </TableCell>
                <TableCell>
                  <Reading message={message} />
                </TableCell>
                <TableCell className="text-right">
                  <Confidence value={message.confidence} />
                </TableCell>
                <TableCell className="text-right font-mono text-sm">{message.first_seen.toFixed(1)} s</TableCell>
                <TableCell className="text-right font-mono text-sm">×{message.appearances}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  )
}

/**
 * One spin: what the two message lines showed from the moment its reels stopped, each distinct message as the image
 * that was cut out and what the OCR read from it, in the order they were shown. `live` is the round being captured.
 */
export function CyclicRoundView({ round, live = false }: { round: CyclicRound; live?: boolean }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex-wrap gap-x-3 gap-y-1">
          {new Date(round.created_at).toLocaleTimeString()}
          <WinBadge round={round} />
        </CardTitle>
        <CardDescription>
          {round.frames} screenshots over {round.seconds.toFixed(1)} s ·{' '}
          {round.end_reason ? `ended: ${END_LABELS[round.end_reason]}` : 'capturing…'}
          {round.events.length > 0 ? (
            <>
              {' · '}
              {round.events.map((event) => `${EVENT_LABELS[event.type]} +${event.at.toFixed(1)} s`).join(', ')}
            </>
          ) : null}
        </CardDescription>
        {live ? (
          <CardAction>
            <Badge className="bg-green-600 text-white">
              <Loader2 className="animate-spin" />
              capturing
            </Badge>
          </CardAction>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-5">
        {round.regions.map((region) => (
          <RegionView key={region.name} region={region} live={live && round.end_reason === null} />
        ))}
      </CardContent>
    </Card>
  )
}

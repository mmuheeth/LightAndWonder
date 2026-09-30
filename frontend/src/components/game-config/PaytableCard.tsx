import { FileBraces, RefreshCw } from 'lucide-react'
import type { ReactNode } from 'react'

import { SubHeading } from '@/components/layout/Section'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardAction, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  formatDenom,
  formatDenomList,
  formatPercent,
  formatPerCredit,
} from '@/lib/gameConfigFormat'
import { cn } from '@/lib/utils'
import type { CurrentPaytable, PaytableSummary } from '@/types/gameConfig'
import type { GameContext } from '@/types/gameContext'

/** Select items cannot have an empty value, so "follow the log" gets one of its own. */
const FOLLOW_LOG = '__log__'

function Row({
  label,
  children,
  className,
}: {
  label: string
  children: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex items-baseline justify-between gap-4', className)}>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{children}</dd>
    </div>
  )
}

/** Why there is no paytable to show yet, in terms of what the user can do about it. */
function waitingMessage(context: GameContext, current: CurrentPaytable | undefined): ReactNode {
  if (!current) return 'Reading the game log…'
  if (!current.log_path) {
    return `${context.game} has no game log configured for ${context.mode} mode.`
  }
  return (
    <>
      {current.log_unreadable
        ? 'The game log cannot be read. Is the game running, and the share reachable?'
        : 'Waiting for the game log to report a paytable…'}
      <span className="mt-1 block truncate font-mono text-xs" title={current.log_path}>
        {current.log_path}
      </span>
    </>
  )
}

interface PaytableCardProps {
  context: GameContext
  /** What the backend says about the log; undefined until it has answered for this game. */
  current: CurrentPaytable | undefined
  /** The paytable being shown: the log's, unless another is being inspected. */
  paytableId: string | null
  inspecting: boolean
  summary: PaytableSummary | undefined
  paytables: string[]
  refreshing: boolean
  onInspect: (paytableId: string | null) => void
  onRefresh: () => void
}

export function PaytableCard({
  context,
  current,
  paytableId,
  inspecting,
  summary,
  paytables,
  refreshing,
  onInspect,
  onRefresh,
}: PaytableCardProps) {
  // The log's denoms belong to the log's paytable, so they mean nothing for an inspected one.
  const denom = inspecting ? null : (current?.denom ?? null)
  const supported = inspecting ? [] : (current?.supported_denoms ?? [])
  // The selected value must be among the items or the trigger shows nothing.
  const options = paytableId && !paytables.includes(paytableId) ? [paytableId, ...paytables] : paytables

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <FileBraces aria-hidden />
          Current paytable
        </CardTitle>
        <CardAction>
          <Button variant="ghost" size="icon-sm" aria-label="Refresh" onClick={onRefresh}>
            <RefreshCw className={cn(refreshing && 'animate-spin')} />
          </Button>
        </CardAction>
      </CardHeader>

      <CardContent className="space-y-5">
        {paytableId ? (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="font-mono text-2xl font-semibold tracking-tight">{paytableId}</p>
              {inspecting ? <Badge variant="secondary">not in play</Badge> : null}
            </div>
            {summary?.display_name ? (
              <p className="text-sm text-muted-foreground">{summary.display_name}</p>
            ) : null}
            {!inspecting && current?.log_unreadable ? (
              <p className="text-sm text-amber-700 dark:text-amber-300">
                The game log cannot be read right now; this is the last paytable it reported.
              </p>
            ) : null}
            {inspecting ? (
              <p className="text-sm text-muted-foreground">
                {current?.paytable_id ? (
                  <>
                    The game log says <span className="font-mono">{current.paytable_id}</span>.{' '}
                  </>
                ) : null}
                <button
                  type="button"
                  className="underline underline-offset-4 hover:text-foreground"
                  onClick={() => onInspect(null)}
                >
                  Follow the log
                </button>
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">{waitingMessage(context, current)}</p>
        )}

        {paytableId && summary ? (
          <dl className="grid gap-x-12 gap-y-3 text-sm md:grid-cols-2">
            <Row label="Return">
              {summary.return_pct !== null ? formatPercent(summary.return_pct) : '—'}
            </Row>
            <Row label="Base game return">
              {summary.base_return_pct !== null ? formatPercent(summary.base_return_pct) : '—'}
            </Row>
            <Row label="Lines">{summary.lines ?? '—'}</Row>
            <Row label="Current denom">
              {denom !== null ? (
                <>
                  {formatDenom(denom)}{' '}
                  <span className="font-mono text-xs font-normal text-muted-foreground">
                    {formatPerCredit(denom)} per credit
                  </span>
                </>
              ) : (
                '—'
              )}
            </Row>
            <Row label="Min total bet">{summary.min_total_bet ?? '—'}</Row>
            <Row label="Max bets">{summary.max_bets.length ? summary.max_bets.join(', ') : '—'}</Row>
            <Row label="Supported denoms" className="md:col-span-2">
              <span className="font-mono text-xs font-normal">
                {supported.length ? formatDenomList(supported) : '—'}
              </span>
            </Row>
          </dl>
        ) : null}

        <div className="space-y-2 border-t pt-5">
          <SubHeading>Inspect another paytable</SubHeading>
          <Select
            value={inspecting && paytableId ? paytableId : FOLLOW_LOG}
            onValueChange={(value) => onInspect(value === FOLLOW_LOG ? null : value)}
          >
            <SelectTrigger aria-label="Paytable to inspect" className="h-9 w-full font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent position="popper" className="max-h-80">
              <SelectItem value={FOLLOW_LOG} className="font-mono">
                Whatever the log says
              </SelectItem>
              {options.map((id) => (
                <SelectItem key={id} value={id} className="font-mono">
                  {id}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  )
}

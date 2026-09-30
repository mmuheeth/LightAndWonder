import { useState } from 'react'
import {
  Activity,
  ArrowLeftRight,
  Coins,
  Dices,
  Eye,
  Gauge,
  HandCoins,
  LayoutGrid,
  List,
  Loader2,
  MessageSquareText,
  Plug,
  RotateCw,
  Unplug,
  Zap,
  type LucideIcon,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useConnectGaf,
  useDisconnectGaf,
  useGafActions,
  useGafStatus,
  useRunGafAction,
} from '@/hooks/useGaf'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { GafActionInfo, GafActionInputs, GafActionParam, GafActionResult } from '@/types/gaf'

/** How many results stay listed. They are only kept while this tab is open. */
const MAX_RESULTS = 10

const ACTION_ICONS: Record<string, LucideIcon> = {
  spin: RotateCw,
  game_state: Activity,
  active_denom: Coins,
  available_denoms: List,
  meters: Gauge,
  take_win: HandCoins,
  gamble: Dices,
  toggle_credit_meter: ArrowLeftRight,
  front_panel_messages: MessageSquareText,
  unique_front_panel_messages: Eye,
  bet_layout: LayoutGrid,
}

interface ActionRun {
  key: number
  at: Date
  result: GafActionResult
}

function StatusBadge({ unreachable, reachable, connected }: {
  unreachable: boolean
  reachable: boolean
  connected: boolean
}) {
  if (unreachable) return <Badge variant="destructive">backend unreachable</Badge>
  if (!reachable) return <Badge variant="destructive">NRobot unreachable</Badge>
  if (connected) return <Badge className="bg-green-600 text-white">connected</Badge>
  return <Badge variant="secondary">disconnected</Badge>
}

/** Why a typed value cannot be used, or null. Choices are always valid; numbers must be within range. */
function problemWith(param: GafActionParam, raw: string): string | null {
  if (param.kind === 'choice') return null
  const value = Number(raw)
  if (raw.trim() === '' || Number.isNaN(value)) return `${param.label} must be a number`
  if (param.min !== null && value < param.min) return `${param.label} is at least ${param.min}`
  if (param.max !== null && value > param.max) return `${param.label} is at most ${param.max}`
  return null
}

const rangeOf = (param: GafActionParam) =>
  param.kind === 'number' && param.min !== null && param.max !== null ? ` (${param.min}–${param.max})` : ''

/**
 * One action: a button, and for an action that takes inputs, the inputs next to it. The inputs start at
 * the defaults the backend gives, and are kept as typed until the game or the action list changes
 * (the parent keys this by both).
 */
function ActionControl({ action, disabled, pending, onRun }: {
  action: GafActionInfo
  disabled: boolean
  pending: boolean
  onRun: (id: string, inputs: GafActionInputs) => void
}) {
  const Icon = ACTION_ICONS[action.id] ?? Zap
  const [typed, setTyped] = useState<Record<string, string>>(() =>
    Object.fromEntries(action.params.map((param) => [param.name, String(param.default)])),
  )
  const problem = action.params.map((param) => problemWith(param, typed[param.name] ?? '')).find(Boolean)

  const button = (
    <Button
      variant={action.id === 'spin' ? 'default' : 'outline'}
      title={problem ?? action.description}
      disabled={disabled || Boolean(problem)}
      onClick={() =>
        onRun(
          action.id,
          Object.fromEntries(
            action.params.map((param) => [
              param.name,
              param.kind === 'number' ? Number(typed[param.name]) : typed[param.name],
            ]),
          ),
        )
      }
    >
      {pending ? <Loader2 className="animate-spin" /> : <Icon />}
      {action.label}
    </Button>
  )
  if (action.params.length === 0) return button

  return (
    <div className="flex flex-wrap items-end gap-2 rounded-lg border p-2" title={action.description}>
      {action.params.map((param) => (
        <label key={param.name} className="space-y-1 text-xs text-muted-foreground">
          {param.label}
          {rangeOf(param)}
          {param.kind === 'choice' ? (
            <select
              value={typed[param.name]}
              onChange={(event) => setTyped((previous) => ({ ...previous, [param.name]: event.target.value }))}
              className="block h-8 rounded-lg border border-input bg-transparent px-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            >
              {param.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          ) : (
            <Input
              value={typed[param.name]}
              onChange={(event) => setTyped((previous) => ({ ...previous, [param.name]: event.target.value }))}
              inputMode="decimal"
              autoComplete="off"
              aria-invalid={problemWith(param, typed[param.name] ?? '') !== null}
              className="w-24 text-foreground"
            />
          )}
        </label>
      ))}
      {button}
    </div>
  )
}

function ResultView({ run }: { run: ActionRun }) {
  const values = Object.entries(run.result.values)
  return (
    <li className="space-y-1 rounded-lg border bg-card p-3">
      <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-medium">{run.result.label}</span>
        <span className="text-xs text-muted-foreground">{run.at.toLocaleTimeString()}</span>
      </p>
      <p className="text-sm">{run.result.message}</p>
      {values.length > 0 ? (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-0.5 text-xs">
          {values.map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="text-muted-foreground">{name}</dt>
              <dd className="font-mono">{Array.isArray(value) ? value.join(' · ') : value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  )
}

export function GafPanel() {
  const context = useGameContextStore((state) => state.context)
  const status = useGafStatus()
  const actions = useGafActions()
  const connect = useConnectGaf()
  const disconnect = useDisconnectGaf()
  const run = useRunGafAction()
  const [runs, setRuns] = useState<ActionRun[]>([])
  const [nextKey, setNextKey] = useState(0)

  const connected = status.data?.connected ?? false
  const reachable = status.data?.reachable ?? false
  const common = actions.data?.filter((action) => action.scope === 'common') ?? []
  const gameSpecific = actions.data?.filter((action) => action.scope === 'game') ?? []

  // Only the newest failure is shown: starting anything clears the others.
  const clearErrors = () => {
    connect.reset()
    disconnect.reset()
    run.reset()
  }

  const runAction = (actionId: string, inputs: GafActionInputs) => {
    if (!context) return
    clearErrors()
    run.mutate(
      { context, actionId, inputs },
      {
        onSuccess: (result) => {
          setRuns((previous) => [{ key: nextKey, at: new Date(), result }, ...previous].slice(0, MAX_RESULTS))
          setNextKey((key) => key + 1)
        },
      },
    )
  }

  const error = connect.error ?? disconnect.error ?? run.error
  // The game connection is shared, so while anything holds it (our own action, or another tab's) the
  // buttons wait rather than being refused as busy.
  const busy = status.data?.busy ?? null
  const buttonsDisabled = !context || !connected || run.isPending || busy !== null
  const pendingAction = run.isPending ? run.variables.actionId : null

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            Game Automation Framework
            <StatusBadge unreachable={status.isError} reachable={reachable} connected={connected} />
            {status.data?.state ? (
              <Badge variant="outline" className="font-mono">
                {status.data.state}
              </Badge>
            ) : null}
            {busy ? (
              <Badge variant="secondary">
                <Loader2 className="animate-spin" />
                {busy}
              </Badge>
            ) : null}
          </CardTitle>
          <CardDescription>
            {context ? (
              <>
                <span className="font-mono text-foreground">{context.game}</span> ·{' '}
                <span className="font-mono text-foreground">{context.mode}</span>
                {status.data?.target ? (
                  <>
                    {' · game at '}
                    <span className="font-mono text-foreground">{status.data.target}</span>
                  </>
                ) : null}
                {status.data ? (
                  <>
                    {' · NRobot at '}
                    <span className="font-mono text-foreground">{status.data.nrobot_url}</span>
                  </>
                ) : null}
              </>
            ) : (
              'Loading selection…'
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <Button
              onClick={() => {
                if (!context) return
                clearErrors()
                connect.mutate(context)
              }}
              disabled={!context || connected || !reachable || !status.data?.target || connect.isPending}
            >
              {connect.isPending ? <Loader2 className="animate-spin" /> : <Plug />}
              {connect.isPending ? 'Connecting…' : 'Connect'}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (!context) return
                clearErrors()
                disconnect.mutate(context)
              }}
              disabled={!context || !connected || disconnect.isPending || run.isPending || busy !== null}
            >
              <Unplug />
              Disconnect
            </Button>
          </div>
          {status.isError ? (
            <p className="text-sm text-destructive">
              Could not load the GAF status: {status.error.message}
            </p>
          ) : status.data?.detail && !connected ? (
            <p className="text-sm text-muted-foreground">{status.data.detail}</p>
          ) : null}
          {error ? <p className="text-sm text-destructive">{error.message}</p> : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Common actions</CardTitle>
          <CardDescription>The same for every game. Connect first.</CardDescription>
        </CardHeader>
        <CardContent>
          {actions.isError ? (
            <p className="text-sm text-destructive">Could not load the actions: {actions.error.message}</p>
          ) : (
            <div className="flex flex-wrap gap-2">
              {common.map((action) => (
                <ActionControl
                  key={`${context?.game}:${context?.mode}:${action.id}`}
                  action={action}
                  disabled={buttonsDisabled}
                  pending={pendingAction === action.id}
                  onRun={runAction}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>{context ? `${context.game} actions` : 'Game actions'}</CardTitle>
          <CardDescription>Only what this game's config lists.</CardDescription>
        </CardHeader>
        <CardContent>
          {gameSpecific.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {gameSpecific.map((action) => (
                <ActionControl
                  key={`${context?.game}:${context?.mode}:${action.id}`}
                  action={action}
                  disabled={buttonsDisabled}
                  pending={pendingAction === action.id}
                  onRun={runAction}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">This game has no game-specific actions.</p>
          )}
        </CardContent>
      </Card>

      <section className="space-y-3">
        <h3 className="font-heading text-base font-medium">Results</h3>
        {runs.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing run yet.</p>
        ) : (
          <ul className="space-y-2">
            {runs.map((entry) => (
              <ResultView key={entry.key} run={entry} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

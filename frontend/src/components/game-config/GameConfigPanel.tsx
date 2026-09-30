import { useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { EmptyState, Notice } from '@/components/ui/notice'
import { OrbValuesCard } from '@/components/game-config/OrbValuesCard'
import { PaylineCombosCard } from '@/components/game-config/PaylineCombosCard'
import { PaytableCard } from '@/components/game-config/PaytableCard'
import { ReelStripsCard } from '@/components/game-config/ReelStripsCard'
import { WinGeometryCard } from '@/components/game-config/WinGeometryCard'
import { useCurrentPaytable, usePaytableConfig, usePaytableList } from '@/hooks/useGameConfig'
import { cn } from '@/lib/utils'
import { useGameContextStore } from '@/store/useGameContextStore'
import type { SymbolInfo } from '@/types/gameConfig'
import type { GameContext } from '@/types/gameContext'

/**
 * The paytable is whatever the game log last reported, and everything below follows it. The
 * view is keyed by game and mode, so an inspected paytable is forgotten when either changes.
 */
export function GameConfigPanel() {
  const context = useGameContextStore((state) => state.context)
  if (!context) return <EmptyState loading title="Loading selection…" />
  return <GameConfigView key={`${context.game}:${context.mode}`} context={context} />
}

function GameConfigView({ context }: { context: GameContext }) {
  const queryClient = useQueryClient()
  const [inspected, setInspected] = useState<string | null>(null)

  const currentQuery = useCurrentPaytable()
  const list = usePaytableList(context)

  // The log watcher moves to another game a moment after the selection does; until it has,
  // what it reports belongs to the previous game.
  const reported = currentQuery.data
  const current =
    reported && reported.game === context.game && reported.mode === context.mode
      ? reported
      : undefined

  const paytableId = inspected ?? current?.paytable_id ?? null
  const detail = usePaytableConfig(context, paytableId)
  const config = paytableId ? detail.data : undefined
  // While the next paytable loads, the previous one stays up, dimmed.
  const stale = config !== undefined && config.paytable_id !== paytableId

  const symbols = useMemo<ReadonlyMap<string, SymbolInfo>>(
    () => new Map((config?.symbols ?? []).map((symbol) => [symbol.code, symbol])),
    [config?.symbols],
  )

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['game-config'] })

  return (
    <div className="space-y-6">
      {currentQuery.isError ? (
        <Notice tone="error">Could not read the game log status: {currentQuery.error.message}</Notice>
      ) : null}

      <PaytableCard
        context={context}
        current={current}
        paytableId={paytableId}
        inspecting={inspected !== null && inspected !== current?.paytable_id}
        summary={config?.summary}
        paytables={list.data?.paytables ?? []}
        refreshing={detail.isFetching || list.isFetching}
        onInspect={setInspected}
        onRefresh={refresh}
      />

      {list.isError ? (
        <Notice tone="error">Could not list paytables: {list.error.message}</Notice>
      ) : null}
      {paytableId && detail.isError ? (
        <Notice tone="error">
          Could not load paytable <span className="font-mono">{paytableId}</span>: {detail.error.message}
        </Notice>
      ) : null}
      {paytableId && detail.isPending ? <EmptyState loading title="Loading paytable…" /> : null}

      {config ? (
        <div
          className={cn('space-y-6 transition-opacity', stale && 'pointer-events-none opacity-50')}
          aria-busy={stale}
        >
          {config.warnings.length > 0 ? (
            <Notice tone="warning">
              <ul className="space-y-1">
                {config.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </Notice>
          ) : null}
          {config.win_geometry ? (
            <WinGeometryCard
              key={`geometry:${config.paytable_id}`}
              geometry={config.win_geometry}
              summary={config.summary}
            />
          ) : null}
          {config.payline_combos ? (
            <PaylineCombosCard combos={config.payline_combos} symbols={symbols} />
          ) : null}
          {config.reel_strip_sets.length > 0 ? (
            <ReelStripsCard key={`reels:${config.paytable_id}`} config={config} symbols={symbols} />
          ) : null}
          {config.orb_tables.length > 0 ? <OrbValuesCard tables={config.orb_tables} /> : null}
        </div>
      ) : null}
    </div>
  )
}

import { GameContextSelectors } from '@/components/layout/GameContextSelectors'
import type { NavTab } from '@/components/layout/navTabs'

/**
 * The same bar on every tab: which page this is and what it is for, and the game and mode every
 * page works on. Stays in view while the page scrolls.
 */
export function PageHeader({ tab }: { tab: NavTab }) {
  const Icon = tab.icon
  return (
    <header className="sticky top-0 z-20 flex h-16 shrink-0 items-center justify-between gap-4 border-b bg-card/90 px-6 shadow-bar backdrop-blur-md lg:px-8">
      <div className="flex min-w-0 items-center gap-3.5">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-xl border bg-gradient-to-b from-card to-muted shadow-card">
          <Icon className="size-5 text-foreground" aria-hidden />
        </span>
        <div className="min-w-0">
          <h1 className="truncate font-heading text-lg leading-tight font-semibold tracking-tight">{tab.label}</h1>
          <p className="hidden truncate text-xs text-muted-foreground sm:block">{tab.description}</p>
        </div>
      </div>
      <GameContextSelectors />
    </header>
  )
}

import { Sparkles } from 'lucide-react'

import { GameContextSelectors } from '@/components/layout/GameContextSelectors'

export function Header() {
  return (
    <header className="flex h-14 items-center justify-between gap-4 border-b bg-background px-4">
      <div className="flex items-center gap-2.5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Sparkles className="size-4" aria-hidden />
        </span>
        <h1 className="font-heading text-lg font-semibold tracking-tight">Light &amp; Wonder</h1>
      </div>
      <GameContextSelectors />
    </header>
  )
}

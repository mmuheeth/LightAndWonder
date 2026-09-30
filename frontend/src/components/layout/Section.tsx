import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A titled block of a page, below the page's main card: the heading, what describes it (badges, a
 * time) beside it, and any actions on the right. Every tab lays its results out with this.
 */
export function Section({
  title,
  meta,
  actions,
  className,
  children,
}: {
  title: ReactNode
  meta?: ReactNode
  actions?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={cn('space-y-3', className)}>
      <div className="flex min-h-8 flex-wrap items-center gap-x-3 gap-y-1.5">
        <h3 className="font-heading text-base font-semibold tracking-tight">{title}</h3>
        {meta}
        {actions ? <div className="ml-auto flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

/** The small caps label over a group inside a card: "Codes", "Awarded", "On the reels". */
export function SubHeading({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h4 className={cn('text-[11px] font-semibold tracking-wider text-muted-foreground uppercase', className)}>
      {children}
    </h4>
  )
}

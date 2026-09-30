import { Tabs as TabsPrimitive } from "radix-ui";

import { NAV_GROUPS } from "@/components/layout/navTabs";
import { cn } from "@/lib/utils";

/**
 * The brand, the tab list (under a heading per group) and the Light & Wonder logo, pinned to the left.
 * Must be rendered inside a <Tabs> root (which is vertical, so the arrow keys move up and down and
 * across groups). Below `lg` only the icons stay, labelled for screen readers and by tooltip, and a
 * rule takes the place of each group's heading.
 */
export function Sidebar() {
  return (
    <aside className="sticky top-0 z-30 flex h-svh w-[4.5rem] shrink-0 flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground shadow-[8px_0_24px_-14px_oklch(0.2_0.02_255/0.2)] lg:w-64">
      <div className="flex h-16 shrink-0 items-center justify-center gap-3 border-b border-sidebar-border lg:justify-start lg:px-5">
        <img
          src="/endurance.svg"
          alt=""
          className="size-9 shrink-0 rounded-[0.6rem] shadow-card"
        />
        <div className="hidden min-w-0 lg:block">
          <p className="font-heading text-[1.2rem] leading-none font-semibold tracking-tight text-foreground">
            Endurance
          </p>
          <p className="mt-1.5 text-[11px] leading-none text-muted-foreground">
            Visual-testing Console
          </p>
        </div>
      </div>

      <nav aria-label="Main" className="flex-1 overflow-y-auto px-3 py-4">
        <TabsPrimitive.List className="flex flex-col">
          {NAV_GROUPS.map((group, index) => (
            <div
              key={group.label}
              role="group"
              aria-label={group.label}
              className={cn(
                "flex flex-col gap-1",
                index > 0 && "mt-5 max-lg:mt-3 max-lg:border-t max-lg:pt-3",
              )}
            >
              <p
                aria-hidden
                className="px-3 pb-1 text-[11px] font-semibold tracking-wider text-muted-foreground uppercase max-lg:hidden"
              >
                {group.label}
              </p>
              {group.tabs.map(({ value, label, icon: Icon }) => (
                <TabsPrimitive.Trigger
                  key={value}
                  value={value}
                  title={label}
                  className="group/nav relative flex h-10 w-full items-center justify-center gap-3 rounded-lg px-3 text-sm font-medium text-sidebar-foreground outline-none transition-colors before:absolute before:top-1/2 before:-left-3 before:h-5 before:w-[3px] before:-translate-y-1/2 before:rounded-r-full before:bg-sidebar-primary before:opacity-0 before:transition-opacity hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-sidebar-ring data-[state=active]:bg-sidebar-accent data-[state=active]:font-semibold data-[state=active]:text-sidebar-accent-foreground data-[state=active]:shadow-[inset_0_0_0_1px_var(--sidebar-border),0_1px_2px_oklch(0.2_0.02_255/0.08)] data-[state=active]:before:opacity-100 lg:justify-start"
                >
                  <Icon className="size-[1.125rem] shrink-0 opacity-70 transition-opacity group-hover/nav:opacity-100 group-data-[state=active]/nav:opacity-100" />
                  <span className="max-lg:sr-only">{label}</span>
                </TabsPrimitive.Trigger>
              ))}
            </div>
          ))}
        </TabsPrimitive.List>
      </nav>

      <div className="flex h-[4.5rem] shrink-0 items-center justify-center border-t border-sidebar-border px-4">
        <img
          src="/lightandwonder-logo.svg"
          alt="Light & Wonder"
          className="hidden h-11 w-auto lg:block"
        />
        <img
          src="/lightandwonder-mark.png"
          alt="Light & Wonder"
          className="size-8 lg:hidden"
        />
      </div>
    </aside>
  );
}

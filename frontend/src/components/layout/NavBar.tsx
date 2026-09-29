import { NAV_TABS } from '@/components/layout/navTabs'
import { TabsList, TabsTrigger } from '@/components/ui/tabs'

/** Must be rendered inside a <Tabs> root. */
export function NavBar() {
  return (
    <nav aria-label="Main" className="border-b bg-background px-4">
      <TabsList variant="line" className="h-11 w-full justify-start gap-1">
        {NAV_TABS.map(({ value, label, icon: Icon }) => (
          <TabsTrigger key={value} value={value} className="flex-none px-3">
            <Icon />
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
    </nav>
  )
}

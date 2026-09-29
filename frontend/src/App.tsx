import { useState } from 'react'

import { Header } from '@/components/layout/Header'
import { NavBar } from '@/components/layout/NavBar'
import { GameConfigPanel } from '@/components/game-config/GameConfigPanel'
import { NAV_TABS } from '@/components/layout/navTabs'
import { ObsPanel } from '@/components/obs/ObsPanel'
import { RoiPanel } from '@/components/roi/RoiPanel'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { useGameContextSync } from '@/hooks/useGameContext'
import { useGameContextStore } from '@/store/useGameContextStore'

function App() {
  const [activeTab, setActiveTab] = useState(NAV_TABS[0].value)
  const { error } = useGameContextSync()
  const context = useGameContextStore((state) => state.context)

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab} className="min-h-svh gap-0">
      <Header />
      <NavBar />
      <main className="flex-1 p-6">
        {error ? (
          <p className="mb-4 text-sm text-destructive">
            Could not load game selection: {error.message}
          </p>
        ) : null}
        {NAV_TABS.map(({ value, label }) => (
          <TabsContent key={value} value={value} className="space-y-4">
            <h2 className="font-heading text-xl font-medium">{label}</h2>
            {value === 'obs' ? (
              <ObsPanel />
            ) : value === 'roi' ? (
              <RoiPanel />
            ) : value === 'game-config' ? (
              <GameConfigPanel />
            ) : (
              <p className="text-sm text-muted-foreground">
                {context ? `${context.game} · ${context.mode}` : 'Loading selection…'}
              </p>
            )}
          </TabsContent>
        ))}
      </main>
    </Tabs>
  )
}

export default App

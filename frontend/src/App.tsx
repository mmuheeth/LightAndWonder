import { useEffect, useState } from "react";

import { Header } from "@/components/layout/Header";
import { NavBar } from "@/components/layout/NavBar";
import { CyclicPanel } from "@/components/cyclic/CyclicPanel";
import { GafPanel } from "@/components/gaf/GafPanel";
import { GameConfigPanel } from "@/components/game-config/GameConfigPanel";
import {
  getTabFromLocation,
  getTabHref,
  NAV_TABS,
} from "@/components/layout/navTabs";
import { ObsPanel } from "@/components/obs/ObsPanel";
import { OcrPanel } from "@/components/ocr/OcrPanel";
import { PaylinePanel } from "@/components/paylines/PaylinePanel";
import { RoiPanel } from "@/components/roi/RoiPanel";
import { SymbolPanel } from "@/components/symbols/SymbolPanel";
import { Tabs, TabsContent } from "@/components/ui/tabs";
import { useGameContextSync } from "@/hooks/useGameContext";
import { useGameContextStore } from "@/store/useGameContextStore";

function App() {
  const [activeTab, setActiveTab] = useState<string>(() =>
    getTabFromLocation(),
  );
  const { error } = useGameContextSync();
  const context = useGameContextStore((state) => state.context);

  useEffect(() => {
    const syncFromLocation = () => {
      const nextTab = getTabFromLocation();
      setActiveTab((current) => (current === nextTab ? current : nextTab));
    };

    window.addEventListener("popstate", syncFromLocation);
    return () => window.removeEventListener("popstate", syncFromLocation);
  }, []);

  useEffect(() => {
    const href = getTabHref(activeTab);
    const current = window.location.pathname;

    if (current !== href) {
      window.history.pushState({}, "", href);
    }
  }, [activeTab]);

  return (
    <Tabs
      value={activeTab}
      onValueChange={setActiveTab}
      className="min-h-svh gap-0"
    >
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
            {value === "obs" ? (
              <ObsPanel />
            ) : value === "gaf" ? (
              <GafPanel />
            ) : value === "roi" ? (
              <RoiPanel />
            ) : value === "ocr" ? (
              <OcrPanel />
            ) : value === "symbol" ? (
              <SymbolPanel />
            ) : value === "paylines" ? (
              <PaylinePanel />
            ) : value === "cyclic-messages" ? (
              <CyclicPanel />
            ) : value === "game-config" ? (
              <GameConfigPanel />
            ) : (
              <p className="text-sm text-muted-foreground">
                {context
                  ? `${context.game} · ${context.mode}`
                  : "Loading selection…"}
              </p>
            )}
          </TabsContent>
        ))}
      </main>
    </Tabs>
  );
}

export default App;

import { useEffect, useState } from "react";

import { PageHeader } from "@/components/layout/PageHeader";
import { Sidebar } from "@/components/layout/Sidebar";
import { CyclicPanel } from "@/components/cyclic/CyclicPanel";
import { GafPanel } from "@/components/gaf/GafPanel";
import { GameConfigPanel } from "@/components/game-config/GameConfigPanel";
import {
  getTab,
  getTabFromLocation,
  getTabHref,
  NAV_TABS,
} from "@/components/layout/navTabs";
import { ObsPanel } from "@/components/obs/ObsPanel";
import { OcrPanel } from "@/components/ocr/OcrPanel";
import { PaylinePanel } from "@/components/paylines/PaylinePanel";
import { RoiPanel } from "@/components/roi/RoiPanel";
import { SymbolPanel } from "@/components/symbols/SymbolPanel";
import { Notice } from "@/components/ui/notice";
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

  // A new tab starts at its top, not wherever the previous one was scrolled to.
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [activeTab]);

  return (
    <Tabs
      value={activeTab}
      onValueChange={setActiveTab}
      orientation="vertical"
      className="min-h-svh flex-row gap-0"
    >
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <PageHeader tab={getTab(activeTab)} />
        <main className="mx-auto w-full max-w-[1400px] flex-1 p-6 lg:p-8">
          {error ? (
            <Notice tone="error" className="mb-6">
              Could not load game selection: {error.message}
            </Notice>
          ) : null}
          {NAV_TABS.map(({ value }) => (
            <TabsContent key={value} value={value}>
              {value === "obs" ? (
                <ObsPanel />
              ) : value === "gaf" ? (
                <GafPanel />
              ) : value === "roi" ? (
                <RoiPanel />
              ) : value === "ocr" ? (
                <OcrPanel />
              ) : value === "symbols" ? (
                <SymbolPanel />
              ) : value === "paylines" ? (
                <PaylinePanel />
              ) : value === "cyclic-messages" ? (
                <CyclicPanel />
              ) : value === "paytables" ? (
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
      </div>
    </Tabs>
  );
}

export default App;

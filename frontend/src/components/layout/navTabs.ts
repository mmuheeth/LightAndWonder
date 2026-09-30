import {
  Crop,
  FileCog,
  Gem,
  type LucideIcon,
  Repeat2,
  ScanText,
  Settings2,
  Spline,
  Video,
} from "lucide-react";

export interface NavTab {
  value: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_TABS: NavTab[] = [
  { value: "obs", label: "Obs", icon: Video },
  { value: "gaf", label: "GAF", icon: FileCog },
  { value: "roi", label: "ROI", icon: Crop },
  { value: "ocr", label: "OCR", icon: ScanText },
  { value: "symbol", label: "Symbol", icon: Gem },
  { value: "paylines", label: "Payline", icon: Spline },
  { value: "cyclic-messages", label: "Cyclic Messages", icon: Repeat2 },
  { value: "game-config", label: "Game Config", icon: Settings2 },
];

export function getDefaultTab(): string {
  return NAV_TABS[0].value;
}

export function getTabFromLocation(): string {
  const tabFromPath = window.location.pathname.replace(/^\/+|\/+$/g, "");
  const tabFromHash = window.location.hash.replace(/^#\/?|\/+$/g, "");
  const lookup = tabFromPath || tabFromHash || getDefaultTab();

  return NAV_TABS.some((tab) => tab.value === lookup)
    ? lookup
    : getDefaultTab();
}

export function getTabHref(tab: string): string {
  return `/${tab}`;
}

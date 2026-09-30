import {
  Crop,
  Gamepad2,
  Gem,
  type LucideIcon,
  Repeat2,
  ScanText,
  Table2,
  Video,
  Waypoints,
} from "lucide-react";

export interface NavTab {
  /** The URL path of the tab. */
  value: string;
  label: string;
  icon: LucideIcon;
  /** One line under the page title: what the tab is for. */
  description: string;
}

/** Tabs that belong together, listed under one heading in the sidebar. */
export interface NavGroup {
  label: string;
  tabs: NavTab[];
}

/** The order here is the order in the sidebar; the first tab is the one the app opens on. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Tools",
    tabs: [
      {
        value: "obs",
        label: "OBS",
        icon: Video,
        description: "Connect to OBS Studio and choose the game window it captures.",
      },
      {
        value: "gaf",
        label: "GAF",
        icon: Gamepad2,
        description: "Drive the game through the Game Automation Framework.",
      },
    ],
  },
  {
    label: "Features",
    tabs: [
      {
        value: "ocr",
        label: "OCR",
        icon: ScanText,
        description: "Read the meters and cyclic messages with PaddleOCR.",
      },
      {
        value: "symbols",
        label: "Symbols",
        icon: Gem,
        description: "Train the classifier and name every tile on the reels.",
      },
      {
        value: "paylines",
        label: "Paylines",
        icon: Waypoints,
        description: "Score the symbols on the reels against the paytable.",
      },
      {
        value: "cyclic-messages",
        label: "Cyclic Messages",
        icon: Repeat2,
        description: "Capture the messages the game cycles through after each spin.",
      },
    ],
  },
  {
    label: "Setup",
    tabs: [
      {
        value: "roi",
        label: "ROI",
        icon: Crop,
        description: "Cut the game's regions of interest out of a screenshot.",
      },
    ],
  },
  {
    label: "Reference",
    tabs: [
      {
        value: "paytables",
        label: "PayTables",
        icon: Table2,
        description: "Inspect the paytable the game is running.",
      },
    ],
  },
];

export const NAV_TABS: NavTab[] = NAV_GROUPS.flatMap((group) => group.tabs);

export function getDefaultTab(): string {
  return NAV_TABS[0].value;
}

export function getTab(value: string): NavTab {
  return NAV_TABS.find((tab) => tab.value === value) ?? NAV_TABS[0];
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

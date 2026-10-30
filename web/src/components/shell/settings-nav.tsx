// Settings entries added by the workspace shell: Workspace, Memory, Agents, Voice, Shortcuts and
// Computer are real pages.

import { lazy, type ComponentType } from "react";
import { Bot, Brain, FolderTree, Keyboard, Mic, Monitor } from "lucide-react";
import type { ShellStrings } from "@/i18n/types";

const WorkspaceSettingsPage = lazy(() => import("@/pages/WorkspaceSettingsPage"));
const MemorySettingsPage = lazy(() => import("@/pages/MemorySettingsPage"));
const AgentsSettingsPage = lazy(() => import("@/pages/ConfigSettingsPages").then((m) => ({ default: m.AgentsSettingsPage })));
const VoiceSettingsPage = lazy(() => import("@/pages/ConfigSettingsPages").then((m) => ({ default: m.VoiceSettingsPage })));
const ShortcutsSettingsPage = lazy(() =>
  import("@/pages/ConfigSettingsPages").then((m) => ({ default: m.ShortcutsSettingsPage })),
);
const ComputerSettingsPage = lazy(() =>
  import("@/pages/ConfigSettingsPages").then((m) => ({ default: m.ComputerSettingsPage })),
);

export interface ShellNavItem {
  path: string;
  labelKey: keyof ShellStrings;
  icon: ComponentType<{ className?: string }>;
}

export const SHELL_SETTINGS_NAV: readonly ShellNavItem[] = [
  { path: "/settings/workspace", labelKey: "navWorkspace", icon: FolderTree },
  { path: "/settings/memory", labelKey: "navMemory", icon: Brain },
  { path: "/settings/agents", labelKey: "navAgents", icon: Bot },
  { path: "/settings/voice", labelKey: "navVoice", icon: Mic },
  { path: "/settings/shortcuts", labelKey: "navShortcuts", icon: Keyboard },
  { path: "/settings/computer", labelKey: "navComputer", icon: Monitor },
];

export const SHELL_SETTINGS_ROUTES: Record<string, ComponentType> = {
  "/settings/workspace": WorkspaceSettingsPage,
  "/settings/memory": MemorySettingsPage,
  "/settings/agents": AgentsSettingsPage,
  "/settings/voice": VoiceSettingsPage,
  "/settings/shortcuts": ShortcutsSettingsPage,
  "/settings/computer": ComputerSettingsPage,
};

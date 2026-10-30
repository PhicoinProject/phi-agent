// The shell's left side: SpaceBar (column 1) plus RoomList or SettingsColumn
// (column 2) on desktop; on phones the drawer shows the space tree with rooms,
// or the settings nav with a back button. Column 2's right edge drags to resize.

import { useEffect } from "react";
import { useLocation } from "react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RoomList } from "./RoomList";
import { SettingsColumn, type NavItem } from "./SettingsColumn";
import { SpaceBar } from "./SpaceBar";
import { useColumnResize } from "./use-column-resize";
import { useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

export const ROOM_COLUMN_WIDTH_KEY = "phi-room-column-width";

export interface ShellColumnsProps {
  /** Below lg: render the drawer variant. */
  isMobile: boolean;
  collapsed: boolean;
  nav: { coreItems: NavItem[]; pluginItems: NavItem[] };
  status: StatusResponse | null;
  /** Called after navigating (closes the drawer). */
  onNavigate: () => void;
}

export function ShellColumns({ isMobile, collapsed, nav, status, onNavigate }: ShellColumnsProps) {
  const { pathname } = useLocation();
  const s = useShellStrings();
  const { mode, setMode } = useWorkspaceShell();
  const { width, separatorProps } = useColumnResize({
    storageKey: ROOM_COLUMN_WIDTH_KEY,
    defaultWidth: 288,
    min: 220,
    max: () => Math.min(560, window.innerWidth * 0.45),
    label: s.resizeColumn,
  });

  // Chat shows the rooms; every other page belongs to settings. Clicking a
  // space or Settings switches the column without navigating.
  useEffect(() => {
    setMode((pathname.replace(/\/$/, "") || "/") === "/chat" ? "rooms" : "settings");
  }, [pathname, setMode]);

  const settings = (onBack?: () => void) => (
    <SettingsColumn
      coreItems={nav.coreItems}
      pluginItems={nav.pluginItems}
      status={status}
      onNavigate={onNavigate}
      onBack={onBack}
    />
  );

  if (isMobile) {
    return (
      <div className="flex min-h-0 flex-1 flex-col pb-[env(safe-area-inset-bottom,0px)]">
        {mode === "settings" ? settings(() => setMode("rooms")) : <SpaceBar showRooms onNavigate={onNavigate} />}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1">
      <div
        className={cn(
          "flex min-h-0 shrink-0 flex-col border-r border-current/10 transition-[width] duration-300",
          collapsed ? "w-14" : "w-56",
        )}
      >
        <SpaceBar collapsed={collapsed} />
      </div>
      <div data-testid="room-column" className="relative flex min-h-0 shrink-0 flex-col" style={{ width }}>
        {mode === "settings" ? settings() : <RoomList />}
        <div {...separatorProps} />
      </div>
    </div>
  );
}

/** Column 1's collapse toggle (desktop only). It has no row of its own: App puts it in the
 *  sidebar header row, right of "Phi Agent", where it stays put in both widths. */
export function CollapseToggle({ collapsed, onToggle }: { collapsed: boolean; onToggle: () => void }) {
  const s = useShellStrings();
  const label = collapsed ? s.expand : s.collapse;
  return (
    <Button
      type="button"
      ghost
      size="icon"
      aria-label={label}
      title={label}
      data-testid="sidebar-collapse"
      className="ml-auto hidden text-text-secondary hover:text-midground lg:grid"
      onClick={onToggle}
    >
      {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
    </Button>
  );
}

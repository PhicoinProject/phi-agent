// Column 1 of the shell: Home, the space tree (spaces only — rooms
// live in column 2), "+ Create space" and Settings. With `showRooms` (the phone
// drawer) each space also lists its rooms, since column 2 is not on screen.
// Spaces drag onto another space (becoming its sub-space) or onto Home (top level).

import { useEffect, useState, type DragEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ChevronDown, ChevronRight, Home, Plus, Settings, SquarePen } from "lucide-react";
import { Select, SelectOption } from "@phi/ui/ui/components/select";
import type { WorkspaceSpaceNode } from "@/lib/api-workspace";
import { canCreateSubSpace, flattenSpaces, orderHome, spaceDropRefusal } from "@/lib/workspace-tree";
import { cn } from "@/lib/utils";
import { isRoomDrag, isSpaceDrag, readRoomDrag, readSpaceDrag, roomDropArgs, startSpaceDrag } from "./room-gestures";
import { RoomRow } from "./RoomRow";
import { NameDialog } from "./ShellDialogs";
import { roomHref } from "./shell-nav";
import { startNewChat } from "./start-new-chat";
import { errorMessage } from "@/lib/api-error";
import { fmt, useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

export interface SpaceBarProps {
  /** Column 1 at CELL width; App's sidebar header holds the toggle. */
  collapsed?: boolean;
  /** Room ids with a running task; a space shows `*` when any room under it runs. */
  running?: ReadonlySet<string>;
  unread?: Readonly<Record<string, number>>;
  /** Phone drawer: list rooms under each space. */
  showRooms?: boolean;
  /** Called after a room opens (closes the drawer). */
  onNavigate?: () => void;
}

function subtreeRuns(node: WorkspaceSpaceNode, running: ReadonlySet<string>): boolean {
  return node.rooms.some((r) => running.has(r)) || node.children.some((c) => subtreeRuns(c, running));
}

/**
 * Drop a dragged room on a space (or Home): move; Ctrl/Cmd-drop: add. A dragged space
 * becomes a sub-space of the target (Home: top level) unless that would nest it in itself
 * or past the limit; the payload is only readable on drop, so the check runs there.
 */
function useRoomDrop(to: string | null) {
  const s = useShellStrings();
  const { tree, maxDepth, moveRoom, notify } = useWorkspaceShell();
  const [over, setOver] = useState(false);
  return {
    over,
    handlers: {
      onDragOver: (e: DragEvent) => {
        const space = isSpaceDrag(e);
        if (!space && !isRoomDrag(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = !space && (e.ctrlKey || e.metaKey) ? "copy" : "move";
        setOver(true);
      },
      onDragLeave: () => setOver(false),
      onDrop: (e: DragEvent) => {
        setOver(false);
        const space = readSpaceDrag(e);
        if (space) {
          e.preventDefault();
          if (space.space_id === to || space.from === to) return;
          const refusal = spaceDropRefusal(tree?.spaces ?? [], space.space_id, to, maxDepth);
          if (refusal === "cycle") notify(s.spaceDropCycle, "error");
          else if (refusal === "depth") notify(fmt(s.spaceDropDepth, { depth: maxDepth }), "error");
          else void moveRoom(space.space_id, space.from, to);
          return;
        }
        const payload = readRoomDrag(e);
        if (!payload) return;
        e.preventDefault();
        const args = roomDropArgs(e, payload, to);
        if (args) void moveRoom(...args);
      },
    },
  };
}

// Expanded column: 12px padding, a 32px icon slot, gap-2, then the label. Avatar, Home,
// top-level space chevrons, + and Settings (and App's header logo) use the slot, so every
// icon centres on x=28 — the collapsed CELL's centre — and every label starts at x=52.
// Rows are inset pills: px-1 on the list + px-2 here keeps the icon column at x=28 and labels at x=52.
const ROW = "flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left text-sm transition-colors hover:bg-midground/5 lg:min-h-9";
const ICON = "flex h-8 w-8 shrink-0 items-center justify-center";
// Collapsed column: every entry is the same centred square, so avatar,
// Home, space initials, + and Settings share one vertical centre line.
const CELL = "relative mx-auto flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-sm transition-colors hover:bg-midground/5";

function HomeEntry({ collapsed, showRooms, ctx }: { collapsed: boolean; showRooms: boolean; ctx: RowCtx }) {
  const s = useShellStrings();
  const { tree, selectedSpace, selectSpace, setMode, mode } = useWorkspaceShell();
  const { over, handlers } = useRoomDrop(null);
  const active = mode === "rooms" && selectedSpace === null;
  return (
    <li>
      <button
        type="button"
        {...handlers}
        title={s.home}
        aria-current={active ? "true" : undefined}
        className={cn(collapsed ? CELL : ROW, active && "phi-nav-selected bg-midground/10 text-midground", over && "ring-2 ring-brand/60")}
        onClick={() => {
          selectSpace(null);
          setMode("rooms");
        }}
      >
        <span className={ICON}>
          <Home className="h-4 w-4" />
        </span>
        {!collapsed && <span className="truncate">{s.home}</span>}
      </button>
      {showRooms && <RoomRows ids={orderHome(tree?.home ?? [])} space={null} ctx={ctx} />}
    </li>
  );
}

interface RowCtx {
  running: ReadonlySet<string>;
  unread: Readonly<Record<string, number>>;
  activeRoom: string | null;
  open: (roomId: string) => void;
}

function RoomRows({ ids, space, ctx }: { ids: string[]; space: string | null; ctx: RowCtx }) {
  if (ids.length === 0) return null;
  return (
    <ul className="pl-4">
      {ids.map((id) => (
        <RoomRow
          key={id}
          roomId={id}
          space={space}
          active={ctx.activeRoom === id}
          unread={ctx.unread[id]}
          running={ctx.running.has(id)}
          onOpen={ctx.open}
        />
      ))}
    </ul>
  );
}

function SpaceNode({
  node,
  parent,
  depth,
  collapsed,
  showRooms,
  expanded,
  toggle,
  ctx,
}: {
  node: WorkspaceSpaceNode;
  /** Space this occurrence sits in; null = top level. */
  parent: string | null;
  depth: number;
  collapsed: boolean;
  showRooms: boolean;
  expanded: ReadonlySet<string>;
  toggle: (id: string) => void;
  ctx: RowCtx;
}) {
  const s = useShellStrings();
  const { selectedSpace, selectSpace, setMode, mode, loadRooms } = useWorkspaceShell();
  const { over, handlers } = useRoomDrop(node.room_id);
  const open = expanded.has(node.room_id);
  const expandable = node.children.length > 0 || (showRooms && node.rooms.length > 0);
  const active = mode === "rooms" && selectedSpace === node.room_id;
  const runs = subtreeRuns(node, ctx.running);
  // Expanded: the whole row highlights. Collapsed: only the square does.
  const highlight = cn(active && "phi-nav-selected bg-midground/10 text-midground", over && "ring-2 ring-brand/60");

  useEffect(() => {
    if (showRooms && open) void loadRooms(node.room_id);
  }, [showRooms, open, node.room_id, loadRooms]);

  return (
    <li data-space-id={node.room_id}>
      <div
        {...handlers}
        draggable
        onDragStart={(e) => startSpaceDrag(e, { space_id: node.room_id, from: parent })}
        className={cn("flex items-center gap-2", !collapsed && cn("rounded-md transition-colors hover:bg-midground/5", highlight))}
        style={collapsed ? undefined : { paddingLeft: 8 + depth * 12 }}
      >
        {!collapsed && (
          <button
            type="button"
            aria-label={open ? s.collapse : s.expand}
            aria-expanded={expandable ? open : undefined}
            disabled={!expandable}
            className={cn(ICON, "h-11 disabled:opacity-0 lg:h-9")}
            onClick={() => toggle(node.room_id)}
          >
            {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        )}
        <button
          type="button"
          title={node.name}
          aria-current={active ? "true" : undefined}
          className={collapsed ? cn(CELL, highlight) : cn(ROW, "min-w-0 flex-1 pl-0 hover:bg-transparent")}
          onClick={() => {
            selectSpace(node.room_id);
            setMode("rooms");
            if (showRooms) toggle(node.room_id);
          }}
        >
          {collapsed ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-midground/10 text-xs font-semibold uppercase">
              {node.name.slice(0, 1)}
            </span>
          ) : (
            <span className="truncate">{node.name}</span>
          )}
          {runs && (
            <span
              data-testid="space-running"
              aria-label={s.running}
              title={s.running}
              className={cn("text-midground", collapsed && "absolute right-0 top-0 leading-none")}
            >
              *
            </span>
          )}
        </button>
      </div>
      {!collapsed && open && (
        <>
          {showRooms && <RoomRows ids={node.rooms} space={node.room_id} ctx={ctx} />}
          {node.children.length > 0 && (
            <ul>
              {node.children.map((child) => (
                <SpaceNode
                  key={child.room_id}
                  node={child}
                  parent={node.room_id}
                  depth={depth + 1}
                  collapsed={collapsed}
                  showRooms={showRooms}
                  expanded={expanded}
                  toggle={toggle}
                  ctx={ctx}
                />
              ))}
            </ul>
          )}
        </>
      )}
    </li>
  );
}

const NO_RUNNING: ReadonlySet<string> = new Set();
const NO_UNREAD: Readonly<Record<string, number>> = {};

export function SpaceBar({
  collapsed = false,
  running = NO_RUNNING,
  unread = NO_UNREAD,
  showRooms = false,
  onNavigate,
}: SpaceBarProps) {
  const s = useShellStrings();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { tree, maxDepth, error, createSpace, setMode, mode, loadRooms, newChat, notify, selectedSpace } = useWorkspaceShell();
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const [creating, setCreating] = useState(false);
  // "" = top level (Select values are strings).
  const [parent, setParent] = useState("");
  const parentOptions = flattenSpaces(tree?.spaces ?? []).filter((sp) => canCreateSubSpace(sp.level, maxDepth));

  useEffect(() => {
    if (showRooms) void loadRooms(null);
  }, [showRooms, loadRooms]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  const ctx: RowCtx = {
    running,
    unread,
    activeRoom: params.get("room"),
    open: (roomId) => {
      navigate(roomHref(roomId));
      onNavigate?.();
    },
  };

  return (
    <nav aria-label={s.spaces} data-testid="space-bar" className="flex h-full min-h-0 flex-col">
      <ul className="min-h-0 flex-1 overflow-y-auto px-1 py-2">
        <HomeEntry collapsed={collapsed} showRooms={showRooms} ctx={ctx} />
        {(tree?.spaces ?? []).map((node) => (
          <SpaceNode
            key={node.room_id}
            node={node}
            parent={null}
            depth={0}
            collapsed={collapsed}
            showRooms={showRooms}
            expanded={expanded}
            toggle={toggle}
            ctx={ctx}
          />
        ))}
      </ul>
      {error && !collapsed && <p role="alert" className="px-3 py-1 text-xs text-destructive">{error}</p>}

      <div className="flex flex-col border-t border-current/10 px-1 py-2">
        {showRooms && (
          <button
            type="button"
            title={s.newChat}
            data-testid="drawer-new-chat"
            className={ROW}
            onClick={() => {
              startNewChat(selectedSpace, ctx.open, newChat).catch((e) =>
                notify(fmt(s.newChatFailed, { error: errorMessage(e) }), "error"),
              );
            }}
          >
            <span className={ICON}>
              <SquarePen className="h-4 w-4" />
            </span>
            <span className="truncate">{s.newChat}</span>
          </button>
        )}
        <button
          type="button"
          title={s.createSpace}
          className={collapsed ? CELL : ROW}
          onClick={() => {
            setParent("");
            setCreating(true);
          }}
        >
          <span className={ICON}>
            <Plus className="h-4 w-4" />
          </span>
          {!collapsed && <span className="truncate">{s.createSpace}</span>}
        </button>
        <button
          type="button"
          title={s.settings}
          aria-current={mode === "settings" ? "true" : undefined}
          className={cn(collapsed ? CELL : ROW, mode === "settings" && "phi-nav-selected bg-midground/10 text-midground")}
          onClick={() => setMode("settings")}
        >
          <span className={ICON}>
            <Settings className="h-4 w-4" />
          </span>
          {!collapsed && <span className="truncate">{s.settings}</span>}
        </button>
      </div>

      <NameDialog
        open={creating}
        title={s.createSpace}
        label={s.spaceName}
        submitLabel={s.create}
        onOpenChange={setCreating}
        onSubmit={(name) => createSpace(name, parent || null)}
      >
        <div className="flex flex-col gap-1 text-xs">
          {s.parentSpace}
          <Select value={parent} onValueChange={setParent}>
            <SelectOption value="">{s.topLevel}</SelectOption>
            {parentOptions.map((sp) => (
              <SelectOption key={sp.room_id} value={sp.room_id}>
                {sp.path}
              </SelectOption>
            ))}
          </Select>
        </div>
      </NameDialog>
    </nav>
  );
}

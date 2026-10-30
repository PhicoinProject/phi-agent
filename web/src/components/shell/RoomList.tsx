// Column 2 of the shell: the selected space's rooms (or Home's), with search
// (Ctrl/Cmd+K), All / Unread / Running filters, sub-spaces as collapsible
// groups, and the space's "..." and "+" menus.

import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { CheckCheck, ChevronDown, ChevronRight, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { Input } from "@phi/ui/ui/components/input";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { errorMessage } from "@/lib/api-error";
import { workspaceApi } from "@/lib/api-workspace";
import type { WorkspaceSpaceNode } from "@/lib/api-workspace";
import { canCreateSubSpace, findSpace, matchesQuery, orderHome, parentsOf, spaceLevel } from "@/lib/workspace-tree";
import { cn } from "@/lib/utils";
import { ActionMenu, MENU_ITEM_CLASS } from "./ActionMenu";
import { RoomRow } from "./RoomRow";
import { AddExistingRoomDialog, NameDialog } from "./ShellDialogs";
import { roomHref } from "./shell-nav";
import { startNewChat } from "./start-new-chat";
import { useRoomActivity } from "./use-room-activity";
import { fmt, useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

type Filter = "all" | "unread" | "running";
type DialogKind = "subspace" | "existing" | "rename" | "delete" | null;

/** Explicit maps override the polled `/api/workspace/activity` state. */
export interface RoomListProps {
  unread?: Readonly<Record<string, number>>;
  running?: ReadonlySet<string>;
}

interface ListCtx {
  show: (id: string) => boolean;
  unread: Readonly<Record<string, number>>;
  running: ReadonlySet<string>;
  activeRoom: string | null;
  open: (id: string) => void;
}

function Rows({ ids, space, ctx }: { ids: string[]; space: string | null; ctx: ListCtx }) {
  return (
    <ul>
      {ids.filter(ctx.show).map((id) => (
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

function SubSpaceGroup({ node, ctx }: { node: WorkspaceSpaceNode; ctx: ListCtx }) {
  const { loadRooms } = useWorkspaceShell();
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (open) void loadRooms(node.room_id);
  }, [open, node.room_id, loadRooms]);
  return (
    <li data-group-id={node.room_id}>
      <button
        type="button"
        aria-expanded={open}
        className="mx-1 flex min-h-11 w-[calc(100%-0.5rem)] items-center gap-1 rounded-md px-2 text-left text-xs font-medium uppercase tracking-wide opacity-60 hover:bg-midground/5 lg:min-h-8"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <span className="truncate">{node.name}</span>
      </button>
      {open && (
        <div className="pl-2">
          <Rows ids={node.rooms} space={node.room_id} ctx={ctx} />
          <ul>
            {node.children.map((child) => (
              <SubSpaceGroup key={child.room_id} node={child} ctx={ctx} />
            ))}
          </ul>
        </div>
      )}
    </li>
  );
}

/** The space that holds sub-space `id` (first match), or null for a top-level space. */
function parentSpaceOf(nodes: WorkspaceSpaceNode[], id: string): string | null {
  for (const n of nodes) {
    if (n.children.some((c) => c.room_id === id)) return n.room_id;
    const hit = parentSpaceOf(n.children, id);
    if (hit) return hit;
  }
  return null;
}

export function RoomList({ unread: unreadProp, running: runningProp }: RoomListProps) {
  const s = useShellStrings();
  const activity = useRoomActivity(!unreadProp || !runningProp);
  const unread = unreadProp ?? activity.unread;
  const running = runningProp ?? activity.running;
  const counts = { all: 0, unread: Object.values(unread).filter((n) => n > 0).length, running: running.size };
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { tree, rooms, maxDepth, selectedSpace, selectSpace, loadRooms, newChat, createSpace, rename, notify, refresh } =
    useWorkspaceShell();
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [menu, setMenu] = useState<"space" | "add" | null>(null);
  const [dialog, setDialog] = useState<DialogKind>(null);
  // @phi/ui Input takes no ref; reach the field through its label.
  const searchRef = useRef<HTMLLabelElement>(null);

  const node = selectedSpace ? findSpace(tree?.spaces ?? [], selectedSpace) : null;
  const level = spaceLevel(tree?.spaces ?? [], selectedSpace);
  const title = node?.name ?? s.home;

  useEffect(() => {
    void loadRooms(selectedSpace);
  }, [selectedSpace, loadRooms]);

  // A room opened by link (reload, notification, search hit) shows up in its space's list: when the
  // URL's room is not in the list on screen, select its first parent space. Only on a room change,
  // so picking another space by hand afterwards is never overridden.
  const urlRoom = params.get("room");
  // The room on screen is read: clear its badge on open and whenever a reply lands while it is shown.
  const shownUnread = urlRoom ? (unread[urlRoom] ?? 0) : 0;
  const { markSeen } = activity;
  useEffect(() => {
    if (urlRoom && !unreadProp) markSeen(urlRoom);
  }, [urlRoom, shownUnread, unreadProp, markSeen]);
  const placedRoom = useRef<string | null>(null);
  useEffect(() => {
    if (!tree || !urlRoom || placedRoom.current === urlRoom) return;
    placedRoom.current = urlRoom;
    const shown = node ? node.rooms : tree.home;
    if (shown.includes(urlRoom) || tree.home.includes(urlRoom)) return;
    const parent = parentsOf(tree, urlRoom)[0];
    if (parent) selectSpace(parent);
  }, [tree, urlRoom, node, selectSpace]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        const field = searchRef.current?.querySelector("input");
        field?.focus();
        field?.select();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const open = (id: string) => navigate(roomHref(id));
  const ctx: ListCtx = {
    show: (id) =>
      (filter === "all" || (filter === "unread" ? (unread[id] ?? 0) > 0 : running.has(id))) &&
      matchesQuery({ room_id: id, name: rooms[id]?.name ?? "" }, query),
    unread,
    running,
    activeRoom: params.get("room"),
    open,
  };
  // While searching, jump across every room the shell knows about.
  const searching = query.trim() !== "";
  const hits = searching ? Object.keys(rooms).filter(ctx.show) : [];
  const ids = node ? node.rooms : orderHome(tree?.home ?? []);
  const pick = (next: DialogKind) => {
    setMenu(null);
    setDialog(next);
  };

  return (
    <section aria-label={title} data-testid="room-list" className="flex h-full min-h-0 flex-col">
      <div className="flex flex-col gap-2 border-b border-current/10 p-3">
        <label ref={searchRef} className="relative flex items-center">
          <Search className="pointer-events-none absolute left-2 h-4 w-4 opacity-60" />
          <Input
            type="search"
            aria-label={s.searchRooms}
            placeholder={s.searchRooms}
            value={query}
            className="pl-8"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && hits[0]) open(hits[0]);
              if (e.key === "Escape") setQuery("");
            }}
          />
        </label>
        <div className="flex items-center gap-1">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h2>
          {node && (
            <ActionMenu
              label={s.spaceMenu}
              icon={<MoreHorizontal className="h-4 w-4" />}
              open={menu === "space"}
              onOpenChange={(v) => setMenu(v ? "space" : null)}
            >
              <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => pick("rename")}>
                {s.rename}
              </button>
              <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => pick("existing")}>
                {s.addExistingRoom}
              </button>
              {canCreateSubSpace(level, maxDepth) && (
                <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => pick("subspace")}>
                  {s.newSubSpace}
                </button>
              )}
              <button
                type="button"
                role="menuitem"
                className={cn(MENU_ITEM_CLASS, "border-t border-border/50 text-destructive")}
                data-testid="delete-space"
                onClick={() => pick("delete")}
              >
                <Trash2 className="h-4 w-4" />
                {s.deleteSpace}
              </button>
            </ActionMenu>
          )}
          <Button
            type="button"
            ghost
            size="icon"
            aria-label={s.newChat}
            title={s.newChat}
            data-testid="new-chat"
            onClick={() => {
              startNewChat(selectedSpace, open, newChat).catch((e) =>
                notify(fmt(s.newChatFailed, { error: errorMessage(e) }), "error"),
              );
            }}
          >
            <Plus className="h-4 w-4" />
          </Button>
        </div>
        <div role="group" className="flex items-center gap-1">
          {(["all", "unread", "running"] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              className={cn(
                "min-h-8 rounded-md px-3 text-xs font-medium transition-colors",
                filter === f ? "bg-brand/15 text-midground" : "opacity-70 hover:bg-midground/5 hover:opacity-100",
              )}
              onClick={() => setFilter(f)}
            >
              {f === "all" ? s.filterAll : f === "unread" ? s.filterUnread : s.filterRunning}
              {counts[f] > 0 && (
                <span data-testid={`filter-count-${f}`} className="ml-1 font-mono">
                  {counts[f]}
                </span>
              )}
            </button>
          ))}
          <Button
            type="button"
            ghost
            size="icon"
            className="ml-auto disabled:bg-transparent disabled:opacity-40"
            aria-label={s.markAllRead}
            title={s.markAllRead}
            data-testid="mark-all-read"
            disabled={counts.unread === 0}
            onClick={() => {
              activity.markAllSeen().catch((e) => notify(fmt(s.markAllReadFailed, { error: errorMessage(e) }), "error"));
            }}
          >
            <CheckCheck className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto py-2">
        {searching ? (
          <Rows ids={hits} space={null} ctx={ctx} />
        ) : (
          <>
            <Rows ids={ids} space={selectedSpace} ctx={ctx} />
            {node && node.children.length > 0 && (
              <ul>
                {node.children.map((child) => (
                  <SubSpaceGroup key={child.room_id} node={child} ctx={ctx} />
                ))}
              </ul>
            )}
          </>
        )}
        {(searching ? hits.length === 0 : ids.filter(ctx.show).length === 0 && !node?.children.length) && (
          <p className="px-3 py-2 text-sm opacity-60">{s.noRooms}</p>
        )}
      </div>

      <NameDialog
        open={dialog === "subspace"}
        title={s.createSubSpace}
        label={s.spaceName}
        submitLabel={s.create}
        onOpenChange={(v) => !v && setDialog(null)}
        onSubmit={(name) => createSpace(name, selectedSpace)}
      />
      {node && (
        <>
          <NameDialog
            open={dialog === "rename"}
            title={fmt(s.renameTitle, { name: node.name })}
            label={s.spaceName}
            submitLabel={s.save}
            initial={node.name}
            onOpenChange={(v) => !v && setDialog(null)}
            onSubmit={(name) => rename(node.room_id, name)}
          />
          <AddExistingRoomDialog
            open={dialog === "existing"}
            space={node.room_id}
            onOpenChange={(v) => !v && setDialog(null)}
          />
          <ConfirmDialog
            open={dialog === "delete"}
            title={fmt(s.deleteSpaceTitle, { name: node.name })}
            description={s.deleteSpaceBody}
            confirmLabel={s.deleteSpace}
            destructive
            loading={deleting}
            onCancel={() => setDialog(null)}
            onConfirm={() => {
              const { room_id, name } = node;
              const up = parentSpaceOf(tree?.spaces ?? [], room_id);
              setDeleting(true);
              workspaceApi
                .deleteSpace(room_id)
                .then(async () => {
                  setDialog(null);
                  selectSpace(up);
                  notify(fmt(s.deleteSpaceDone, { name }), "success");
                  await refresh();
                })
                .catch((e) => notify(fmt(s.deleteSpaceFailed, { error: errorMessage(e) }), "error"))
                .finally(() => setDeleting(false));
            }}
          />
        </>
      )}
    </section>
  );
}

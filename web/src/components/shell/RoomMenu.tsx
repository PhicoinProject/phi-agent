// A room's "..." menu: rename, move / add to a space, copy its directory, open
// Files, room settings and archive. Opened by the button or a long-press.

import { useState } from "react";
import { useNavigate } from "react-router";
import {
  Archive,
  ChevronDown,
  ChevronRight,
  Copy,
  FolderOpen,
  FolderInput,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Settings,
} from "lucide-react";
import { copyTextToClipboard } from "@/lib/clipboard";
import { errorMessage } from "@/lib/api-error";
import { AGENT_ROOM_ID, workspaceApi } from "@/lib/api-workspace";
import { flattenSpaces, parentsOf } from "@/lib/workspace-tree";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import { ActionMenu, MENU_ITEM_CLASS } from "./ActionMenu";
import { NameDialog } from "./ShellDialogs";
import { fmt, useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

type Sub = "move" | "add" | null;

export function RoomMenu({
  roomId,
  space,
  open,
  onOpenChange,
}: {
  roomId: string;
  /** Space the room is listed under; null = Home. */
  space: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const s = useShellStrings();
  const navigate = useNavigate();
  const p = usePanelStrings();
  const { tree, rooms, moveRoom, rename, notify, refresh } = useWorkspaceShell();
  const [sub, setSub] = useState<Sub>(null);
  const [renaming, setRenaming] = useState(false);
  const room = rooms[roomId];
  const name = room?.name ?? roomId;
  const spaces = flattenSpaces(tree?.spaces ?? []);
  const linked = tree ? parentsOf(tree, roomId) : [];
  const movable = roomId !== AGENT_ROOM_ID;

  const close = () => {
    setSub(null);
    onOpenChange(false);
  };
  const toggleSub = (next: Exclude<Sub, null>) => setSub((cur) => (cur === next ? null : next));
  const move = (from: string | null, to: string | null) => {
    close();
    void moveRoom(roomId, from, to);
  };
  const copyPath = async () => {
    close();
    const path = room?.path ?? room?.rel_path;
    if (path && (await copyTextToClipboard(path))) notify(s.pathCopied, "success");
  };

  const archive = async () => {
    close();
    try {
      await workspaceApi.archive(roomId);
      notify(fmt(p.archived, { name }), "success");
      await refresh();
    } catch (e) {
      notify(fmt(p.archiveFailed, { error: errorMessage(e) }), "error");
    }
  };

  const targets = (kind: Exclude<Sub, null>) => {
    const list = spaces.filter((sp) => sp.room_id !== space && (kind === "move" || !linked.includes(sp.room_id)));
    return (
      <div role="group" aria-label={kind === "move" ? s.moveToSpace : s.addToSpace} className="border-y border-border/50 py-1 pl-4">
        {kind === "move" && space !== null && (
          <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => move(space, null)}>
            {s.home}
          </button>
        )}
        {list.map((sp) => (
          <button
            key={sp.room_id}
            type="button"
            role="menuitem"
            className={MENU_ITEM_CLASS}
            onClick={() => move(kind === "move" ? space : null, sp.room_id)}
          >
            {sp.path}
          </button>
        ))}
      </div>
    );
  };

  const Chevron = (kind: Exclude<Sub, null>) =>
    sub === kind ? <ChevronDown className="ml-auto h-4 w-4" /> : <ChevronRight className="ml-auto h-4 w-4" />;

  return (
    <>
      <ActionMenu
        label={s.roomMenu}
        icon={<MoreHorizontal className="h-4 w-4" />}
        open={open}
        onOpenChange={(next) => (next ? onOpenChange(true) : close())}
        triggerClassName="h-8 w-8 opacity-70 hover:opacity-100"
      >
        <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => { close(); setRenaming(true); }}>
          <Pencil className="h-4 w-4" />
          {s.rename}
        </button>
        {movable && (
          <>
            <button type="button" role="menuitem" aria-haspopup="menu" aria-expanded={sub === "move"} className={MENU_ITEM_CLASS} onClick={() => toggleSub("move")}>
              <FolderInput className="h-4 w-4" />
              {s.moveToSpace}
              {Chevron("move")}
            </button>
            {sub === "move" && targets("move")}
            <button type="button" role="menuitem" aria-haspopup="menu" aria-expanded={sub === "add"} className={MENU_ITEM_CLASS} onClick={() => toggleSub("add")}>
              <FolderPlus className="h-4 w-4" />
              {s.addToSpace}
              {Chevron("add")}
            </button>
            {sub === "add" && targets("add")}
          </>
        )}
        <button type="button" role="menuitem" className={MENU_ITEM_CLASS} disabled={!room?.path && !room?.rel_path} onClick={() => void copyPath()}>
          <Copy className="h-4 w-4" />
          {s.copyPath}
        </button>
        <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => { close(); navigate(room?.path ? `/files?path=${encodeURIComponent(room.path)}` : "/files"); }}>
          <FolderOpen className="h-4 w-4" />
          {s.openInFiles}
        </button>
        <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => { close(); notify(s.roomSettingsSoon, "success"); }}>
          <Settings className="h-4 w-4" />
          {s.roomSettings}
        </button>
        {movable && (
          <button type="button" role="menuitem" className={MENU_ITEM_CLASS} onClick={() => void archive()}>
            <Archive className="h-4 w-4" />
            {s.archive}
          </button>
        )}
      </ActionMenu>
      <NameDialog
        open={renaming}
        title={fmt(s.renameTitle, { name })}
        label={s.roomName}
        submitLabel={s.save}
        initial={room?.name ?? ""}
        onOpenChange={setRenaming}
        onSubmit={(next) => rename(roomId, next)}
      />
    </>
  );
}

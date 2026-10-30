// One room in the room list (and in the mobile drawer's tree): opens on click,
// drags onto a space, long-press or "..." opens the room menu.

import { useState } from "react";
import { Bot, Hash } from "lucide-react";
import { AGENT_ROOM_ID } from "@/lib/api-workspace";
import { cn } from "@/lib/utils";
import { RoomMenu } from "./RoomMenu";
import { startRoomDrag, useLongPress } from "./room-gestures";
import { useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

export function RoomRow({
  roomId,
  space,
  active = false,
  unread = 0,
  running = false,
  onOpen,
}: {
  roomId: string;
  /** Space this row is listed under; null = Home. */
  space: string | null;
  active?: boolean;
  unread?: number;
  running?: boolean;
  onOpen: (roomId: string) => void;
}) {
  const s = useShellStrings();
  const { rooms } = useWorkspaceShell();
  const [menuOpen, setMenuOpen] = useState(false);
  const longPress = useLongPress(() => setMenuOpen(true));
  const agent = roomId === AGENT_ROOM_ID;
  const name = rooms[roomId]?.name || (agent ? s.agentDm : roomId);
  const Icon = agent ? Bot : Hash;

  return (
    <li
      data-room-id={roomId}
      draggable={!agent}
      onDragStart={(e) => startRoomDrag(e, { room_id: roomId, from: space })}
      {...longPress}
      className={cn(
        "group mx-1 flex min-h-11 items-center gap-1 rounded-md pr-1 transition-colors lg:min-h-9",
        active ? "phi-nav-selected bg-midground/10 text-midground" : "hover:bg-midground/5",
      )}
    >
      <button
        type="button"
        className="flex min-h-11 min-w-0 flex-1 items-center gap-2 px-2 text-left text-sm lg:min-h-9"
        aria-current={active ? "page" : undefined}
        onClick={() => onOpen(roomId)}
      >
        <Icon className="h-4 w-4 shrink-0 opacity-70" />
        <span className="truncate">{name}</span>
        {running && (
          <span data-testid="room-running" aria-label={s.running} title={s.running} className="text-midground">
            *
          </span>
        )}
      </button>
      {unread > 0 && (
        <span data-testid="room-unread" className="min-w-5 rounded-full bg-brand px-1.5 text-center text-xs font-semibold tabular-nums text-brand-foreground">
          {unread}
        </span>
      )}
      <RoomMenu roomId={roomId} space={space} open={menuOpen} onOpenChange={setMenuOpen} />
    </li>
  );
}

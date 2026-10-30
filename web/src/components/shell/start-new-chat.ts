// New chat: the server hands back the space's empty "New chat" room (or makes
// one) and the chat page opens it, so the PTY starts inside the room's
// directory at once. The first message the user types names the room.

import { workspaceApi } from "@/lib/api-workspace";
import type { WorkspaceRoom } from "@/lib/api-workspace";

/** Gets `space`'s New chat room, then opens it. Throws (opening nothing) if the call fails. */
export async function startNewChat(
  space: string | null,
  openRoom: (roomId: string) => void,
  create: (space: string | null) => Promise<WorkspaceRoom> = (s) => workspaceApi.newChat(s),
): Promise<string> {
  const room = await create(space);
  openRoom(room.room_id);
  return room.room_id;
}

/** What to type once the PTY opens: a `?learn=` seed (removed from the URL so a reload doesn't repeat it). */
export function takeOpenSeed(
  searchParams: URLSearchParams,
  setSearchParams: (next: URLSearchParams, opts: { replace: boolean }) => void,
): string | null {
  const learnSeed = searchParams.get("learn");
  if (!learnSeed) return null;
  const next = new URLSearchParams(searchParams);
  next.delete("learn");
  setSearchParams(next, { replace: true });
  return `/learn ${learnSeed}`.trim();
}

// Running / unread state per room from GET /api/workspace/activity, polled
// while the tab is visible and refreshed the moment it becomes visible again.
// Opening a room or "mark all as read" clears its badge at once (a seen marker
// is posted and the next poll is taken right away); a reply after that counts again.

import { useCallback, useEffect, useRef, useState } from "react";
import { workspaceApi, type RoomActivity } from "@/lib/api-workspace";

export const ACTIVITY_POLL_MS = 10_000;

export interface RoomActivityState {
  unread: Readonly<Record<string, number>>;
  running: ReadonlySet<string>;
}

export interface RoomActivityApi extends RoomActivityState {
  /** The room was shown: clear its badge and record it server-side. */
  markSeen: (roomId: string) => void;
  /** Mark every room as read. */
  markAllSeen: () => Promise<void>;
}

const EMPTY: RoomActivityState = { unread: {}, running: new Set() };

export function activityState(res: RoomActivity): RoomActivityState {
  const unread: Record<string, number> = {};
  const running = new Set<string>();
  for (const [id, room] of Object.entries(res?.rooms ?? {})) {
    if (room?.running) running.add(id);
    if (typeof room?.unread === "number" && room.unread > 0) unread[id] = room.unread;
  }
  return { unread, running };
}

export function useRoomActivity(enabled = true): RoomActivityApi {
  const [state, setState] = useState<RoomActivityState>(EMPTY);
  const pollRef = useRef<() => Promise<void>>(async () => undefined);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    let inFlight = false;
    const poll = async () => {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      try {
        const res = await workspaceApi.activity();
        if (alive) setState(activityState(res));
      } catch {
        // Older servers lack the route; the filters just stay empty.
      } finally {
        inFlight = false;
      }
    };
    pollRef.current = poll;
    const onVisible = () => {
      if (document.visibilityState === "visible") void poll();
    };
    void poll();
    const timer = window.setInterval(() => void poll(), ACTIVITY_POLL_MS);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [enabled]);

  const markSeen = useCallback((roomId: string) => {
    setState((prev) => {
      if (!prev.unread[roomId]) return prev;
      const unread = { ...prev.unread };
      delete unread[roomId];
      return { ...prev, unread };
    });
    void workspaceApi
      .markSeen(roomId)
      .then(() => pollRef.current())
      .catch(() => undefined);
  }, []);

  const markAllSeen = useCallback(async () => {
    setState((prev) => ({ ...prev, unread: {} }));
    await workspaceApi.markAllSeen();
    await pollRef.current();
  }, []);

  return { ...state, markSeen, markAllSeen };
}

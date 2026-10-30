// Room and space drag-and-drop payloads and the touch long-press used to open a room's menu.

import { useCallback, useEffect, useRef, type DragEvent, type TouchEvent } from "react";

export const ROOM_DRAG_TYPE = "application/x-phi-room";

export interface RoomDragPayload {
  room_id: string;
  /** Space the room was dragged out of; null = Home. */
  from: string | null;
}

export function startRoomDrag(e: DragEvent, payload: RoomDragPayload): void {
  e.dataTransfer.setData(ROOM_DRAG_TYPE, JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "copyMove";
}

export function isRoomDrag(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes(ROOM_DRAG_TYPE);
}

export function readRoomDrag(e: DragEvent): RoomDragPayload | null {
  try {
    const parsed = JSON.parse(e.dataTransfer.getData(ROOM_DRAG_TYPE)) as RoomDragPayload;
    return typeof parsed?.room_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export const SPACE_DRAG_TYPE = "application/x-phi-space";

export interface SpaceDragPayload {
  space_id: string;
  /** Parent space it was dragged out of; null = top level. */
  from: string | null;
}

export function startSpaceDrag(e: DragEvent, payload: SpaceDragPayload): void {
  e.dataTransfer.setData(SPACE_DRAG_TYPE, JSON.stringify(payload));
  e.dataTransfer.effectAllowed = "move";
}

export function isSpaceDrag(e: DragEvent): boolean {
  return Array.from(e.dataTransfer?.types ?? []).includes(SPACE_DRAG_TYPE);
}

export function readSpaceDrag(e: DragEvent): SpaceDragPayload | null {
  try {
    const parsed = JSON.parse(e.dataTransfer.getData(SPACE_DRAG_TYPE)) as SpaceDragPayload;
    return typeof parsed?.space_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Drop onto a space: a plain drop moves the room out of `from`; Ctrl/Cmd-drop also keeps
 * it where it was (POST /api/workspace/move with from = null adds a link).
 */
export function roomDropArgs(
  e: Pick<DragEvent, "ctrlKey" | "metaKey">,
  payload: RoomDragPayload,
  to: string | null,
): [string, string | null, string | null] | null {
  const add = e.ctrlKey || e.metaKey;
  if (add && to === null) return null; // Home is "no space"; nothing to add to
  const from = add ? null : payload.from;
  if (from === to) return null;
  return [payload.room_id, from, to];
}

const LONG_PRESS_MS = 500;

/** Touch long-press → `onLongPress`; a move cancels it so scrolling never opens the menu. */
export function useLongPress(onLongPress: () => void) {
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fired = useRef(false);
  const clear = useCallback(() => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  useEffect(() => clear, [clear]);
  return {
    onTouchStart: (_e: TouchEvent) => {
      fired.current = false;
      clear();
      timer.current = setTimeout(() => {
        fired.current = true;
        onLongPress();
      }, LONG_PRESS_MS);
    },
    onTouchMove: clear,
    onTouchEnd: (e: TouchEvent) => {
      clear();
      // Swallow the click that follows a long-press so the room doesn't also open.
      if (fired.current) e.preventDefault();
    },
    onTouchCancel: clear,
  };
}

const EDGE_PX = 32;
const SWIPE_PX = 60;

/** Swipe right starting at the left screen edge → `onSwipe` (the phone "back to rooms"). */
export function useEdgeSwipe(onSwipe: () => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  return {
    onTouchStart: (e: TouchEvent) => {
      const t = e.touches[0];
      start.current = t && t.clientX < EDGE_PX ? { x: t.clientX, y: t.clientY } : null;
    },
    onTouchEnd: (e: TouchEvent) => {
      const from = start.current;
      start.current = null;
      const t = e.changedTouches[0];
      if (!from || !t) return;
      const dx = t.clientX - from.x;
      if (dx > SWIPE_PX && Math.abs(t.clientY - from.y) < dx) onSwipe();
    },
  };
}

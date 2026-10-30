// Drag-to-resize for a column edge, Element-style: a vertical separator that
// changes the width live under the pointer, steps with Left/Right, resets on
// double-click and remembers the width in localStorage. The column using it
// must be `relative`; the handle sits inside its start or end edge.

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { cn } from "@/lib/utils";

export const RESIZE_STEP = 16;

export function clampWidth(width: number, min: number, max: number): number {
  return Math.round(Math.min(Math.max(width, min), Math.max(min, max)));
}

function readWidth(key: string): number | null {
  try {
    const raw = localStorage.getItem(key);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function writeWidth(key: string, value: number | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, String(value));
  } catch {
    /* localStorage may be unavailable in private browsing */
  }
}

type Px = number | (() => number);
const px = (value: Px) => (typeof value === "function" ? value() : value);

export interface ColumnResizeOptions {
  storageKey: string;
  /** Width with nothing stored, and after a double-click reset. */
  defaultWidth: Px;
  min: number;
  /** Re-read on window resize, so it may depend on the viewport. */
  max: Px;
  /** The handle's side: "end" = right edge (dragging right widens), "start" = left edge. */
  edge?: "start" | "end";
  label: string;
}

export function useColumnResize({ storageKey, defaultWidth, min, max, edge = "end", label }: ColumnResizeOptions) {
  const [stored, setStored] = useState<number | null>(() => readWidth(storageKey));
  const [, setViewport] = useState(0);
  const drag = useRef<{ x: number; width: number; last: number } | null>(null);

  useEffect(() => {
    const onResize = () => setViewport((n) => n + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const maxWidth = Math.max(min, Math.round(px(max)));
  const width = clampWidth(stored ?? px(defaultWidth), min, maxWidth);
  const dir = edge === "end" ? 1 : -1;

  const commit = (value: number) => {
    const next = clampWidth(value, min, maxWidth);
    setStored(next);
    writeWidth(storageKey, next);
  };

  const endDrag = (e: PointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (!d) return;
    drag.current = null;
    e.currentTarget.releasePointerCapture?.(e.pointerId);
    writeWidth(storageKey, d.last);
  };

  const separatorProps = {
    role: "separator",
    "aria-orientation": "vertical" as const,
    "aria-label": label,
    "aria-valuenow": width,
    "aria-valuemin": min,
    "aria-valuemax": maxWidth,
    tabIndex: 0,
    title: label,
    className: cn(
      "absolute inset-y-0 z-10 w-1.5 cursor-col-resize touch-none select-none bg-clip-content px-0.5 outline-none",
      "hover:bg-current/20 focus-visible:bg-current/20 active:bg-current/20",
      edge === "end" ? "right-0" : "left-0",
    ),
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      if (e.button !== 0) return;
      e.preventDefault();
      e.currentTarget.setPointerCapture?.(e.pointerId);
      drag.current = { x: e.clientX, width, last: width };
    },
    onPointerMove: (e: PointerEvent<HTMLElement>) => {
      const d = drag.current;
      if (!d) return;
      d.last = clampWidth(d.width + dir * (e.clientX - d.x), min, maxWidth);
      setStored(d.last);
    },
    onPointerUp: endDrag,
    onPointerCancel: endDrag,
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      commit(width + dir * (e.key === "ArrowRight" ? RESIZE_STEP : -RESIZE_STEP));
    },
    onDoubleClick: () => {
      setStored(null);
      writeWidth(storageKey, null);
    },
  };

  return { width, separatorProps };
}

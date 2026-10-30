/**
 * Pure helpers for the Computer panel: lease ownership, panzoom-aware pointer mapping, keysyms.
 * Kept free of React and noVNC so the panel's tricky arithmetic is unit-testable.
 */
import type { DisplayLease } from "@phi/shared";

/** The display bridge closes a viewer's stream with this code when the lease changes hands. */
export const CLOSE_CONTROL_TAKEN = 4000;
/** A watch re-attach evicted again within this window counts as a rapid eviction. */
export const EVICTION_LOOP_WINDOW_MS = 10_000;
export const MAX_RAPID_EVICTIONS = 3;
/** noVNC ClientCutText ceiling the bridge accepts. */
export const MAX_PASTE_CUT_TEXT = 256 * 1024;
export const MOBILE_BREAKPOINT = 768;
export const DEFAULT_GEOMETRY = { height: 1080, width: 1920 };

/** "1920x1080" → size; anything unparsable falls back to the 1920x1080 default. */
export function parseGeometry(geometry: string | null | undefined): { width: number; height: number } {
  const m = /^\s*(\d{2,5})\s*x\s*(\d{2,5})\s*$/i.exec(geometry ?? "");
  return m ? { height: Number(m[2]), width: Number(m[1]) } : { ...DEFAULT_GEOMETRY };
}

/**
 * True when the lease is a human lease (exclusive or shared) taken by THIS panel. The lease names its
 * holder by `viewer_hash`; we remember the hash the server returned for our own `display.lease.acquire`
 * rather than hashing the viewer id locally (crypto.subtle is missing on plain-HTTP dashboards).
 */
export function leaseHeldBy(lease: DisplayLease | null | undefined, heldHash: string | null | undefined): boolean {
  return Boolean(lease && heldHash && lease.holder !== "agent" && lease.viewer_hash === heldHash);
}

export interface ClientPoint {
  clientX: number;
  clientY: number;
}

export interface RectLike {
  left: number;
  top: number;
}

/**
 * noVNC maps a pointer with the canvas's getBoundingClientRect(), which already includes the
 * panzoom CSS scale, and then divides only by its own viewport scale. Re-express the point as if
 * the canvas were untransformed so the remote click lands under the finger.
 */
export function correctForPanzoom(point: ClientPoint, rect: RectLike, scale: number): ClientPoint {
  if (!(scale > 0) || scale === 1) return { clientX: point.clientX, clientY: point.clientY };
  return {
    clientX: rect.left + (point.clientX - rect.left) / scale,
    clientY: rect.top + (point.clientY - rect.top) / scale,
  };
}

/** What noVNC does with a client point: offset into the canvas rect, divided by its viewport scale. */
export function clientToFramebuffer(point: ClientPoint, rect: RectLike, viewportScale: number): { x: number; y: number } {
  return {
    x: Math.floor((point.clientX - rect.left) / viewportScale),
    y: Math.floor((point.clientY - rect.top) / viewportScale),
  };
}

export const KEYSYM = {
  Alt: 0xffe9,
  BackSpace: 0xff08,
  Control: 0xffe3,
  Down: 0xff54,
  Escape: 0xff1b,
  Left: 0xff51,
  Return: 0xff0d,
  Right: 0xff53,
  Tab: 0xff09,
  Up: 0xff52,
} as const;

/** X11 keysym for a typed character: Latin-1 maps to itself, other Unicode to 0x01000000 | cp. */
export function keysymForChar(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0;
  if (ch === "\n" || ch === "\r") return KEYSYM.Return;
  if (ch === "\t") return KEYSYM.Tab;
  return cp < 0x100 ? cp : 0x01000000 | cp;
}

/** Special keys from a hidden-input keydown that the virtual keyboard will not deliver as text. */
export const SPECIAL_KEYS: Record<string, { keysym: number; code: string }> = {
  ArrowDown: { code: "ArrowDown", keysym: KEYSYM.Down },
  ArrowLeft: { code: "ArrowLeft", keysym: KEYSYM.Left },
  ArrowRight: { code: "ArrowRight", keysym: KEYSYM.Right },
  ArrowUp: { code: "ArrowUp", keysym: KEYSYM.Up },
  Backspace: { code: "Backspace", keysym: KEYSYM.BackSpace },
  Enter: { code: "Enter", keysym: KEYSYM.Return },
  Escape: { code: "Escape", keysym: KEYSYM.Escape },
  Tab: { code: "Tab", keysym: KEYSYM.Tab },
};

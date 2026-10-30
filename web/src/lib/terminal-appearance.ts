/**
 * Terminal appearance helpers shared by the chat composer's xterm host:
 * theme colors, font size and line height. Extracted from ChatPage.tsx so the
 * page file can keep shrinking (repo file-size ratchet).
 *
 * Font size: 14px default on every width (phones included), never below 13px,
 * adjustable per device via a step offset persisted in localStorage.
 */

// Colors for the terminal body.  Matches the dashboard's dark teal canvas
// with cream foreground — we intentionally don't pick monokai or a loud
// theme, because the TUI's skin engine already paints the content; the
// terminal chrome just needs to sit quietly inside the dashboard.
export const DEFAULT_TERMINAL_BACKGROUND = "#000000";
export const DEFAULT_TERMINAL_FOREGROUND = "#f0e6d2";

export function buildTerminalTheme(background: string, foreground: string) {
  return {
    background,
    foreground,
    cursor: foreground,
    cursorAccent: background,
    selectionBackground:
      foreground.length === 7 ? `${foreground}44` : foreground,
  };
}

/**
 * CSS width for xterm font tiers.
 *
 * Prefer the terminal host's `clientWidth` — Chrome DevTools device mode often
 * keeps `window.innerWidth` at the full desktop value while the *drawn* layout
 * is phone-sized, which made us pick desktop font sizes (~14px) and look huge.
 */
export function terminalTierWidthPx(host: HTMLElement | null): number {
  if (typeof window === "undefined") return 1280;
  const fromHost = host?.clientWidth ?? 0;
  if (fromHost > 2) return Math.round(fromHost);
  const doc = document.documentElement?.clientWidth ?? 0;
  const vv = window.visualViewport;
  const inner = window.innerWidth;
  const vvw = vv?.width ?? inner;
  const layout = Math.min(inner, vvw, doc > 0 ? doc : inner);
  return Math.max(1, Math.round(layout));
}

export const TERMINAL_FONT_MIN = 13;
export const TERMINAL_FONT_MAX = 24;
export const TERMINAL_FONT_DEFAULT = 14;
/** localStorage key for the per-device font offset (integer px steps). */
export const TERMINAL_FONT_ADJUST_KEY = "phi.terminalFontAdjust";

/** Integer offset that keeps `TERMINAL_FONT_DEFAULT + adjust` within [MIN, MAX]. */
function clampTerminalFontAdjust(adjust: number): number {
  const step = Number.isFinite(adjust) ? Math.round(adjust) : 0;
  return Math.min(
    TERMINAL_FONT_MAX - TERMINAL_FONT_DEFAULT,
    Math.max(TERMINAL_FONT_MIN - TERMINAL_FONT_DEFAULT, step),
  );
}

/**
 * Terminal font size in px. The width is accepted for call-site stability
 * (and future tiers) but no longer shrinks the font: small fonts on phones
 * were unreadable.
 */
export function terminalFontSizeForWidth(
  _layoutWidthPx: number,
  adjust = 0,
): number {
  return TERMINAL_FONT_DEFAULT + clampTerminalFontAdjust(adjust);
}

/** Stored per-device font offset; 0 when missing, invalid or storage is unavailable. */
export function readTerminalFontAdjust(): number {
  try {
    const raw = localStorage.getItem(TERMINAL_FONT_ADJUST_KEY);
    if (raw == null) return 0;
    const trimmed = raw.trim();
    if (!/^[+-]?\d+$/.test(trimmed)) return 0;
    return clampTerminalFontAdjust(Number(trimmed));
  } catch {
    return 0;
  }
}

/** Clamps and persists the per-device font offset; returns the stored value. */
export function writeTerminalFontAdjust(adjust: number): number {
  const next = clampTerminalFontAdjust(adjust);
  try {
    localStorage.setItem(TERMINAL_FONT_ADJUST_KEY, String(next));
  } catch {
    // Private mode / storage disabled: the value still applies for this session.
  }
  return next;
}

export function terminalLineHeightForWidth(layoutWidthPx: number): number {
  return layoutWidthPx < 1024 ? 1.02 : 1.15;
}

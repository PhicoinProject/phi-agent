import { useState } from "react";
import { Button } from "@phi/ui/ui/components/button";
import { useShellStrings } from "@/components/shell/use-shell-strings";
import { cn } from "@/lib/utils";

const ARROW_FINALS = "ABCD";

/**
 * Applies Ctrl to one key's terminal bytes: letters become their C0 control
 * code, "/" becomes US (\x1f), CSI arrows gain the Ctrl modifier
 * (\x1b[A -> \x1b[1;5A). Anything else is returned unchanged.
 */
export function applyCtrl(data: string): string {
  if (data.length === 1) {
    const code = data.charCodeAt(0);
    const isLetter = (code >= 0x41 && code <= 0x5a) || (code >= 0x61 && code <= 0x7a);
    if (isLetter) return String.fromCharCode(code & 0x1f);
    if (data === "/") return "\x1f";
    return data;
  }
  if (data.length === 3 && data.startsWith("\x1b[") && ARROW_FINALS.includes(data[2])) {
    return `\x1b[1;5${data[2]}`;
  }
  return data;
}

type BarKey = {
  id: "esc" | "tab" | "up" | "down" | "slash";
  label: string;
  data: string;
  /** Esc/Tab are sent as-is even while Ctrl is latched. */
  ctrlable: boolean;
};

const LEADING_KEYS: readonly BarKey[] = [
  { id: "esc", label: "Esc", data: "\x1b", ctrlable: false },
  { id: "tab", label: "Tab", data: "\t", ctrlable: false },
];

// ↑/↓ walk history and menus; ←/→ are left to the soft keyboard's cursor drag.
const TRAILING_KEYS: readonly BarKey[] = [
  { id: "up", label: "↑", data: "\x1b[A", ctrlable: true },
  { id: "down", label: "↓", data: "\x1b[B", ctrlable: true },
  { id: "slash", label: "/", data: "/", ctrlable: true },
];

// A 44px touch target around a 36px outlined chip; the bar itself has no fill.
const KEY_CLASS = cn(
  "h-11 min-w-11 shrink-0 aspect-auto p-0 px-0.5 hover:bg-transparent",
  "normal-case tracking-normal font-normal text-xs",
);
const CHIP_CLASS = "flex h-9 min-w-9 items-center justify-center rounded-lg border border-current/15 px-2.5";

/**
 * Phone-only terminal key row (Esc, Tab, sticky Ctrl, ↑ ↓, "/") shown above the composer
 * pill, which owns Send. Buttons swallow pointerdown so a tap never steals focus from the
 * terminal and the soft keyboard stays open.
 *
 * Ctrl is a one-shot latch: it modifies the next key sent from the bar (or,
 * via `ctrlActive`/`onCtrlChange`, the next typed key handled by the parent)
 * and then releases.
 */
export function MobileKeyBar({
  onSend,
  onCtrlChange,
  ctrlActive,
}: {
  onSend: (data: string) => void;
  onCtrlChange?: (active: boolean) => void;
  /** Optional controlled latch state; omit to let the bar own it. */
  ctrlActive?: boolean;
}) {
  const s = useShellStrings();
  const [ownCtrl, setOwnCtrl] = useState(false);
  const ctrl = ctrlActive ?? ownCtrl;

  const setCtrl = (next: boolean) => {
    setOwnCtrl(next);
    if (next !== ctrl) onCtrlChange?.(next);
  };

  const press = (key: BarKey) => {
    onSend(ctrl && key.ctrlable ? applyCtrl(key.data) : key.data);
    if (ctrl) setCtrl(false);
  };

  const renderKey = (key: BarKey) => (
    <Button
      key={key.id}
      type="button"
      ghost
      size="icon"
      data-key={key.id}
      onPointerDown={(e) => e.preventDefault()}
      onClick={() => press(key)}
      className={KEY_CLASS}
    >
      <span className={CHIP_CLASS}>{key.label}</span>
    </Button>
  );

  return (
    <div
      role="toolbar"
      aria-label={s.keyBar}
      data-testid="mobile-key-bar"
      className={cn(
        "flex w-full shrink-0 items-center gap-1 overflow-x-auto overscroll-x-contain px-1 py-1",
        "[scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
      )}
    >
      {LEADING_KEYS.map(renderKey)}
      <Button
        type="button"
        ghost
        size="icon"
        data-key="ctrl"
        aria-pressed={ctrl}
        onPointerDown={(e) => e.preventDefault()}
        onClick={() => setCtrl(!ctrl)}
        className={KEY_CLASS}
      >
        <span className={cn(CHIP_CLASS, ctrl && "border-current/30 bg-midground/15")}>{s.keyCtrl}</span>
      </Button>
      {TRAILING_KEYS.map(renderKey)}
    </div>
  );
}

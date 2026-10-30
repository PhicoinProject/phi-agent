/**
 * Composer mic: click or press the shortcut (`voice.web_shortcut`, default F8, set in Settings →
 * Shortcuts) to dictate, press it again (or the stop button) to finish, Esc to cancel. The control
 * is one fixed box in every state so the footer never shifts: the mic and the device menu when idle,
 * the stop button beside a live waveform and the elapsed time while recording. Partial text only
 * streams to `onPartial`; the final goes to `onFinal` for editing and is only sent (`onSend`) when
 * auto-send is on, which it is not by default.
 */
import { Button } from "@phi/ui/ui/components/button";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import { cn } from "@/lib/utils";

import { MicDevicePicker } from "./MicDevicePicker";
import { MicWaveform } from "./MicWaveform";
import { useDictation, type DictationDeps } from "./useDictation";

export const DEFAULT_VOICE_SHORTCUT = "F8";

const MODIFIERS = new Set(["alt", "cmd", "control", "ctrl", "meta", "mod", "option", "shift"]);

/** "F8", "Ctrl+Shift+M", "Mod+K" (Cmd on macOS, Ctrl elsewhere). Modifiers must match exactly. */
export function matchesShortcut(e: Pick<KeyboardEvent, "altKey" | "ctrlKey" | "key" | "metaKey" | "shiftKey">, shortcut: string): boolean {
  const parts = shortcut.split("+").map((p) => p.trim().toLowerCase()).filter(Boolean);
  const key = parts.pop();
  if (!key || MODIFIERS.has(key)) return false;
  const mac = typeof navigator !== "undefined" && /mac|iphone|ipad/i.test(navigator.platform);
  const want = { alt: false, ctrl: false, meta: false, shift: false };
  for (const p of parts) {
    if (p === "ctrl" || p === "control") want.ctrl = true;
    else if (p === "alt" || p === "option") want.alt = true;
    else if (p === "shift") want.shift = true;
    else if (p === "meta" || p === "cmd") want.meta = true;
    else if (p === "mod") want[mac ? "meta" : "ctrl"] = true;
    else return false;
  }
  return (
    e.key.toLowerCase() === key &&
    e.altKey === want.alt &&
    e.ctrlKey === want.ctrl &&
    e.metaKey === want.meta &&
    e.shiftKey === want.shift
  );
}

export function formatElapsed(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

/** Whole seconds since `active` last turned true; 0 while inactive. */
export function useElapsedSeconds(active: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    setElapsed(0);
    if (!active) return;
    const startedAt = Date.now();
    const id = window.setInterval(() => setElapsed(Math.floor((Date.now() - startedAt) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [active]);
  return elapsed;
}

export interface MicButtonProps {
  /** Global toggle key, from `voice.web_shortcut`. */
  shortcut?: string;
  /** Send the final transcript (Settings → Voice). */
  autoSend?: boolean;
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onSend?: (text: string) => void;
  onCancel?: () => void;
  /** Whether a shortcut key press may toggle dictation (e.g. not while another field has focus). */
  shortcutEnabled?: (e: KeyboardEvent) => boolean;
  deps?: DictationDeps;
  className?: string;
}

export function MicButton({
  autoSend = false,
  className,
  deps,
  onCancel,
  onFinal,
  onPartial,
  onSend,
  shortcut = DEFAULT_VOICE_SHORTCUT,
  shortcutEnabled,
}: MicButtonProps) {
  const { t } = useI18n();
  const s = { ...en.voiceComputer!, ...t.voiceComputer };

  const dictation = useDictation({
    deps,
    onFinal: (text) => {
      onFinal?.(text);
      if (autoSend && text) onSend?.(text);
    },
    onPartial,
  });
  const { cancel, disabledReason, error, meter, start, state, stop } = dictation;
  const active = state === "requesting" || state === "recording" || state === "finalizing";
  const elapsed = useElapsedSeconds(state === "recording");

  const live = useRef({ active, cancel, onCancel, shortcut, shortcutEnabled, start, state, stop });
  live.current = { active, cancel, onCancel, shortcut, shortcutEnabled, start, state, stop };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const cur = live.current;
      if (e.key === "Escape" && cur.active) {
        e.preventDefault();
        cur.cancel();
        cur.onCancel?.();
        return;
      }
      if (e.repeat || !matchesShortcut(e, cur.shortcut) || cur.shortcutEnabled?.(e) === false) return;
      e.preventDefault();
      if (cur.state === "idle" || cur.state === "error") void cur.start();
      else if (cur.state === "requesting" || cur.state === "recording") cur.stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const disabledText = disabledReason === "insecure" ? s.insecure : disabledReason === "unsupported" ? s.unsupported : null;
  const recording = state === "requesting" || state === "recording";
  const failed = state === "error" && error ? error : null;
  const label = disabledText ?? failed ?? (state === "finalizing" ? s.finalizing : state === "requesting" ? s.requesting : recording ? s.stopDictation : s.dictate);

  // Fixed columns, identical in every state: [button | slot]. Only the slot's content changes.
  return (
    <div className={cn("grid shrink-0 grid-cols-[2.75rem_2.5rem]", className)} data-testid="mic-box">
      <Button
        aria-label={failed ? `${s.dictate}: ${failed}` : label}
        aria-pressed={recording}
        data-testid="mic-button"
        disabled={Boolean(disabledText) || state === "finalizing"}
        ghost
        destructive={recording}
        className={cn(
          "rounded-full [&>svg]:size-4",
          recording ? "bg-destructive/15 hover:bg-destructive/20" : "bg-midground/10 hover:bg-midground/15 active:bg-midground/20",
        )}
        onClick={() => (recording ? stop() : void start())}
        size="icon"
        title={disabledText || failed ? label : `${label} (${shortcut})`}
        type="button"
      >
        {recording ? <Square /> : <Mic />}
      </Button>
      <span className="relative flex min-w-0 items-stretch justify-center" data-testid="mic-side">
        {active ? (
          <span className="flex flex-col items-center justify-center gap-1 text-destructive">
            <MicWaveform meter={meter} frozen={state === "finalizing"} width={36} height={14} />
            {state === "finalizing" ? (
              <Spinner aria-label={s.finalizing} className="text-[10px] text-muted-foreground" data-testid="mic-finalizing" />
            ) : (
              <span className="font-mono text-[10px] leading-none tabular-nums" data-testid="mic-elapsed">
                {formatElapsed(elapsed)}
              </span>
            )}
          </span>
        ) : (
          <>
            <MicDevicePicker className="flex-1 [&>button]:flex-1" deps={deps} disabledText={disabledText} />
            {failed && (
              <>
                <span
                  aria-hidden
                  className="pointer-events-none absolute right-1 top-1 size-1.5 rounded-full bg-destructive"
                  data-testid="mic-error-dot"
                />
                <span className="sr-only" role="alert">
                  {failed}
                </span>
              </>
            )}
          </>
        )}
      </span>
    </div>
  );
}

/**
 * Mobile hold-to-talk: press and hold to dictate, release to send (or fill the composer with
 * `releaseAction="fill"`). Slide up to lock the take hands-free (tap again to send), slide left to
 * cancel. A press shorter than 300 ms is treated as an accidental tap and discarded.
 *
 * Inside a composer (a VoiceStatusSlot is provided) it is the composer's round mic and a plain
 * toggle: a tap (or a press of any length) starts dictation, the next tap ends it and fills the
 * composer. Nothing has to be held down (PHI, admin 2026-10-31). The recording status renders in
 * the slot over the composer's field instead of floating above the button.
 */
import { Button } from "@phi/ui/ui/components/button";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { Lock, Mic } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import { createPortal } from "react-dom";

import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import { cn } from "@/lib/utils";
import { roundButtonClass, roundFaceClass } from "@/components/shell/RoundIconButton";

import { formatElapsed, useElapsedSeconds } from "./MicButton";
import { MicWaveform } from "./MicWaveform";
import { useDictation, type DictationDeps } from "./useDictation";
import { useVoiceStatusSlot } from "./voice-status-slot";

export const MIN_HOLD_MS = 300;
export const LOCK_SLIDE_PX = 60;
export const CANCEL_SLIDE_PX = 80;

export type ReleaseDecision = "discard" | "keep" | "commit";

/**
 * What releasing the button does with the take. With `tapLocks` a short tap keeps it hands-free;
 * with `toggle` every release keeps it (tap to start, tap again to stop).
 */
export function releaseDecision({
  cancelled,
  durationMs,
  locked,
  tapLocks = false,
  toggle = false,
}: {
  cancelled: boolean;
  durationMs: number;
  locked: boolean;
  tapLocks?: boolean;
  toggle?: boolean;
}): ReleaseDecision {
  if (cancelled) return "discard";
  if (locked || toggle) return "keep";
  if (durationMs >= MIN_HOLD_MS) return "commit";
  return tapLocks ? "keep" : "discard";
}

/** Slide distance from the press point (screen y grows downward). Cancel wins over lock. */
export function slideGesture(dx: number, dy: number): "cancel" | "lock" | null {
  if (dx <= -CANCEL_SLIDE_PX) return "cancel";
  if (dy <= -LOCK_SLIDE_PX) return "lock";
  return null;
}

export interface HoldToTalkProps {
  releaseAction?: "send" | "fill";
  onSend?: (text: string) => void;
  onFill?: (text: string) => void;
  onPartial?: (text: string) => void;
  deps?: DictationDeps;
  className?: string;
}

interface Gesture {
  x: number;
  y: number;
  at: number;
  locked: boolean;
  cancelled: boolean;
}

export function HoldToTalk({ className, deps, onFill, onPartial, onSend, releaseAction = "send" }: HoldToTalkProps) {
  const { t } = useI18n();
  const s = { ...en.voiceComputer!, ...t.voiceComputer };
  const slot = useVoiceStatusSlot();
  const inComposer = slot !== undefined;
  const gesture = useRef<Gesture | null>(null);
  // Only a committed take (release / locked tap) delivers its final; a cancelled one never does.
  const commit = useRef(false);
  const [pressed, setPressed] = useState(false);
  const [locked, setLocked] = useState(false);

  const { cancel, disabledReason, meter, partial, start, state, stop } = useDictation({
    deps,
    onFinal: (text) => {
      if (!commit.current) return;
      commit.current = false;
      if (text) (releaseAction === "fill" ? onFill : onSend)?.(text);
    },
    onPartial,
  });
  const elapsed = useElapsedSeconds(state === "recording");
  // A hands-free take that failed or ended on its own leaves nothing to tap off.
  useEffect(() => {
    if (locked && (state === "idle" || state === "error")) setLocked(false);
  }, [locked, state]);
  const disabledText = disabledReason === "insecure" ? s.insecure : disabledReason === "unsupported" ? s.unsupported : null;

  const onPointerDown = (e: ReactPointerEvent<HTMLButtonElement>) => {
    if (disabledText) return;
    e.preventDefault();
    if (locked) {
      setLocked(false);
      commit.current = true;
      stop();
      return;
    }
    if (state !== "idle" && state !== "error") return;
    try {
      // Keep receiving move/up when the finger slides off the button.
      e.currentTarget.setPointerCapture(e.pointerId);
    } catch {
      // Synthetic or already-released pointer: the gesture still works while over the button.
    }
    gesture.current = { at: Date.now(), cancelled: false, locked: false, x: e.clientX, y: e.clientY };
    commit.current = false;
    setPressed(true);
    navigator.vibrate?.(10);
    void start();
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const g = gesture.current;
    // The composer mic is a tap toggle: no slide-to-lock / slide-to-cancel gestures.
    if (!g || g.locked || g.cancelled || inComposer) return;
    const slide = slideGesture(e.clientX - g.x, e.clientY - g.y);
    if (slide === "cancel") {
      g.cancelled = true;
      setPressed(false);
      cancel();
    } else if (slide === "lock") {
      g.locked = true;
      setLocked(true);
    }
  };

  const onPointerUp = () => {
    const g = gesture.current;
    if (!g) return;
    gesture.current = null;
    setPressed(false);
    const decision = releaseDecision({
      cancelled: g.cancelled,
      durationMs: Date.now() - g.at,
      locked: g.locked,
      tapLocks: inComposer,
      toggle: inComposer,
    });
    if (decision === "keep" && !g.locked) setLocked(true);
    if (decision === "commit") {
      commit.current = true;
      stop();
    } else if (decision === "discard") {
      cancel();
    }
  };

  const onPointerCancel = () => {
    const g = gesture.current;
    if (!g || g.locked) return;
    gesture.current = null;
    setPressed(false);
    cancel();
  };

  const showOverlay = pressed || locked || state === "finalizing";
  const handlers = {
    onContextMenu: (e: { preventDefault: () => void }) => e.preventDefault(),
    onPointerCancel,
    onPointerDown,
    onPointerMove,
    onPointerUp,
  };

  if (inComposer) {
    const live = pressed || locked || state === "recording";
    return (
      <>
        {showOverlay &&
          slot &&
          createPortal(
            <div
              className="flex w-full min-w-0 items-center gap-2 font-mono text-xs text-destructive"
              data-testid="hold-overlay"
              role="status"
            >
              <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-destructive animate-pulse" />
              <span className="tabular-nums">{formatElapsed(elapsed)}</span>
              <MicWaveform meter={meter} frozen={state === "finalizing"} bars={24} width={120} height={16} />
              {state === "finalizing" && <Spinner aria-label={s.finalizing} className="text-muted-foreground" />}
              {partial ? (
                <span className="min-w-0 truncate font-sans text-sm text-foreground" data-testid="hold-partial">
                  {partial}
                </span>
              ) : null}
            </div>,
            slot,
          )}
        <Button
          aria-label={disabledText ?? (locked ? s.stopDictation : s.dictate)}
          aria-pressed={pressed || locked}
          className={cn(roundButtonClass(), "touch-none select-none", className)}
          data-testid="hold-to-talk"
          disabled={Boolean(disabledText)}
          ghost
          size="icon"
          title={disabledText ?? s.dictate}
          type="button"
          {...handlers}
        >
          <span aria-hidden data-round-face={live ? "danger" : "ghost"} className={roundFaceClass(live ? "danger" : "ghost")}>
            <Mic />
          </span>
        </Button>
      </>
    );
  }

  return (
    <div className={cn("relative flex flex-col items-center gap-2", className)}>
      {showOverlay && (
        <div
          className="absolute bottom-full mb-3 w-64 max-w-[80vw] border border-border bg-background-base p-3 text-sm shadow-lg"
          data-testid="hold-overlay"
          role="status"
        >
          <div className="flex items-center gap-2 font-mono text-xs text-destructive">
            <span aria-hidden className="h-2 w-2 shrink-0 rounded-full bg-destructive animate-pulse" />
            <span className="tabular-nums">{formatElapsed(elapsed)}</span>
            <MicWaveform meter={meter} frozen={state === "finalizing"} bars={24} width={120} height={16} />
            {state === "finalizing" && <Spinner aria-label={s.finalizing} className="text-muted-foreground" />}
          </div>
          {partial && (
            <p className="mt-1.5 text-foreground" data-testid="hold-partial">
              {partial}
            </p>
          )}
          <p className="mt-1.5 font-mono text-xs text-muted-foreground">{locked ? s.lockedHint : s.slideHint}</p>
        </div>
      )}
      <Button
        aria-label={disabledText ?? (locked ? s.lockedHint : s.holdToTalk)}
        aria-pressed={pressed || locked}
        className="h-16 w-16 touch-none select-none rounded-full"
        data-testid="hold-to-talk"
        destructive={pressed || locked}
        disabled={Boolean(disabledText)}
        size="icon"
        title={disabledText ?? s.holdToTalk}
        type="button"
        {...handlers}
      >
        {locked ? <Lock /> : <Mic />}
      </Button>
    </div>
  );
}

interface ScrollableTerminal {
  buffer: {
    active: {
      baseY: number;
      viewportY: number;
    };
  };
  scrollLines: (amount: number) => void;
}

export interface TouchScrollClock {
  now: () => number;
  raf: (cb: (t: number) => void) => number;
  caf: (id: number) => void;
}

const TOUCH_SCROLL_PX_PER_LINE = 18;
const TOUCH_SCROLL_MIN_PX = 2;
/** A flick faster than this (px/ms) keeps scrolling after the finger lifts. */
export const FLING_MIN_VELOCITY = 0.3;
/** Velocity kept per 16 ms frame while flinging. */
const FLING_FRICTION = 0.95;
const FLING_STOP_VELOCITY = 0.02;
/** Only the last stretch of the drag decides the fling speed. */
const VELOCITY_WINDOW_MS = 100;
const CAPTURE = { capture: true } as const;
const PASSIVE_CAPTURE = { capture: true, passive: true } as const;
const ACTIVE_CAPTURE = { capture: true, passive: false } as const;

const defaultClock: TouchScrollClock = {
  now: () => performance.now(),
  raf: (cb) => requestAnimationFrame(cb),
  caf: (id) => cancelAnimationFrame(id),
};

function firstTouch(ev: TouchEvent): Touch | null {
  return ev.touches[0] ?? ev.changedTouches[0] ?? null;
}

function canScrollTerminal(term: ScrollableTerminal, amount: number): boolean {
  const { baseY, viewportY } = term.buffer.active;

  if (amount < 0) {
    return viewportY > 0;
  }

  if (amount > 0) {
    return viewportY < baseY;
  }

  return false;
}

/**
 * Touch-drag scrollback for dashboard xterm panes.
 *
 * Phone WebKit/Chrome do not turn a finger drag inside xterm into wheel events, so a vertical
 * one-finger drag is converted into `scrollLines()`. The terminal owns the gesture: a vertical
 * drag never reaches the page, even at the top or bottom of the scrollback, so the header and
 * footer stay put (PHI, admin 2026-10-31). A flick keeps scrolling with momentum after the finger
 * lifts; touching again stops it. Horizontal drags are left alone for the room swipe gestures.
 */
export function installTerminalTouchScroll(
  host: HTMLElement,
  term: ScrollableTerminal,
  clock: TouchScrollClock = defaultClock,
): () => void {
  let startX: number | null = null;
  let lastY: number | null = null;
  let residualPx = 0;
  let vertical: boolean | null = null;
  let samples: { t: number; y: number }[] = [];
  let flingFrame: number | null = null;

  const stopFling = () => {
    if (flingFrame !== null) clock.caf(flingFrame);
    flingFrame = null;
  };

  const reset = () => {
    startX = null;
    lastY = null;
    residualPx = 0;
    vertical = null;
    samples = [];
  };

  /** Scroll by `px` of finger travel; false once the scrollback edge is reached. */
  const scrollPx = (px: number): boolean => {
    residualPx += px;
    const lines = residualPx / TOUCH_SCROLL_PX_PER_LINE;
    const wholeLines = lines < 0 ? Math.ceil(lines) : Math.floor(lines);
    if (wholeLines === 0) return true;
    if (!canScrollTerminal(term, wholeLines)) {
      residualPx = 0;
      return false;
    }
    residualPx -= wholeLines * TOUCH_SCROLL_PX_PER_LINE;
    term.scrollLines(wholeLines);
    return true;
  };

  const startFling = (velocity: number) => {
    let v = velocity;
    let last = clock.now();
    residualPx = 0;
    const step = () => {
      const t = clock.now();
      const dt = Math.max(1, t - last);
      last = t;
      if (!scrollPx(v * dt)) {
        flingFrame = null;
        return;
      }
      v *= Math.pow(FLING_FRICTION, dt / 16);
      if (Math.abs(v) < FLING_STOP_VELOCITY) {
        flingFrame = null;
        residualPx = 0;
        return;
      }
      flingFrame = clock.raf(step);
    };
    flingFrame = clock.raf(step);
  };

  const onTouchStart = (ev: TouchEvent) => {
    stopFling();
    reset();
    if (ev.touches.length !== 1) return;
    const touch = firstTouch(ev);
    if (!touch) return;
    startX = touch.clientX ?? 0;
    lastY = touch.clientY;
    samples = [{ t: clock.now(), y: touch.clientY }];
  };

  const onTouchMove = (ev: TouchEvent) => {
    if (ev.touches.length !== 1 || lastY === null) {
      reset();
      return;
    }

    const touch = firstTouch(ev);
    if (!touch) {
      reset();
      return;
    }

    if (vertical === null) {
      const dx = Math.abs((touch.clientX ?? 0) - (startX ?? 0));
      const dy = Math.abs(touch.clientY - lastY);
      if (dx < TOUCH_SCROLL_MIN_PX && dy < TOUCH_SCROLL_MIN_PX) return;
      vertical = dy >= dx;
    }
    if (!vertical) return;

    // The terminal owns a vertical drag: the page behind it never scrolls or bounces.
    ev.preventDefault();
    ev.stopPropagation();

    const deltaPx = lastY - touch.clientY;
    lastY = touch.clientY;
    const t = clock.now();
    samples.push({ t, y: touch.clientY });
    while (samples.length > 2 && t - samples[0].t > VELOCITY_WINDOW_MS) samples.shift();

    if (Math.abs(deltaPx) < TOUCH_SCROLL_MIN_PX) return;
    scrollPx(deltaPx);
  };

  const onTouchEnd = () => {
    const wasVertical = vertical;
    const first = samples[0];
    const last = samples[samples.length - 1];
    reset();
    if (!wasVertical || !first || !last || last.t === first.t) return;
    if (clock.now() - last.t > VELOCITY_WINDOW_MS) return; // finger rested before lifting
    const velocity = (first.y - last.y) / (last.t - first.t); // px/ms, positive scrolls down
    if (Math.abs(velocity) >= FLING_MIN_VELOCITY) startFling(velocity);
  };

  const onTouchCancel = () => {
    stopFling();
    reset();
  };

  host.addEventListener("touchstart", onTouchStart, PASSIVE_CAPTURE);
  host.addEventListener("touchmove", onTouchMove, ACTIVE_CAPTURE);
  host.addEventListener("touchcancel", onTouchCancel, CAPTURE);
  host.addEventListener("touchend", onTouchEnd, CAPTURE);

  return () => {
    stopFling();
    host.removeEventListener("touchstart", onTouchStart, PASSIVE_CAPTURE);
    host.removeEventListener("touchmove", onTouchMove, ACTIVE_CAPTURE);
    host.removeEventListener("touchcancel", onTouchCancel, CAPTURE);
    host.removeEventListener("touchend", onTouchEnd, CAPTURE);
  };
}

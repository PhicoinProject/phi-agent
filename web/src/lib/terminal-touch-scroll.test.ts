import { describe, expect, it, vi } from "vitest";

import { installTerminalTouchScroll, type TouchScrollClock } from "./terminal-touch-scroll";

function touchEvent(type: string, y: number, x = 100): TouchEvent {
  const ev = new Event(type, { bubbles: true, cancelable: true }) as TouchEvent;
  const touch = { clientX: x, clientY: y } as Touch;

  Object.defineProperty(ev, "touches", { value: type === "touchend" ? [] : [touch] });
  Object.defineProperty(ev, "changedTouches", { value: [touch] });

  return ev;
}

function term(viewportY: number, baseY: number) {
  const terminal = {
    buffer: { active: { baseY, viewportY } },
    scrollLines: vi.fn((amount: number) => {
      const active = terminal.buffer.active;
      active.viewportY = Math.max(0, Math.min(active.baseY, active.viewportY + amount));
    }),
  };

  return terminal;
}

/** Manual clock: `frame()` runs the pending animation frame 16 ms later. */
function fakeClock() {
  let t = 0;
  let pending: ((t: number) => void) | null = null;
  const clock: TouchScrollClock = {
    now: () => t,
    raf: (cb) => {
      pending = cb;
      return 1;
    },
    caf: () => {
      pending = null;
    },
  };
  return {
    clock,
    advance: (ms: number) => {
      t += ms;
    },
    frame: () => {
      const cb = pending;
      pending = null;
      t += 16;
      cb?.(t);
    },
    hasPending: () => pending !== null,
  };
}

describe("installTerminalTouchScroll", () => {
  it("converts one-finger vertical drags into xterm scrollback lines", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(20, 100);
    const cleanup = installTerminalTouchScroll(host, terminal);

    host.dispatchEvent(touchEvent("touchstart", 200));
    const move = touchEvent("touchmove", 164);
    host.dispatchEvent(move);

    expect(terminal.scrollLines).toHaveBeenCalledWith(2);
    expect(move.defaultPrevented).toBe(true);

    cleanup();
  });

  it("keeps the page still even at the scrollback edge (the terminal owns vertical drags)", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(0, 100);
    const cleanup = installTerminalTouchScroll(host, terminal);

    host.dispatchEvent(touchEvent("touchstart", 100));
    const move = touchEvent("touchmove", 136);
    host.dispatchEvent(move);

    expect(terminal.scrollLines).not.toHaveBeenCalled();
    expect(move.defaultPrevented).toBe(true);

    cleanup();
  });

  it("leaves horizontal drags to the page (room swipe gestures)", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(20, 100);
    const cleanup = installTerminalTouchScroll(host, terminal);

    host.dispatchEvent(touchEvent("touchstart", 200, 100));
    const move = touchEvent("touchmove", 196, 160);
    host.dispatchEvent(move);

    expect(terminal.scrollLines).not.toHaveBeenCalled();
    expect(move.defaultPrevented).toBe(false);

    cleanup();
  });

  it("a flick keeps scrolling after the finger lifts, and a new touch stops it", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(500, 1000);
    const c = fakeClock();
    const cleanup = installTerminalTouchScroll(host, terminal, c.clock);

    host.dispatchEvent(touchEvent("touchstart", 400));
    c.advance(16);
    host.dispatchEvent(touchEvent("touchmove", 380));
    c.advance(16);
    host.dispatchEvent(touchEvent("touchmove", 360));
    c.advance(16);
    host.dispatchEvent(touchEvent("touchmove", 340));
    const afterDrag = terminal.buffer.active.viewportY;
    host.dispatchEvent(touchEvent("touchend", 340));

    expect(c.hasPending()).toBe(true);
    for (let i = 0; i < 10; i++) c.frame();
    expect(terminal.buffer.active.viewportY).toBeGreaterThan(afterDrag);

    host.dispatchEvent(touchEvent("touchstart", 300));
    expect(c.hasPending()).toBe(false);

    cleanup();
  });

  it("a slow drag that rests before lifting does not fling", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(500, 1000);
    const c = fakeClock();
    const cleanup = installTerminalTouchScroll(host, terminal, c.clock);

    host.dispatchEvent(touchEvent("touchstart", 400));
    c.advance(16);
    host.dispatchEvent(touchEvent("touchmove", 340));
    c.advance(400);
    host.dispatchEvent(touchEvent("touchend", 340));

    expect(c.hasPending()).toBe(false);

    cleanup();
  });

  it("removes listeners on cleanup", () => {
    const host = new EventTarget() as HTMLElement;
    const terminal = term(20, 100);
    const cleanup = installTerminalTouchScroll(host, terminal);

    cleanup();

    host.dispatchEvent(touchEvent("touchstart", 200));
    host.dispatchEvent(touchEvent("touchmove", 164));

    expect(terminal.scrollLines).not.toHaveBeenCalled();
  });
});

// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { stubCanvas } from "./fakes";
import { MicWaveform, type MicWaveformProps } from "./MicWaveform";
import { createLevelMeter } from "./useDictation";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BARS = 16;
const HEIGHT = 16;

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let canvas: ReturnType<typeof stubCanvas>;

beforeEach(() => {
  canvas = stubCanvas();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function render(props: MicWaveformProps) {
  container ??= document.createElement("div");
  document.body.appendChild(container);
  root ??= createRoot(container);
  act(() => root!.render(<MicWaveform bars={BARS} height={HEIGHT} {...props} />));
}

describe("MicWaveform", () => {
  it("draws one bar per slot in currentColor, the newest level rising on the right", () => {
    const meter = createLevelMeter();
    render({ meter });
    const el = container!.querySelector("canvas")!;
    expect(el.getAttribute("aria-hidden")).toBe("true");
    expect(canvas.ctx.fillRect).toHaveBeenCalledTimes(BARS);
    expect(Math.max(...canvas.bars(BARS))).toBeLessThan(3);

    meter.push(0.9);
    canvas.flushFrames();
    const loud = canvas.bars(BARS);
    expect(loud.at(-1)).toBeGreaterThan(HEIGHT * 0.8);
    expect(Math.max(...loud.slice(0, -1))).toBeLessThan(3);

    // Falls again when the speaker pauses; the loud bar has moved one step left.
    meter.push(0);
    canvas.flushFrames();
    const quiet = canvas.bars(BARS);
    expect(quiet.at(-1)).toBeLessThan(3);
    expect(quiet.at(-2)).toBeGreaterThan(HEIGHT * 0.8);
  });

  it("coalesces levels into one draw per animation frame", () => {
    const meter = createLevelMeter();
    render({ meter });
    canvas.ctx.fillRect.mockClear();
    meter.push(0.2);
    meter.push(0.5);
    meter.push(0.7);
    expect(canvas.pending()).toBe(1);
    expect(canvas.ctx.fillRect).not.toHaveBeenCalled();
    canvas.flushFrames();
    expect(canvas.ctx.fillRect).toHaveBeenCalledTimes(BARS);
    expect(canvas.bars(3).map((h) => Math.round((h / HEIGHT) * 10))).toEqual([2, 5, 7]);
  });

  it("frozen stops following the meter and keeps the last bars", () => {
    const meter = createLevelMeter();
    render({ meter });
    meter.push(0.9);
    canvas.flushFrames();
    const before = canvas.bars(BARS);
    render({ frozen: true, meter });
    canvas.ctx.fillRect.mockClear();
    meter.push(0);
    meter.push(0);
    canvas.flushFrames();
    expect(canvas.ctx.fillRect).not.toHaveBeenCalled();
    expect(before.at(-1)).toBeGreaterThan(HEIGHT * 0.8);
  });

  it("with reduced motion still follows the real level (all bars at the current level, no pattern)", () => {
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), media: query }));
    const meter = createLevelMeter();
    render({ meter });
    const heights = () => canvas.ctx.fillRect.mock.calls.slice(-BARS).map((c) => c[3] as number);
    // Silent: every bar at the floor, not a decorative pattern.
    expect(new Set(heights()).size).toBe(1);
    canvas.ctx.fillRect.mockClear();
    meter.push(0.9);
    canvas.flushFrames();
    const loud = heights();
    expect(new Set(loud).size).toBe(1);
    expect(loud[0]).toBeGreaterThan(HEIGHT * 0.8);
    canvas.ctx.fillRect.mockClear();
    meter.push(0);
    canvas.flushFrames();
    expect(heights()[0]).toBeLessThan(HEIGHT * 0.2);
  });

  it("unsubscribes and cancels a pending frame on unmount", () => {
    const meter = createLevelMeter();
    const seen = vi.fn();
    meter.subscribe(seen);
    render({ meter });
    meter.push(0.5);
    expect(canvas.pending()).toBe(1);
    act(() => root!.unmount());
    root = null;
    expect(canvas.pending()).toBe(0);
    canvas.ctx.fillRect.mockClear();
    meter.push(0.5);
    expect(canvas.pending()).toBe(0);
    expect(seen).toHaveBeenCalledTimes(2);
  });
});

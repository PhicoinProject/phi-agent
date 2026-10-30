// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  TERMINAL_FONT_ADJUST_KEY,
  TERMINAL_FONT_MAX,
  TERMINAL_FONT_MIN,
  readTerminalFontAdjust,
  terminalFontSizeForWidth,
  writeTerminalFontAdjust,
} from "./terminal-appearance";

const store = new Map<string, string>();
const localStorageMock = {
  clear: () => store.clear(),
  getItem: (key: string) => store.get(key) ?? null,
  key: (index: number) => Array.from(store.keys())[index] ?? null,
  get length() {
    return store.size;
  },
  removeItem: (key: string) => {
    store.delete(key);
  },
  setItem: (key: string, value: string) => {
    store.set(key, String(value));
  },
};

beforeEach(() => {
  store.clear();
  vi.stubGlobal("localStorage", localStorageMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("terminalFontSizeForWidth", () => {
  it("keeps phones readable: 14px default, never below the minimum", () => {
    expect(terminalFontSizeForWidth(360)).toBeGreaterThanOrEqual(TERMINAL_FONT_MIN);
    expect(terminalFontSizeForWidth(360)).toBe(14);
    expect(terminalFontSizeForWidth(280)).toBe(14);
  });

  it("uses 14px on desktop widths", () => {
    expect(terminalFontSizeForWidth(1280)).toBe(14);
  });

  it("clamps a large negative adjustment to the minimum", () => {
    expect(TERMINAL_FONT_MIN).toBe(13);
    expect(terminalFontSizeForWidth(360, -5)).toBe(13);
  });

  it("clamps a large positive adjustment to the maximum", () => {
    expect(TERMINAL_FONT_MAX).toBe(24);
    expect(terminalFontSizeForWidth(1280, 20)).toBe(24);
  });
});

describe("terminal font adjust persistence", () => {
  it("round-trips the adjustment through localStorage", () => {
    expect(readTerminalFontAdjust()).toBe(0);
    expect(writeTerminalFontAdjust(3)).toBe(3);
    expect(store.get(TERMINAL_FONT_ADJUST_KEY)).toBe("3");
    expect(readTerminalFontAdjust()).toBe(3);
    expect(terminalFontSizeForWidth(360, readTerminalFontAdjust())).toBe(17);
  });

  it("stores the clamped value", () => {
    expect(writeTerminalFontAdjust(-5)).toBe(TERMINAL_FONT_MIN - 14);
    expect(readTerminalFontAdjust()).toBe(-1);
    expect(writeTerminalFontAdjust(99)).toBe(TERMINAL_FONT_MAX - 14);
    expect(readTerminalFontAdjust()).toBe(10);
  });

  it("reads 0 for an invalid stored value", () => {
    store.set(TERMINAL_FONT_ADJUST_KEY, "huge");
    expect(readTerminalFontAdjust()).toBe(0);
    store.set(TERMINAL_FONT_ADJUST_KEY, "1.5");
    expect(readTerminalFontAdjust()).toBe(0);
  });

  it("reads 0 when storage throws", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    });
    expect(readTerminalFontAdjust()).toBe(0);
    expect(writeTerminalFontAdjust(2)).toBe(2);
  });
});

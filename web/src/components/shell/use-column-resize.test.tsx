// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { clampWidth, useColumnResize, type ColumnResizeOptions } from "./use-column-resize";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const KEY = "phi-test-column-width";

// jsdom runs without an origin here, so localStorage is undefined: stub it.
const store = new Map<string, string>();
const localStorageMock = {
  clear: () => store.clear(),
  getItem: (key: string) => store.get(key) ?? null,
  removeItem: (key: string) => void store.delete(key),
  setItem: (key: string, value: string) => void store.set(key, String(value)),
};

function Probe(props: Partial<ColumnResizeOptions>) {
  const { width, separatorProps } = useColumnResize({
    storageKey: KEY,
    defaultWidth: 288,
    min: 220,
    max: () => Math.min(560, window.innerWidth * 0.45),
    label: "Resize column",
    ...props,
  });
  return (
    <div data-testid="column" className="relative" style={{ width }}>
      <div {...separatorProps} />
    </div>
  );
}

let container: HTMLDivElement | undefined;
let root: Root | undefined;

function render(props: Partial<ColumnResizeOptions> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<Probe {...props} />));
}

const column = () => container!.querySelector<HTMLElement>('[data-testid="column"]')!;
const handle = () => container!.querySelector<HTMLElement>('[role="separator"]')!;
const width = () => column().style.width;

function pointer(type: string, x: number) {
  const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, button: 0 });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  act(() => void handle().dispatchEvent(ev));
}

function key(name: string) {
  act(() => void handle().dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: name })));
}

function viewport(px: number) {
  Object.defineProperty(window, "innerWidth", { configurable: true, value: px });
}

describe("useColumnResize", () => {
  beforeEach(() => {
    store.clear();
    vi.stubGlobal("localStorage", localStorageMock);
    viewport(1600);
  });

  afterEach(() => {
    act(() => root?.unmount());
    container?.remove();
    root = container = undefined;
    vi.unstubAllGlobals();
  });

  it("clampWidth keeps a width inside [min, max]", () => {
    expect(clampWidth(100, 220, 560)).toBe(220);
    expect(clampWidth(900, 220, 560)).toBe(560);
    expect(clampWidth(300.4, 220, 560)).toBe(300);
    // A viewport so narrow that max < min still yields min.
    expect(clampWidth(300, 220, 150)).toBe(220);
  });

  it("is a labelled vertical separator starting at the default width", () => {
    render();
    expect(width()).toBe("288px");
    const h = handle();
    expect(h.getAttribute("aria-orientation")).toBe("vertical");
    expect(h.getAttribute("aria-label")).toBe("Resize column");
    expect(h.getAttribute("aria-valuenow")).toBe("288");
    expect(h.getAttribute("aria-valuemin")).toBe("220");
    expect(h.getAttribute("aria-valuemax")).toBe("560");
    expect(h.tabIndex).toBe(0);
    expect(h.className).toMatch(/\bcursor-col-resize\b/);
    expect(h.className).toMatch(/\bright-0\b/);
  });

  it("drags live, clamps at max and min, and persists on release", () => {
    render();
    pointer("pointerdown", 300);
    pointer("pointermove", 350);
    expect(width()).toBe("338px");
    expect(store.has(KEY)).toBe(false);
    pointer("pointermove", 2000);
    expect(width()).toBe("560px");
    expect(handle().getAttribute("aria-valuenow")).toBe("560");
    pointer("pointermove", -500);
    expect(width()).toBe("220px");
    pointer("pointerup", -500);
    expect(store.get(KEY)).toBe("220");
    // Moving after release does nothing.
    pointer("pointermove", 400);
    expect(width()).toBe("220px");
  });

  it("a start-edge handle widens when dragged left", () => {
    render({ edge: "start", min: 420, max: () => window.innerWidth * 0.8, defaultWidth: 600 });
    expect(handle().className).toMatch(/\bleft-0\b/);
    pointer("pointerdown", 1000);
    pointer("pointermove", 900);
    expect(width()).toBe("700px");
    pointer("pointermove", 0);
    expect(width()).toBe("1280px");
    pointer("pointerup", 0);
    expect(store.get(KEY)).toBe("1280");
  });

  it("restores a persisted width, clamped to the current bounds", () => {
    store.set(KEY, "400");
    render();
    expect(width()).toBe("400px");
    act(() => root!.unmount());
    container!.remove();

    store.set(KEY, "9999");
    render();
    expect(width()).toBe("560px");
  });

  it("re-clamps when the window gets narrower", () => {
    store.set(KEY, "500");
    render();
    expect(width()).toBe("500px");
    viewport(1000);
    act(() => void window.dispatchEvent(new Event("resize")));
    expect(width()).toBe("450px");
    expect(handle().getAttribute("aria-valuemax")).toBe("450");
  });

  it("steps 16px with Left/Right and stops at the bounds", () => {
    render();
    key("ArrowRight");
    expect(width()).toBe("304px");
    expect(store.get(KEY)).toBe("304");
    key("ArrowLeft");
    key("ArrowLeft");
    expect(width()).toBe("272px");
    for (let i = 0; i < 10; i++) key("ArrowLeft");
    expect(width()).toBe("220px");
    key("Enter");
    expect(width()).toBe("220px");
  });

  it("Right narrows a start-edge pane", () => {
    render({ edge: "start", defaultWidth: 400 });
    key("ArrowRight");
    expect(width()).toBe("384px");
  });

  it("double-click resets to the default and forgets the stored width", () => {
    store.set(KEY, "500");
    render();
    act(() => void handle().dispatchEvent(new MouseEvent("dblclick", { bubbles: true })));
    expect(width()).toBe("288px");
    expect(store.has(KEY)).toBe(false);
  });
});

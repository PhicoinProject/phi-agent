// @vitest-environment jsdom
import { act, type ButtonHTMLAttributes, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MobileKeyBar, applyCtrl } from "./MobileKeyBar";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("@phi/ui/ui/components/button", () => {
  const variantProps = new Set(["destructive", "ghost", "invert", "outlined", "prefix", "size", "suffix"]);
  return {
    Button: (props: ButtonHTMLAttributes<HTMLButtonElement> & Record<string, unknown>) => (
      <button
        {...(Object.fromEntries(
          Object.entries(props).filter(([name]) => !variantProps.has(name)),
        ) as ButtonHTMLAttributes<HTMLButtonElement>)}
      />
    ),
  };
});

let container: HTMLDivElement | undefined;
let root: Root | undefined;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root?.render(ui));
}

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  root = undefined;
  container = undefined;
});

function byKey(id: string): HTMLButtonElement {
  const el = container?.querySelector<HTMLButtonElement>(`[data-key="${id}"]`);
  if (!el) throw new Error(`missing key button: ${id}`);
  return el;
}

function byTestId(id: string): HTMLElement {
  const el = container?.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  if (!el) throw new Error(`missing element: ${id}`);
  return el;
}

async function click(el: HTMLElement) {
  await act(async () => el.click());
}

describe("applyCtrl", () => {
  it("maps letters, slash and arrows to their Ctrl forms", () => {
    expect(applyCtrl("c")).toBe("\x03");
    expect(applyCtrl("C")).toBe("\x03");
    expect(applyCtrl("/")).toBe("\x1f");
    expect(applyCtrl("\x1b[D")).toBe("\x1b[1;5D");
    expect(applyCtrl("\x1b[A")).toBe("\x1b[1;5A");
    expect(applyCtrl("1")).toBe("1");
    expect(applyCtrl("\x1b")).toBe("\x1b");
  });
});

describe("MobileKeyBar", () => {
  it("renders a labelled toolbar", async () => {
    await render(<MobileKeyBar onSend={() => {}} />);
    const bar = byTestId("mobile-key-bar");
    expect(bar.getAttribute("role")).toBe("toolbar");
    expect(bar.getAttribute("aria-label")).toBe("Terminal keys");
    expect(byKey("esc").getAttribute("type")).toBe("button");
  });

  it("sends the raw ESC byte for Esc", async () => {
    const onSend = vi.fn<(data: string) => void>();
    await render(<MobileKeyBar onSend={onSend} />);
    await click(byKey("esc"));
    expect(onSend).toHaveBeenCalledTimes(1);
    const sent = onSend.mock.calls[0][0];
    expect(sent).toBe("\x1b");
    expect(sent).toHaveLength(1);
    expect(sent).not.toBe("Escape");
    expect(sent).not.toBe("\u001b[");
  });

  it("sends a tab character for Tab", async () => {
    const onSend = vi.fn<(data: string) => void>();
    await render(<MobileKeyBar onSend={onSend} />);
    await click(byKey("tab"));
    expect(onSend.mock.calls).toEqual([["\t"]]);
  });

  it("sends the CSI up sequence for the up arrow", async () => {
    const onSend = vi.fn<(data: string) => void>();
    await render(<MobileKeyBar onSend={onSend} />);
    await click(byKey("up"));
    expect(onSend.mock.calls).toEqual([["\x1b[A"]]);
  });

  it("latches Ctrl for exactly one key", async () => {
    const onSend = vi.fn<(data: string) => void>();
    const onCtrlChange = vi.fn<(active: boolean) => void>();
    await render(<MobileKeyBar onSend={onSend} onCtrlChange={onCtrlChange} />);

    const ctrl = byKey("ctrl");
    expect(ctrl.getAttribute("aria-pressed")).toBe("false");
    await click(ctrl);
    expect(ctrl.getAttribute("aria-pressed")).toBe("true");
    expect(onSend).not.toHaveBeenCalled();

    await click(byKey("slash"));
    expect(onSend.mock.calls).toEqual([["\x1f"]]);
    expect(ctrl.getAttribute("aria-pressed")).toBe("false");

    await click(byKey("slash"));
    expect(onSend.mock.calls).toEqual([["\x1f"], ["/"]]);
    expect(onCtrlChange.mock.calls).toEqual([[true], [false]]);
  });

  it("adds the Ctrl modifier to arrows but not to Esc", async () => {
    const onSend = vi.fn<(data: string) => void>();
    await render(<MobileKeyBar onSend={onSend} />);
    await click(byKey("ctrl"));
    await click(byKey("up"));
    await click(byKey("ctrl"));
    await click(byKey("esc"));
    expect(onSend.mock.calls).toEqual([["\x1b[1;5A"], ["\x1b"]]);
  });

  it("has no Send or Enter key (the composer pill owns Send) and no left/right arrows", async () => {
    await render(<MobileKeyBar onSend={() => {}} />);
    const bar = byTestId("mobile-key-bar");
    expect(Array.from(bar.querySelectorAll("[data-key]")).map((b) => b.getAttribute("data-key"))).toEqual([
      "esc",
      "tab",
      "ctrl",
      "up",
      "down",
      "slash",
    ]);
    expect(bar.querySelector('[aria-label="Send"]')).toBeNull();
  });

  it("draws every key as an outlined ghost chip; only a latched Ctrl gets a fill", async () => {
    await render(<MobileKeyBar onSend={() => {}} />);
    for (const id of ["esc", "tab", "ctrl", "up", "down", "slash"]) {
      const chip = byKey(id).firstElementChild as HTMLElement;
      expect(chip.className).toMatch(/\bh-9\b/);
      expect(chip.className).toMatch(/\brounded-lg\b/);
      expect(chip.className).toMatch(/border-current\/15/);
      expect(chip.className).not.toMatch(/\bbg-/);
      expect(byKey(id).className).toMatch(/\btext-xs\b/);
      // 44px touch target around the 36px chip.
      expect(byKey(id).className).toMatch(/\bh-11\b/);
    }
    await click(byKey("ctrl"));
    expect((byKey("ctrl").firstElementChild as HTMLElement).className).toMatch(/\bbg-midground\/15\b/);
  });
});

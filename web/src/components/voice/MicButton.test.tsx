// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeMic, settle, stubCanvas } from "./fakes";
import { MicButton, matchesShortcut, type MicButtonProps } from "./MicButton";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  stubCanvas();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function render(props: MicButtonProps) {
  const handlers = { onCancel: vi.fn(), onFinal: vi.fn(), onPartial: vi.fn(), onSend: vi.fn() };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<MicButton {...handlers} {...props} />));
  const button = () => container!.querySelector<HTMLButtonElement>('[data-testid="mic-button"]')!;
  return { button, handlers };
}

const q = (sel: string) => container!.querySelector<HTMLElement>(sel);

/** The footer geometry contract: one box, same classes and inline style in every state, nothing else rendered. */
function geometry() {
  const box = q('[data-testid="mic-box"]')!;
  const slot = q('[data-testid="mic-side"]')!;
  expect(container!.children).toHaveLength(1);
  expect(container!.firstElementChild).toBe(box);
  expect(box.children).toHaveLength(2);
  return [box.className, box.getAttribute("style"), slot.className, slot.getAttribute("style")].join(" | ");
}

function press(init: KeyboardEventInit) {
  act(() => {
    window.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, ...init }));
  });
}

describe("matchesShortcut", () => {
  const ev = (key: string, mods: Partial<Record<"altKey" | "ctrlKey" | "metaKey" | "shiftKey", boolean>> = {}) => ({
    altKey: false, ctrlKey: false, key, metaKey: false, shiftKey: false, ...mods,
  });

  it("matches a bare function key and requires the exact modifiers", () => {
    expect(matchesShortcut(ev("F8"), "F8")).toBe(true);
    expect(matchesShortcut(ev("F8", { ctrlKey: true }), "F8")).toBe(false);
    expect(matchesShortcut(ev("F9"), "F8")).toBe(false);
    expect(matchesShortcut(ev("M", { ctrlKey: true, shiftKey: true }), "Ctrl+Shift+M")).toBe(true);
    expect(matchesShortcut(ev("m", { ctrlKey: true }), "Ctrl+Shift+M")).toBe(false);
    expect(matchesShortcut(ev("Shift", { shiftKey: true }), "Shift")).toBe(false);
  });
});

describe("MicButton", () => {
  it("F8 starts and stops dictation; the final fills the composer without sending by default", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps });

    press({ key: "F8" });
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
    expect(button().getAttribute("aria-pressed")).toBe("true");

    act(() => mic.socket.serverOpen());
    act(() => mic.socket.serverSend({ text: "draft text", type: "partial" }));
    // Partial text goes to the composer through onPartial; the mic itself never prints it.
    expect(handlers.onPartial).toHaveBeenLastCalledWith("draft text");
    expect(q('[data-testid="mic-partial"]')).toBeNull();
    expect(container!.textContent).not.toContain("draft text");

    press({ key: "F8", repeat: true }); // auto-repeat must not toggle
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    press({ key: "F8" });
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    act(() => mic.socket.serverSend({ transcript: "draft text done", type: "final" }));
    await settle();
    expect(handlers.onFinal).toHaveBeenCalledWith("draft text done");
    expect(handlers.onSend).not.toHaveBeenCalled();
    expect(button().getAttribute("aria-pressed")).toBe("false");
  });

  it("keeps one fixed box in every state: no hint row, no REC/listening text, no second line", async () => {
    const mic = fakeMic();
    const { button } = render({ deps: mic.deps });
    const idle = geometry();
    expect(q('[data-testid="mic-side"] [data-testid="mic-device-button"]')).not.toBeNull();
    expect(q('[data-testid="mic-side"] canvas')).toBeNull();
    expect(q('[data-testid="mic-elapsed"]')).toBeNull();

    act(() => button().click());
    await settle();
    act(() => mic.socket.serverOpen());
    mic.emitPcm(new Array(640).fill(9000));
    expect(geometry()).toBe(idle);
    // Recording: the same box holds the stop button, and the slot the live waveform and elapsed time.
    expect(button().getAttribute("aria-label")).toBe("Stop dictation");
    expect(button().querySelector("svg")).not.toBeNull();
    expect(q('[data-testid="mic-side"] canvas')).not.toBeNull();
    expect(q('[data-testid="mic-side"] [data-testid="mic-elapsed"]')!.textContent).toBe("0:00");
    expect(q('[data-testid="mic-device-button"]')).toBeNull();
    const text = container!.textContent ?? "";
    for (const hint of ["F8", "Esc", "auto-send", "REC", "listening"]) expect(text).not.toContain(hint);
    expect(q('[data-testid="mic-autosend"]')).toBeNull();
    expect(q('[data-testid="mic-status"]')).toBeNull();

    // Finalizing: still the same box; the bars stay (frozen) beside a spinner.
    act(() => button().click());
    expect(geometry()).toBe(idle);
    expect(q('[data-testid="mic-side"] canvas')).not.toBeNull();
    expect(q('[data-testid="mic-side"] [data-testid="mic-finalizing"]')).not.toBeNull();
    expect(button().disabled).toBe(true);

    act(() => mic.socket.serverSend({ transcript: "done", type: "final" }));
    await settle();
    expect(geometry()).toBe(idle);
    expect(q('[data-testid="mic-side"] canvas')).toBeNull();
    expect(q('[data-testid="mic-device-button"]')).not.toBeNull();
  });

  it("shows an error only as the button tooltip and a red dot in the slot", async () => {
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    const mic = fakeMic({ getUserMedia: vi.fn(async () => Promise.reject(denied)) });
    const { button } = render({ deps: mic.deps });
    const idle = geometry();
    act(() => button().click());
    await settle();
    expect(geometry()).toBe(idle);
    expect(button().getAttribute("title")).toBe("Microphone permission was denied");
    expect(button().getAttribute("aria-label")).toContain("Microphone permission was denied");
    expect(q('[data-testid="mic-side"] [data-testid="mic-error-dot"]')).not.toBeNull();
    // Announced to screen readers, but never as a visible text line beside the button.
    const alert = q('[role="alert"]')!;
    expect(alert.className).toContain("sr-only");
    expect(q('[data-testid="mic-box"]')!.contains(alert)).toBe(true);
  });

  it("honours a configured shortcut instead of F8", async () => {
    const mic = fakeMic();
    render({ deps: mic.deps, shortcut: "Ctrl+Shift+M" });
    press({ key: "F8" });
    await settle();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
    press({ ctrlKey: true, key: "M", shiftKey: true });
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("Esc cancels: no eos, no final, onCancel fires", async () => {
    const mic = fakeMic();
    const { handlers } = render({ deps: mic.deps });
    press({ key: "F8" });
    await settle();
    act(() => mic.socket.serverOpen());
    act(() => mic.socket.serverSend({ text: "never mind", type: "partial" }));

    press({ key: "Escape" });
    expect(handlers.onCancel).toHaveBeenCalledTimes(1);
    expect(mic.socket.closeCode).not.toBeNull();
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    act(() => mic.socket.serverSend({ transcript: "late", type: "final" }));
    await settle();
    expect(handlers.onFinal).not.toHaveBeenCalled();
    expect(q('[data-testid="mic-side"] canvas')).toBeNull();
    expect(q('[data-testid="mic-device-button"]')).not.toBeNull();
  });

  it("Esc while idle is left alone for the rest of the page", () => {
    const mic = fakeMic();
    const { handlers } = render({ deps: mic.deps });
    const ev = new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" });
    act(() => void window.dispatchEvent(ev));
    expect(ev.defaultPrevented).toBe(false);
    expect(handlers.onCancel).not.toHaveBeenCalled();
  });

  it("sends the final when auto-send is on (set in Settings, no toggle by the mic)", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ autoSend: true, deps: mic.deps });
    act(() => button().click());
    await settle();
    expect(q('[data-testid="mic-autosend"]')).toBeNull();
    act(() => mic.socket.serverOpen());
    act(() => button().click());
    act(() => mic.socket.serverSend({ transcript: "ship it", type: "final" }));
    await settle();
    expect(handlers.onFinal).toHaveBeenCalledWith("ship it");
    expect(handlers.onSend).toHaveBeenCalledWith("ship it");
  });

  it("is disabled with the HTTPS reason outside a secure context, and F8 does nothing", async () => {
    const mic = fakeMic({ secureContext: false });
    const { button } = render({ deps: mic.deps });
    expect(button().disabled).toBe(true);
    expect(button().getAttribute("title")).toBe("Microphone needs HTTPS or localhost");
    press({ key: "F8" });
    await settle();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
  });
});

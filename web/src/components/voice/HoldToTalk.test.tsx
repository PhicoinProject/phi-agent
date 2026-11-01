// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeMic, settle, stubCanvas, stubLocalStorage } from "./fakes";
import { HoldToTalk, releaseDecision, slideGesture, type HoldToTalkProps } from "./HoldToTalk";
import { MIC_DEVICE_KEY } from "./voice-prefs";
import { VoiceStatusSlot } from "./voice-status-slot";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let now = 0;
const vibrate = vi.fn();

beforeEach(() => {
  now = 1_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
  Object.defineProperty(navigator, "vibrate", { configurable: true, value: vibrate });
  vibrate.mockClear();
  stubLocalStorage();
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

function render(props: HoldToTalkProps) {
  const handlers = { onFill: vi.fn(), onPartial: vi.fn(), onSend: vi.fn() };
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<HoldToTalk {...handlers} {...props} />));
  const button = container.querySelector<HTMLButtonElement>('[data-testid="hold-to-talk"]')!;
  return { button, handlers };
}

function pointer(el: Element, type: string, x = 100, y = 400) {
  const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  act(() => void el.dispatchEvent(ev));
}

/** The release contract: an accidental tap (<300 ms) never sends, a real hold does. */
function expectReleaseContract(decide: typeof releaseDecision) {
  expect(decide({ cancelled: false, durationMs: 120, locked: false })).toBe("discard");
  expect(decide({ cancelled: false, durationMs: 299, locked: false })).toBe("discard");
  expect(decide({ cancelled: false, durationMs: 300, locked: false })).toBe("commit");
  expect(decide({ cancelled: true, durationMs: 2000, locked: false })).toBe("discard");
  expect(decide({ cancelled: false, durationMs: 50, locked: true })).toBe("keep");
}

describe("hold-to-talk gesture rules", () => {
  it("releaseDecision ignores short presses and commits real holds", () => {
    expectReleaseContract(releaseDecision);
  });

  it("negative control: a variant that sends on a short press is rejected", () => {
    const sendsOnShortPress: typeof releaseDecision = ({ cancelled, locked }) =>
      cancelled ? "discard" : locked ? "keep" : "commit";
    expect(() => expectReleaseContract(sendsOnShortPress)).toThrow();
  });

  it("slide thresholds: up 60 px locks, left 80 px cancels", () => {
    expect(slideGesture(0, -59)).toBeNull();
    expect(slideGesture(0, -60)).toBe("lock");
    expect(slideGesture(-79, 0)).toBeNull();
    expect(slideGesture(-80, 0)).toBe("cancel");
    expect(slideGesture(-90, -90)).toBe("cancel");
  });
});

describe("HoldToTalk", () => {
  it("is a round button of at least 64 px", () => {
    const { button } = render({ deps: fakeMic().deps });
    expect(button.className).toMatch(/\bh-16\b/);
    expect(button.className).toMatch(/\bw-16\b/);
    expect(button.className).toMatch(/\brounded-full\b/);
  });

  it("captures from the microphone chosen on the desktop picker, without showing a picker", async () => {
    window.localStorage.setItem(MIC_DEVICE_KEY, "usb-1");
    const mic = fakeMic();
    const { button } = render({ deps: mic.deps });
    expect(container!.querySelector('[data-testid="mic-device-button"]')).toBeNull();

    pointer(button, "pointerdown");
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledWith({
      audio: { channelCount: 1, deviceId: { exact: "usb-1" }, echoCancellation: true, noiseSuppression: true },
    });
    now += 100;
    pointer(button, "pointerup");
    await settle();
  });

  it("ignores a press shorter than 300 ms", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps });
    pointer(button, "pointerdown");
    expect(vibrate).toHaveBeenCalledWith(10);
    await settle();
    act(() => mic.socket.serverOpen());
    now += 200;
    pointer(button, "pointerup");
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(mic.socket.closeCode).not.toBeNull();
    act(() => mic.socket.serverSend({ transcript: "oops", type: "final" }));
    await settle();
    expect(handlers.onSend).not.toHaveBeenCalled();
    expect(container!.querySelector('[data-testid="hold-overlay"]')).toBeNull();
  });

  it("hold then release sends the transcript, with the overlay showing the waveform, timer and partial text", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps });
    expect(button.className).toContain("h-16 w-16");
    pointer(button, "pointerdown");
    await settle();
    act(() => mic.socket.serverOpen());
    act(() => mic.socket.serverSend({ text: "buy milk", type: "partial" }));
    const overlay = container!.querySelector('[data-testid="hold-overlay"]')!;
    expect(overlay.querySelector("canvas")).not.toBeNull();
    expect(overlay.textContent).toContain("0:00");
    expect(overlay.textContent).not.toContain("REC");
    expect(overlay.textContent).not.toContain("listening");
    expect(overlay.textContent).toContain("buy milk");
    // The button keeps its size (64px round, bottom centre) while recording.
    expect(button.className).toContain("h-16 w-16");

    now += 1200;
    pointer(button, "pointerup");
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    act(() => mic.socket.serverSend({ transcript: "buy milk", type: "final" }));
    await settle();
    expect(handlers.onSend).toHaveBeenCalledWith("buy milk");
    expect(handlers.onFill).not.toHaveBeenCalled();
  });

  it("slide left cancels the take and the release sends nothing", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps });
    pointer(button, "pointerdown", 200, 400);
    await settle();
    act(() => mic.socket.serverOpen());
    pointer(button, "pointermove", 115, 400);
    expect(mic.socket.closeCode).not.toBeNull();
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    now += 2000;
    pointer(button, "pointerup", 115, 400);
    await settle();
    expect(handlers.onSend).not.toHaveBeenCalled();
    expect(mic.transcribe).not.toHaveBeenCalled();
  });

  it("slide up locks: release keeps recording, the next tap sends", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps });
    pointer(button, "pointerdown", 100, 400);
    await settle();
    act(() => mic.socket.serverOpen());
    pointer(button, "pointermove", 100, 330);
    now += 800;
    pointer(button, "pointerup", 100, 330);
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(button.getAttribute("aria-label")).toBe("Locked — tap to send");
    expect(container!.textContent).toContain("Locked — tap to send");

    now += 5000;
    pointer(button, "pointerdown");
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    pointer(button, "pointerup");
    act(() => mic.socket.serverSend({ transcript: "long note", type: "final" }));
    await settle();
    expect(handlers.onSend).toHaveBeenCalledTimes(1);
    expect(handlers.onSend).toHaveBeenCalledWith("long note");
  });

  it("releaseAction=fill hands the transcript to onFill instead of sending", async () => {
    const mic = fakeMic();
    const { button, handlers } = render({ deps: mic.deps, releaseAction: "fill" });
    pointer(button, "pointerdown");
    await settle();
    act(() => mic.socket.serverOpen());
    now += 900;
    pointer(button, "pointerup");
    act(() => mic.socket.serverSend({ transcript: "edit me", type: "final" }));
    await settle();
    expect(handlers.onFill).toHaveBeenCalledWith("edit me");
    expect(handlers.onSend).not.toHaveBeenCalled();
  });

  it("is disabled outside a secure context", () => {
    const mic = fakeMic({ secureContext: false });
    const { button } = render({ deps: mic.deps });
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("title")).toBe("Microphone needs HTTPS or localhost");
  });
});

describe("HoldToTalk inside a composer", () => {
  let slot: HTMLDivElement;

  function renderInComposer(props: HoldToTalkProps = {}) {
    const handlers = { onFill: vi.fn(), onPartial: vi.fn(), onSend: vi.fn() };
    slot = document.createElement("div");
    document.body.appendChild(slot);
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    act(() =>
      root!.render(
        <VoiceStatusSlot.Provider value={slot}>
          <HoldToTalk {...handlers} releaseAction="fill" {...props} />
        </VoiceStatusSlot.Provider>,
      ),
    );
    const button = container.querySelector<HTMLButtonElement>('[data-testid="hold-to-talk"]')!;
    return { button, handlers };
  }

  afterEach(() => slot.remove());

  it("is a 44px ghost round button with a 40px face, not the 64px solid one", () => {
    const { button } = renderInComposer({ deps: fakeMic().deps });
    expect(button.className).toMatch(/\bsize-11\b/);
    expect(button.className).toMatch(/\brounded-full\b/);
    expect(button.className).not.toMatch(/\bh-16\b/);
    expect(button.querySelector(".arc-border")).toBeNull();
    const face = button.querySelector<HTMLElement>("[data-round-face]")!;
    expect(face.getAttribute("data-round-face")).toBe("ghost");
    expect(face.className).toMatch(/\bsize-10\b/);
    expect(button.getAttribute("aria-label")).toBe("Dictate");
  });

  it("a tap starts hands-free dictation and the next tap fills the composer, never sends", async () => {
    const mic = fakeMic();
    const { button, handlers } = renderInComposer({ deps: mic.deps });
    pointer(button, "pointerdown");
    await settle();
    act(() => mic.socket.serverOpen());
    now += 120;
    pointer(button, "pointerup");
    await settle();
    // Still recording: the tap did not discard the take.
    expect(mic.socket.closeCode).toBeNull();
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(button.getAttribute("aria-label")).toBe("Stop dictation");
    expect(button.querySelector("[data-round-face]")!.getAttribute("data-round-face")).toBe("danger");
    expect(slot.querySelector('[data-testid="hold-overlay"] canvas')).not.toBeNull();

    now += 3000;
    pointer(button, "pointerdown");
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    pointer(button, "pointerup");
    act(() => mic.socket.serverSend({ transcript: "long note", type: "final" }));
    await settle();
    expect(handlers.onFill).toHaveBeenCalledWith("long note");
    expect(handlers.onSend).not.toHaveBeenCalled();
    expect(button.getAttribute("aria-label")).toBe("Dictate");
  });

  it("a long press does not stop it either: releasing keeps recording until the next tap", async () => {
    const mic = fakeMic();
    const { button, handlers } = renderInComposer({ deps: mic.deps });
    pointer(button, "pointerdown");
    await settle();
    act(() => mic.socket.serverOpen());
    act(() => mic.socket.serverSend({ text: "buy milk", type: "partial" }));
    const status = slot.querySelector('[data-testid="hold-overlay"]')!;
    expect(status.textContent).toContain("0:00");
    expect(status.textContent).toContain("buy milk");
    expect(container!.querySelector('[data-testid="hold-overlay"]')).toBeNull();
    expect(button.className).toMatch(/\bsize-11\b/);

    now += 900;
    pointer(button, "pointerup");
    await settle();
    // Still recording after a long press: nothing has to be held down.
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(handlers.onFill).not.toHaveBeenCalled();
    expect(button.getAttribute("aria-label")).toBe("Stop dictation");

    now += 2000;
    pointer(button, "pointerdown");
    pointer(button, "pointerup");
    act(() => mic.socket.serverSend({ transcript: "buy milk", type: "final" }));
    await settle();
    expect(handlers.onFill).toHaveBeenCalledWith("buy milk");
    expect(handlers.onSend).not.toHaveBeenCalled();
    expect(slot.querySelector('[data-testid="hold-overlay"]')).toBeNull();
  });

  it("sliding the finger while tapping does not cancel: the composer mic is a plain toggle", async () => {
    const mic = fakeMic();
    const { button, handlers } = renderInComposer({ deps: mic.deps });
    pointer(button, "pointerdown", 200, 400);
    await settle();
    act(() => mic.socket.serverOpen());
    pointer(button, "pointermove", 115, 400);
    now += 200;
    pointer(button, "pointerup", 115, 400);
    await settle();
    expect(mic.socket.closeCode).toBeNull();
    expect(button.getAttribute("aria-label")).toBe("Stop dictation");

    pointer(button, "pointerdown");
    pointer(button, "pointerup");
    act(() => mic.socket.serverSend({ transcript: "note", type: "final" }));
    await settle();
    expect(handlers.onFill).toHaveBeenCalledWith("note");
  });
});

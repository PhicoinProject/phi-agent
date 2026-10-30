// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { en } from "@/i18n/en";

import { fakeMic, settle, stubLocalStorage } from "./fakes";
import { MicButton, type MicButtonProps } from "./MicButton";
import { MIC_DEVICE_KEY } from "./voice-prefs";

// Negative control switch: when set, the saved choice is invisible to the capture path.
const variant = vi.hoisted(() => ({ ignoreSavedId: false }));

vi.mock("./voice-prefs", async (importOriginal) => {
  const real = await importOriginal<typeof import("./voice-prefs")>();
  return { ...real, readMicDeviceId: () => (variant.ignoreSavedId ? null : real.readMicDeviceId()) };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const s = en.voiceComputer!;
const AUDIO = { channelCount: 1, echoCancellation: true, noiseSuppression: true };

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  stubLocalStorage();
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  variant.ignoreSavedId = false;
  vi.unstubAllGlobals();
});

function device(deviceId: string, label: string, kind: MediaDeviceKind = "audioinput"): MediaDeviceInfo {
  return { deviceId, groupId: `g-${deviceId}`, kind, label, toJSON: () => ({}) } as MediaDeviceInfo;
}

/** A scriptable device list plus a devicechange hub. */
function fakeDevices(initial: MediaDeviceInfo[]) {
  let list = initial;
  const listeners = new Set<() => void>();
  return {
    enumerateDevices: vi.fn(async () => list),
    listeners,
    onDeviceChange: (listener: () => void) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
    set(next: MediaDeviceInfo[]) {
      list = next;
    },
  };
}

function render(props: MicButtonProps) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<MicButton {...props} />));
  const q = <T extends Element>(sel: string) => container!.querySelector<T>(sel);
  return {
    chevron: () => q<HTMLButtonElement>('[data-testid="mic-device-button"]')!,
    menu: () => q<HTMLElement>('[role="menu"]'),
    mic: () => q<HTMLButtonElement>('[data-testid="mic-button"]')!,
  };
}

function click(el: Element) {
  act(() => void el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true })));
}

function options(menu: HTMLElement | null) {
  return Array.from(menu?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? []).map((el) => ({
    checked: el.getAttribute("aria-checked") === "true",
    label: el.textContent,
  }));
}

function option(menu: HTMLElement | null, label: string) {
  const el = Array.from(menu?.querySelectorAll<HTMLElement>('[role="menuitemradio"]') ?? []).find((o) => o.textContent === label);
  if (!el) throw new Error(`no option ${label}`);
  return el;
}

/** The capture contract: the saved device is requested exactly, with the usual processing kept. */
function expectCapturedDevice(getUserMedia: ReturnType<typeof fakeMic>["getUserMedia"], id: string | null) {
  expect(getUserMedia).toHaveBeenLastCalledWith({ audio: id ? { ...AUDIO, deviceId: { exact: id } } : AUDIO });
}

function escape() {
  act(() => void window.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" })));
}

const DEVICES = [
  device("default", "Default - USB Mic"),
  device("communications", "Communications - Headset"),
  device("usb-1", "USB Mic"),
  device("built-in", "Built-in Mic"),
  device("cam-1", "Webcam", "videoinput"),
  device("spk-1", "Speakers", "audiooutput"),
];

describe("MicDevicePicker", () => {
  it("puts a menu button beside the mic listing microphones, System default first and checked", async () => {
    const devices = fakeDevices(DEVICES);
    const ui = render({ deps: fakeMic(devices).deps });

    const chevron = ui.chevron();
    expect(chevron.getAttribute("aria-haspopup")).toBe("menu");
    expect(chevron.getAttribute("aria-label")).toBe("Choose microphone");
    expect(chevron.getAttribute("aria-expanded")).toBe("false");
    expect(ui.mic().nextElementSibling?.contains(chevron)).toBe(true);
    expect(ui.menu()).toBeNull();

    click(chevron);
    await settle();
    expect(chevron.getAttribute("aria-expanded")).toBe("true");
    expect(devices.enumerateDevices).toHaveBeenCalled();
    expect(options(ui.menu())).toEqual([
      { checked: true, label: "System default" },
      { checked: false, label: "USB Mic" },
      { checked: false, label: "Built-in Mic" },
    ]);

    escape();
    expect(ui.menu()).toBeNull();
  });

  it("choosing a device saves it, closes the menu, and the next capture asks for exactly that device", async () => {
    const mic = fakeMic(fakeDevices(DEVICES));
    const ui = render({ deps: mic.deps });

    click(ui.chevron());
    await settle();
    click(option(ui.menu(), "USB Mic"));
    expect(window.localStorage.getItem(MIC_DEVICE_KEY)).toBe("usb-1");
    expect(ui.menu()).toBeNull();

    click(ui.mic());
    await settle();
    expectCapturedDevice(mic.getUserMedia, "usb-1");
    escape();
    await settle();

    click(ui.chevron());
    await settle();
    expect(options(ui.menu())).toEqual([
      { checked: false, label: "System default" },
      { checked: true, label: "USB Mic" },
      { checked: false, label: "Built-in Mic" },
    ]);
    click(option(ui.menu(), "System default"));
    expect(window.localStorage.getItem(MIC_DEVICE_KEY)).toBeNull();

    click(ui.mic());
    await settle();
    expectCapturedDevice(mic.getUserMedia, null);
  });

  it("without labels it offers to allow access, asking once and stopping the tracks", async () => {
    const devices = fakeDevices([device("a", ""), device("b", "")]);
    const mic = fakeMic(devices);
    mic.getUserMedia.mockImplementationOnce(async () => {
      devices.set([device("a", "USB Mic"), device("b", "Built-in Mic")]);
      return { getTracks: () => [mic.track] } as unknown as MediaStream;
    });
    const ui = render({ deps: mic.deps });

    click(ui.chevron());
    await settle();
    expect(options(ui.menu())).toEqual([{ checked: true, label: "System default" }]);
    const allow = ui.menu()!.querySelector<HTMLElement>('[role="menuitem"]')!;
    expect(allow.textContent).toBe("Allow microphone access to see devices");

    click(allow);
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
    expect(mic.getUserMedia).toHaveBeenCalledWith({ audio: true });
    expect(mic.track.stop).toHaveBeenCalled();
    expect(options(ui.menu()).map((o) => o.label)).toEqual(["System default", "USB Mic", "Built-in Mic"]);
    expect(ui.menu()!.querySelector('[role="menuitem"]')).toBeNull();
  });

  it("refreshes on devicechange; an unplugged saved device shows System default as current", async () => {
    window.localStorage.setItem(MIC_DEVICE_KEY, "usb-1");
    const devices = fakeDevices([device("usb-1", "USB Mic")]);
    const ui = render({ deps: fakeMic(devices).deps });

    click(ui.chevron());
    await settle();
    expect(options(ui.menu())).toEqual([
      { checked: false, label: "System default" },
      { checked: true, label: "USB Mic" },
    ]);

    devices.set([device("built-in", "Built-in Mic")]);
    act(() => devices.listeners.forEach((l) => l()));
    await settle();
    expect(options(ui.menu())).toEqual([
      { checked: true, label: "System default" },
      { checked: false, label: "Built-in Mic" },
    ]);

    act(() => root!.unmount());
    root = null;
    expect(devices.listeners.size).toBe(0);
  });

  it("is disabled on an insecure page with the same reason as the mic", async () => {
    const devices = fakeDevices(DEVICES);
    const ui = render({ deps: fakeMic({ ...devices, secureContext: false }).deps });

    const chevron = ui.chevron();
    expect(chevron.disabled).toBe(true);
    expect(chevron.title).toBe(s.insecure);
    expect(ui.mic().title).toBe(s.insecure);
    click(chevron);
    await settle();
    expect(ui.menu()).toBeNull();
    expect(devices.enumerateDevices).not.toHaveBeenCalled();
  });

  it("negative control: a capture path that ignores the saved device is rejected", async () => {
    variant.ignoreSavedId = true;
    window.localStorage.setItem(MIC_DEVICE_KEY, "usb-1");
    const mic = fakeMic(fakeDevices(DEVICES));
    const ui = render({ deps: mic.deps });

    click(ui.mic());
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
    expect(() => expectCapturedDevice(mic.getUserMedia, "usb-1")).toThrow();
  });
});

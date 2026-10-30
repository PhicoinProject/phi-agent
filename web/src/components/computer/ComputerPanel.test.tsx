// @vitest-environment jsdom
import type { DisplayLease, DisplayStatus } from "@phi/shared";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { settle } from "../voice/fakes";
import {
  ComputerPanel,
  type ComputerGateway,
  type ComputerPanelProps,
  type PanzoomLike,
  type RfbClient,
} from "./ComputerPanel";
import {
  clientToFramebuffer,
  correctForPanzoom,
  KEYSYM,
  leaseHeldBy,
  parseGeometry,
  type ClientPoint,
  type RectLike,
} from "./computerModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const VIEWER = "viewer-abc";
const MY_HASH = "a1b2c3d4e5f6";
const OTHER_HASH = "ffffffffffff";
const AGENT: DisplayLease = { epoch: 1, holder: "agent", since: 1 };
const MINE: DisplayLease = { epoch: 2, holder: "shared", since: 2, viewer_hash: MY_HASH };
const OTHER: DisplayLease = { epoch: 3, holder: "human", since: 3, viewer_hash: OTHER_HASH };
const OTHER_SHARED: DisplayLease = { epoch: 4, holder: "shared", since: 4, viewer_hash: OTHER_HASH };

function status(over: Partial<DisplayStatus> = {}): DisplayStatus {
  return {
    geometry: "1920x1080",
    installed: true,
    lease: AGENT,
    missing: [],
    profile: "default",
    profile_key: "pk-1",
    running: true,
    supported: true,
    ...over,
  };
}

class FakeWs extends EventTarget {
  static all: FakeWs[] = [];
  binaryType = "blob";
  closes: Array<number | undefined> = [];
  readonly url: string;
  constructor(url: string) {
    super();
    this.url = url;
    FakeWs.all.push(this);
  }
  close(code?: number) {
    this.closes.push(code);
  }
  serverClose(code: number, reason = "") {
    const ev = new Event("close");
    Object.assign(ev, { code, reason });
    this.dispatchEvent(ev);
  }
}

class FakeRfb extends EventTarget implements RfbClient {
  static all: FakeRfb[] = [];
  viewOnly = false;
  scaleViewport = false;
  resizeSession = true;
  focusOnClick = false;
  background = "";
  qualityLevel = 6;
  keys: Array<[number, string | null, boolean | undefined]> = [];
  ctrlAltDel = 0;
  pasted: string[] = [];
  focused = 0;
  disconnected = 0;
  canvas: HTMLCanvasElement;
  /** Gesture points as noVNC's clientToElement() would see them (offset into the canvas rect). */
  gestures: Array<{ type: string; x: number; y: number }> = [];
  readonly target: HTMLElement;
  readonly socket: FakeWs;
  readonly options?: { shared?: boolean };
  constructor(target: HTMLElement, socket: FakeWs, options?: { shared?: boolean }) {
    super();
    this.target = target;
    this.socket = socket;
    this.options = options;
    FakeRfb.all.push(this);
    this.canvas = document.createElement("canvas");
    target.appendChild(this.canvas);
    this.canvas.addEventListener("gesturestart", (ev) => {
      const d = (ev as CustomEvent<{ type: string; clientX: number; clientY: number }>).detail;
      const r = this.canvas.getBoundingClientRect();
      this.gestures.push({ type: d.type, x: d.clientX - r.left, y: d.clientY - r.top });
    });
  }
  sendKey(keysym: number, code: string | null, down?: boolean) {
    this.keys.push([keysym, code, down]);
  }
  sendCtrlAltDel() {
    this.ctrlAltDel += 1;
  }
  clipboardPasteFrom(text: string) {
    this.pasted.push(text);
  }
  focus() {
    this.focused += 1;
  }
  disconnect() {
    this.disconnected += 1;
  }
  serverConnect() {
    this.dispatchEvent(new Event("connect"));
  }
  serverDisconnect(clean: boolean) {
    this.dispatchEvent(new CustomEvent("disconnect", { detail: { clean } }));
  }
}

class FakePanzoom implements PanzoomLike {
  scale = 1;
  options: Record<string, unknown>[] = [];
  resets = 0;
  zooms: Array<[number, ClientPoint]> = [];
  destroyed = false;
  getScale = () => this.scale;
  reset = () => {
    this.resets += 1;
    this.scale = 1;
  };
  setOptions = (opts?: Record<string, unknown>) => {
    this.options.push({ ...opts });
  };
  zoomToPoint = (scale: number, point: ClientPoint) => {
    this.zooms.push([scale, { clientX: point.clientX, clientY: point.clientY }]);
    this.scale = scale;
  };
  destroy = () => {
    this.destroyed = true;
  };
}

type Handler = (event: { payload?: unknown }) => void;

interface FakeOptions {
  /** display.start throws this many times before it succeeds. */
  failStarts?: number;
  /** display.start waits for this before answering. */
  startGate?: Promise<void>;
}

function fakeGateway(initial: DisplayStatus, opts: FakeOptions = {}) {
  const handlers = new Map<string, Handler[]>();
  let current = initial;
  let tickets = 0;
  let failStarts = opts.failStarts ?? 0;
  const request = vi.fn(async (method: string, params: Record<string, unknown> = {}): Promise<unknown> => {
    switch (method) {
      case "display.status":
        return current;
      case "display.start":
        await opts.startGate;
        if (failStarts-- > 0) throw new Error("Xvnc did not come up");
        current = { ...current, running: true };
        return current;
      case "display.observe":
        return { ...current, path: "/api/display/ws", ticket: `t-${++tickets}`, viewer_id: (params.viewer_id as string) || VIEWER };
      case "display.lease.acquire": {
        // Like the gateway: no mode is the exclusive human lease, mode "shared" co-drives.
        const lease: DisplayLease = { ...MINE, holder: params.mode === "shared" ? "shared" : "human" };
        current = { ...current, lease };
        return { lease };
      }
      case "display.lease.release":
        current = { ...current, lease: AGENT };
        return { lease: AGENT };
      default:
        throw new Error(`unexpected ${method}`);
    }
  });
  const gateway: ComputerGateway = {
    on: (type, handler) => {
      handlers.set(type, [...(handlers.get(type) ?? []), handler]);
      return () => handlers.set(type, (handlers.get(type) ?? []).filter((h) => h !== handler));
    },
    request: request as ComputerGateway["request"],
  };
  const emit = (type: string, payload: unknown) => {
    // The server's own state follows the lease it broadcasts, so a later observe reports it too.
    const p = payload as { lease?: DisplayLease; profile_key?: string };
    if (type === "display.lease" && p.lease && p.profile_key === current.profile_key) current = { ...current, lease: p.lease };
    act(() => (handlers.get(type) ?? []).forEach((h) => h({ payload })));
  };
  const calls = (method: string) => request.mock.calls.filter(([m]) => m === method).map(([, p]) => p);
  return { calls, emit, gateway, request };
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;
let panzoom: FakePanzoom;

beforeEach(() => {
  FakeWs.all = [];
  FakeRfb.all = [];
  panzoom = new FakePanzoom();
  vi.stubGlobal("matchMedia", () => ({ addEventListener() {}, matches: false, media: "", removeEventListener() {} }));
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

async function render(initial: DisplayStatus, props: Partial<ComputerPanelProps> = {}, opts: FakeOptions = {}) {
  const gw = fakeGateway(initial, opts);
  const onHandBack = vi.fn();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() =>
    root!.render(
      <ComputerPanel
        createPanzoom={() => panzoom}
        createSocket={(url) => new FakeWs(url) as unknown as WebSocket}
        gateway={gw.gateway}
        loadRfb={async () => FakeRfb as unknown as new (t: HTMLElement, s: WebSocket, o?: { shared?: boolean }) => RfbClient}
        mobile={false}
        onHandBack={onHandBack}
        {...props}
      />,
    ),
  );
  await settle();
  return { ...gw, onHandBack };
}

const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel);
const byText = (text: string) =>
  Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent?.trim() === text);
const panel = () => q('[data-testid="computer-panel"]')!;
const rfb = () => FakeRfb.all.at(-1)!;
const click = (el: Element | null | undefined) => act(() => (el as HTMLElement).click());

const checked = (label: string) => byText(label)?.getAttribute("aria-checked");

/** Attached and connected: Take over is the default, so the shared lease is held with no click. */
async function renderLive(props: Partial<ComputerPanelProps> = {}) {
  const gw = await render(status(), props);
  act(() => rfb().serverConnect());
  await settle();
  expect(gw.calls("display.lease.acquire")).toHaveLength(1);
  return gw;
}

/** Live with another viewer holding the lease: the tab opens in Watch and acquires nothing. */
async function renderWatchingOther(lease: DisplayLease) {
  const gw = await render(status({ lease }));
  act(() => rfb().serverConnect());
  await settle();
  expect(gw.calls("display.lease.acquire")).toHaveLength(0);
  return gw;
}

/** Watch: releases our lease (no hand back to the agent) and turns input off. */
async function watch(gw: Awaited<ReturnType<typeof render>>) {
  const before = gw.calls("display.lease.release").length;
  click(byText("Watch"));
  await settle();
  expect(gw.calls("display.lease.release")).toHaveLength(before + 1);
  expect(checked("Watch")).toBe("true");
}

/** Take over from another viewer through the confirm dialog: nothing is acquired until the user confirms. */
async function takeOverFromOther(gw: Awaited<ReturnType<typeof render>>) {
  const before = gw.calls("display.lease.acquire").length;
  click(byText("Take over"));
  await settle();
  expect(gw.calls("display.lease.acquire")).toHaveLength(before);
  click(q("[data-confirm]"));
  await settle();
  expect(gw.calls("display.lease.acquire")).toHaveLength(before + 1);
}

describe("computer model", () => {
  it("defaults the geometry to 1920x1080", () => {
    expect(parseGeometry("1920x1080")).toEqual({ height: 1080, width: 1920 });
    expect(parseGeometry("")).toEqual({ height: 1080, width: 1920 });
    expect(parseGeometry(undefined)).toEqual({ height: 1080, width: 1920 });
    expect(parseGeometry("1280x720")).toEqual({ height: 720, width: 1280 });
  });

  it("recognises only our own lease, exclusive or shared", () => {
    expect(leaseHeldBy(MINE, MY_HASH)).toBe(true);
    expect(leaseHeldBy({ ...MINE, holder: "human" }, MY_HASH)).toBe(true);
    expect(leaseHeldBy(OTHER, MY_HASH)).toBe(false);
    expect(leaseHeldBy(OTHER_SHARED, MY_HASH)).toBe(false);
    expect(leaseHeldBy(AGENT, MY_HASH)).toBe(false);
    expect(leaseHeldBy({ ...AGENT, viewer_hash: MY_HASH }, MY_HASH)).toBe(false);
    expect(leaseHeldBy(MINE, null)).toBe(false);
  });

  // A 960x540 canvas shows the 1920x1080 framebuffer (noVNC scale 0.5); panzoom has zoomed it 2.4x
  // and panned it so its transformed rect starts at x=-100, y=20. A finger at the transformed point
  // that sits over framebuffer (960, 540) must click there.
  function expectMapsUnderZoom(mapper: typeof correctForPanzoom) {
    const rect: RectLike = { left: -100, top: 20 };
    const finger = { clientX: -100 + 480 * 2.4, clientY: 20 + 270 * 2.4 };
    const fb = clientToFramebuffer(mapper(finger, rect, 2.4), rect, 0.5);
    expect(Math.abs(fb.x - 960)).toBeLessThanOrEqual(1);
    expect(Math.abs(fb.y - 540)).toBeLessThanOrEqual(1);
  }

  it("maps a pointer to the framebuffer under a 2.4x panzoom", () => {
    expectMapsUnderZoom(correctForPanzoom);
    expect(correctForPanzoom({ clientX: 50, clientY: 60 }, { left: 0, top: 0 }, 1)).toEqual({ clientX: 50, clientY: 60 });
  });

  it("negative control: the naive mapping that ignores the panzoom transform is rejected", () => {
    const naive: typeof correctForPanzoom = (point) => point;
    expect(() => expectMapsUnderZoom(naive)).toThrow();
  });
});

describe("ComputerPanel status", () => {
  it("shows the install command when the bot desktop is not installed", async () => {
    const gw = await render(status({ install_command: "phi desktop install", installed: false, running: false }));
    expect(panel().textContent).toContain("The bot desktop is not installed.");
    expect(panel().textContent).toContain("phi desktop install");
    expect(FakeWs.all).toHaveLength(0);
    expect(gw.calls("display.start")).toHaveLength(0);
  });

  it("opens a stopped desktop straight into a shared session: start once, then acquire, no click", async () => {
    let open!: () => void;
    const startGate = new Promise<void>((resolve) => (open = resolve));
    const gw = await render(status({ running: false }), {}, { startGate });
    expect(gw.calls("display.start")).toHaveLength(1);
    expect(panel().textContent).toContain("Starting the bot desktop…");
    expect(byText("Start")).toBeUndefined();
    expect(byText("Retry")).toBeUndefined();

    await act(async () => open());
    await settle();
    expect(gw.calls("display.observe")).toHaveLength(1);
    expect(FakeWs.all).toHaveLength(1);
    act(() => rfb().serverConnect());
    await settle();
    expect(gw.request.mock.calls.map(([m]) => m)).toEqual([
      "display.status",
      "display.start",
      "display.observe",
      "display.lease.acquire",
    ]);
    expect(gw.calls("display.lease.acquire")).toEqual([{ mode: "shared", viewer_id: VIEWER }]);
    expect(q('[role="dialog"]')).toBeNull();
    expect(panel().getAttribute("data-holding")).toBe("true");
    expect(checked("Take over")).toBe("true");
    expect(checked("Watch")).toBe("false");
    expect(byText("Start")).toBeUndefined();

    // Started once per opening: a later stop is shown, not silently restarted.
    gw.emit("display.status", status({ lease: AGENT, running: false }));
    await settle();
    expect(gw.calls("display.start")).toHaveLength(1);
    expect(gw.calls("display.lease.acquire")).toHaveLength(1);
    expect(panel().textContent).toContain("The bot desktop is stopped.");
  });

  it("a failed start offers Retry; nothing retries on its own", async () => {
    const gw = await render(status({ running: false }), {}, { failStarts: 1 });
    expect(gw.calls("display.start")).toHaveLength(1);
    expect(panel().textContent).toContain("The bot desktop did not start: Xvnc did not come up");
    expect(byText("Start")).toBeUndefined();
    await settle();
    expect(gw.calls("display.start")).toHaveLength(1);
    expect(FakeWs.all).toHaveLength(0);

    click(byText("Retry"));
    await settle();
    expect(gw.calls("display.start")).toHaveLength(2);
    expect(FakeWs.all).toHaveLength(1);
    expect(byText("Retry")).toBeUndefined();
  });

  it("attaches view only with a display ticket and noVNC scaled to the pane, then takes over by default", async () => {
    const gw = await render(status(), { profile: "work" });
    expect(gw.calls("display.status")[0]).toEqual({ profile: "work" });
    expect(gw.calls("display.observe")[0]).toEqual({ profile: "work" });
    const ws = FakeWs.all[0];
    expect(ws.url).toMatch(/^ws:\/\/[^/]+\/api\/display\/ws\?display_ticket=t-\d+$/);
    expect(ws.binaryType).toBe("arraybuffer");
    expect(rfb().socket).toBe(ws);
    expect(rfb().options).toEqual({ shared: true });
    expect(rfb().viewOnly).toBe(true);
    expect(rfb().scaleViewport).toBe(true);
    expect(rfb().resizeSession).toBe(false);
    expect(gw.calls("display.lease.acquire")).toHaveLength(0);
    act(() => rfb().serverConnect());
    await settle();
    expect(gw.calls("display.lease.acquire")).toEqual([{ mode: "shared", profile: "work", viewer_id: VIEWER }]);
    expect(panel().textContent).toContain("Bot desktop 1920x1080");
    expect(panel().textContent).toContain("You and the agent both have control");
    expect(checked("Take over")).toBe("true");
    expect(panel().textContent).toContain("not bound by the lease");
    expect(panel().getAttribute("data-holding")).toBe("true");
  });

  it("keeps the desktop's 16:9 screen in the window; full screen gives it the remaining height", async () => {
    await render(status());
    const stage = () => panel().querySelector<HTMLElement>('[data-testid="computer-stage"]')!;
    expect(stage().style.aspectRatio).toBe("1920 / 1080");
    expect(stage().className).not.toMatch(/\bflex-1\b/);
  });
});

describe("ComputerPanel lease", () => {
  it("Take over is the default: shared lease with no dialog, no red frame, input enabled, toolbar live", async () => {
    const gw = await renderLive();
    expect(q('[role="dialog"]')).toBeNull();
    expect(gw.calls("display.lease.acquire")).toEqual([{ mode: "shared", viewer_id: VIEWER }]);
    expect(panel().getAttribute("data-holding")).toBe("true");
    // Holding control is shown by a quiet brand pill, never a red frame or red controls.
    expect(panel().className).not.toMatch(/destructive/);
    expect(panel().className).toMatch(/\brounded-lg\b/);
    expect(panel().querySelector(".text-destructive, .border-destructive, .bg-destructive")).toBeNull();
    expect(panel().textContent).toContain("You and the agent both have control");
    expect(rfb().viewOnly).toBe(false);
    expect(rfb().focused).toBeGreaterThan(0);

    click(byText("Ctrl+Alt+Del"));
    click(byText("Esc"));
    click(byText("Tab"));
    expect(rfb().ctrlAltDel).toBe(1);
    expect(rfb().keys).toEqual([
      [KEYSYM.Escape, "Escape", undefined],
      [KEYSYM.Tab, "Tab", undefined],
    ]);
  });

  it("Watch releases our lease without a hand back; Take over re-acquires shared with no dialog", async () => {
    const gw = await renderLive();
    await watch(gw);
    expect(gw.calls("display.lease.release")).toEqual([{ viewer_id: VIEWER }]);
    expect(gw.onHandBack).not.toHaveBeenCalled();
    expect(panel().getAttribute("data-holding")).toBe("false");
    expect(rfb().viewOnly).toBe(true);
    expect(checked("Take over")).toBe("false");
    expect(panel().textContent).toContain("Agent is driving");
    // Watch stays put: nothing re-acquires behind the user's back.
    await settle();
    expect(gw.calls("display.lease.acquire")).toHaveLength(1);

    click(byText("Take over"));
    await settle();
    expect(q('[role="dialog"]')).toBeNull();
    expect(gw.calls("display.lease.acquire")).toEqual([
      { mode: "shared", viewer_id: VIEWER },
      { mode: "shared", viewer_id: VIEWER },
    ]);
    expect(checked("Take over")).toBe("true");
    expect(panel().getAttribute("data-holding")).toBe("true");
    expect(rfb().viewOnly).toBe(false);
  });

  it("toolbar keys do nothing in Watch mode", async () => {
    const gw = await renderLive();
    await watch(gw);
    expect(byText("Ctrl+Alt+Del")?.disabled).toBe(true);
    expect(byText("Esc")?.disabled).toBe(true);
    expect(byText("Paste")?.disabled).toBe(true);
  });

  it("another viewer holding: opens in Watch showing who; Take over needs the dialog, cancelling acquires nothing", async () => {
    const gw = await renderWatchingOther(OTHER_SHARED);
    expect(checked("Watch")).toBe("true");
    expect(panel().textContent).toContain(`Another viewer (${OTHER_HASH}) has control`);
    expect(panel().getAttribute("data-holding")).toBe("false");
    expect(rfb().viewOnly).toBe(true);
    click(byText("Take over"));
    expect(q('[role="dialog"]')?.textContent).toContain("Take over from the other viewer?");
    expect(q('[role="dialog"]')?.textContent).toContain("not bound by the lease");
    expect(gw.calls("display.lease.acquire")).toHaveLength(0);
    click(byText("Cancel"));
    await settle();
    expect(q('[role="dialog"]')).toBeNull();
    expect(gw.calls("display.lease.acquire")).toHaveLength(0);
    expect(checked("Watch")).toBe("true");
    expect(rfb().viewOnly).toBe(true);
  });

  it("confirming replaces the other viewer's exclusive lease with our shared one", async () => {
    const gw = await renderWatchingOther(OTHER);
    await takeOverFromOther(gw);
    expect(gw.calls("display.lease.acquire")).toEqual([{ mode: "shared", viewer_id: VIEWER }]);
    expect(checked("Take over")).toBe("true");
    expect(panel().getAttribute("data-holding")).toBe("true");
    expect(panel().textContent).toContain("You and the agent both have control");
    expect(rfb().viewOnly).toBe(false);
  });

  it("another viewer taking the lease drops us back to Watch, and we do not take it back", async () => {
    const gw = await renderLive();
    gw.emit("display.lease", { lease: OTHER, profile_key: "pk-1" });
    await settle();
    expect(panel().getAttribute("data-holding")).toBe("false");
    expect(rfb().viewOnly).toBe(true);
    expect(panel().textContent).toContain(`Another viewer (${OTHER_HASH}) has control`);
    expect(checked("Watch")).toBe("true");
    expect(gw.calls("display.lease.acquire")).toHaveLength(1);
    // Events for another profile's screen are not ours.
    gw.emit("display.lease", { lease: MINE, profile_key: "pk-other" });
    expect(panel().getAttribute("data-holding")).toBe("false");
  });

  it("a 4000 close re-attaches in Watch on a fresh ticket with the same viewer id", async () => {
    const gw = await renderLive();
    const first = rfb();
    gw.emit("display.lease", { lease: OTHER, profile_key: "pk-1" });
    act(() => {
      first.socket.serverClose(4000, "control-taken");
      first.serverDisconnect(false);
    });
    await settle();
    expect(panel().textContent).toContain("Control changed hands");
    expect(FakeWs.all).toHaveLength(2);
    expect(gw.calls("display.observe").at(-1)).toEqual({ viewer_id: VIEWER });
    expect(rfb()).not.toBe(first);
    expect(rfb().viewOnly).toBe(true);
    act(() => rfb().serverConnect());
    await settle();
    expect(panel().textContent).not.toContain("Control changed hands");
    expect(q('[role="alert"]')).toBeNull();
    expect(checked("Watch")).toBe("true");
    expect(gw.calls("display.lease.acquire")).toHaveLength(1);
  });

  it("an unclean drop that is not an eviction shows the error with Reconnect", async () => {
    const gw = await renderLive();
    act(() => {
      rfb().socket.serverClose(1006);
      rfb().serverDisconnect(false);
    });
    await settle();
    expect(q('[role="alert"]')?.textContent).toContain("The desktop stream was lost.");
    expect(FakeWs.all).toHaveLength(1);
    click(byText("Reconnect"));
    await settle();
    expect(gw.calls("display.observe")).toHaveLength(2);
    expect(FakeWs.all).toHaveLength(2);
  });

  it("Hand back releases the lease and returns the note to the caller only", async () => {
    const gw = await renderLive();
    const note = q<HTMLInputElement>('[data-testid="computer-note"]')!;
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setter.call(note, "logged in, continue");
      note.dispatchEvent(new Event("input", { bubbles: true }));
    });
    click(byText("Hand back"));
    await settle();
    expect(gw.calls("display.lease.release")).toEqual([{ viewer_id: VIEWER }]);
    expect(gw.onHandBack).toHaveBeenCalledWith("logged in, continue");
    expect(JSON.stringify(gw.request.mock.calls)).not.toContain("logged in");
    expect(panel().getAttribute("data-holding")).toBe("false");
    expect(rfb().viewOnly).toBe(true);
    expect(checked("Watch")).toBe("true");
    await settle();
    expect(gw.calls("display.lease.acquire")).toHaveLength(1);
  });

  it("Paste sends clipboard text to the remote clipboard while holding", async () => {
    const readText = vi.fn(async () => "hunter2-free text");
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { readText } });
    await renderLive();
    click(byText("Paste"));
    await settle();
    expect(rfb().pasted).toEqual(["hunter2-free text"]);
  });

  it("unmounting closes the stream with 1000 so the bridge hands control back", async () => {
    await renderLive();
    const ws = FakeWs.all[0];
    act(() => root!.unmount());
    root = null;
    expect(ws.closes[0]).toBe(1000);
    expect(rfb().disconnected).toBe(1);
  });
});

describe("ComputerPanel full screen (desktop)", () => {
  const toggle = () => q<HTMLButtonElement>('[data-testid="computer-fullscreen"]')!;
  const page = document.documentElement as { requestFullscreen?: unknown };
  const doc = document as { exitFullscreen?: unknown; fullscreenElement?: unknown };
  let fullscreenElement: Element | null = null;

  function fullscreenApi(request: () => Promise<void>) {
    const requestFullscreen = vi.fn(request);
    const exitFullscreen = vi.fn(async () => {
      fullscreenElement = null;
    });
    Object.defineProperty(page, "requestFullscreen", { configurable: true, value: requestFullscreen });
    Object.defineProperty(doc, "exitFullscreen", { configurable: true, value: exitFullscreen });
    Object.defineProperty(doc, "fullscreenElement", { configurable: true, get: () => fullscreenElement });
    return { exitFullscreen, requestFullscreen };
  }

  async function press() {
    await act(async () => toggle().click());
    await settle();
  }

  afterEach(() => {
    fullscreenElement = null;
    delete page.requestFullscreen;
    delete doc.exitFullscreen;
    delete doc.fullscreenElement;
  });

  it("requests full screen for the page when the API exists; the same button exits", async () => {
    const api = fullscreenApi(async () => {
      fullscreenElement = document.documentElement;
    });
    await renderLive();
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
    expect(toggle().getAttribute("aria-label")).toBe("Full screen");
    expect(panel().className).not.toMatch(/\bfixed\b/);

    await press();
    expect(api.requestFullscreen).toHaveBeenCalledTimes(1);
    expect(toggle().getAttribute("aria-pressed")).toBe("true");
    expect(toggle().getAttribute("aria-label")).toBe("Exit full screen");
    expect(panel().getAttribute("data-fullscreen")).toBe("native");
    expect(panel().className).toMatch(/\bfixed inset-0\b/);

    await press();
    expect(api.exitFullscreen).toHaveBeenCalledTimes(1);
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
    expect(panel().className).not.toMatch(/\bfixed\b/);
  });

  it("leaving full screen from the browser (Esc) turns the toggle off", async () => {
    const api = fullscreenApi(async () => {
      fullscreenElement = document.documentElement;
    });
    await renderLive();
    await press();
    fullscreenElement = null;
    act(() => void document.dispatchEvent(new Event("fullscreenchange")));
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
    expect(api.exitFullscreen).not.toHaveBeenCalled();
  });

  it("without the API it falls back to the fixed overlay, and Esc exits", async () => {
    expect(typeof page.requestFullscreen).not.toBe("function");
    await renderLive();
    await press();
    expect(toggle().getAttribute("aria-pressed")).toBe("true");
    expect(panel().getAttribute("data-fullscreen")).toBe("overlay");
    expect(panel().className).toMatch(/\bfixed inset-0 z-50\b/);
    act(() => void window.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key: "Escape" })));
    expect(toggle().getAttribute("aria-pressed")).toBe("false");
    expect(panel().className).not.toMatch(/\bfixed\b/);
  });

  it("a refused request also falls back to the overlay", async () => {
    const api = fullscreenApi(() => Promise.reject(new Error("denied")));
    await renderLive();
    await press();
    expect(api.requestFullscreen).toHaveBeenCalledTimes(1);
    expect(panel().getAttribute("data-fullscreen")).toBe("overlay");
    expect(toggle().getAttribute("aria-pressed")).toBe("true");
  });
});

describe("ComputerPanel mobile", () => {
  function stage() {
    return q('[data-testid="computer-stage"]')!;
  }

  function gesture(type: string, clientX: number, clientY: number) {
    act(() => void rfb().canvas.dispatchEvent(new CustomEvent("gesturestart", { detail: { clientX, clientY, type } })));
  }

  function pointer(type: string, id: number) {
    const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 10, clientY: 10 });
    Object.defineProperty(ev, "pointerId", { value: id });
    act(() => void rfb().canvas.dispatchEvent(ev));
  }

  const hint = () => q('[data-testid="computer-sideways-hint"]');
  const size = { height: window.innerHeight, width: window.innerWidth };

  function viewport(width: number, height: number) {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    Object.defineProperty(window, "innerHeight", { configurable: true, value: height });
  }

  function orientation(value: { lock?: (o: string) => Promise<void>; unlock: () => void }) {
    Object.defineProperty(screen, "orientation", { configurable: true, value });
  }

  afterEach(() => {
    viewport(size.width, size.height);
    delete (screen as { orientation?: unknown }).orientation;
  });

  it("asks for landscape; upright with the lock refused, a dismissible hint says to turn the phone", async () => {
    const lock = vi.fn(() => Promise.reject(new Error("not allowed")));
    orientation({ lock, unlock: vi.fn() });
    viewport(400, 800);
    await renderLive({ mobile: true });
    expect(lock).toHaveBeenCalledWith("landscape");
    expect(hint()?.textContent).toBe("Turn your phone sideways for a larger view");
    click(hint()!.querySelector('button[aria-label="Close"]'));
    expect(hint()).toBeNull();
    // Panzoom is untouched by the hint.
    expect(q('[data-testid="computer-stage"]')).not.toBeNull();
  });

  it("without a lock API (iOS) the hint shows upright and goes once the phone is turned", async () => {
    orientation({ unlock: vi.fn() });
    viewport(400, 800);
    await renderLive({ mobile: true });
    expect(hint()).not.toBeNull();
    viewport(800, 400);
    act(() => void window.dispatchEvent(new Event("resize")));
    expect(hint()).toBeNull();
  });

  it("a granted lock shows no hint and is released when the panel closes", async () => {
    const unlock = vi.fn();
    const lock = vi.fn(() => Promise.resolve());
    orientation({ lock, unlock });
    const requestFullscreen = vi.fn(() => Promise.resolve());
    Object.defineProperty(document.documentElement, "requestFullscreen", { configurable: true, value: requestFullscreen });
    viewport(400, 800);
    await renderLive({ mobile: true });
    expect(hint()).toBeNull();
    // Orientation locks need a full-screen document: full screen first, then landscape.
    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(lock).toHaveBeenCalledWith("landscape");
    act(() => root!.unmount());
    root = null;
    expect(unlock).toHaveBeenCalledTimes(1);
    delete (document.documentElement as { requestFullscreen?: unknown }).requestFullscreen;
  });

  it("Watch: full screen; double tap zooms 2x at the point, Fit resets", async () => {
    const gw = await renderLive({ mobile: true });
    await watch(gw);
    expect(panel().className).toMatch(/\bfixed\b/);
    // Edge to edge on phones: no frame (rounded screen corners would clip it), even while holding.
    expect(panel().className).not.toMatch(/\bborder\b|border-destructive/);
    expect(panel().textContent).toContain("Watching");
    // jsdom has no orientation lock but is landscape: nothing to ask, and no desktop toggle.
    expect(hint()).toBeNull();
    expect(q('[data-testid="computer-fullscreen"]')).toBeNull();
    expect(byText("kbd")?.disabled).toBe(true);
    gesture("onetap", 200, 300);
    gesture("onetap", 202, 301);
    expect(panzoom.zooms).toEqual([[2, { clientX: 202, clientY: 301 }]]);
    click(byText("Fit"));
    expect(panzoom.resets).toBe(1);
  });

  it("Watch: a single finger pans; holding: a single finger goes to noVNC, two fingers panzoom", async () => {
    const gw = await renderLive({ mobile: true });
    await watch(gw);
    pointer("pointerdown", 1);
    expect(panzoom.options.at(-1)).toMatchObject({ disablePan: false });
    pointer("pointerup", 1);
    click(byText("Take over"));
    await settle();
    expect(q('[role="dialog"]')).toBeNull();
    expect(gw.calls("display.lease.acquire")).toHaveLength(2);
    pointer("pointerdown", 1);
    expect(panzoom.options.at(-1)).toMatchObject({ disablePan: true });
    pointer("pointerdown", 2);
    expect(panzoom.options.at(-1)).toMatchObject({ disablePan: false });
    pointer("pointerup", 2);
    expect(panzoom.options.at(-1)).toMatchObject({ disablePan: true });
  });

  it("holding: a tap under a 2.4x zoom reaches noVNC at the corrected point; two-finger gestures stay local", async () => {
    await renderLive({ mobile: true });
    panzoom.scale = 2.4;
    const canvas = rfb().canvas;
    canvas.getBoundingClientRect = () => ({ bottom: 20 + 1296, height: 1296, left: -100, right: -100 + 2304, toJSON() {}, top: 20, width: 2304, x: -100, y: 20 });
    gesture("onetap", -100 + 480 * 2.4, 20 + 270 * 2.4);
    const seen = rfb().gestures.at(-1)!;
    expect(seen.type).toBe("onetap");
    // noVNC divides this canvas-local offset by its own 0.5 viewport scale.
    expect(Math.abs(seen.x / 0.5 - 960)).toBeLessThanOrEqual(1);
    expect(Math.abs(seen.y / 0.5 - 540)).toBeLessThanOrEqual(1);
    expect(panzoom.zooms).toHaveLength(0);

    gesture("twodrag", 500, 500);
    gesture("pinch", 500, 500);
    expect(rfb().gestures.map((g) => g.type)).toEqual(["onetap"]);
    expect(stage()).not.toBeNull();
  });

  it("holding: key bar sends Esc/Tab/arrows, Ctrl latches onto the next key, kbd types text", async () => {
    await renderLive({ mobile: true });
    expect(panel().textContent).toContain("You + agent");
    click(byText("Esc"));
    click(byText("Tab"));
    click(q('[aria-label="Up"]'));
    expect(rfb().keys).toEqual([
      [KEYSYM.Escape, "Escape", undefined],
      [KEYSYM.Tab, "Tab", undefined],
      [KEYSYM.Up, "ArrowUp", undefined],
    ]);
    rfb().keys = [];
    click(byText("Ctrl"));
    expect(byText("Ctrl")?.getAttribute("aria-pressed")).toBe("true");
    const input = q<HTMLInputElement>('[data-testid="computer-kbd-input"]')!;
    click(byText("kbd"));
    expect(document.activeElement).toBe(input);
    act(() => {
      input.value = "cé";
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(input.value).toBe("");
    expect(rfb().keys).toEqual([
      [KEYSYM.Control, "ControlLeft", true],
      [0x63, null, undefined],
      [KEYSYM.Control, "ControlLeft", false],
      [0xe9, null, undefined],
    ]);
    expect(byText("Ctrl")?.getAttribute("aria-pressed")).toBe("false");
  });
});

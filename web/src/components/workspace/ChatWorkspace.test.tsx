// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { enPanels, enShell } from "@/i18n/en";
import type { ChatPageProps } from "@/pages/ChatPage";
import { fmt } from "@/components/shell/use-shell-strings";
import { fakeMic, settle, stubCanvas } from "@/components/voice/fakes";
import ChatWorkspace, { isComputerRequest } from "./ChatWorkspace";
import { WINDOW_WIDTH } from "./WorkspaceSheet";

interface FakeFeed {
  connect: ReturnType<typeof vi.fn>;
  emit: (type: string, payload: unknown) => void;
  request: (req: { id: string; method: string; params: Record<string, unknown> }) => unknown[];
}

const phone = vi.hoisted(() => ({ value: false }));
const feeds = vi.hoisted(() => [] as FakeFeed[]);
const writePty = vi.hoisted(() => vi.fn((_data: string) => true));
const getConfig = vi.hoisted(() => vi.fn(async () => ({}) as Record<string, unknown>));

vi.mock("@phi/ui/hooks/use-below-breakpoint", () => ({ useBelowBreakpoint: () => phone.value }));
vi.mock("@phi/ui/ui/components/bottom-sheet", () => ({
  BottomSheet: ({ open, title, children }: { open: boolean; title?: string; children?: ReactNode }) =>
    open ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
}));
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { ...actual.api, getConfig } };
});
vi.mock("@/lib/eventsFeedClient", () => {
  type Handler = (ev: { type: string; payload: unknown }) => void;
  type RequestHandler = (req: unknown) => unknown;
  class EventsFeedClient {
    handlers = new Map<string, Handler[]>();
    requestHandlers: RequestHandler[] = [];
    lastCloseCode: number | null = null;
    connect = vi.fn(async (_channel: string) => {});
    close = vi.fn();
    constructor() {
      feeds.push(this as unknown as FakeFeed);
    }
    on(type: string, handler: Handler) {
      this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler]);
      return () => this.handlers.set(type, (this.handlers.get(type) ?? []).filter((h) => h !== handler));
    }
    onRequest(handler: RequestHandler) {
      this.requestHandlers.push(handler);
      return () => (this.requestHandlers = this.requestHandlers.filter((h) => h !== handler));
    }
    onClose() {
      return () => {};
    }
    onState() {
      return () => {};
    }
    emit(type: string, payload: unknown) {
      for (const h of this.handlers.get(type) ?? []) h({ type, payload });
    }
    request(req: unknown) {
      return this.requestHandlers.map((h) => h(req));
    }
  }
  return { EventsFeedClient };
});
vi.mock("@/lib/gatewayClient", () => ({
  GatewayClient: class {
    connect = vi.fn(async () => {});
    close = vi.fn();
  },
}));
vi.mock("@/components/computer/ComputerPanel", () => ({
  ComputerPanel: ({ mobile }: { mobile?: boolean }) => <div data-testid="computer-panel" data-mobile={String(!!mobile)} />,
}));
// ChatPage itself (xterm, PTY socket) is out of scope: a stub that hands over a
// bridge and renders the real header actions and footer slots it is given.
vi.mock("@/pages/ChatPage", async () => {
  const { useEffect } = await import("react");
  const { ChatHeaderActions } = await import("@/components/shell/ChatHeader");
  const { ChatFooter } = await import("@/components/shell/ChatFooter");
  const { useBelowBreakpoint } = await import("@phi/ui/hooks/use-below-breakpoint");
  function ChatPageStub({ composerAccessory, headerActions, onBridge }: ChatPageProps) {
    const isPhone = useBelowBreakpoint(768);
    useEffect(() => {
      onBridge?.({ channel: "chan-1", roomId: "!room-a", writePty });
    }, [onBridge]);
    return (
      <div data-testid="chat-page">
        <ChatHeaderActions {...(headerActions ?? {})} />
        <textarea aria-label="terminal input" />
        <ChatFooter
          isPhone={isPhone}
          session={false}
          onSend={() => {}}
          onWrite={writePty}
          ctrlActive={false}
          onCtrlChange={() => {}}
          onFontAdjust={() => {}}
          composerAccessory={composerAccessory}
          onAddFile={async () => "/r/x"}
          modelCard={null}
        />
      </div>
    );
  }
  return { default: ChatPageStub };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom runs without an origin here, so localStorage is undefined: stub it.
const store = new Map<string, string>();
const localStorageMock = {
  clear: () => store.clear(),
  getItem: (key: string) => store.get(key) ?? null,
  removeItem: (key: string) => {
    store.delete(key);
  },
  setItem: (key: string, value: string) => {
    store.set(key, String(value));
  },
};

let container: HTMLDivElement;
let root: Root;
let outside: HTMLInputElement;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function render(mic = fakeMic()) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<ChatWorkspace voiceDeps={mic.deps} />));
  await flush();
  return mic;
}

function pointer(el: Element, type: string) {
  const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: 100, clientY: 400 });
  Object.defineProperty(ev, "pointerId", { value: 1 });
  act(() => void el.dispatchEvent(ev));
}

function press(target: EventTarget, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { bubbles: true, cancelable: true, key }));
  });
}

const sheet = (id: string) => document.body.querySelector<HTMLElement>(`[data-sheet="${id}"]`);
const action = (key: string) => container.querySelector<HTMLButtonElement>(`button[data-action="${key}"]`);
const feed = () => feeds.at(-1)!;

const PLAN = {
  revision: 2,
  todos: [
    { id: "t1", content: "Scan sources", status: "completed", depends_on: [], assignee: "self" },
    { id: "t2", content: "Port parser", status: "in_progress", depends_on: ["t1"], assignee: "agent" },
    { id: "t3", content: "Write tests", status: "pending", depends_on: ["t2"], assignee: "self" },
  ],
  plan: { title: "Port", waves: [["t1"], ["t2", "t3"]], critical_path: ["t1", "t2", "t3"] },
};

describe("ChatWorkspace", () => {
  beforeEach(() => {
    phone.value = false;
    feeds.length = 0;
    writePty.mockClear();
    getConfig.mockReset();
    getConfig.mockResolvedValue({});
    store.clear();
    vi.stubGlobal("localStorage", localStorageMock);
    // Stands in for the shell's Ctrl+K room search, outside the chat scope.
    outside = document.createElement("input");
    outside.setAttribute("aria-label", enShell.searchRooms);
    document.body.appendChild(outside);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    outside.remove();
    vi.unstubAllGlobals();
  });

  it("F8 dictates into the terminal composer as a bracketed paste, without sending", async () => {
    const mic = await render();
    expect(feed().connect).toHaveBeenCalledWith("chan-1");

    press(window, "F8");
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
    act(() => mic.socket.serverOpen());
    press(window, "F8");
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    act(() => mic.socket.serverSend({ transcript: "list the tests", type: "final" }));
    await settle();

    expect(writePty).toHaveBeenCalledWith("\x1b[200~list the tests\x1b[201~");
    expect(writePty).not.toHaveBeenCalledWith("\r");
  });

  it("F8 still toggles while typing inside the chat", async () => {
    const mic = await render();
    const terminalInput = container.querySelector<HTMLTextAreaElement>('textarea[aria-label="terminal input"]')!;
    terminalInput.focus();
    press(terminalInput, "F8");
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("negative control: F8 in the room search does not toggle dictation", async () => {
    const mic = await render();
    outside.focus();
    expect(document.activeElement).toBe(outside);
    press(outside, "F8");
    await settle();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="mic-button"]')?.getAttribute("aria-pressed")).not.toBe("true");

    outside.blur();
    press(window, "F8");
    await settle();
    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
  });

  it("disables the mic outside a secure context and explains why", async () => {
    const mic = await render(fakeMic({ secureContext: false }));
    const button = container.querySelector<HTMLButtonElement>('[data-testid="mic-button"]')!;
    expect(button.disabled).toBe(true);
    expect(button.getAttribute("title")).toBe("Microphone needs HTTPS or localhost");
    press(window, "F8");
    await settle();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
  });

  it("puts hold-to-talk in the bottom-centre slot on phones only", async () => {
    await render();
    expect(container.querySelector('[data-testid="hold-to-talk"]')).toBeNull();
    expect(container.querySelector('[data-testid="mic-slot"]')).toBeNull();
    expect(container.querySelector('[data-testid="chat-footer"] [data-testid="mic-button"]')).not.toBeNull();
    act(() => root.unmount());
    container.remove();

    phone.value = true;
    await render();
    expect(container.querySelector('[data-testid="mic-slot"] [data-testid="hold-to-talk"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="mic-button"]')).toBeNull();
  });

  it("on phones the mic types into the terminal (one bracketed paste, not run); Send is Enter", async () => {
    phone.value = true;
    let now = 1_000_000;
    const clock = vi.spyOn(Date, "now").mockImplementation(() => now);
    stubCanvas();
    try {
      const mic = await render();
      const hold = container.querySelector<HTMLButtonElement>('[data-testid="mic-slot"] [data-testid="hold-to-talk"]')!;
      pointer(hold, "pointerdown");
      await settle();
      act(() => mic.socket.serverOpen());
      now += 900;
      pointer(hold, "pointerup");
      act(() => mic.socket.serverSend({ transcript: "buy milk", type: "final" }));
      await settle();

      expect(container.querySelector('[data-testid="composer-pill"] textarea')).toBeNull();
      expect(writePty.mock.calls).toEqual([["\x1b[200~buy milk\x1b[201~"]]);

      const row = container.querySelector<HTMLElement>('[data-testid="phone-bar"]')!;
      act(() => row.querySelector<HTMLButtonElement>(`button[aria-label="${enShell.sendEnter}"]`)!.click());
      expect(writePty.mock.calls).toEqual([["\x1b[200~buy milk\x1b[201~"], ["\r"]]);
    } finally {
      clock.mockRestore();
    }
  });

  it("opens the Computer view on desktop as a floating widescreen window over the page", async () => {
    await render();
    const chat = container.querySelector('[data-testid="chat-page"]');
    const chatScope = container.querySelector("[data-chat-scope]")!;
    expect(sheet("computer")).toBeNull();
    await act(async () => action("computer")!.click());
    await flush();
    const win = sheet("computer")!;
    expect(win.getAttribute("data-sheet-mode")).toBe("window");
    expect(win.getAttribute("role")).toBe("dialog");
    expect(win.getAttribute("aria-modal")).toBe("true");
    // Portalled over the page (dimmed backdrop), not a column in the chat's row.
    expect(chatScope.parentElement!.contains(win)).toBe(false);
    expect(win.parentElement!.getAttribute("data-sheet-backdrop")).toBe("computer");
    expect(win.style.getPropertyValue("--phi-window-width")).toBe(WINDOW_WIDTH);
    expect(win.className).toMatch(/w-\[var\(--phi-window-width\)\]/);
    expect(win.querySelector('[role="separator"]')).toBeNull();
    expect(win.querySelector('[data-testid="computer-panel"]')?.getAttribute("data-mobile")).toBe("false");
    // The chat keeps its layout and its terminal; Esc belongs to the remote desktop.
    expect(container.querySelector('[data-testid="chat-page"]')).toBe(chat);
    press(window, "Escape");
    expect(sheet("computer")).not.toBeNull();
  });

  it("opens the Computer view full screen on phones", async () => {
    phone.value = true;
    await render();
    await act(async () => action("computer")!.click());
    await flush();
    expect(sheet("computer")?.getAttribute("data-sheet-mode")).toBe("full");
    expect(sheet("computer")?.querySelector('[data-testid="computer-panel"]')?.getAttribute("data-mobile")).toBe("true");
  });

  it("shows the Plan count and waves from plan.updated", async () => {
    await render();
    expect(action("plan")).toBeNull();
    act(() => feed().emit("plan.updated", PLAN));

    const label = fmt(enPanels.planProgress, { done: 1, total: 3 });
    expect(label).toBe("Plan 1/3");
    expect(action("plan")?.getAttribute("aria-label")).toBe(label);
    await act(async () => action("plan")!.click());
    const panel = sheet("plan")!;
    // Plan, Ledger and Rules stay a right-hand overlay.
    expect(panel.getAttribute("data-sheet-mode")).toBe("right");
    const waves = Array.from(panel.querySelectorAll('[data-testid="plan-wave"]'));
    expect(waves.map((w) => Array.from(w.querySelectorAll("[data-task-id]")).map((li) => li.getAttribute("data-task-id")))).toEqual([
      ["t1"],
      ["t2", "t3"],
    ]);
    expect(panel.querySelector('[data-task-id="t2"] [data-testid="plan-assignee"]')?.textContent).toBe(
      fmt(enPanels.planAgent, { n: 1 }),
    );
    expect(panel.querySelector('[data-testid="plan-critical-path"]')?.textContent).toContain("t1 > t2 > t3");
  });

  it("asks for help on the computer for computer_use approvals only, and opens the sheet", async () => {
    await render();
    act(() => void feed().request({ id: "r0", method: "approval", params: { description: "Allow `rm -rf build`?" } }));
    expect(container.querySelector('[data-testid="computer-help"]')).toBeNull();

    act(() =>
      void feed().request({
        id: "r1",
        method: "approval",
        params: { description: "Allow computer_use to perform `click`?", pattern_key: "cua:click:act" },
      }),
    );
    const card = container.querySelector('[data-testid="computer-help"]');
    expect(card?.textContent).toContain(enPanels.needsComputer);

    act(() => feed().emit("request.cancel", { id: "r1", method: "approval", reason: "timeout" }));
    expect(container.querySelector('[data-testid="computer-help"]')).toBeNull();

    act(() => void feed().request({ id: "r2", method: "approval", params: { pattern_key: "cua:type:act" } }));
    const open = Array.from(container.querySelectorAll('[data-testid="computer-help"] button')).find(
      (b) => b.textContent === enPanels.open,
    ) as HTMLButtonElement;
    await act(async () => open.click());
    await flush();
    expect(container.querySelector('[data-testid="computer-help"]')).toBeNull();
    expect(sheet("computer")).not.toBeNull();
  });
});

describe("isComputerRequest", () => {
  it("matches desktop approvals and ignores other prompts", () => {
    expect(isComputerRequest("approval", { pattern_key: "cua:click:act" })).toBe(true);
    expect(isComputerRequest("clarify", { question: "Please log in on the desktop" })).toBe(true);
    expect(isComputerRequest("approval", { description: "Allow `git push`?" })).toBe(false);
    expect(isComputerRequest("sudo", { description: "computer_use" })).toBe(false);
  });
});

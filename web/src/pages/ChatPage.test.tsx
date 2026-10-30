// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { enShell } from "@/i18n/en";
import {
  PTY_RECONNECT_MAX_ATTEMPTS,
  PTY_RECONNECT_MAX_MS,
  PTY_TICKET_TIMEOUT_MS,
} from "@/lib/pty-reconnect";

class FakeFitAddon {
  fit() {}
}

const webglInstances: FakeWebglAddon[] = [];

class FakeWebglAddon {
  disposed = false;
  onContextLoss() {
    return { dispose() {} };
  }
  dispose() {
    this.disposed = true;
  }
  constructor() {
    webglInstances.push(this);
  }
}

class FakeTerminal {
  options: Record<string, unknown>;
  rows = 24;
  cols = 80;
  parser = {
    registerOscHandler: vi.fn(),
  };
  unicode = { activeVersion: "" };

  constructor(options: Record<string, unknown>) {
    this.options = options;
  }

  attachCustomKeyEventHandler() {
    return true;
  }

  attachCustomWheelEventHandler() {
    return true;
  }

  clearSelection() {}

  clearTextureAtlas() {}

  dispose() {}

  focus() {}

  getSelection() {
    return "";
  }

  loadAddon() {}

  onData() {
    return { dispose() {} };
  }

  onResize() {
    return { dispose() {} };
  }

  onScroll() {
    return { dispose() {} };
  }

  get buffer() {
    // Minimal active-buffer surface for the resume follow-scroll pin
    // (isViewportPinnedToBottom reads viewportY/baseY).
    return { active: { baseY: 0, viewportY: 0 } };
  }

  scrollToBottom() {}

  open() {}

  paste() {}

  refresh() {}

  write() {}
}

const maybeReloadForLoopbackWsAuthFailure = vi.fn(() => false);
const apiMocks = vi.hoisted(() => ({
  buildWsUrl: vi.fn(async () => "ws://localhost/api/pty?channel=chat-1"),
  getSessionDetail: vi.fn(async (): Promise<{ title: string | null }> => ({ title: null })),
  getSessionLatestDescendant: vi.fn(async (): Promise<{ session_id: string | null }> => ({ session_id: null })),
}));
const workspaceMocks = vi.hoisted(() => ({
  getRooms: vi.fn(),
  getSettings: vi.fn(),
  getTree: vi.fn(),
  newChat: vi.fn(),
}));
// The latest props the (mocked) model card was rendered with.
const sidebarProps = vi.hoisted(
  () => ({ current: null }) as { current: { onSessionTitleChange?: (title: string | null) => void } | null },
);
const uploadChatImage = vi.hoisted(() =>
  vi.fn(async () => ({ path: "/tmp/pasted.png" })),
);

vi.mock("@/lib/chatImagePaste", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/chatImagePaste")>()),
  uploadChatImage,
}));

vi.mock("@xterm/addon-fit", () => ({ FitAddon: FakeFitAddon }));
vi.mock("@xterm/addon-unicode11", () => ({ Unicode11Addon: class {} }));
vi.mock("@xterm/addon-web-links", () => ({ WebLinksAddon: class {} }));
vi.mock("@xterm/addon-webgl", () => ({ WebglAddon: FakeWebglAddon }));
vi.mock("@xterm/xterm", () => ({ Terminal: FakeTerminal }));
vi.mock("@/components/ChatSidebar", async () => {
  const { createElement } = await import("react");
  return {
    ChatSidebar: (props: { onSessionTitleChange?: (title: string | null) => void }) => {
      sidebarProps.current = props;
      return createElement("div", { "data-testid": "chat-model-card" });
    },
  };
});
vi.mock("@/components/ChatSessionList", () => ({
  ChatSessionList: () => null,
}));
// /api/events feed clients created during a test (the plan / computer-help hooks open them).
const richFeeds = vi.hoisted(
  () => [] as { emit: (type: string, payload?: unknown) => void }[],
);
vi.mock("@/lib/eventsFeedClient", () => ({
  EventsFeedClient: class {
    handlers: ((event: { type: string; payload?: unknown }) => void)[] = [];
    lastCloseCode = null;
    constructor() {
      richFeeds.push(this);
    }
    connect = vi.fn(async () => {});
    close = vi.fn();
    on() {
      return () => {};
    }
    onAny(handler: (event: { type: string; payload?: unknown }) => void) {
      this.handlers.push(handler);
      return () => {};
    }
    onClose() {
      return () => {};
    }
    onState() {
      return () => {};
    }
    emit(type: string, payload?: unknown) {
      for (const handler of this.handlers) handler({ type, payload });
    }
  },
}));
vi.mock("@/components/Backdrop", () => ({ Backdrop: () => null }));
vi.mock("@/plugins", () => ({
  PluginSlot: () => null,
}));
vi.mock("@/contexts/usePageHeader", () => ({
  usePageHeader: () => ({ setEnd: vi.fn(), setTitle: vi.fn() }),
}));
vi.mock("@/contexts/useProfileScope", () => ({
  useProfileScope: () => ({ profile: "" }),
}));
vi.mock("@/themes", () => ({
  useTheme: () => ({ theme: { terminalBackground: "#000000" } }),
}));
vi.mock("@/i18n", () => ({
  useI18n: () => ({
    t: {
      app: {
        closeModelTools: "Close model tools",
        modelToolsSheetSubtitle: "Tools",
        modelToolsSheetTitle: "Model",
      },
    },
  }),
}));
vi.mock("@/lib/dashboard-auth-reload", () => ({
  maybeReloadForLoopbackWsAuthFailure,
}));
vi.mock("@/lib/api", () => ({
  PHI_BASE_PATH: "",
  api: apiMocks,
  buildWsUrl: apiMocks.buildWsUrl,
}));
vi.mock("@/lib/api-workspace", () => ({
  AGENT_ROOM_ID: "!local_agent",
  workspaceApi: workspaceMocks,
}));

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static OPEN = 1;

  binaryType = "blob";
  onclose: ((event: CloseEventLike) => void) | null = null;
  onmessage: ((event: { data: ArrayBuffer | string }) => void) | null = null;
  onopen: (() => void) | null = null;
  readyState = FakeWebSocket.OPEN;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.readyState = 3;
  }

  send = vi.fn();
}

type CloseEventLike = {
  code: number;
  reason: string;
  wasClean: boolean;
};

let container: HTMLDivElement;
let root: Root;

// jsdom runs without an origin here (per-file @vitest-environment jsdom on a
// node-default config), so localStorage is undefined. Stub it so components
// that persist UI state (terminal font size) can be exercised.
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = String(value);
    },
    removeItem: (key: string) => {
      delete store[key];
    },
    clear: () => {
      store = {};
    },
  };
})();

// React only routes updates through act() when this flag is set; without it
// the isActive re-renders in the keyboard-inset gate test warn.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  richFeeds.length = 0;
  webglInstances.length = 0;
  maybeReloadForLoopbackWsAuthFailure.mockClear();
  apiMocks.buildWsUrl.mockReset();
  apiMocks.buildWsUrl.mockResolvedValue("ws://localhost/api/pty?channel=chat-1");
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      disconnect() {}
      observe() {}
      unobserve() {}
    },
  );
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    cb(0);
    return 1;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
  vi.stubGlobal("matchMedia", () => ({
    addEventListener() {},
    matches: false,
    media: "",
    removeEventListener() {},
  }));
  vi.stubGlobal("crypto", {
    getRandomValues: (values: Uint8Array) => {
      values.fill(7);
      return values;
    },
    randomUUID: () => "chat-test-id",
  });

  Object.defineProperty(window, "visualViewport", {
    configurable: true,
    value: { addEventListener() {}, removeEventListener() {}, width: 1280 },
  });
  Object.defineProperty(window, "__PHI_SESSION_TOKEN__", {
    configurable: true,
    value: "stale-token",
    writable: true,
  });
  Object.defineProperty(window, "__PHI_AUTH_REQUIRED__", {
    configurable: true,
    value: false,
    writable: true,
  });
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: {
      readText: vi.fn(async () => ""),
      writeText: vi.fn(async () => {}),
    },
  });
  sessionStorage.clear();
  vi.stubGlobal("localStorage", localStorageMock);
  localStorageMock.clear();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.unstubAllGlobals();
});

describe("ChatPage", () => {
  it("sends a PTY keepalive frame every 20 seconds while the socket is open", async () => {
    vi.useFakeTimers();
    try {
      const { default: ChatPage } = await import("./ChatPage");
      await render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive />
        </MemoryRouter>,
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(FakeWebSocket.instances).toHaveLength(1);

      const socket = FakeWebSocket.instances[0];
      await act(async () => socket.onopen?.());
      socket.send.mockClear();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(20_000);
      });

      expect(socket.send).toHaveBeenCalledWith("\x1b[RESIZE:80;24]");
    } finally {
      vi.useRealTimers();
    }
  });

  it("defers a reconnect while the chat tab is inactive", async () => {
    vi.useFakeTimers();
    try {
      const { default: ChatPage } = await import("./ChatPage");
      await render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive />
        </MemoryRouter>,
      );
      await act(async () => {
        await Promise.resolve();
      });
      const socket = FakeWebSocket.instances[0];
      await act(async () => {
        socket.onclose?.({ code: 1001, reason: "", wasClean: true });
        root.render(
          <MemoryRouter initialEntries={["/chat"]}>
            <ChatPage isActive={false} />
          </MemoryRouter>,
        );
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });

      expect(FakeWebSocket.instances).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  // #52471: a native/DOM paste (context-menu paste, middle-click, or any
  // Ctrl+V route that bypasses the keydown interception) must deliver its
  // text through term.paste() exactly once — never through the browser's
  // default insertion into xterm's hidden textarea, which leaves a stale
  // value there and duplicates the next typed character.
  async function renderChat() {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    return container.querySelector(".phi-chat-xterm-host")!;
  }

  function textPasteEvent(text: string) {
    const paste = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(paste, "clipboardData", {
      value: {
        files: [],
        getData: (type: string) => (type === "text/plain" ? text : ""),
        items: [],
      },
    });
    return paste;
  }

  it("delivers a native text paste through term.paste exactly once (#52471)", async () => {
    const host = await renderChat();
    const pasteSpy = vi.spyOn(FakeTerminal.prototype, "paste");
    try {
      const paste = textPasteEvent("abc");
      await act(async () => {
        host.dispatchEvent(paste);
      });
      // Exactly one delivery, via the terminal paste path that resets the
      // hidden textarea — a paste of "abc" yields "abc", never a stale-value
      // double send of the last character on the next keystroke.
      expect(pasteSpy).toHaveBeenCalledTimes(1);
      expect(pasteSpy).toHaveBeenCalledWith("abc");
      expect(paste.defaultPrevented).toBe(true);
      expect(uploadChatImage).not.toHaveBeenCalled();
    } finally {
      pasteSpy.mockRestore();
    }
  });

  it("keeps the image-paste route working: image pastes upload instead of pasting text", async () => {
    const host = await renderChat();
    const pasteSpy = vi.spyOn(FakeTerminal.prototype, "paste");
    try {
      const paste = new Event("paste", { bubbles: true, cancelable: true });
      const file = new File([new Uint8Array([1, 2, 3])], "shot.png", {
        type: "image/png",
      });
      Object.defineProperty(paste, "clipboardData", {
        value: {
          files: [file],
          getData: () => "",
          items: [{ getAsFile: () => file, kind: "file", type: "image/png" }],
        },
      });
      await act(async () => {
        host.dispatchEvent(paste);
      });
      await vi.waitFor(() => expect(uploadChatImage).toHaveBeenCalledTimes(1));
      expect(pasteSpy).not.toHaveBeenCalled();
      expect(paste.defaultPrevented).toBe(true);
    } finally {
      pasteSpy.mockRestore();
    }
  });

  it("reconnects on tab return after a hidden-tab close even when a stale upload banner is showing", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const socket = FakeWebSocket.instances[0];
    await act(async () => socket.onopen?.());

    // A failed image paste leaves a non-rejection banner behind.
    uploadChatImage.mockRejectedValueOnce(new Error("disk full"));
    const host = container.querySelector(".phi-chat-xterm-host");
    expect(host).not.toBeNull();
    const paste = new Event("paste", { bubbles: true, cancelable: true });
    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    Object.defineProperty(paste, "clipboardData", {
      value: {
        files: [file],
        items: [{ getAsFile: () => file, kind: "file", type: "image/png" }],
      },
    });
    await act(async () => {
      host!.dispatchEvent(paste);
    });
    await vi.waitFor(() =>
      expect(container.textContent).toContain("Image upload failed"),
    );

    // The socket dies while the tab is hidden: the reconnect is deferred.
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    await act(async () => {
      socket.onclose?.({ code: 1001, reason: "", wasClean: true });
    });
    expect(FakeWebSocket.instances).toHaveLength(1);

    // Coming back must start the deferred reconnect despite the old banner.
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
  });

  it("treats loopback 4401 closes as stale-token reload candidates", async () => {
    const { default: ChatPage } = await import("./ChatPage");

    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    FakeWebSocket.instances[0].onclose?.({
      code: 4401,
      reason: "auth: token_mismatch",
      wasClean: true,
    });

    expect(maybeReloadForLoopbackWsAuthFailure).toHaveBeenCalledWith(4401);
  });

  it("offers a Reload button for an expired login when auto-reload is spent", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    await act(async () => {
      FakeWebSocket.instances[0].onclose?.({ code: 4401, reason: "auth: bad-token", wasClean: true });
    });

    const labels = Array.from(container.querySelectorAll("button")).map((b) => b.textContent?.trim());
    expect(labels).toContain("Reload page");
  });

  it("renders Start new session after the server could not start the chat (1011)", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    await act(async () => {
      FakeWebSocket.instances[0].onclose?.({ code: 1011, reason: "", wasClean: true });
    });

    const labels = Array.from(container.querySelectorAll("button")).map((b) => b.textContent?.trim());
    expect(labels).toContain("Start new session");
  });

  it("offers Start new session and Open logs when the agent process ended", async () => {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    await act(async () => {
      FakeWebSocket.instances[0].onclose?.({ code: 4410, reason: "", wasClean: true });
    });

    const labels = Array.from(container.querySelectorAll("button")).map((b) => b.textContent?.trim());
    expect(labels).toContain("Start new session");
    expect(labels).toContain("Open logs");
  });

  it("stops retrying after the ladder is spent and offers Check server status", async () => {
    vi.useFakeTimers();
    try {
      const { default: ChatPage } = await import("./ChatPage");
      await render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive />
        </MemoryRouter>,
      );
      await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

      // Drop the socket abnormally; walk every scheduled retry to failure.
      for (let attempt = 0; attempt <= PTY_RECONNECT_MAX_ATTEMPTS; attempt += 1) {
        const sockets = FakeWebSocket.instances.length;
        await act(async () => {
          FakeWebSocket.instances[sockets - 1].onclose?.({ code: 1006, reason: "", wasClean: false });
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(PTY_RECONNECT_MAX_MS + 100);
        });
      }

      const labels = Array.from(container.querySelectorAll("button")).map((b) => b.textContent?.trim());
      expect(labels).toContain("Reconnect now");
      expect(labels).toContain("Check server status");
    } finally {
      vi.useRealTimers();
    }
  });

  it("redials after a clean 1012 service-restart close (#95951)", async () => {
    const { default: ChatPage } = await import("./ChatPage");

    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    // 1012 is a CLEAN close (wasClean=true) that is neither 1001 nor 1006 —
    // the old guard fell through to "[session ended]" with no retry. The
    // server is coming back, so the pane must redial: the 250ms first-attempt
    // backoff re-runs the connect effect and opens a fresh socket.
    FakeWebSocket.instances[0].onclose?.({
      code: 1012,
      reason: "",
      wasClean: true,
    });

    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2), {
      timeout: 3000,
    });
  });

  it("attaches visualViewport keyboard-inset listeners only while the chat tab is active", async () => {
    // NS-434 follow-up: ChatPage stays mounted (hidden) on every dashboard
    // route. The keyboard-inset/scroll-pin listeners must only be live while
    // /chat is the active tab, or the scroll pin fires when a soft keyboard
    // opens on Settings etc.
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    Object.defineProperty(window, "visualViewport", {
      configurable: true,
      value: { addEventListener, removeEventListener, width: 1280 },
    });

    const { default: ChatPage } = await import("./ChatPage");

    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive={false} />
      </MemoryRouter>,
    );
    expect(addEventListener).not.toHaveBeenCalled();

    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive />
        </MemoryRouter>,
      ),
    );
    expect(addEventListener.mock.calls.map((c) => c[0]).sort()).toEqual([
      "resize",
      "scroll",
    ]);
    expect(removeEventListener).not.toHaveBeenCalled();

    await act(async () =>
      root.render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive={false} />
        </MemoryRouter>,
      ),
    );
    expect(removeEventListener.mock.calls.map((c) => c[0]).sort()).toEqual([
      "resize",
      "scroll",
    ]);
  });
});

describe("ChatPage chat column", () => {
  async function renderChat(entry: string) {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={[entry]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
  }

  beforeEach(() => {
    for (const mock of Object.values(workspaceMocks)) mock.mockReset();
    sidebarProps.current = null;
  });

  it("shows the model card in the chat column, with no copy-last button or side panel", async () => {
    await renderChat("/chat");
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    const cards = container.querySelectorAll('[data-testid="chat-model-card"]');
    expect(cards).toHaveLength(1);
    expect(
      container.querySelector('[data-testid="chat-footer"]')?.contains(cards[0]),
    ).toBe(true);
    expect(
      container.querySelector('[aria-label="Copy last assistant response"]'),
    ).toBeNull();
    expect(container.querySelector("#chat-side-panel")).toBeNull();
    expect(
      container.querySelector('[aria-label="Collapse chat side panel"]'),
    ).toBeNull();
  });

  it("reloads the room's listing on a title event so the room list and header show its new name", async () => {
    const ROOM = "0123456789abcdef";
    workspaceMocks.getSettings.mockResolvedValue({ max_space_depth: 2 });
    workspaceMocks.getTree.mockResolvedValue({
      spaces: [{ room_id: "!space-a", name: "Travel", children: [], rooms: [ROOM] }],
      home: [],
    });
    let name = "New chat";
    workspaceMocks.getRooms.mockImplementation(async () => ({
      rooms: [{ room_id: ROOM, type: "room", name }],
    }));
    const { WorkspaceShellProvider } = await import("@/components/shell/WorkspaceShellContext");
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={[`/chat?room=${ROOM}`]}>
        <WorkspaceShellProvider>
          <ChatPage isActive />
        </WorkspaceShellProvider>
      </MemoryRouter>,
    );
    const heading = () => container.querySelector('[data-testid="chat-header"] h1')?.textContent;
    await vi.waitFor(() => expect(heading()).toBe("New chat"));
    await vi.waitFor(() =>
      expect(container.querySelector('[data-testid="chat-breadcrumb"]')?.textContent).toContain("Travel"),
    );
    const before = workspaceMocks.getRooms.mock.calls.length;

    name = "Plan the trip";
    await act(async () => sidebarProps.current?.onSessionTitleChange?.("Plan the trip"));
    await vi.waitFor(() => expect(heading()).toBe("Plan the trip"));
    expect(workspaceMocks.getRooms.mock.calls.length).toBe(before + 1);
    expect(workspaceMocks.getRooms).toHaveBeenLastCalledWith("!space-a");
  });

  it("leaves the room list alone on a title event outside a room", async () => {
    workspaceMocks.getSettings.mockResolvedValue({ max_space_depth: 2 });
    workspaceMocks.getTree.mockResolvedValue({ spaces: [], home: [] });
    workspaceMocks.getRooms.mockResolvedValue({ rooms: [] });
    const { WorkspaceShellProvider } = await import("@/components/shell/WorkspaceShellContext");
    const { default: ChatPage } = await import("./ChatPage");
    // A plain /chat is the agent DM; a resumed session is the one chat outside a room.
    await render(
      <MemoryRouter initialEntries={["/chat?resume=sess-1"]}>
        <WorkspaceShellProvider>
          <ChatPage isActive />
        </WorkspaceShellProvider>
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(workspaceMocks.getTree).toHaveBeenCalled());
    await act(async () => sidebarProps.current?.onSessionTitleChange?.("Plan the trip"));
    expect(sidebarProps.current?.onSessionTitleChange).toBeTypeOf("function");
    expect(workspaceMocks.getRooms).not.toHaveBeenCalled();
  });

  function LocationProbe() {
    const loc = useLocation();
    return <output data-testid="location">{loc.pathname + loc.search}</output>;
  }

  async function renderInShell(entry: string) {
    workspaceMocks.getSettings.mockResolvedValue({ max_space_depth: 2 });
    workspaceMocks.getTree.mockResolvedValue({ spaces: [], home: ["!local_agent"] });
    workspaceMocks.getRooms.mockResolvedValue({ rooms: [] });
    const { WorkspaceShellProvider } = await import("@/components/shell/WorkspaceShellContext");
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={[entry]}>
        <WorkspaceShellProvider>
          <ChatPage isActive />
        </WorkspaceShellProvider>
        <LocationProbe />
      </MemoryRouter>,
    );
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    for (let i = 0; i < 3; i++) await act(async () => {});
  }
  const location = () => container.querySelector('[data-testid="location"]')?.textContent;
  const ptyParams = (call: number) => (apiMocks.buildWsUrl.mock.calls[call] as unknown[])[1] as Record<string, string>;

  it("opens the agent DM when /chat has no room: on the first connect, not after a reconnect", async () => {
    await renderInShell("/chat");
    // The very first PTY already runs in the agent room; the URL catches up without a second socket.
    expect(ptyParams(0).room_id).toBe("!local_agent");
    const url = new URL(location() ?? "", "http://localhost");
    expect(url.pathname).toBe("/chat");
    expect(url.searchParams.get("room")).toBe("!local_agent");
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(apiMocks.buildWsUrl).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="chat-header"] h1')?.textContent).toBe(enShell.agentDm);
  });

  it("keeps a resumed session out of the agent DM and names it in the room header", async () => {
    apiMocks.getSessionDetail.mockResolvedValueOnce({ title: "Plan the trip" });
    await renderInShell("/chat?resume=sess-1");
    expect(ptyParams(0).room_id).toBeUndefined();
    expect(ptyParams(0).resume).toBe("sess-1");
    expect(location()).toBe("/chat?resume=sess-1");
    // /chat has no page title bar any more, so the session title shows in column 3's header.
    await vi.waitFor(() =>
      expect(container.querySelector('[data-testid="chat-header"] h1')?.textContent).toBe("Plan the trip"),
    );
  });
});

// The gated-mode ticket request runs before any socket exists, so a rejection
// or a hang emits no `close` event and never arms PTY_CONNECTING_TIMEOUT_MS
// (that timer is set after `new WebSocket`). Without its own deadline the tab
// strands on "connecting" with no retry. Mirrors the ChatSidebar events-feed
// coverage in src/components/ChatSidebar.test.tsx.
describe("ChatPage bundled font swap-in", () => {
  it("redraws the terminal with the bundled font once it finishes loading", async () => {
    let releaseFont!: () => void;
    const fontGate = new Promise<void>((resolve) => {
      releaseFont = resolve;
    });
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: {
        check: () => false,
        load: async () => {
          await fontGate;
          return [{}];
        },
      },
    });
    const clearAtlas = vi.spyOn(FakeTerminal.prototype, "clearTextureAtlas");
    try {
      const { default: ChatPage } = await import("./ChatPage");
      await render(
        <MemoryRouter initialEntries={["/chat"]}>
          <ChatPage isActive />
        </MemoryRouter>,
      );
      expect(clearAtlas).not.toHaveBeenCalled();

      await act(async () => {
        releaseFont();
        await fontGate;
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      expect(clearAtlas).toHaveBeenCalledTimes(1);
    } finally {
      clearAtlas.mockRestore();
      delete (document as { fonts?: unknown }).fonts;
    }
  });
});

describe("ChatPage PTY ticket connect deadline", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  async function renderChat() {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
  }

  /** Advance timers and flush the async connect that fires on the tick. */
  async function advance(ms: number) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("retries when the ticket request rejects", async () => {
    apiMocks.buildWsUrl.mockRejectedValueOnce(
      new Error("ticket endpoint unavailable"),
    );

    await renderChat();
    await advance(0);
    expect(FakeWebSocket.instances).toHaveLength(0);

    // First backoff step is 250ms; the retry must mint a fresh ticket.
    await advance(250);
    expect(apiMocks.buildWsUrl).toHaveBeenCalledTimes(2);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("times out a stalled ticket request and retries", async () => {
    let resolveStalledRequest!: (url: string) => void;
    apiMocks.buildWsUrl.mockImplementationOnce(
      () =>
        new Promise<string>((resolve) => {
          resolveStalledRequest = resolve;
        }),
    );

    await renderChat();
    await advance(0);
    expect(FakeWebSocket.instances).toHaveLength(0);

    await advance(PTY_TICKET_TIMEOUT_MS);
    expect(FakeWebSocket.instances).toHaveLength(0);

    // A late ticket from the timed-out attempt must not open a socket behind
    // the replacement the deadline scheduled.
    await act(async () => {
      resolveStalledRequest("ws://localhost/api/pty?channel=stale");
      await Promise.resolve();
    });
    expect(FakeWebSocket.instances).toHaveLength(0);

    await advance(250);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].url).not.toContain("channel=stale");
  });

  it("leaves a settled ticket's socket to the CONNECTING timer", async () => {
    await renderChat();
    await advance(0);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    // NS-591 regression: once the socket exists the ticket deadline is
    // disarmed, so PTY_CONNECTING_TIMEOUT_MS stays the only thing that may
    // force-close a wedged handshake — the two must not both fire.
    await advance(PTY_TICKET_TIMEOUT_MS);
    expect(apiMocks.buildWsUrl).toHaveBeenCalledTimes(1);
  });
});

// xterm WebGL renderer gating (#18773 / #45520 / #58685): the addon must only
// load when the host can actually use it (wide layout, non-Safari, hardware GL)
// and must be dropped when shaped-script text arrives.
describe("ChatPage WebGL renderer gating", () => {
  const CHROME_UA =
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
  const SAFARI_UA =
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15";

  /** Stub the probe's canvas context per test. */
  function stubCanvasContext(
    getContext: () => WebGLRenderingContext | null,
  ): void {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(
      getContext as never,
    );
  }

  function hardwareGl(): WebGLRenderingContext | null {
    return {
      getExtension: (name: string) => {
        if (name === "WEBGL_debug_renderer_info") {
          return { UNMASKED_RENDERER_WEBGL: 0x9246 };
        }
        if (name === "WEBGL_lose_context") {
          return { loseContext: () => undefined };
        }
        return null;
      },
      getParameter: () => "Apple M2",
    } as unknown as WebGLRenderingContext;
  }

  async function renderChat() {
    const { default: ChatPage } = await import("./ChatPage");
    await render(
      <MemoryRouter initialEntries={["/chat"]}>
        <ChatPage isActive />
      </MemoryRouter>,
    );
    await act(async () => {
      await Promise.resolve();
    });
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // PHI keeps xterm's DOM renderer (wide-screen WebGL rendered blank, PHI 6d4ce225).
  it.skip("loads the WebGL addon on a wide hardware-GL Chrome host", async () => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: CHROME_UA,
      writable: true,
    });
    stubCanvasContext(hardwareGl);

    await renderChat();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(webglInstances).toHaveLength(1);
    expect(webglInstances[0].disposed).toBe(false);
  });

  it("skips the WebGL addon on Safari (#18773)", async () => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: SAFARI_UA,
      writable: true,
    });
    stubCanvasContext(hardwareGl);

    await renderChat();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(webglInstances).toHaveLength(0);
  });

  it("skips the WebGL addon when no WebGL context exists (#45520)", async () => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: CHROME_UA,
      writable: true,
    });
    stubCanvasContext(() => null);

    await renderChat();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(webglInstances).toHaveLength(0);
  });

  it("skips the WebGL addon on a software renderer like llvmpipe (#45520)", async () => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: CHROME_UA,
      writable: true,
    });
    stubCanvasContext(() =>
      ({
        ...hardwareGl(),
        getParameter: () => "llvmpipe (LLVM 21.1.8, 256 bits)",
      }) as unknown as WebGLRenderingContext,
    );

    await renderChat();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));

    expect(webglInstances).toHaveLength(0);
  });

  // PHI keeps xterm's DOM renderer (wide-screen WebGL rendered blank, PHI 6d4ce225).
  it.skip("disposes the WebGL addon when Bengali text arrives (#58685)", async () => {
    Object.defineProperty(window.navigator, "userAgent", {
      configurable: true,
      value: CHROME_UA,
      writable: true,
    });
    stubCanvasContext(hardwareGl);

    await renderChat();
    const socket = FakeWebSocket.instances[0];
    await act(async () => socket.onopen?.());
    expect(webglInstances).toHaveLength(1);
    expect(webglInstances[0].disposed).toBe(false);

    await act(async () => {
      socket.onmessage?.({ data: "যুক্তাক্ষর প্রযুক্তি" });
    });

    expect(webglInstances[0].disposed).toBe(true);
  });
});

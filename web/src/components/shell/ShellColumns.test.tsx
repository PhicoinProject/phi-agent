// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { enShell } from "@/i18n/en";
import { CollapseToggle, ROOM_COLUMN_WIDTH_KEY, ShellColumns } from "./ShellColumns";
import type { NavItem } from "./SettingsColumn";
import { WorkspaceShellProvider } from "./WorkspaceShellContext";

const api = vi.hoisted(() => ({
  getTree: vi.fn(),
  getRooms: vi.fn(),
  getSettings: vi.fn(),
}));

vi.mock("@/lib/api-workspace", () => ({ AGENT_ROOM_ID: "!local_agent", workspaceApi: api }));
vi.mock("@phi/ui/ui/components/dialog", () => {
  const Box = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    Dialog: ({ children, open }: { children?: ReactNode; open?: boolean }) =>
      open ? <div role="dialog">{children}</div> : null,
    DialogContent: Box,
    DialogDescription: ({ children }: { children?: ReactNode }) => <p>{children}</p>,
    DialogFooter: Box,
    DialogHeader: Box,
    DialogTitle: ({ children }: { children?: ReactNode }) => <h2>{children}</h2>,
  };
});
vi.mock("@phi/ui/ui/components/toast", () => ({ Toast: () => null }));
vi.mock("@phi/ui/ui/components/confirm-dialog", () => ({ ConfirmDialog: () => null }));
vi.mock("@phi/ui/ui/components/spinner", () => ({ Spinner: () => null }));
// The settings column's widgets talk to the backend; only its nav is under test.
vi.mock("@/components/AuthWidget", () => ({ AuthWidget: () => null }));
vi.mock("@/components/LanguageSwitcher", () => ({ LanguageSwitcher: () => null }));
vi.mock("@/components/ProfileSwitcher", () => ({ ProfileSwitcher: () => null }));
vi.mock("@/components/SidebarFooter", () => ({ SidebarFooter: () => null }));
vi.mock("@/components/ThemeSwitcher", () => ({ ThemeSwitcher: () => null }));
vi.mock("@/components/SidebarStatusStrip", () => ({
  SidebarStatusStrip: () => null,
  gatewayLine: () => ({ label: "", tone: "" }),
}));
vi.mock("@/plugins", () => ({ PluginSlot: () => null }));
vi.mock("@/contexts/useSystemActions", () => ({
  useSystemActions: () => ({ activeAction: null, isBusy: false, isRunning: false, pendingAction: null, runAction: vi.fn() }),
}));

const Icon = () => null;
// A slice of the dashboard's built-in nav, as App passes it in.
const NAV = {
  coreItems: [
    { path: "/chat", label: "Chat", icon: Icon },
    { path: "/sessions", label: "Sessions", icon: Icon },
    { path: "/logs", label: "Logs", icon: Icon },
    { path: "/config", label: "Config", icon: Icon },
  ] satisfies NavItem[],
  pluginItems: [] as NavItem[],
};

let container: HTMLDivElement;
let root: Root;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function click(el: Element | null | undefined) {
  expect(el).toBeTruthy();
  await act(async () => {
    el!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await flush();
}

async function mount(node: ReactNode, path = "/chat") {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <WorkspaceShellProvider>{node}</WorkspaceShellProvider>
      </MemoryRouter>,
    );
  });
  await flush();
}

async function renderColumns(path: string, isMobile: boolean, collapsed = false) {
  await mount(
    <ShellColumns isMobile={isMobile} collapsed={collapsed} nav={NAV} status={null} onNavigate={() => {}} />,
    path,
  );
}

const q = (testId: string) => container.querySelector<HTMLElement>(`[data-testid="${testId}"]`);
const hrefs = (scope: Element | null) =>
  Array.from(scope?.querySelectorAll("a[href]") ?? []).map((a) => a.getAttribute("href"));

describe("ShellColumns", () => {
  it("column 1 has no toggle row in either width; the toggle is one bare button for the sidebar header row", async () => {
    for (const collapsed of [false, true]) {
      await renderColumns("/chat", false, collapsed);
      expect(q("space-bar")?.firstElementChild?.tagName, `collapsed=${collapsed}`).toBe("UL");
      expect(q("sidebar-collapse")).toBeNull();
      act(() => root.unmount());
      container.remove();
    }

    const onToggle = vi.fn();
    await mount(
      <div data-testid="header-row">
        <CollapseToggle collapsed={false} onToggle={onToggle} />
      </div>,
    );
    const row = q("header-row")!;
    expect(row.children).toHaveLength(1);
    const toggle = row.firstElementChild as HTMLButtonElement;
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle.getAttribute("aria-label")).toBe(enShell.collapse);
    // Desktop only (the phone drawer never collapses), pushed to the right of the title.
    expect(toggle.classList.contains("hidden")).toBe(true);
    expect(toggle.classList.contains("lg:grid")).toBe(true);
    expect(toggle.classList.contains("ml-auto")).toBe(true);
    await click(toggle);
    expect(onToggle).toHaveBeenCalledTimes(1);
    act(() => root.unmount());
    container.remove();

    await mount(<CollapseToggle collapsed onToggle={onToggle} />);
    expect(q("sidebar-collapse")?.getAttribute("aria-label")).toBe(enShell.expand);
  });

  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getTree.mockResolvedValue({ spaces: [], home: ["!room-h", "!local_agent"] });
    api.getSettings.mockResolvedValue({ max_space_depth: 2 });
    api.getRooms.mockResolvedValue({ rooms: [] });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("shows the dashboard nav in column 2 on settings pages", async () => {
    await renderColumns("/sessions", false);
    expect(q("space-bar")).not.toBeNull();
    expect(q("room-list")).toBeNull();
    const settings = q("settings-column");
    expect(settings).not.toBeNull();
    expect(hrefs(settings)).toEqual(expect.arrayContaining(["/sessions", "/logs", "/config"]));
    // Chat is the rooms view, reached from column 1; the settings nav does not list it.
    expect(hrefs(settings)).not.toContain("/chat");
    const shellGroup = settings!.querySelector(`[role="group"][aria-label="${enShell.settings}"]`);
    expect(hrefs(shellGroup)).toContain("/settings/workspace");
    // Column 1 stays the space bar: the old nav is not there.
    expect(hrefs(q("space-bar"))).toEqual([]);
  });

  it("shows the room list in column 2 on the chat page", async () => {
    await renderColumns("/chat", false);
    expect(q("room-list")).not.toBeNull();
    expect(q("settings-column")).toBeNull();
  });

  describe("column 2 width", () => {
    const store = new Map<string, string>();
    const separator = () => q("room-column")?.querySelector<HTMLElement>('[role="separator"]') ?? null;
    const drag = (type: string, x: number) => {
      const ev = new MouseEvent(type, { bubbles: true, cancelable: true, clientX: x, button: 0 });
      Object.defineProperty(ev, "pointerId", { value: 1 });
      act(() => void separator()!.dispatchEvent(ev));
    };

    beforeEach(() => {
      store.clear();
      vi.stubGlobal("localStorage", {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, String(v)),
        removeItem: (k: string) => void store.delete(k),
      });
      Object.defineProperty(window, "innerWidth", { configurable: true, value: 1600 });
    });

    afterEach(() => vi.unstubAllGlobals());

    it("is 288px with a labelled drag handle on its right edge, for rooms and settings alike", async () => {
      await renderColumns("/chat", false);
      expect(q("room-column")?.style.width).toBe("288px");
      expect(separator()?.getAttribute("aria-label")).toBe(enShell.resizeColumn);
      expect(separator()?.getAttribute("aria-valuemax")).toBe("560");
      act(() => root.unmount());
      container.remove();

      await renderColumns("/sessions", false);
      expect(q("room-column")?.querySelector('[data-testid="settings-column"]')).not.toBeNull();
      expect(separator()).not.toBeNull();
    });

    it("drags within 220..min(560px, 45vw) and restores the saved width", async () => {
      await renderColumns("/chat", false);
      drag("pointerdown", 300);
      drag("pointermove", 1300);
      expect(q("room-column")?.style.width).toBe("560px");
      drag("pointermove", 0);
      expect(q("room-column")?.style.width).toBe("220px");
      drag("pointermove", 350);
      drag("pointerup", 350);
      expect(q("room-column")?.style.width).toBe("338px");
      expect(store.get(ROOM_COLUMN_WIDTH_KEY)).toBe("338");
      act(() => root.unmount());
      container.remove();

      store.set(ROOM_COLUMN_WIDTH_KEY, "333");
      await renderColumns("/chat", false);
      expect(q("room-column")?.style.width).toBe("333px");
    });

    it("has no handle in the phone drawer", async () => {
      await renderColumns("/chat", true);
      expect(container.querySelector('[role="separator"]')).toBeNull();
    });
  });

  it("shows the space tree with rooms in the phone drawer, and settings with a way back", async () => {
    await renderColumns("/chat", true);
    expect(q("room-list")).toBeNull();
    expect(q("space-bar")?.querySelector('[data-room-id="!local_agent"]')).not.toBeNull();

    await click(q("space-bar")?.querySelector(`button[title="${enShell.settings}"]`));
    expect(q("space-bar")).toBeNull();
    expect(hrefs(q("settings-column"))).toContain("/logs");

    await click(q("settings-column")?.querySelector(`button[aria-label="${enShell.backToRooms}"]`));
    expect(q("settings-column")).toBeNull();
    expect(q("space-bar")).not.toBeNull();
  });
});

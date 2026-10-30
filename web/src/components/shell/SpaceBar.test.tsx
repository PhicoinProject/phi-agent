// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { enShell } from "@/i18n/en";
import { SpaceBar } from "./SpaceBar";
import { fmt } from "./use-shell-strings";
import { WorkspaceShellProvider } from "./WorkspaceShellContext";

const api = vi.hoisted(() => ({
  getTree: vi.fn(),
  getRooms: vi.fn(),
  getSettings: vi.fn(),
  move: vi.fn(),
  createSpace: vi.fn(),
  newChat: vi.fn(),
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
vi.mock("@phi/ui/ui/components/toast", () => ({
  Toast: ({ toast }: { toast: { message: string; type: string } | null }) =>
    toast ? (
      <div role="status" data-type={toast.type}>
        {toast.message}
      </div>
    ) : null,
}));
vi.mock("@phi/ui/ui/components/select", () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children?: ReactNode;
    onValueChange?: (value: string) => void;
    value?: string;
  }) => (
    <select value={value} onChange={(e) => onValueChange?.(e.currentTarget.value)}>
      {children}
    </select>
  ),
  SelectOption: ({ children, value }: { children?: ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}));

const TREE = {
  spaces: [
    {
      room_id: "!space-a",
      name: "Projects",
      rooms: ["!room-a"],
      children: [{ room_id: "!space-b", name: "Hardware", rooms: ["!room-b"], children: [] }],
    },
  ],
  home: ["!room-h", "!local_agent"],
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

function Location() {
  const { pathname, search } = useLocation();
  return <output data-testid="location">{pathname + search}</output>;
}

async function renderBar(props: Parameters<typeof SpaceBar>[0] = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/chat"]}>
        <WorkspaceShellProvider>
          <SpaceBar {...props} />
          <Location />
        </WorkspaceShellProvider>
      </MemoryRouter>,
    );
  });
  await flush();
}

const bar = () => container.querySelector('[data-testid="space-bar"]')!;
const toast = () => container.querySelector('[role="status"]')?.textContent ?? null;
const ids = (els: Iterable<Element>, attr: string) => Array.from(els).map((el) => el.getAttribute(attr));
const expand = (spaceId: string) =>
  click(bar().querySelector(`[data-space-id="${spaceId}"] button[aria-label="${enShell.expand}"]`));

// A sub-space B under A, plus two plain top-level spaces C and D.
const DND_TREE = {
  spaces: [
    {
      room_id: "!space-a",
      name: "Projects",
      rooms: [],
      children: [{ room_id: "!space-b", name: "Hardware", rooms: [], children: [] }],
    },
    { room_id: "!space-c", name: "Clients", rooms: [], children: [] },
    { room_id: "!space-d", name: "Drafts", rooms: [], children: [] },
  ],
  home: [],
};

// jsdom has no DataTransfer: one store shared by dragstart and drop, as a browser does.
function fakeTransfer() {
  const data = new Map<string, string>();
  return {
    get types() {
      return [...data.keys()];
    },
    getData: (type: string) => data.get(type) ?? "",
    setData: (type: string, value: string) => void data.set(type, value),
    dropEffect: "none",
    effectAllowed: "all",
  };
}

function fireDrag(el: Element, type: string, dataTransfer: ReturnType<typeof fakeTransfer>) {
  const ev = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperty(ev, "dataTransfer", { value: dataTransfer });
  el.dispatchEvent(ev);
  return ev;
}

const spaceRow = (id: string) => bar().querySelector(`[data-space-id="${id}"] > div`)!;
const homeRow = () => bar().querySelector(`button[title="${enShell.home}"]`)!;

/** Drag space row `from` and drop it on `target`; returns whether the target showed the ring. */
async function dragSpace(from: string, target: Element) {
  const dt = fakeTransfer();
  let ring = false;
  await act(async () => {
    fireDrag(spaceRow(from), "dragstart", dt);
  });
  await act(async () => {
    fireDrag(target, "dragover", dt);
  });
  ring = target.classList.contains("ring-2");
  await act(async () => {
    fireDrag(target, "drop", dt);
  });
  await flush();
  return ring;
}

async function typeName(value: string) {
  const input = container.querySelector<HTMLInputElement>(`[role="dialog"] input[aria-label="${enShell.spaceName}"]`)!;
  expect(input).toBeTruthy();
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function chooseParent(value: string) {
  const select = container.querySelector<HTMLSelectElement>('[role="dialog"] select')!;
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

const dialogButton = (label: string) =>
  Array.from(container.querySelectorAll('[role="dialog"] button')).find((b) => b.textContent === label);

describe("SpaceBar", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getTree.mockResolvedValue(TREE);
    api.getSettings.mockResolvedValue({ max_space_depth: 3 });
    api.getRooms.mockResolvedValue({ rooms: [{ room_id: "!room-a", type: "room", name: "Room A" }] });
  });

  afterEach(() => {
    vi.useRealTimers();
    act(() => root.unmount());
    container.remove();
  });

  it("renders the space tree without rooms on desktop", async () => {
    await renderBar();
    expect(ids(bar().querySelectorAll("[data-space-id]"), "data-space-id")).toEqual(["!space-a"]);
    await expand("!space-a");
    expect(ids(bar().querySelectorAll("[data-space-id]"), "data-space-id")).toEqual(["!space-a", "!space-b"]);
    expect(bar().querySelectorAll("[data-room-id]")).toHaveLength(0);
    expect(api.getRooms).not.toHaveBeenCalled();
  });

  it("has no profile chip (the profile is chosen in Settings)", async () => {
    await renderBar();
    expect(bar().querySelector('span[title="default"]')).toBeNull();
    expect(bar().textContent).not.toContain("default");
  });

  it("has no collapse-toggle row: the tree starts at the top (App's sidebar header holds the toggle)", async () => {
    for (const collapsed of [false, true]) {
      await renderBar({ collapsed });
      expect(bar().firstElementChild?.tagName, `collapsed=${collapsed}`).toBe("UL");
      expect(bar().querySelector('[data-testid="sidebar-collapse"]')).toBeNull();
      // Space chevrons share the Collapse/Expand labels; none sits outside the tree.
      for (const b of bar().querySelectorAll(`button[aria-label="${enShell.collapse}"], button[aria-label="${enShell.expand}"]`)) {
        expect(b.closest("[data-space-id]"), "only space chevrons").toBeTruthy();
      }
      act(() => root.unmount());
      container.remove();
    }
    await renderBar();
  });

  it("collapsed: every entry is the same centred square, highlight included", async () => {
    await renderBar({ collapsed: true });
    const cells = {
      home: bar().querySelector(`button[title="${enShell.home}"]`),
      space: bar().querySelector('button[title="Projects"]'),
      create: bar().querySelector(`button[title="${enShell.createSpace}"]`),
      settings: bar().querySelector(`button[title="${enShell.settings}"]`),
    };
    for (const [name, el] of Object.entries(cells)) {
      expect(el, name).toBeTruthy();
      for (const token of ["mx-auto", "h-9", "w-9", "justify-center"]) {
        expect(el!.classList.contains(token), `${name} has ${token}`).toBe(true);
      }
      expect(el!.classList.contains("w-full"), `${name} is not a full-width bar`).toBe(false);
    }
    // Home is active by default: the square itself carries the highlight.
    expect(cells.home!.classList.contains("phi-nav-selected")).toBe(true);

    await click(cells.space);
    const space = bar().querySelector('button[title="Projects"]')!;
    expect(space.classList.contains("phi-nav-selected")).toBe(true);
    expect(space.parentElement!.classList.contains("phi-nav-selected")).toBe(false);
    expect(bar().querySelector(`button[title="${enShell.home}"]`)!.classList.contains("phi-nav-selected")).toBe(false);
  });

  it("Settings lights up only once clicked; Home is the default selection", async () => {
    await renderBar();
    const settings = () => bar().querySelector(`button[title="${enShell.settings}"]`)!;
    expect(homeRow().classList.contains("phi-nav-selected")).toBe(true);
    expect(settings().classList.contains("phi-nav-selected")).toBe(false);
    expect(settings().getAttribute("aria-current")).toBeNull();
    await click(settings());
    expect(settings().classList.contains("phi-nav-selected")).toBe(true);
    expect(settings().getAttribute("aria-current")).toBe("true");
    expect(homeRow().classList.contains("phi-nav-selected")).toBe(false);
  });

  it("expanded: Home, space chevrons, + and Settings share one icon slot and one label column", async () => {
    await renderBar();
    await expand("!space-a");
    const slots = {
      home: bar().querySelector(`button[title="${enShell.home}"] > span`),
      space: spaceRow("!space-a").querySelector("button[aria-expanded]"),
      create: bar().querySelector(`button[title="${enShell.createSpace}"] > span`),
      settings: bar().querySelector(`button[title="${enShell.settings}"] > span`),
    };
    for (const [name, el] of Object.entries(slots)) {
      expect(el, name).toBeTruthy();
      // A 32px slot, first in its row, 12px in (4px list inset + 8px row padding): icon centre x=28
      // (the collapsed CELL's centre in the 56px column), label at 12 + 32 + gap-2 = 52.
      for (const token of ["w-8", "shrink-0", "justify-center"]) {
        expect(el!.classList.contains(token), `${name} slot has ${token}`).toBe(true);
      }
      expect(el!.previousElementSibling, `${name} slot comes first`).toBeNull();
      const row = el!.parentElement!;
      const inset = row.classList.contains("px-2") || row.style.paddingLeft === "8px";
      expect(row.closest("ul, div.border-t")!.classList.contains("px-1"), `${name} list insets 4px`).toBe(true);
      expect(inset, `${name} row starts 12px in`).toBe(true);
      expect(row.classList.contains("gap-2"), `${name} row has gap-2`).toBe(true);
    }
    // The space name button adds no left padding of its own, so its label lands on the same column.
    const name = spaceRow("!space-a").querySelector('button[title="Projects"]')!;
    expect(name.classList.contains("pl-0")).toBe(true);
    // A sub-space is indented one 12px step.
    expect((spaceRow("!space-b") as HTMLElement).style.paddingLeft).toBe("20px");
  });

  describe("dragging spaces", () => {
    beforeEach(() => {
      api.getTree.mockResolvedValue(DND_TREE);
      api.move.mockResolvedValue({ room: {} });
    });

    it("moves a sub-space onto another space or Home, and a top-level space into another", async () => {
      await renderBar();
      await expand("!space-a");
      expect(spaceRow("!space-b").getAttribute("draggable")).toBe("true");

      expect(await dragSpace("!space-b", spaceRow("!space-c"))).toBe(true);
      expect(api.move).toHaveBeenLastCalledWith("!space-b", "!space-a", "!space-c");

      expect(await dragSpace("!space-b", homeRow())).toBe(true);
      expect(api.move).toHaveBeenLastCalledWith("!space-b", "!space-a", null);

      await dragSpace("!space-c", spaceRow("!space-d"));
      expect(api.move).toHaveBeenLastCalledWith("!space-c", null, "!space-d");
      expect(api.move).toHaveBeenCalledTimes(3);
      expect(toast()).toBeNull();
    });

    it("refuses a drop into the space itself, its descendant, or past the nesting limit", async () => {
      await renderBar();
      await expand("!space-a");

      await dragSpace("!space-a", spaceRow("!space-b"));
      expect(toast()).toBe(enShell.spaceDropCycle);

      // Projects has a sub-space: under Clients its rooms would be level 4 > 3.
      await dragSpace("!space-a", spaceRow("!space-c"));
      expect(toast()).toBe(fmt(enShell.spaceDropDepth, { depth: 3 }));

      // Onto itself or its current parent: nothing to do.
      await dragSpace("!space-b", spaceRow("!space-b"));
      await dragSpace("!space-b", spaceRow("!space-a"));
      await dragSpace("!space-c", homeRow());
      expect(api.move).not.toHaveBeenCalled();
    });

    it("shows the server's refusal and keeps the tree", async () => {
      api.move.mockRejectedValue(new Error("nesting limit is 3 levels counting the room"));
      await renderBar();
      await dragSpace("!space-c", spaceRow("!space-d"));
      expect(api.move).toHaveBeenCalledWith("!space-c", null, "!space-d");
      expect(toast()).toBe(fmt(enShell.moveFailed, { error: "nesting limit is 3 levels counting the room" }));
      expect(ids(bar().querySelectorAll("[data-space-id]"), "data-space-id")).toEqual([
        "!space-a",
        "!space-c",
        "!space-d",
      ]);
    });
  });

  it("create space: picks a parent among spaces that can take a child, top level by default", async () => {
    api.createSpace.mockResolvedValue({ space: { room_id: "!space-new", name: "Boards", type: "space" } });
    await renderBar();
    await click(bar().querySelector(`button[title="${enShell.createSpace}"]`));
    const select = container.querySelector<HTMLSelectElement>('[role="dialog"] select')!;
    expect(select).toBeTruthy();
    // Limit 3: Projects (level 1) can take a sub-space; Hardware (level 2) cannot.
    expect(Array.from(select.options).map((o) => [o.value, o.textContent])).toEqual([
      ["", enShell.topLevel],
      ["!space-a", "Projects"],
    ]);
    expect(select.value).toBe("");

    await typeName("Boards");
    await chooseParent("!space-a");
    await click(dialogButton(enShell.create));
    expect(api.createSpace).toHaveBeenLastCalledWith("Boards", "!space-a");
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    // Reopened, it is back to top level.
    await click(bar().querySelector(`button[title="${enShell.createSpace}"]`));
    expect(container.querySelector<HTMLSelectElement>('[role="dialog"] select')!.value).toBe("");
    await typeName("Loose");
    await click(dialogButton(enShell.create));
    expect(api.createSpace).toHaveBeenLastCalledWith("Loose", null);
  });

  describe("phone drawer", () => {
    it("lists Home's rooms with the agent DM first and each space's rooms", async () => {
      await renderBar({ showRooms: true });
      const homeRows = Array.from(bar().querySelectorAll("[data-room-id]")).filter((el) => !el.closest("[data-space-id]"));
      expect(ids(homeRows, "data-room-id")).toEqual(["!local_agent", "!room-h"]);
      expect(homeRows[0].textContent).toContain(enShell.agentDm);

      await click(bar().querySelector('button[title="Projects"]'));
      const space = bar().querySelector('[data-space-id="!space-a"]')!;
      expect(api.getRooms).toHaveBeenCalledWith("!space-a");
      // Hardware is listed but still collapsed, so only Projects' own room shows.
      expect(ids(space.querySelectorAll("[data-room-id]"), "data-room-id")).toEqual(["!room-a"]);
      expect(space.querySelector('[data-room-id="!room-a"]')?.textContent).toContain("Room A");
    });

    it("opens a tapped room and closes the drawer", async () => {
      const onNavigate = vi.fn();
      await renderBar({ showRooms: true, onNavigate });
      await click(bar().querySelector('[data-room-id="!local_agent"] button'));
      expect(container.querySelector('[data-testid="location"]')?.textContent).toBe("/chat?room=!local_agent");
      expect(onNavigate).toHaveBeenCalledTimes(1);
    });

    it("has New chat beside Create space in the drawer; one tap opens the new room and closes it", async () => {
      api.newChat.mockResolvedValue({ room_id: "0123456789abcdef", type: "room", name: enShell.newChat });
      const onNavigate = vi.fn();
      await renderBar({ showRooms: true, onNavigate });
      const newChat = bar().querySelector<HTMLElement>('[data-testid="drawer-new-chat"]')!;
      const create = bar().querySelector<HTMLElement>(`button[title="${enShell.createSpace}"]`)!;
      expect(newChat.parentElement).toBe(create.parentElement);
      expect(newChat.nextElementSibling).toBe(create);
      await click(newChat);
      expect(api.newChat).toHaveBeenCalledWith(null);
      expect(container.querySelector('[data-testid="location"]')?.textContent).toBe("/chat?room=0123456789abcdef");
      expect(onNavigate).toHaveBeenCalledTimes(1);
    });

    it("keeps New chat out of the desktop space column", async () => {
      await renderBar({});
      expect(bar().querySelector('[data-testid="drawer-new-chat"]')).toBeNull();
    });

    it("opens the room menu on long-press", async () => {
      await renderBar({ showRooms: true });
      vi.useFakeTimers();
      const row = bar().querySelector('[data-room-id="!room-h"]')!;
      await act(async () => {
        row.dispatchEvent(new Event("touchstart", { bubbles: true }));
      });
      expect(row.querySelector('[role="menu"]')).toBeNull();
      await act(async () => {
        vi.advanceTimersByTime(500);
      });
      expect(row.querySelector(`[role="menu"][aria-label="${enShell.roomMenu}"]`)).not.toBeNull();
    });
  });
});

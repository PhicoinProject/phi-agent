// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { enPanels, enShell } from "@/i18n/en";
import { RoomList } from "./RoomList";
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
  rename: vi.fn(),
  activity: vi.fn(),
  archive: vi.fn(),
  deleteSpace: vi.fn(),
  markSeen: vi.fn(),
  markAllSeen: vi.fn(),
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

// Projects (level 1) > Hardware (level 2); Home lists the agent DM after another room.
const tree = () => ({
  spaces: [
    {
      room_id: "!space-a",
      name: "Projects",
      rooms: ["!room-a"],
      children: [{ room_id: "!space-b", name: "Hardware", rooms: ["!room-b"], children: [] }],
    },
  ],
  home: ["!room-h", "!local_agent"],
});
const ROOMS = [
  { room_id: "!room-a", type: "room", name: "Room A" },
  { room_id: "!room-b", type: "room", name: "Room B" },
  { room_id: "!room-h", type: "room", name: "Room H" },
];

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

function LocationProbe() {
  const loc = useLocation();
  return <output data-testid="location">{loc.pathname + loc.search}</output>;
}

async function renderShell(maxDepth = 2, entry = "/chat") {
  api.getSettings.mockResolvedValue({ root: "/srv/placeholder_root", max_space_depth: maxDepth, default_fence: "approve" });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[entry]}>
        <WorkspaceShellProvider>
          <SpaceBar />
          <RoomList />
        </WorkspaceShellProvider>
        <LocationProbe />
      </MemoryRouter>,
    );
  });
  await flush();
}

const spaceBar = () => container.querySelector('[data-testid="space-bar"]')!;
const roomList = () => container.querySelector('[data-testid="room-list"]')!;
const rowIds = (scope: Element) =>
  Array.from(scope.querySelectorAll("[data-room-id]")).map((el) => el.getAttribute("data-room-id"));

async function selectSpace(name: string) {
  if (name === "Hardware") await click(spaceBar().querySelector(`[data-space-id="!space-a"] button[aria-label="${enShell.expand}"]`));
  await click(spaceBar().querySelector(`button[title="${name}"]`));
}

const location = () => container.querySelector('[data-testid="location"]')?.textContent;
const filterButton = (label: string) =>
  Array.from(roomList().querySelectorAll("button[aria-pressed]")).find((el) => el.textContent?.startsWith(label));

/** The space's "..." menu (Home has none). */
async function spaceMenuItems(): Promise<string[]> {
  await click(roomList().querySelector(`button[aria-label="${enShell.spaceMenu}"]`));
  const menu = roomList().querySelector(`[role="menu"][aria-label="${enShell.spaceMenu}"]`);
  expect(menu).toBeTruthy();
  return Array.from(menu!.querySelectorAll('[role="menuitem"]')).map((el) => el.textContent ?? "");
}

const newChatButton = () => roomList().querySelector('[data-testid="new-chat"]');

describe("RoomList", () => {
  beforeEach(() => {
    for (const fn of Object.values(api)) fn.mockReset();
    api.getTree.mockImplementation(async () => tree());
    api.getRooms.mockResolvedValue({ rooms: ROOMS });
    api.activity.mockResolvedValue({ rooms: {} });
    api.markSeen.mockResolvedValue({ room: null });
    api.markAllSeen.mockResolvedValue({ marked: 0 });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("opens a linked room inside its space, not Home", async () => {
    await renderShell(2, "/chat?room=!room-b");
    expect(roomList().getAttribute("aria-label")).toBe("Hardware");
    expect(rowIds(roomList())).toContain("!room-b");
  });

  it("keeps Home for a linked room that lives in Home", async () => {
    await renderShell(2, "/chat?room=!room-h");
    expect(rowIds(roomList())).toContain("!room-h");
    expect(rowIds(roomList())).not.toContain("!room-b");
  });

  it("lists the agent DM first in Home", async () => {
    await renderShell();
    expect(rowIds(roomList())).toEqual(["!local_agent", "!room-h"]);
    expect(roomList().querySelector('[data-room-id="!local_agent"]')?.textContent).toContain(enShell.agentDm);
  });

  it("hides New sub-space in the space menu at the depth limit", async () => {
    await renderShell(2);
    await selectSpace("Projects");
    const items = await spaceMenuItems();
    expect(items).toContain(enShell.addExistingRoom);
    expect(items).not.toContain(enShell.newSubSpace);
  });

  it("+ starts a chat at once; New chat gets the space's room once, lists it as New chat and opens it", async () => {
    const NEW = "0123456789abcdef";
    api.newChat.mockResolvedValue({ room_id: NEW, type: "room", name: enShell.newChat });
    api.getTree.mockImplementation(async () => {
      const t = tree();
      if (api.newChat.mock.calls.length) t.spaces[0].rooms.push(NEW);
      return t;
    });
    await renderShell(3);
    await selectSpace("Projects");
    const items = await spaceMenuItems();
    expect(items).toEqual([enShell.rename, enShell.addExistingRoom, enShell.newSubSpace, enShell.deleteSpace]);
    expect(items).not.toContain("New room");
    await click(roomList().querySelector(`button[aria-label="${enShell.spaceMenu}"]`));

    // "+" is one click: no menu in between.
    await click(newChatButton());
    expect(roomList().querySelector(`[role="menu"]`)).toBeNull();
    expect(api.newChat).toHaveBeenCalledTimes(1);
    expect(api.newChat).toHaveBeenCalledWith("!space-a");
    expect(location()).toBe(`/chat?room=${NEW}`);
    expect(roomList().querySelector(`[data-room-id="${NEW}"]`)?.textContent).toContain(enShell.newChat);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
  });

  it("stays put and says why when New chat cannot get a room", async () => {
    api.newChat.mockRejectedValue(new Error("unknown space"));
    await renderShell();
    await click(newChatButton());
    expect(api.newChat).toHaveBeenCalledWith(null);
    expect(location()).toBe("/chat");
    expect(container.querySelector('[role="status"]')?.textContent).toBe(
      fmt(enShell.newChatFailed, { error: "unknown space" }),
    );
  });

  it("hides New sub-space for a level-2 space when the limit is 3", async () => {
    await renderShell(3);
    await selectSpace("Hardware");
    expect(await spaceMenuItems()).not.toContain(enShell.newSubSpace);
  });

  it("offers New sub-space below the depth limit", async () => {
    await renderShell(3);
    await selectSpace("Projects");
    expect(await spaceMenuItems()).toContain(enShell.newSubSpace);
  });

  it("moves a room through its menu and rolls back when the API fails", async () => {
    let fail: (e: Error) => void = () => {};
    api.move.mockReturnValue(new Promise((_, reject) => (fail = reject)));
    await renderShell(3);
    await selectSpace("Projects");
    const inHardware = () => roomList().querySelector('[data-group-id="!space-b"] [data-room-id="!room-a"]');
    expect(inHardware()).toBeNull();

    const row = roomList().querySelector('[data-room-id="!room-a"]');
    await click(row?.querySelector(`button[aria-label="${enShell.roomMenu}"]`));
    const moveItem = Array.from(row!.querySelectorAll('[role="menuitem"][aria-haspopup]')).find(
      (el) => el.textContent?.includes(enShell.moveToSpace),
    );
    await click(moveItem);
    const targets = row!.querySelector(`[role="group"][aria-label="${enShell.moveToSpace}"]`);
    const toHardware = Array.from(targets?.querySelectorAll("button") ?? []).find(
      (el) => el.textContent === "Projects / Hardware",
    );
    await click(toHardware);

    expect(api.move).toHaveBeenCalledWith("!room-a", "!space-a", "!space-b");
    // Optimistic: shown in Hardware while the request is pending.
    expect(inHardware()).not.toBeNull();
    expect(rowIds(roomList()).filter((id) => id === "!room-a")).toHaveLength(1);

    await act(async () => fail(new Error("nesting limit reached")));
    await flush();

    expect(inHardware()).toBeNull();
    expect(rowIds(roomList())).toEqual(["!room-a", "!room-b"]);
    expect(container.querySelector('[role="status"]')?.textContent).toBe(
      fmt(enShell.moveFailed, { error: "nesting limit reached" }),
    );
    expect(api.getTree).toHaveBeenCalledTimes(1);
  });

  it("filters Running and Unread from the polled activity", async () => {
    api.activity.mockResolvedValue({ rooms: { "!room-h": { running: true }, "!local_agent": { unread: 2, running: false } } });
    await renderShell();
    expect(api.activity).toHaveBeenCalled();
    expect(roomList().querySelector('[data-testid="filter-count-running"]')?.textContent).toBe("1");
    expect(roomList().querySelector('[data-testid="filter-count-unread"]')?.textContent).toBe("1");

    await click(filterButton(enShell.filterRunning));
    expect(rowIds(roomList())).toEqual(["!room-h"]);
    await click(filterButton(enShell.filterUnread));
    expect(rowIds(roomList())).toEqual(["!local_agent"]);
    await click(filterButton(enShell.filterAll));
    expect(rowIds(roomList())).toEqual(["!local_agent", "!room-h"]);
  });

  it("clears a room's unread badge when it is opened, and counts new replies again", async () => {
    let unread = 3;
    api.activity.mockImplementation(async () => ({ rooms: { "!room-h": { unread, running: false } } }));
    api.markSeen.mockImplementation(async () => {
      unread = 0;
      return { room: null };
    });
    await renderShell();
    const badge = () => roomList().querySelector('[data-room-id="!room-h"] [data-testid="room-unread"]')?.textContent ?? null;
    expect(badge()).toBe("3");

    await click(roomList().querySelector('[data-room-id="!room-h"] button'));
    expect(location()).toBe("/chat?room=!room-h");
    expect(api.markSeen).toHaveBeenCalledWith("!room-h");
    expect(badge()).toBeNull();

    // A reply in another room still shows.
    api.activity.mockResolvedValue({ rooms: { "!local_agent": { unread: 1, running: false } } });
    await act(async () => document.dispatchEvent(new Event("visibilitychange")));
    await flush();
    expect(roomList().querySelector('[data-room-id="!local_agent"] [data-testid="room-unread"]')?.textContent).toBe("1");
  });

  it("marks every room as read in one click", async () => {
    let state: Record<string, { unread: number; running: boolean }> = {
      "!room-h": { unread: 2, running: false },
      "!local_agent": { unread: 5, running: false },
    };
    api.activity.mockImplementation(async () => ({ rooms: state }));
    api.markAllSeen.mockImplementation(async () => {
      state = {};
      return { marked: 2 };
    });
    await renderShell();
    expect(roomList().querySelectorAll('[data-testid="room-unread"]').length).toBe(2);
    await click(roomList().querySelector('[data-testid="mark-all-read"]'));
    expect(api.markAllSeen).toHaveBeenCalledTimes(1);
    expect(roomList().querySelectorAll('[data-testid="room-unread"]').length).toBe(0);
    expect(roomList().querySelector('[data-testid="mark-all-read"]')?.hasAttribute("disabled")).toBe(true);
  });

  it("keeps mark-all a plain ghost icon like + and …, muted rather than filled when disabled", async () => {
    await renderShell();
    const mark = roomList().querySelector<HTMLButtonElement>('[data-testid="mark-all-read"]')!;
    const plus = roomList().querySelector<HTMLButtonElement>('[data-testid="new-chat"]')!;
    expect(mark.disabled).toBe(true);
    // The base Button fills disabled buttons (bg-midground/15), which reads as a selected filter chip.
    const tokens = (el: HTMLElement) => el.className.split(/\s+/).filter(Boolean);
    expect(tokens(mark)).toContain("disabled:bg-transparent");
    expect(tokens(mark)).toContain("disabled:opacity-40");
    expect(tokens(mark)).not.toContain("disabled:bg-midground/15");
    // Enabled chrome is exactly the + button's (ghost, size icon); only layout and the disabled look differ.
    const chrome = (el: HTMLElement) =>
      tokens(el)
        .filter((c) => c !== "ml-auto" && !c.startsWith("disabled:"))
        .sort();
    expect(chrome(mark)).toEqual(chrome(plus));
  });

  it("archives a room from its menu and reloads the tree", async () => {
    api.archive.mockResolvedValue({ ok: true });
    await renderShell();
    const menuItems = async (id: string) => {
      const row = roomList().querySelector(`[data-room-id="${id}"]`);
      await click(row?.querySelector(`button[aria-label="${enShell.roomMenu}"]`));
      return Array.from(row!.querySelectorAll('[role="menuitem"]'));
    };
    // The agent DM cannot be archived.
    expect((await menuItems("!local_agent")).some((el) => el.textContent === enShell.archive)).toBe(false);
    await click(roomList().querySelector(`[data-room-id="!local_agent"] button[aria-label="${enShell.roomMenu}"]`));

    const archive = (await menuItems("!room-h")).find((el) => el.textContent === enShell.archive);
    expect(archive?.hasAttribute("disabled")).toBe(false);
    await click(archive);
    expect(api.archive).toHaveBeenCalledWith("!room-h");
    expect(api.getTree).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="status"]')?.textContent).toBe(fmt(enPanels.archived, { name: "Room H" }));
  });

  it("deletes a space from its menu after a confirm, then shows its parent (rooms move up, nothing on disk)", async () => {
    api.deleteSpace.mockResolvedValue({ deleted: "!space-a", moved_up: ["!room-p"], into: [] });
    await renderShell();
    await selectSpace("Projects");
    expect(await spaceMenuItems()).toContain(enShell.deleteSpace);
    await click(roomList().querySelector('[data-testid="delete-space"]'));
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog?.textContent).toContain(fmt(enShell.deleteSpaceTitle, { name: "Projects" }));
    expect(dialog?.textContent).toContain(enShell.deleteSpaceBody);
    expect(api.deleteSpace).not.toHaveBeenCalled();
    await click(dialog!.querySelector("[data-confirm]"));
    expect(api.deleteSpace).toHaveBeenCalledWith("!space-a");
    expect(api.getTree).toHaveBeenCalledTimes(2);
    expect(container.querySelector('[role="status"]')?.textContent).toBe(fmt(enShell.deleteSpaceDone, { name: "Projects" }));
    expect(roomList().querySelector("h2")?.textContent).toBe(enShell.home);
  });

  it("keeps the space and says why when the delete is refused", async () => {
    api.deleteSpace.mockRejectedValue(new Error("This space mirrors a Matrix space."));
    await renderShell();
    await selectSpace("Projects");
    await spaceMenuItems();
    await click(roomList().querySelector('[data-testid="delete-space"]'));
    await click(document.querySelector('[role="dialog"] [data-confirm]'));
    expect(container.querySelector('[role="status"]')?.textContent).toBe(
      fmt(enShell.deleteSpaceFailed, { error: "This space mirrors a Matrix space." }),
    );
    expect(roomList().querySelector("h2")?.textContent).toBe("Projects");
  });
});

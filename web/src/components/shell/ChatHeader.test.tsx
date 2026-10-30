// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { registerComposer } from "@/components/voice/composer-bridge";
import { enShell } from "@/i18n/en";
import { api as filesApi } from "@/lib/api";
import { ApiError } from "@/lib/api-error";
import { ChatHeader, type ChatModelEntry } from "./ChatHeader";
import { WorkspaceShellProvider } from "./WorkspaceShellContext";

const api = vi.hoisted(() => ({
  getTree: vi.fn(),
  getRooms: vi.fn(),
  getSettings: vi.fn(),
}));
vi.mock("@/lib/api-workspace", () => ({ AGENT_ROOM_ID: "!local_agent", workspaceApi: api }));
vi.mock("@phi/ui/ui/components/bottom-sheet", () => ({
  BottomSheet: ({ open, title, children }: { open: boolean; title: string; children: ReactNode }) =>
    open ? (
      <div role="dialog" aria-label={title}>
        {children}
      </div>
    ) : null,
}));

const DIR = "/srv/placeholder_root/room-h";

let container: HTMLDivElement;
let root: Root;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const onComputer = vi.fn();

async function renderHeader(onBack?: () => void, model?: ChatModelEntry) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={["/chat?room=!room-h"]}>
        <WorkspaceShellProvider>
          <ChatHeader roomId="!room-h" onBack={onBack} actions={{ onOpenComputer: onComputer }} model={model} />
        </WorkspaceShellProvider>
      </MemoryRouter>,
    );
  });
  for (let i = 0; i < 3; i++) await act(async () => {});
}

const header = () => container.querySelector('[data-testid="chat-header"]')!;
const action = (key: string) => header().querySelector(`button[data-action="${key}"]`);
const sheet = () => container.querySelector<HTMLElement>(`[role="dialog"][aria-label="${enShell.roomSheet}"]`);
const row = (key: string) => sheet()?.querySelector<HTMLButtonElement>(`button[data-action="${key}"]`) ?? null;
const moreButton = () => header().querySelector<HTMLButtonElement>(`button[aria-label="${enShell.chatActions}"]`);
const openSheet = async () => act(async () => moreButton()!.click());

async function pickFile(file: File) {
  const input = container.querySelector<HTMLInputElement>('[data-testid="room-file-input"]')!;
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  for (let i = 0; i < 3; i++) await act(async () => {});
}

describe("ChatHeader", () => {
  beforeEach(() => {
    api.getTree.mockResolvedValue({ spaces: [], home: ["!room-h", "!local_agent"] });
    api.getRooms.mockResolvedValue({ rooms: [{ room_id: "!room-h", type: "room", name: "Room H", path: DIR }] });
    api.getSettings.mockResolvedValue({ root: "/srv/placeholder_root", max_space_depth: 2, default_fence: "approve" });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.restoreAllMocks();
    onComputer.mockReset();
  });

  it("is the phone's app bar: only [≡] room name [⋯], all round ghost buttons", async () => {
    const onBack = vi.fn();
    await renderHeader(onBack);
    expect(container.querySelectorAll("header")).toHaveLength(1);
    expect(header().querySelector("h1")?.textContent).toBe("Room H");
    // No path line on phones and no action icons: they all live in the Room sheet.
    expect(header().querySelector('[data-testid="chat-breadcrumb"]')).toBeNull();
    expect(header().textContent).not.toContain(DIR);
    const buttons = Array.from(header().querySelectorAll<HTMLButtonElement>("button"));
    expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([enShell.backToRooms, enShell.chatActions]);
    expect(header().firstElementChild).toBe(buttons[0]);
    const title = header().querySelector("h1")!.parentElement;
    expect(buttons[0].nextElementSibling).toBe(title);
    expect(title?.nextElementSibling).toBe(buttons[1]);
    expect(header().querySelector("h1")?.className).toMatch(/\btruncate\b/);
    for (const b of buttons) {
      expect(b.className).toMatch(/\bshadow-none\b/);
      expect(b.className).toMatch(/\bsize-11\b/);
      expect(b.className).not.toMatch(/inset_/);
      expect(b.querySelector(".arc-border")).toBeNull();
      expect(b.querySelector('[data-round-face="ghost"]')?.className).toMatch(/\bsize-10\b.*\brounded-full\b|\brounded-full\b.*\bsize-10\b/);
    }
    expect(moreButton()?.getAttribute("aria-haspopup")).toBe("dialog");
    await act(async () => buttons[0].click());
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(sheet()).toBeNull();
  });

  it("opens the Room sheet from ⋯ with the room's actions, Add photo or file and the model", async () => {
    const pick = vi.fn();
    await renderHeader(vi.fn(), { label: "gpt-6-luna", open: pick });
    await openSheet();
    expect(sheet()).not.toBeNull();
    const keys = Array.from(sheet()!.querySelectorAll("button[data-action]")).map((b) => b.getAttribute("data-action"));
    expect(keys).toEqual(["copy-path", "files", "add-file", "computer", "model"]);
    expect(row("add-file")?.textContent).toBe(enShell.addPhotoOrFile);
    expect(row("copy-path")?.getAttribute("aria-label")).toBe(`${enShell.copyDirectory}: ${DIR}`);
    expect(row("model")?.getAttribute("aria-label")).toBe(`${enShell.model}: gpt-6-luna`);
    expect(row("model")?.textContent).toContain("gpt-6-luna");
    // 56px rows.
    for (const b of sheet()!.querySelectorAll("button[data-action]")) expect(b.className).toMatch(/\bmin-h-14\b/);

    await act(async () => row("computer")!.click());
    expect(onComputer).toHaveBeenCalledTimes(1);
    expect(sheet()).toBeNull();

    await openSheet();
    await act(async () => row("model")!.click());
    expect(pick).toHaveBeenCalledTimes(1);
    expect(sheet()).toBeNull();
  });

  it("Add photo or file opens the native picker, uploads into the room folder and puts the path in the composer", async () => {
    await renderHeader(vi.fn());
    const input = container.querySelector<HTMLInputElement>('[data-testid="room-file-input"]')!;
    expect(input.type).toBe("file");
    const click = vi.spyOn(input, "click").mockImplementation(() => {});
    await openSheet();
    await act(async () => row("add-file")!.click());
    expect(click).toHaveBeenCalledTimes(1);

    const inserted: string[] = [];
    const off = registerComposer("text", { insert: (t) => inserted.push(t), submit: () => {} });
    const upload = vi
      .spyOn(filesApi, "uploadFile")
      .mockRejectedValueOnce(new ApiError("File already exists", { status: 409, body: "", url: "/api/files/upload-stream" }))
      .mockImplementation(async (path) => ({ path }) as Awaited<ReturnType<typeof filesApi.uploadFile>>);
    const file = new File(["x"], "photo.png", { type: "image/png" });
    await pickFile(file);
    off();
    // Never overwrites: an existing name gets a -1 suffix.
    expect(upload.mock.calls).toEqual([
      [`${DIR}/photo.png`, file, false],
      [`${DIR}/photo-1.png`, file, false],
    ]);
    expect(inserted).toEqual([`${DIR}/photo-1.png`]);
    expect(input.value).toBe("");
  });

  it("keeps the breadcrumb and path line on desktop, with no drawer or copy icon", async () => {
    await renderHeader();
    expect(header().querySelector('[data-testid="chat-breadcrumb"]')?.textContent).toBe(enShell.home);
    expect(header().textContent).toContain(DIR);
    expect(header().querySelector(`button[aria-label="${enShell.backToRooms}"]`)).toBeNull();
    expect(action("copy-path")).toBeNull();
    expect(moreButton()).toBeNull();
    // Same ghost round style as the phone, compact: 32px buttons with 16px icons.
    for (const key of ["files", "computer"]) {
      const b = action(key)!;
      expect(b.className).toMatch(/\blg:size-8\b/);
      expect(b.className).toMatch(/\bshadow-none\b/);
      expect(b.querySelector('[data-round-face="ghost"]')?.className).toMatch(/\[&>svg\]:size-4/);
    }
  });
});

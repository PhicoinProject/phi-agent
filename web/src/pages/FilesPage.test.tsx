// @vitest-environment jsdom
// FilesPage: `?path=` deep links (a directory opens; a file opens its parent
// and previews the file) and file names opening the preview panel.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  listFiles: vi.fn(),
  readFile: vi.fn(),
}));

vi.mock("@/lib/api", () => ({
  PHI_BASE_PATH: "",
  api: { listFiles: mocks.listFiles, readFile: mocks.readFile },
}));
vi.mock("@/contexts/usePageHeader", () => ({
  usePageHeader: () => ({ setAfterTitle: vi.fn(), setEnd: vi.fn() }),
}));
vi.mock("@/plugins", () => ({ PluginSlot: () => null }));

import FilesPage from "./FilesPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DOCS = {
  root: null,
  path: "/tmp/docs",
  parent: "/tmp",
  locked_root: null,
  can_change_path: true,
  entries: [
    { name: "readme.md", path: "/tmp/docs/readme.md", is_directory: false, size: 7, mtime: null, mime_type: "text/markdown" },
    { name: "img", path: "/tmp/docs/img", is_directory: true, size: null, mtime: null, mime_type: null },
  ],
};

let container: HTMLDivElement;
let root: Root;

async function settle(rounds = 6) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

async function mount(entry: string) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <MemoryRouter initialEntries={[entry]}>
        <FilesPage />
      </MemoryRouter>,
    ),
  );
  await settle();
}

beforeEach(() => {
  mocks.listFiles.mockReset();
  mocks.listFiles.mockImplementation(async (path?: string) => {
    if (path === "/tmp/docs") return DOCS;
    if (path === "/tmp/docs/readme.md") throw new Error("400: Path is not a directory");
    throw new Error("404: Not found");
  });
  mocks.readFile.mockResolvedValue({
    name: "readme.md",
    path: "/tmp/docs/readme.md",
    size: 7,
    mime_type: "text/markdown",
    data_url: `data:text/markdown;base64,${btoa("# Hello")}`,
    root: null,
    locked_root: null,
    can_change_path: true,
  });
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  vi.unstubAllGlobals();
});

describe("FilesPage", () => {
  it("opens a ?path= directory without a preview", async () => {
    await mount("/files?path=%2Ftmp%2Fdocs");
    expect(mocks.listFiles).toHaveBeenCalledWith("/tmp/docs");
    expect(container.textContent).toContain("readme.md");
    expect(document.querySelector("[data-file-preview]")).toBeNull();
  });

  it("opens a ?path= file's folder and shows the file in the preview", async () => {
    await mount("/files?path=%2Ftmp%2Fdocs%2Freadme.md");
    expect(mocks.listFiles).toHaveBeenCalledWith("/tmp/docs");
    expect(container.textContent).toContain("img");
    const preview = document.querySelector("[data-file-preview]");
    expect(preview).not.toBeNull();
    expect(preview?.textContent).toContain("readme.md");
    expect(mocks.readFile).toHaveBeenCalledWith("/tmp/docs/readme.md");
  });

  it("opens a clicked file in the preview instead of downloading it", async () => {
    await mount("/files?path=%2Ftmp%2Fdocs");
    const name = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("readme.md"),
    );
    expect(name).toBeDefined();
    await act(async () => name!.click());
    await settle();
    expect(document.querySelector("[data-file-preview]")).not.toBeNull();
  });
});

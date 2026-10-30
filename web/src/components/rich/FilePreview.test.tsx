// @vitest-environment jsdom
// FilePreview: the viewer picked per extension, SVG kept out of the page DOM,
// Esc/close, desktop panel vs. narrow sheet, footer actions, PDF page search.

import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  readFile: vi.fn(),
  copyTextToClipboard: vi.fn(async (_text: string) => true),
  narrow: false,
}));

vi.mock("@/lib/api", () => ({ PHI_BASE_PATH: "", api: { readFile: mocks.readFile } }));
vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copyTextToClipboard }));

// Two-page PDF whose second page holds the search term.
vi.mock("pdfjs-dist", () => {
  const page = (text: string) => ({
    getViewport: () => ({ width: 200, height: 100 }),
    render: () => ({ promise: Promise.resolve(), cancel() {} }),
    getTextContent: async () => ({ items: [{ str: text, hasEOL: false }] }),
  });
  const pages = [page("Intro text"), page("The Needle is here")];
  return {
    GlobalWorkerOptions: { workerSrc: "" },
    getDocument: () => ({
      promise: Promise.resolve({ numPages: pages.length, getPage: async (n: number) => pages[n - 1] }),
      destroy: async () => {},
    }),
  };
});
vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "/assets/pdf.worker.mjs" }));

import { FilePreview, fencedCode } from "./FilePreview";
import type { PreviewFile } from "./file-kind";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SVG_SOURCE =
  '<svg xmlns="http://www.w3.org/2000/svg"><script>window.__phiSvgPwned=1</script><g id="phi-svg-marker"/></svg>';

const FILES: Record<string, { mime: string; text: string }> = {
  "/w/shot.png": { mime: "image/png", text: "\u0089PNG" },
  "/w/logo.svg": { mime: "image/svg+xml", text: SVG_SOURCE },
  "/w/report.pdf": { mime: "application/pdf", text: "%PDF-1.7" },
  "/w/notes.md": { mime: "text/markdown", text: "# Notes\n\nMEDIA:/w/shot.png\n" },
  "/w/app.ts": { mime: "text/plain", text: "const answer: number = 42;\n" },
  "/w/run.log": { mime: "text/plain", text: "started\nfinished\n" },
};

function toBase64(text: string): string {
  return btoa(String.fromCharCode(...new TextEncoder().encode(text)));
}

let container: HTMLDivElement;
let root: Root;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

/** Let pending promises (file read, pdf.js) settle, a few act() rounds at a time. */
async function settle(rounds = 6) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
  }
}

async function click(element: Element | null) {
  expect(element).not.toBeNull();
  await act(async () => {
    (element as HTMLElement).click();
  });
}

function dialog(): HTMLElement {
  const element = document.querySelector<HTMLElement>('[role="dialog"]');
  expect(element).not.toBeNull();
  return element!;
}

async function openPreview(file: PreviewFile, props: { onClose?: () => void; onOpenInFiles?: (path: string) => void } = {}) {
  await render(<FilePreview file={file} onClose={props.onClose ?? (() => {})} onOpenInFiles={props.onOpenInFiles} />);
  await settle();
  return dialog();
}

beforeEach(() => {
  mocks.narrow = false;
  vi.stubGlobal("matchMedia", () => ({
    matches: mocks.narrow,
    addEventListener() {},
    removeEventListener() {},
  }));
  mocks.copyTextToClipboard.mockClear();
  mocks.readFile.mockReset();
  mocks.readFile.mockImplementation(async (path: string) => {
    const entry = FILES[path];
    if (!entry) throw new Error("not found");
    return {
      name: path.split("/").pop(),
      path,
      size: entry.text.length,
      mime_type: entry.mime,
      data_url: `data:${entry.mime};base64,${toBase64(entry.text)}`,
      root: null,
      locked_root: null,
      can_change_path: true,
    };
  });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("viewer per extension", () => {
  it.each([
    ["/w/shot.png", "image", 'img[src^="data:image/png;base64,"]'],
    ["/w/song.mp3", "audio", 'audio[controls][src="/api/files/stream?path=%2Fw%2Fsong.mp3"]'],
    ["/w/clip.mp4", "video", 'video[controls][src="/api/files/stream?path=%2Fw%2Fclip.mp4"]'],
    ["/w/report.pdf", "pdf", '[data-pdf-pages="2"] canvas'],
    ["/w/notes.md", "markdown", 'h1'],
    ["/w/app.ts", "code", '[data-code-block="typescript"] code.hljs'],
    ["/w/run.log", "text", '[data-code-block="text"]'],
    ["/w/archive.bin", "other", "dl"],
  ])("%s opens the %s viewer", async (path, kind, selector) => {
    const panel = await openPreview({ path });
    const viewer = panel.querySelector(`[data-viewer="${kind}"]`);
    expect(viewer).not.toBeNull();
    expect(viewer!.querySelector(selector)).not.toBeNull();
    // Audio/video stream directly; "other" never downloads the file to look at it.
    const reads = ["audio", "video", "other"].includes(kind) ? 0 : 1;
    expect(mocks.readFile).toHaveBeenCalledTimes(reads);
  });

  it("plays audio/video through the token-capable download route when the page has a session token", async () => {
    window.__PHI_SESSION_TOKEN__ = "tok";
    try {
      const panel = await openPreview({ path: "/w/clip.mp4" });
      const video = panel.querySelector('[data-viewer="video"] video');
      expect(video?.getAttribute("src")).toBe("/api/files/download?path=%2Fw%2Fclip.mp4&token=tok");
    } finally {
      delete window.__PHI_SESSION_TOKEN__;
    }
  });

  it("renders Markdown files and keeps code files as code", async () => {
    let panel = await openPreview({ path: "/w/notes.md" });
    expect(panel.querySelector("h1")?.textContent).toBe("Notes");
    await act(async () => root.unmount());
    document.body.innerHTML = "";

    panel = await openPreview({ path: "/w/app.ts" });
    expect(panel.querySelector("h1")).toBeNull();
    // Shown verbatim: the code element holds exactly the file's text.
    expect(panel.querySelector("pre code")?.textContent).toBe(FILES["/w/app.ts"].text);
    // Previewed files show in full, never behind "Show all".
    expect(panel.querySelector("button[aria-expanded]")).toBeNull();
  });

  it("shows an error when the file cannot be read", async () => {
    const panel = await openPreview({ path: "/w/missing.png" });
    expect(panel.textContent).toContain("Could not load file");
  });

  it("follows a file card inside a previewed Markdown file in the same panel", async () => {
    const panel = await openPreview({ path: "/w/notes.md" });
    await click(panel.querySelector('button[aria-label="Open shot.png"]'));
    await settle();
    expect(document.querySelectorAll('[role="dialog"]')).toHaveLength(1);
    expect(panel.querySelector('[data-viewer="image"] img')).not.toBeNull();
  });
});

describe("SVG", () => {
  it("is shown through <img>, never inlined", async () => {
    // Deliberately-wrong variant: inlining the file as markup creates the
    // marker element; the assertions below must reject that.
    const inlined = document.createElement("template");
    inlined.innerHTML = SVG_SOURCE;
    expect(inlined.content.querySelector("#phi-svg-marker")).not.toBeNull();

    const panel = await openPreview({ path: "/w/logo.svg" });
    const img = panel.querySelector<HTMLImageElement>('[data-viewer="image"] img');
    expect(img?.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(document.getElementById("phi-svg-marker")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
  });
});

describe("panel", () => {
  it("closes on Esc and on the close button", async () => {
    const onClose = vi.fn();
    await openPreview({ path: "/w/archive.bin" }, { onClose });
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);
    await click(dialog().querySelector('button[aria-label="Close preview"]'));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("renders nothing without a file", async () => {
    await render(<FilePreview file={null} onClose={() => {}} />);
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("is a side panel on desktop and a full-screen sheet when narrow", async () => {
    let panel = await openPreview({ path: "/w/archive.bin" });
    expect(panel.dataset.filePreview).toBe("panel");
    expect(panel.className).toContain("right-0");
    expect(panel.querySelector('button[aria-label="Expand preview"]')).not.toBeNull();
    await act(async () => root.unmount());
    document.body.innerHTML = "";

    mocks.narrow = true;
    panel = await openPreview({ path: "/w/archive.bin" });
    expect(panel.dataset.filePreview).toBe("sheet");
    expect(panel.className).toContain("inset-0");
    expect(panel.getAttribute("aria-modal")).toBe("true");
    expect(panel.querySelector('button[aria-label="Expand preview"]')).toBeNull();
  });

  it("offers Open in Files, Download and Copy path", async () => {
    const onOpenInFiles = vi.fn();
    const clicked: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this.getAttribute("href") ?? "");
    });
    const panel = await openPreview({ path: "/w/archive.bin" }, { onOpenInFiles });
    const button = (label: string) =>
      [...panel.querySelectorAll("button")].find((element) => element.textContent?.trim() === label) ?? null;

    await click(button("Open in Files"));
    expect(onOpenInFiles).toHaveBeenCalledWith("/w/archive.bin");
    await click(button("Download"));
    expect(clicked).toEqual(["/api/files/download?path=%2Fw%2Farchive.bin"]);
    await click(button("Copy path"));
    expect(mocks.copyTextToClipboard).toHaveBeenCalledWith("/w/archive.bin");
    expect(button("Copied")).not.toBeNull();
  });

  it("hides Open in Files when the host has no Files page hook", async () => {
    const panel = await openPreview({ path: "/w/archive.bin" });
    expect(panel.textContent).not.toContain("Open in Files");
  });
});

describe("PDF", () => {
  it("pages, zooms and searches", async () => {
    const panel = await openPreview({ path: "/w/report.pdf" });
    const pageLabel = () => panel.querySelector("[data-pdf-page]")?.textContent;
    expect(pageLabel()).toBe("1 / 2");
    await click(panel.querySelector('button[aria-label="Next page"]'));
    expect(pageLabel()).toBe("2 / 2");
    await click(panel.querySelector('button[aria-label="Previous page"]'));
    expect(pageLabel()).toBe("1 / 2");
    await click(panel.querySelector('button[aria-label="Zoom in"]'));
    expect(panel.textContent).toContain("156%");

    const input = panel.querySelector<HTMLInputElement>('input[type="search"]')!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "needle");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      input.form!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    await settle(2);
    expect(pageLabel()).toBe("2 / 2");
    expect(panel.querySelector("[data-pdf-search]")?.textContent).toBe("Page 1 of 1 with matches");
  });
});

describe("fencedCode", () => {
  it("fences text so no inner fence can close it", () => {
    expect(fencedCode("a = 1\n", "python")).toBe("```python\na = 1\n```");
    expect(fencedCode("x\n```\ny", "md")).toBe("````md\nx\n```\ny\n````");
    expect(fencedCode("`````", "")).toBe("``````\n`````\n``````");
  });
});

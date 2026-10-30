// @vitest-environment jsdom
// RichMarkdown: GFM, KaTeX, highlighted code with copy/collapse, streaming
// fences, file cards, and the raw-HTML / javascript: safety guarantees.

import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  copyTextToClipboard: vi.fn(async (_text: string) => true),
  readFile: vi.fn(),
  mermaidInitialize: vi.fn(),
  mermaidRender: vi.fn(async () => ({
    svg: '<svg xmlns="http://www.w3.org/2000/svg" id="phi-mermaid-inline"><text>A</text></svg>',
  })),
}));

vi.mock("@/lib/clipboard", () => ({ copyTextToClipboard: mocks.copyTextToClipboard }));
vi.mock("@/lib/api", () => ({ PHI_BASE_PATH: "", api: { readFile: mocks.readFile } }));
vi.mock("mermaid", () => ({
  default: { initialize: mocks.mermaidInitialize, render: mocks.mermaidRender },
}));

import { RichMarkdown } from "./RichMarkdown";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

async function click(element: Element | null) {
  expect(element).not.toBeNull();
  await act(async () => {
    (element as HTMLElement).click();
  });
}

/** Let pending timers and promises settle, a few act() rounds at a time. */
async function settle(rounds = 10) {
  for (let i = 0; i < rounds; i += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
  }
}

/** True when markup from the reply became live DOM with an event handler or script. */
function rawHtmlLeaks(scope: ParentNode): boolean {
  return scope.querySelector("[onerror], [onload], [onclick], script") !== null;
}

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
  mocks.copyTextToClipboard.mockClear();
  mocks.readFile.mockReset();
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

describe("GFM", () => {
  it("renders tables", async () => {
    await render(<RichMarkdown content={"| name | size |\n|:---|---:|\n| a.txt | 12 |"} />);
    const table = container.querySelector("table");
    expect(table).not.toBeNull();
    expect([...table!.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["name", "size"]);
    expect([...table!.querySelectorAll("td")].map((td) => td.textContent)).toEqual(["a.txt", "12"]);
    expect((table!.querySelectorAll("td")[1] as HTMLElement).style.textAlign).toBe("right");
  });

  it("renders task lists as disabled checkboxes", async () => {
    await render(<RichMarkdown content={"- [x] shipped\n- [ ] pending"} />);
    const boxes = [...container.querySelectorAll<HTMLInputElement>('input[type="checkbox"]')];
    expect(boxes.map((box) => box.checked)).toEqual([true, false]);
    expect(boxes.every((box) => box.disabled)).toBe(true);
    expect(container.querySelector("ul.contains-task-list")).not.toBeNull();
  });

  it("renders footnotes with in-page links", async () => {
    await render(<RichMarkdown content={"Claim[^src].\n\n[^src]: The source."} />);
    const ref = container.querySelector<HTMLAnchorElement>("a[data-footnote-ref]");
    expect(ref).not.toBeNull();
    expect(ref!.getAttribute("href")).toMatch(/^#/);
    expect(ref!.getAttribute("target")).toBeNull();
    const notes = container.querySelector("section[data-footnotes]");
    expect(notes?.textContent).toContain("The source.");
    // The generated "Footnotes" heading stays screen-reader only.
    expect(notes?.querySelector("h2")?.className).toContain("sr-only");
  });

  it("renders strikethrough and autolinks opening in a new tab", async () => {
    await render(<RichMarkdown content={"~~old~~ see https://example.com/docs"} />);
    expect(container.querySelector("del")?.textContent).toBe("old");
    const link = container.querySelector<HTMLAnchorElement>('a[href="https://example.com/docs"]');
    expect(link).not.toBeNull();
    expect(link!.target).toBe("_blank");
    expect(link!.rel).toBe("noopener noreferrer");
  });
});

describe("math", () => {
  it("renders inline and block KaTeX", async () => {
    await render(<RichMarkdown content={"Energy $E=mc^2$ here.\n\n$$\n\\int_0^1 x\\,dx\n$$"} />);
    expect(container.querySelector("p .katex")).not.toBeNull();
    expect(container.querySelector(".katex-display .katex")).not.toBeNull();
    expect(container.querySelector(".katex-mathml math")).not.toBeNull();
  });
});

describe("code blocks", () => {
  it("highlights fenced code and copies the exact source", async () => {
    await render(<RichMarkdown content={"```python\ndef hi():\n    return 'hi'\n```"} />);
    const block = container.querySelector('[data-code-block="python"]');
    expect(block).not.toBeNull();
    expect(block!.querySelector('pre code [class^="hljs-"]')).not.toBeNull();
    await click(block!.querySelector('button[aria-label="Copy code"]'));
    expect(mocks.copyTextToClipboard).toHaveBeenCalledWith("def hi():\n    return 'hi'");
    expect(block!.querySelector('button[aria-label="Copied"]')).not.toBeNull();
  });

  it("collapses long code behind Show all", async () => {
    const code = Array.from({ length: 40 }, (_, i) => `line ${i + 1}`).join("\n");
    await render(<RichMarkdown content={"```\n" + code + "\n```"} />);
    const pre = container.querySelector("pre")!;
    expect(pre.className).toContain("overflow-y-hidden");
    const toggle = container.querySelector<HTMLButtonElement>("button[aria-expanded]")!;
    expect(toggle.textContent).toBe("Show all (40 lines)");
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(toggle.textContent).toBe("Show less");
    expect(pre.className).not.toContain("overflow-y-hidden");
    // Copy still copies everything, not only the visible part.
    await click(container.querySelector('button[aria-label="Copy code"]'));
    expect(mocks.copyTextToClipboard).toHaveBeenCalledWith(code);
  });

  it("does not collapse short code", async () => {
    await render(<RichMarkdown content={"```\na\nb\n```"} />);
    expect(container.querySelector("button[aria-expanded]")).toBeNull();
  });

  it("renders an unterminated fence as code", async () => {
    const content = "Here:\n\n```ts\nconst a = 1;\nconst b = **not bold**";
    await render(<RichMarkdown content={content} streaming />);
    const pre = container.querySelector('[data-code-block="ts"] pre');
    expect(pre?.textContent).toContain("const a = 1;");
    expect(pre?.textContent).toContain("const b = **not bold**");
    expect(container.querySelector("strong")).toBeNull();
  });

  it("renders mermaid lazily through <img>, never inline SVG", async () => {
    await render(<RichMarkdown content={"```mermaid\ngraph TD; A-->B\n```"} />);
    await settle();
    expect(mocks.mermaidInitialize).toHaveBeenCalledWith(expect.objectContaining({ securityLevel: "strict" }));
    const img = container.querySelector<HTMLImageElement>("figure[data-mermaid] img");
    expect(img?.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    expect(document.getElementById("phi-mermaid-inline")).toBeNull();
  });
});

describe("safety", () => {
  it("never renders <script>", async () => {
    await render(<RichMarkdown content={"<script>window.__phiPwned = 1</script>\n\nhello"} />);
    expect(container.querySelector("script")).toBeNull();
    expect((window as { __phiPwned?: number }).__phiPwned).toBeUndefined();
    expect(container.textContent).toContain("hello");
  });

  it("strips javascript: links", async () => {
    await render(
      <RichMarkdown content={'[click](javascript:alert(1)) and <a href="javascript:alert(2)">raw</a>'} />,
    );
    const hrefs = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href") ?? "");
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs.some((href) => /^\s*javascript:/i.test(href))).toBe(false);
  });

  it("never turns raw <img onerror> into an element (fails if rehype-raw were enabled)", async () => {
    const payload = '<img src="x" onerror="window.__phiImgPwned=1">\n\nafter';
    // Deliberately-wrong variant: the payload parsed as live markup, which is
    // what rehype-raw would produce. The leak check must catch it. (An inert
    // <template> so the handler cannot run here either.)
    const wrong = document.createElement("template");
    wrong.innerHTML = payload;
    expect(rawHtmlLeaks(wrong.content)).toBe(true);

    await render(<RichMarkdown content={payload} />);
    expect(rawHtmlLeaks(container)).toBe(false);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("after");
  });

  it("does not load remote images", async () => {
    await render(<RichMarkdown content={"![chart](https://example.com/chart.png)"} />);
    expect(container.querySelector("img")).toBeNull();
    const link = container.querySelector<HTMLAnchorElement>('a[href="https://example.com/chart.png"]');
    expect(link?.textContent).toBe("chart");
    expect(link?.rel).toBe("noopener noreferrer");
  });
});

describe("file cards", () => {
  it("turns MEDIA lines and local image refs into file cards", async () => {
    const onOpenFile = vi.fn();
    await render(
      <RichMarkdown
        content={"Done.\nMEDIA:/tmp/out/plot.png\n\n![diagram](/tmp/out/arch.svg)"}
        onOpenFile={onOpenFile}
      />,
    );
    const cards = [...container.querySelectorAll<HTMLButtonElement>("button[data-file-kind]")];
    expect(cards.map((card) => card.title)).toEqual(["/tmp/out/plot.png", "/tmp/out/arch.svg"]);
    expect(container.textContent).not.toContain("MEDIA:");
    await click(cards[0]);
    expect(onOpenFile).toHaveBeenCalledWith({ path: "/tmp/out/plot.png" });
  });

  it("opens its own preview when no host handler is given", async () => {
    mocks.readFile.mockResolvedValue({
      name: "plot.png",
      path: "/tmp/out/plot.png",
      size: 4,
      mime_type: "image/png",
      data_url: "data:image/png;base64,iVBORw==",
      root: null,
      locked_root: null,
      can_change_path: true,
    });
    await render(<RichMarkdown content={"MEDIA:/tmp/out/plot.png"} />);
    await click(container.querySelector('button[aria-label="Open plot.png"]'));
    const dialog = document.querySelector('[role="dialog"]');
    expect(dialog?.querySelector('[data-viewer="image"]')).not.toBeNull();
    expect(mocks.readFile).toHaveBeenCalledWith("/tmp/out/plot.png");
  });

  it("holds back a half-typed MEDIA line while streaming", async () => {
    await render(<RichMarkdown content={"Look:\nMEDIA:/tmp/a.p"} streaming />);
    expect(container.querySelector("button[data-file-kind]")).toBeNull();
  });
});

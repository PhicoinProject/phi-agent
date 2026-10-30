// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { PageHeaderProvider } from "./PageHeaderProvider";

let container: HTMLDivElement;
let root: Root;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function renderAt(path: string) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <MemoryRouter initialEntries={[path]}>
        <PageHeaderProvider pluginTabs={[]}>
          <div data-testid="page" />
        </PageHeaderProvider>
      </MemoryRouter>,
    );
  });
}

describe("PageHeaderProvider", () => {
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("renders no page-title header on /chat: the room header is column 3's top bar", async () => {
    for (const path of ["/chat", "/chat/", "/chat?room=!r"]) {
      await renderAt(path);
      expect(container.querySelector('header[role="banner"]'), path).toBeNull();
      expect(container.querySelector("h1"), path).toBeNull();
      expect(container.textContent).not.toContain("Chat");
      // The chat outlet still fills a non-scrolling main.
      const main = container.querySelector("main")!;
      expect(main.querySelector('[data-testid="page"]')).toBeTruthy();
      expect(main.classList.contains("overflow-hidden")).toBe(true);
      act(() => root.unmount());
      container.remove();
    }
    await renderAt("/files");
  });

  it("keeps the page header on other pages", async () => {
    await renderAt("/files");
    const banner = container.querySelector('header[role="banner"]');
    expect(banner).toBeTruthy();
    expect(banner!.querySelector("h1")?.textContent).toBe("Files");
  });
});

// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { enShell } from "@/i18n/en";
import { ChatFooter } from "./ChatFooter";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

// Shaped like ChatSidebar's model card: notices, then the [status] [model ▾] chip.
const modelCard = (
  <>
    <div data-testid="chat-model-notices" className="order-first basis-full" />
    <div data-testid="chat-model-chip">
      <button type="button" data-testid="chat-model-button">
        demo-model
      </button>
    </div>
  </>
);

async function renderFooter(isPhone: boolean, session = true) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <ChatFooter
        isPhone={isPhone}
        session={session}
        onSend={() => {}}
        ctrlActive={false}
        onCtrlChange={() => {}}
        onFontAdjust={() => {}}
        composerAccessory={<button type="button" data-testid="mic-button" />}
        onAddFile={async () => "/r/x"}
        modelCard={modelCard}
      />,
    ),
  );
}

const all = (sel: string) => container.querySelectorAll(sel);
const one = (sel: string) => container.querySelector<HTMLElement>(sel);
const before = (a: Element | null, b: Element | null) =>
  !!a && !!b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;

describe("ChatFooter", () => {
  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("is one control row on phones: [+] [Esc] [↑] [↓] [mic] [Send]; no field, no A-/A+, no model chip", async () => {
    await renderFooter(true);
    expect(all('[data-testid="phone-bar"]')).toHaveLength(1);
    expect(one('[data-testid="mobile-key-bar"]')).toBeNull();
    expect(one('[data-testid="composer-pill"]')).toBeNull();
    expect(container.querySelector("textarea")).toBeNull();
    expect(one('[data-testid="chat-footer"]')).toBeNull();
    expect(one('[data-testid="terminal-font-controls"]')).toBeNull();
    const row = one('[data-testid="phone-bar"]')!;
    const plus = row.querySelector(`button[aria-label="${enShell.addPhotoOrFile}"]`);
    const mic = row.querySelector('[data-testid="mic-slot"] [data-testid="mic-button"]');
    const send = row.querySelector(`button[aria-label="${enShell.sendEnter}"]`);
    expect(before(plus, mic) && before(mic, send)).toBe(true);
    expect(before(one('[data-testid="chat-model-notices"]'), row)).toBe(true);
    expect(row.querySelector('[data-testid="chat-model-button"]')).toBeNull();
  });

  it("keeps the desktop row [A-] [A+] [mic] [model] in order, with no phone bars", async () => {
    await renderFooter(false);
    const row = one('[data-testid="chat-footer"]')!;
    const [smaller, larger] = row.querySelectorAll('[data-testid="terminal-font-controls"] button');
    expect(smaller.getAttribute("aria-label")).toBe(enShell.fontSmaller);
    expect(larger.getAttribute("aria-label")).toBe(enShell.fontLarger);
    const mic = row.querySelector('[data-testid="chat-mic-slot"] [data-testid="mic-button"]');
    const model = row.querySelector('[data-testid="chat-model-button"]');
    expect(before(smaller, larger) && before(larger, mic) && before(mic, model)).toBe(true);
    expect(one('[data-testid="composer-pill"]')).toBeNull();
    expect(one('[data-testid="mobile-key-bar"]')).toBeNull();
    // Ghost round icons, no bevel.
    for (const b of [smaller, larger]) {
      expect(b.className).toMatch(/\bshadow-none\b/);
      expect(b.className).toMatch(/\blg:size-8\b/);
      expect(b.querySelector("[data-round-face]")).not.toBeNull();
    }
  });
});

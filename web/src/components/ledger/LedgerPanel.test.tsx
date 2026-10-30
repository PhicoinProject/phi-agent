// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fmt } from "@/components/shell/use-shell-strings";
import { enPanels } from "@/i18n/en";
import type { LedgerEntry } from "@/lib/api-workspace";
import { LEDGER_SEARCH_DEBOUNCE_MS, LedgerPanel } from "./LedgerPanel";

const getLedger = vi.hoisted(() => vi.fn());

vi.mock("@/lib/api-workspace", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-workspace")>();
  return { ...actual, workspaceApi: { getLedger } };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ENTRIES: LedgerEntry[] = [
  { id: 2, ts: 1_000, kind: "decision", text: "Use parser A", status: "superseded", refs: [], superseded_by: 3 },
  { id: 3, ts: 2_000, kind: "decision", text: "Use parser B", status: "active", refs: ["web/src/App.tsx"] },
  { id: 4, ts: 3_000, kind: "fact", text: "Parser B is 2x faster", status: "active", refs: [] },
];

let container: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () =>
    root.render(
      <MemoryRouter>
        <LedgerPanel roomId="!room-a" />
      </MemoryRouter>,
    ),
  );
  await flush();
}

async function type(value: string) {
  const input = container.querySelector<HTMLInputElement>(`input[aria-label="${enPanels.ledgerSearch}"]`)!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const queries = () => getLedger.mock.calls.map((call) => (call[1] as { q?: string }).q);
const entry = (id: number) => container.querySelector<HTMLElement>(`li[data-entry-id="${id}"]`);

describe("LedgerPanel", () => {
  beforeEach(() => {
    getLedger.mockReset();
    getLedger.mockResolvedValue({ entries: ENTRIES });
  });

  afterEach(() => {
    vi.useRealTimers();
    act(() => root.unmount());
    container.remove();
  });

  it("lists newest first and greys superseded entries with their replacement", async () => {
    await render();
    expect(getLedger).toHaveBeenCalledWith("!room-a", { q: undefined, kind: undefined, include_superseded: true, limit: 200 });
    const ids = Array.from(container.querySelectorAll("li[data-entry-id]")).map((li) => li.getAttribute("data-entry-id"));
    expect(ids).toEqual(["4", "3", "2"]);

    expect(entry(2)?.getAttribute("data-superseded")).toBe("true");
    expect(entry(2)?.className).toContain("opacity-50");
    expect(entry(2)?.querySelector('[data-testid="ledger-replaced"]')?.textContent).toBe(
      fmt(enPanels.ledgerReplacedBy, { id: 3 }),
    );
    expect(entry(3)?.hasAttribute("data-superseded")).toBe(false);
    expect(entry(3)?.className).not.toContain("opacity-50");
    expect(entry(3)?.querySelector('[data-testid="ledger-replaced"]')).toBeNull();
    expect(entry(3)?.querySelector("a")?.getAttribute("href")).toBe("/files?path=web%2Fsrc%2FApp.tsx");
  });

  it("debounces the search and refetches once with the final text", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    await render();
    expect(queries()).toEqual([undefined]);

    await type("p");
    await act(async () => vi.advanceTimersByTime(100));
    await type("pa");
    await act(async () => vi.advanceTimersByTime(100));
    await type("par");
    await act(async () => vi.advanceTimersByTime(LEDGER_SEARCH_DEBOUNCE_MS - 1));
    expect(queries()).toEqual([undefined]);

    await act(async () => vi.advanceTimersByTime(1));
    await flush();
    expect(queries()).toEqual([undefined, "par"]);
  });

  it("filters by kind from the chips", async () => {
    await render();
    await act(async () => container.querySelector<HTMLButtonElement>('button[data-kind-chip="fact"]')!.click());
    await flush();
    expect(getLedger).toHaveBeenLastCalledWith("!room-a", expect.objectContaining({ kind: "fact" }));
    expect(container.querySelector('button[data-kind-chip="fact"]')?.getAttribute("aria-pressed")).toBe("true");
  });
});

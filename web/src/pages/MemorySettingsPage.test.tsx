// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { fmt } from "@/components/shell/use-shell-strings";
import { enShell } from "@/i18n/en";

// Mock the shared fetch helper, not the memory client, so the asserted
// method/URL/body are exactly what reaches the backend.
const apiMocks = vi.hoisted(() => ({ fetchJSON: vi.fn() }));
vi.mock("@/lib/api", () => ({ fetchJSON: apiMocks.fetchJSON }));

const NOW = 1_800_000_000; // epoch seconds
const DAY = 86_400;

const entry = (over: Record<string, unknown>) => ({
  target: "memory",
  priority: 0,
  use_count: 0,
  last_used_at: null,
  created_at: NOW - 30 * DAY,
  updated_at: NOW - 30 * DAY,
  ...over,
});

const USAGE = {
  hard: { memory: { used: 3100, limit: 4000 }, user: { used: 2400, limit: 4000 } },
  soft_count: 212,
};
const HARD = [
  entry({ id: 11, tier: "hard", kind: "rule", text: "Reply in Chinese", priority: 1 }),
  entry({ id: 12, tier: "hard", kind: "skill", text: "upstream-maintenance skill", target: "user" }),
];
const SOFT = [
  entry({ id: 21, tier: "soft", kind: "fact", text: "test containers carry a label", last_used_at: NOW - 3 * DAY }),
  entry({ id: 22, tier: "soft", kind: "note", text: "default branch is feat/x" }),
];
const HITS = [
  entry({ id: 22, tier: "soft", kind: "note", text: "default branch is feat/x", score: 0.8234 }),
  entry({ id: 23, tier: "soft", kind: "fact", text: "branch names are kebab-case", score: 0.4, last_used_at: NOW - 21 * DAY }),
];

type Call = { method: string; path: string; params: URLSearchParams; body: unknown };

function route(url: string, init?: RequestInit): Promise<unknown> {
  const u = new URL(url, "http://localhost");
  const method = init?.method ?? "GET";
  if (method === "GET" && u.pathname === "/api/memory/usage") return Promise.resolve(JSON.parse(JSON.stringify(USAGE)));
  if (method === "GET" && u.pathname === "/api/memory/entries") {
    const tier = u.searchParams.get("tier");
    if (tier === "hard") return Promise.resolve({ entries: HARD });
    if (tier === "soft") return Promise.resolve({ entries: u.searchParams.get("q") ? HITS : SOFT });
  }
  const m = /^\/api\/memory\/(\d+)(?:\/(promote|demote|archive|pin))?$/.exec(u.pathname);
  if (m && (method === "POST" || method === "PATCH")) return Promise.resolve({ ok: true, id: Number(m[1]) + 100 });
  return Promise.reject(new Error(`unexpected ${method} ${url}`));
}

function calls(): Call[] {
  return apiMocks.fetchJSON.mock.calls.map((args) => {
    const [url, init] = args as [string, RequestInit | undefined];
    const u = new URL(url, "http://localhost");
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    return { method: init?.method ?? "GET", path: u.pathname, params: u.searchParams, body };
  });
}
const writes = () => calls().filter((c) => c.method !== "GET");
const usageLoads = () => calls().filter((c) => c.path === "/api/memory/usage").length;

let container: HTMLDivElement;
let root: Root;
let nowSpy: MockInstance<() => number>;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function flush() {
  for (let i = 0; i < 5; i++) await act(async () => {});
}

async function renderPage() {
  const { default: MemorySettingsPage } = await import("./MemorySettingsPage");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<MemorySettingsPage />));
  await flush();
}

function byTestId(id: string, scope: ParentNode = container): HTMLElement {
  const el = scope.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  if (!el) throw new Error(`missing [data-testid="${id}"]`);
  return el;
}

function row(tier: "hard" | "soft", id: number): HTMLElement {
  const el = container.querySelector<HTMLElement>(`[data-testid="mem-entry"][data-tier="${tier}"][data-id="${id}"]`);
  if (!el) throw new Error(`missing ${tier} entry ${id}`);
  return el;
}

function actionIn(scope: HTMLElement, action: string): HTMLButtonElement {
  const el = scope.querySelector<HTMLButtonElement>(`button[data-action="${action}"]`);
  if (!el) throw new Error(`no ${action} button`);
  return el;
}

async function click(el: Element) {
  await act(async () => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function typeInto(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function submit(form: HTMLFormElement) {
  await act(async () => {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
  await flush();
}

function bar(target: "memory" | "user") {
  const scope = byTestId(`mem-budget-${target}`);
  const progress = scope.querySelector<HTMLElement>('[role="progressbar"]');
  if (!progress) throw new Error(`no progressbar for ${target}`);
  const fill = progress.firstElementChild as HTMLElement | null;
  return { value: byTestId(`mem-budget-${target}-value`).textContent, progress, width: fill?.style.width };
}

beforeEach(() => {
  apiMocks.fetchJSON.mockReset();
  apiMocks.fetchJSON.mockImplementation(route);
  nowSpy = vi.spyOn(Date, "now").mockReturnValue(NOW * 1000);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
  nowSpy.mockRestore();
});

describe("MemorySettingsPage", () => {
  it("renders both hard budgets, the hard list and the soft list", async () => {
    await renderPage();

    expect(calls().map((c) => `${c.method} ${c.path}?${c.params.toString()}`).sort()).toEqual([
      "GET /api/memory/entries?tier=hard",
      "GET /api/memory/entries?tier=soft",
      "GET /api/memory/usage?",
    ]);

    const memory = bar("memory");
    expect(memory.value).toBe("3.1k/4k");
    expect(memory.progress.getAttribute("aria-valuenow")).toBe("3100");
    expect(memory.progress.getAttribute("aria-valuemax")).toBe("4000");
    expect(memory.width).toBe("77.5%");
    const user = bar("user");
    expect(user.value).toBe("2.4k/4k");
    expect(user.progress.getAttribute("aria-valuenow")).toBe("2400");
    expect(user.progress.getAttribute("aria-valuemax")).toBe("4000");
    expect(user.width).toBe("60%");

    const hard = row("hard", 11);
    expect(byTestId("mem-kind", hard).textContent).toBe("rule");
    expect(byTestId("mem-text", hard).textContent).toBe("Reply in Chinese");
    expect(actionIn(hard, "pin").textContent).toBe(enShell.memUnpin);
    expect(hard.querySelector('[data-testid="mem-target"]')).toBeNull();
    const userHard = row("hard", 12);
    expect(byTestId("mem-target", userHard).textContent).toBe(enShell.memTargetUser);
    expect(actionIn(userHard, "pin").textContent).toBe(enShell.memPin);

    expect(byTestId("mem-soft-count").textContent).toBe(fmt(enShell.memSoftCount, { count: 212 }));
    expect(byTestId("mem-used", row("soft", 21)).textContent).toBe(fmt(enShell.memUsedDaysAgo, { days: 3 }));
    expect(byTestId("mem-used", row("soft", 22)).textContent).toBe(enShell.memNeverUsed);
    expect(container.querySelector('[data-testid="mem-score"]')).toBeNull();
    expect(row("soft", 21).querySelector('button[data-action="demote"]')).toBeNull();
    expect(writes()).toEqual([]);
  });

  it("demotes a hard entry via POST /api/memory/<id>/demote and refreshes", async () => {
    await renderPage();
    expect(usageLoads()).toBe(1);

    await click(actionIn(row("hard", 11), "demote"));

    expect(writes().map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/memory/11/demote"]);
    expect(writes()[0].body).toBeUndefined();
    expect(calls().some((c) => c.path.endsWith("/promote"))).toBe(false);
    expect(usageLoads()).toBe(2);
    expect(container.querySelector('[data-testid="mem-error"]')).toBeNull();
  });

  it("promotes a soft entry via POST /api/memory/<id>/promote and shows a 409 detail", async () => {
    await renderPage();

    await click(actionIn(row("soft", 21), "promote"));
    expect(writes().map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/memory/21/promote"]);
    expect(calls().some((c) => c.path.endsWith("/demote"))).toBe(false);
    expect(usageLoads()).toBe(2);

    apiMocks.fetchJSON.mockImplementation((url: string, init?: RequestInit) =>
      url.endsWith("/promote")
        ? Promise.reject(new Error("hard memory budget exceeded"))
        : route(url, init),
    );
    await click(actionIn(row("soft", 22), "promote"));

    expect(writes().map((c) => c.path)).toEqual(["/api/memory/21/promote", "/api/memory/22/promote"]);
    expect(byTestId("mem-error").textContent).toBe(
      fmt(enShell.memActionFailed, { error: "hard memory budget exceeded" }),
    );
    expect(usageLoads()).toBe(2); // a failed action does not refetch
  });

  it("searches soft memory with tier=soft&q=<query> and shows scores", async () => {
    await renderPage();
    const form = byTestId("mem-search") as HTMLFormElement;
    const input = form.querySelector("input");
    if (!input) throw new Error("no search input");

    await typeInto(input, "  branch ");
    await submit(form);

    const searches = calls().filter((c) => c.path === "/api/memory/entries" && c.params.has("q"));
    expect(searches).toHaveLength(1);
    expect(searches[0].params.get("tier")).toBe("soft");
    expect(searches[0].params.get("q")).toBe("branch");
    expect(calls().filter((c) => c.params.get("tier") === "hard" && c.params.has("q"))).toEqual([]);

    const scores = Array.from(container.querySelectorAll('[data-testid="mem-soft"] [data-testid="mem-score"]'));
    expect(scores.map((el) => el.textContent)).toEqual(["0.82", "0.40"]);
    expect(byTestId("mem-text", row("soft", 23)).textContent).toBe("branch names are kebab-case");
    expect(container.querySelector('[data-tier="soft"][data-id="21"]')).toBeNull();
    expect(byTestId("mem-used", row("soft", 23)).textContent).toBe(fmt(enShell.memUsedDaysAgo, { days: 21 }));
  });

  it("edits a hard entry inline via PATCH /api/memory/<id> with the new text", async () => {
    await renderPage();

    await click(actionIn(row("hard", 12), "edit"));
    const input = row("hard", 12).querySelector("input");
    if (!input) throw new Error("no edit input");
    expect(input.value).toBe("upstream-maintenance skill");
    await typeInto(input, "upstream maintenance skill");
    await click(actionIn(row("hard", 12), "save"));

    expect(writes()).toEqual([
      expect.objectContaining({ method: "PATCH", path: "/api/memory/12", body: { text: "upstream maintenance skill" } }),
    ]);
    expect(usageLoads()).toBe(2);
    expect(row("hard", 12).querySelector("input")).toBeNull();
  });
});

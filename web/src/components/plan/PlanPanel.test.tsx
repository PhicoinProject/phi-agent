// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import type { PlanUpdatedPayload } from "@phi/shared";

import { fmt } from "@/components/shell/use-shell-strings";
import { enPanels } from "@/i18n/en";
import { PlanPanel, planLabel, planView } from "./PlanPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const payload = (todos: unknown[], waves: string[][] = [], critical_path: string[] = []) =>
  ({ revision: 1, todos, plan: { title: "Ship", waves, critical_path } }) as unknown as PlanUpdatedPayload;

const TODOS = [
  { id: "a", content: "Read", status: "completed", depends_on: [], assignee: "self" },
  { id: "b", content: "Port", status: "in_progress", depends_on: ["a"], assignee: "agent" },
  { id: "c", content: "Docs", status: "pending", depends_on: ["a"], assignee: "agent" },
  { id: "d", content: "Release", status: "pending", depends_on: ["b", "c"], assignee: "self" },
  { id: "x", content: "Dropped", status: "cancelled", depends_on: [], assignee: "self" },
];

let container: HTMLDivElement | null = null;
let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

function render(p: PlanUpdatedPayload | null) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(<PlanPanel payload={p} />));
  return container;
}

describe("planView", () => {
  it("is null without live tasks, so the header hides the Plan button", () => {
    expect(planView(null)).toBeNull();
    expect(planView(payload([]))).toBeNull();
    expect(planView(payload([TODOS[4]]))).toBeNull();
  });

  it("counts live tasks only and labels the header", () => {
    const view = planView(payload(TODOS, [["a"], ["b", "c"], ["d"]]))!;
    expect([view.done, view.total]).toEqual([1, 4]);
    expect(planLabel(view, enPanels)).toBe("Plan 1/4");
  });
});

describe("PlanPanel", () => {
  it("renders waves with status, assignee, deps and the critical path", () => {
    const el = render(payload(TODOS, [["a"], ["b", "c"], ["d"]], ["a", "b", "d"]));
    const waves = Array.from(el.querySelectorAll('[data-testid="plan-wave"]'));
    expect(waves).toHaveLength(3);
    expect(waves[1].querySelector("h3")?.textContent).toBe(fmt(enPanels.planWave, { n: 2 }));

    const row = (id: string) => el.querySelector(`li[data-task-id="${id}"]`)!;
    expect(row("b").getAttribute("data-status")).toBe("in_progress");
    expect(row("a").querySelector('[data-testid="plan-assignee"]')?.textContent).toBe(enPanels.planSelf);
    expect(row("b").querySelector('[data-testid="plan-assignee"]')?.textContent).toBe(fmt(enPanels.planAgent, { n: 1 }));
    expect(row("c").querySelector('[data-testid="plan-assignee"]')?.textContent).toBe(fmt(enPanels.planAgent, { n: 2 }));
    expect(row("d").querySelector('[data-testid="plan-deps"]')?.textContent?.trim()).toBe("<- b c");
    expect(row("a").querySelector('[data-testid="plan-deps"]')).toBeNull();
    expect(el.querySelector('li[data-task-id="x"]')).toBeNull();
    expect(el.querySelector('[data-testid="plan-progress"]')?.textContent).toContain("1/4");
    expect(el.querySelector('[data-testid="plan-critical-path"]')?.textContent).toBe(
      fmt(enPanels.planCriticalPath, { path: "a > b > d" }),
    );
    // Read-only: no controls.
    expect(el.querySelectorAll("button, input, select, textarea")).toHaveLength(0);
  });

  it("still lists tasks the schedule left out of every wave", () => {
    const el = render(payload(TODOS, [["a"]]));
    expect(el.querySelectorAll('[data-testid="plan-wave"]')).toHaveLength(1);
    expect(el.querySelector('li[data-task-id="d"]')).not.toBeNull();
  });
});

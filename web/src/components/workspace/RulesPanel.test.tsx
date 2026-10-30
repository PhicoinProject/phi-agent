// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fmt } from "@/components/shell/use-shell-strings";
import { enPanels, enShell } from "@/i18n/en";
import { ApiError } from "@/lib/api-error";
import { RULES_MAX_CHARS, RulesPanel } from "./RulesPanel";

const ws = vi.hoisted(() => ({ getRules: vi.fn(), putRules: vi.fn() }));

vi.mock("@/lib/api-workspace", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api-workspace")>();
  return { ...actual, workspaceApi: ws };
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<RulesPanel roomId="!room-a" />));
  await flush();
}

const textarea = () => container.querySelector<HTMLTextAreaElement>(`textarea[aria-label="${enShell.rules}"]`)!;
const counter = () => container.querySelector<HTMLElement>('[data-testid="rules-counter"]')!;
const saveButton = () =>
  Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find((b) => b.textContent === enShell.save)!;

async function edit(value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(textarea(), value);
    textarea().dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("RulesPanel", () => {
  beforeEach(() => {
    ws.getRules.mockReset();
    ws.putRules.mockReset();
    ws.getRules.mockResolvedValue({ content: "Be brief.", max_chars: RULES_MAX_CHARS });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it("loads the rules and counts characters against 8000", async () => {
    await render();
    expect(ws.getRules).toHaveBeenCalledWith("!room-a");
    expect(textarea().value).toBe("Be brief.");
    expect(counter().textContent).toBe(fmt(enPanels.rulesCounter, { count: 9, max: 8000 }));
    expect(saveButton().disabled).toBe(true);

    await edit("x".repeat(8001));
    expect(counter().textContent).toBe("8001/8000");
    expect(counter().className).toContain("text-destructive");
  });

  it("saves through PUT and shows the server's 413 message", async () => {
    ws.putRules.mockRejectedValue(
      new ApiError("Rules exceed 8000 characters", { status: 413, body: '{"detail":"Rules exceed 8000 characters"}', url: "/api/workspace/rooms/x/rules" }),
    );
    await render();
    await edit("x".repeat(8001));
    await act(async () => saveButton().click());
    await flush();

    expect(ws.putRules).toHaveBeenCalledWith("!room-a", "x".repeat(8001));
    expect(container.querySelector('[role="alert"]')?.textContent).toBe("Rules exceed 8000 characters");
    // The draft survives the rejection.
    expect(textarea().value).toHaveLength(8001);
  });

  it("confirms a successful save", async () => {
    ws.putRules.mockImplementation(async (_room: string, content: string) => ({ content, max_chars: RULES_MAX_CHARS }));
    await render();
    await edit("Be brief. Cite files.");
    await act(async () => saveButton().click());
    await flush();
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(container.querySelector('[role="status"]')?.textContent).toBe(enShell.saved);
    expect(saveButton().disabled).toBe(true);
  });
});

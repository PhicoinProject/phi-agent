// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fmt } from "@/components/shell/use-shell-strings";
import { enShell } from "@/i18n/en";

const wsMocks = vi.hoisted(() => ({
  check: vi.fn(),
  getSettings: vi.fn(),
  putSettings: vi.fn(),
}));

vi.mock("@/lib/api-workspace", () => ({
  FENCE_MODES: ["approve", "strict", "off"],
  workspaceApi: wsMocks,
}));
vi.mock("@phi/ui/ui/components/select", () => ({
  Select: ({
    children,
    disabled,
    onValueChange,
    value,
  }: {
    children?: ReactNode;
    disabled?: boolean;
    onValueChange?: (value: string) => void;
    value?: string;
  }) => (
    <select disabled={disabled} value={value} onChange={(e) => onValueChange?.(e.currentTarget.value)}>
      {children}
    </select>
  ),
  SelectOption: ({ children, value }: { children?: ReactNode; value: string }) => (
    <option value={value}>{children}</option>
  ),
}));
vi.mock("@phi/ui/ui/components/dialog", () => {
  const Box = ({ children }: { children?: ReactNode }) => <div>{children}</div>;
  return {
    Dialog: ({ children, open }: { children?: ReactNode; open?: boolean }) =>
      open ? <div role="dialog">{children}</div> : null,
    DialogContent: Box,
    DialogDescription: ({ children }: { children?: ReactNode }) => <p>{children}</p>,
    DialogFooter: Box,
    DialogHeader: Box,
    DialogTitle: ({ children }: { children?: ReactNode }) => <h2>{children}</h2>,
  };
});
vi.mock("@phi/ui/ui/components/toast", () => ({
  Toast: ({ toast }: { toast: { message: string; type: string } | null }) =>
    toast ? (
      <div role="status" data-type={toast.type}>
        {toast.message}
      </div>
    ) : null,
}));

const ROOT = "/srv/placeholder_root";
const SETTINGS = { root: ROOT, configured_root: null, max_space_depth: 3, default_fence: "approve" };
const CLEAN_CHECK = { root: ROOT, rooms: 4, issues: [] };
const ISSUES_CHECK = {
  root: ROOT,
  rooms: 2,
  issues: [
    { kind: "missing_dir", room_id: "!room_a", path: `${ROOT}/room_a` },
    { kind: "unmapped_dir", path: `${ROOT}/stray_dir` },
  ],
};

let container: HTMLDivElement;
let root: Root;
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function renderPage() {
  const { default: WorkspaceSettingsPage } = await import("./WorkspaceSettingsPage");
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(<WorkspaceSettingsPage />));
  await flush();
}

function byTestId(id: string): HTMLElement {
  const el = container.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  if (!el) throw new Error(`missing [data-testid="${id}"]`);
  return el;
}

function selectIn(id: string): HTMLSelectElement {
  const el = byTestId(id).querySelector("select");
  if (!el) throw new Error(`no select inside [data-testid="${id}"]`);
  return el;
}

function buttonByText(scope: ParentNode, text: string): HTMLButtonElement {
  const el = Array.from(scope.querySelectorAll("button")).find((b) => b.textContent === text);
  if (!el) throw new Error(`no button "${text}"`);
  return el;
}

async function click(el: Element) {
  await act(async () => {
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
  });
  await flush();
}

async function choose(select: HTMLSelectElement, value: string) {
  await act(async () => {
    select.value = value;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await flush();
}

const optionValues = (select: HTMLSelectElement) => Array.from(select.options).map((o) => o.value);

beforeEach(() => {
  for (const fn of Object.values(wsMocks)) fn.mockReset();
  wsMocks.getSettings.mockResolvedValue({ ...SETTINGS });
  wsMocks.check.mockResolvedValue({ ...CLEAN_CHECK });
});

afterEach(async () => {
  await act(async () => root?.unmount());
  container?.remove();
});

describe("WorkspaceSettingsPage", () => {
  it("renders the root read-only and the mapping count from check", async () => {
    await renderPage();

    expect(wsMocks.getSettings).toHaveBeenCalledTimes(1);
    expect(wsMocks.check).toHaveBeenCalledTimes(1);
    const rootEl = byTestId("ws-root");
    expect(rootEl.tagName).not.toBe("INPUT"); // read-only text; not <code>, which phi-ui paints with selection colours
    expect(rootEl.textContent).toBe(ROOT);
    expect(container.querySelector("input, textarea")).toBeNull();
    expect(container.textContent).toContain(enShell.wsRoot);
    expect(byTestId("ws-mappings").textContent).toBe("4");
    expect(container.textContent).toContain(enShell.wsMappings);
    expect(selectIn("ws-depth").value).toBe("3");

    await click(buttonByText(container, enShell.wsChange));
    const dialog = container.querySelector('[role="dialog"]');
    if (!dialog) throw new Error("change dialog did not open");
    expect(dialog.querySelector("h2")?.textContent).toBe(enShell.wsChangeTitle);
    expect(dialog.textContent).toContain(enShell.wsChangeBody);
    await click(buttonByText(dialog, enShell.cancel));
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    expect(wsMocks.putSettings).not.toHaveBeenCalled();
  });

  it("saves a new nesting limit through putSettings", async () => {
    wsMocks.putSettings.mockResolvedValue({ ...SETTINGS, max_space_depth: 5 });
    await renderPage();

    const depth = selectIn("ws-depth");
    expect(optionValues(depth)).toEqual(["2", "3", "4", "5", "6", "7", "8"]);
    await choose(depth, "5");

    expect(wsMocks.putSettings).toHaveBeenCalledTimes(1);
    expect(wsMocks.putSettings).toHaveBeenCalledWith({ max_space_depth: 5 });
    expect(selectIn("ws-depth").value).toBe("5");
    expect(selectIn("ws-depth").disabled).toBe(false);
    const toast = container.querySelector('[role="status"]');
    expect(toast?.textContent).toBe(enShell.saved);
    expect(toast?.getAttribute("data-type")).toBe("success");
  });

  it("reverts the nesting limit when putSettings rejects", async () => {
    wsMocks.putSettings.mockRejectedValue(new Error("disk full"));
    await renderPage();

    await choose(selectIn("ws-depth"), "6");

    expect(wsMocks.putSettings).toHaveBeenCalledTimes(1);
    expect(wsMocks.putSettings).toHaveBeenCalledWith({ max_space_depth: 6 });
    expect(selectIn("ws-depth").value).toBe("3");
    const toast = container.querySelector('[role="status"]');
    expect(toast?.textContent).toBe(fmt(enShell.saveFailed, { error: "disk full" }));
    expect(toast?.getAttribute("data-type")).toBe("error");
  });

  it("lists missing and unmapped directories after Check", async () => {
    const pending: { resolve: (value: unknown) => void } = { resolve: () => {} };
    wsMocks.check
      .mockResolvedValueOnce({ ...CLEAN_CHECK })
      .mockImplementationOnce(() => new Promise((resolve) => (pending.resolve = resolve)));
    await renderPage();

    expect(byTestId("ws-issues").textContent).toBe(enShell.wsNoIssues);
    const checkButton = byTestId("ws-check") as HTMLButtonElement;
    expect(checkButton.textContent).toBe(enShell.wsCheck);

    await click(checkButton);
    expect(wsMocks.check).toHaveBeenCalledTimes(2);
    expect(checkButton.textContent).toBe(enShell.wsChecking);
    expect(checkButton.disabled).toBe(true);

    await act(async () => pending.resolve({ ...ISSUES_CHECK }));
    await flush();

    expect(checkButton.textContent).toBe(enShell.wsCheck);
    expect(checkButton.disabled).toBe(false);
    expect(byTestId("ws-mappings").textContent).toBe("2");
    const issues = byTestId("ws-issues");
    expect(issues.textContent).not.toContain(enShell.wsNoIssues);
    const rows = Array.from(issues.querySelectorAll("li"));
    expect(rows).toHaveLength(2);
    expect(rows[0].getAttribute("data-kind")).toBe("missing_dir");
    expect(rows[0].textContent).toContain(enShell.wsMissingDir);
    expect(rows[0].textContent).toContain(`${ROOT}/room_a`);
    expect(rows[0].textContent).toContain("!room_a");
    expect(rows[1].getAttribute("data-kind")).toBe("unmapped_dir");
    expect(rows[1].textContent).toContain(enShell.wsUnmappedDir);
    expect(rows[1].textContent).toContain(`${ROOT}/stray_dir`);
    expect(rows[1].textContent).not.toContain("!room_a");
  });

  it("offers exactly approve/strict/off as fence modes", async () => {
    wsMocks.putSettings.mockResolvedValue({ ...SETTINGS, default_fence: "strict" });
    await renderPage();

    const fence = selectIn("ws-fence");
    expect(optionValues(fence)).toEqual(["approve", "strict", "off"]);
    expect(Array.from(fence.options).map((o) => o.textContent)).toEqual([
      enShell.wsFenceApprove,
      enShell.wsFenceStrict,
      enShell.wsFenceOff,
    ]);
    expect(fence.value).toBe("approve");

    await choose(fence, "strict");
    expect(wsMocks.putSettings).toHaveBeenCalledTimes(1);
    expect(wsMocks.putSettings).toHaveBeenCalledWith({ default_fence: "strict" });
    expect(selectIn("ws-fence").value).toBe("strict");
  });
});

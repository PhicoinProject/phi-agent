// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { Keyboard } from "lucide-react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SHELL_SETTINGS_NAV, SHELL_SETTINGS_ROUTES } from "@/components/shell/settings-nav";
import { fmt } from "@/components/shell/use-shell-strings";
import { VOICE_AUTO_SEND_KEY } from "@/components/voice/voice-prefs";
import { enPanels, enShell } from "@/i18n/en";
import { AgentsSettingsPage, ComputerSettingsPage, ShortcutsSettingsPage, VoiceSettingsPage } from "./ConfigSettingsPages";

const cfg = vi.hoisted(() => ({ getConfig: vi.fn(), saveConfig: vi.fn() }));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return { ...actual, api: { ...actual.api, ...cfg } };
});
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
vi.mock("@phi/ui/ui/components/toast", () => ({
  Toast: ({ toast }: { toast: { message: string; type: string } | null }) =>
    toast ? (
      <div role="status" data-type={toast.type}>
        {toast.message}
      </div>
    ) : null,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom runs without an origin here, so localStorage is undefined: stub it.
const store = new Map<string, string>();
const localStorageMock = {
  clear: () => store.clear(),
  getItem: (key: string) => store.get(key) ?? null,
  removeItem: (key: string) => {
    store.delete(key);
  },
  setItem: (key: string, value: string) => {
    store.set(key, String(value));
  },
};

let container: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 3; i++) await act(async () => {});
}

async function render(page: ReactNode) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(<MemoryRouter>{page}</MemoryRouter>));
  await flush();
}

const select = (testId: string) => container.querySelector<HTMLSelectElement>(`[data-testid="${testId}"] select`)!;
const status = () => container.querySelector('[role="status"]')?.textContent;

async function choose(testId: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")!.set!.call(select(testId), value);
    select(testId).dispatchEvent(new Event("change", { bubbles: true }));
  });
  await flush();
}

async function commit(testId: string, value: string) {
  const input = container.querySelector<HTMLInputElement>(`[data-testid="${testId}"] input`)!;
  await act(async () => {
    input.focus();
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => input.blur());
  await flush();
}

describe("config settings pages", () => {
  beforeEach(() => {
    cfg.getConfig.mockReset();
    cfg.saveConfig.mockReset();
    cfg.saveConfig.mockResolvedValue({ ok: true });
    cfg.getConfig.mockResolvedValue({
      delegation: { max_concurrent_children: 10, model: "" },
      stt: {},
      voice: {},
      bot_desktop: { geometry: "1920x1080", idle_stop_minutes: 30 },
    });
    store.clear();
    vi.stubGlobal("localStorage", localStorageMock);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  });

  it("Agents writes delegation.max_concurrent_children and the sub-agent model", async () => {
    await render(<AgentsSettingsPage />);
    expect(select("agents-max-children").value).toBe("10");

    await choose("agents-max-children", "4");
    expect(cfg.saveConfig).toHaveBeenCalledWith({ delegation: { max_concurrent_children: 4 } });
    expect(select("agents-max-children").value).toBe("4");
    expect(status()).toBe(enShell.saved);

    await commit("agents-model", "small-model");
    expect(cfg.saveConfig).toHaveBeenLastCalledWith({ delegation: { model: "small-model" } });
  });

  it("Agents rolls the value back when the save fails", async () => {
    cfg.saveConfig.mockRejectedValue(new Error("disk full"));
    await render(<AgentsSettingsPage />);
    await choose("agents-max-children", "6");
    expect(select("agents-max-children").value).toBe("10");
    expect(status()).toBe(fmt(enShell.saveFailed, { error: "disk full" }));
  });

  it("Voice saves the provider to config and keeps auto-send in the browser; the shortcut lives on Shortcuts", async () => {
    await render(<VoiceSettingsPage />);
    expect(container.querySelector('[data-testid="voice-shortcut"]')).toBeNull();
    expect(container.querySelector("input")).toBeNull();
    const link = container.querySelector<HTMLAnchorElement>('[data-testid="voice-shortcuts-link"] a')!;
    expect(link.getAttribute("href")).toBe("/settings/shortcuts");

    expect(select("voice-provider").value).toBe("");
    await choose("voice-provider", "groq");
    expect(cfg.saveConfig).toHaveBeenLastCalledWith({ stt: { provider: "groq" } });

    const toggle = container.querySelector<HTMLButtonElement>(`[data-testid="voice-auto-send"] button[aria-label="${enPanels.voiceAutoSend}"]`)!;
    await act(async () => toggle.click());
    expect(localStorage.getItem(VOICE_AUTO_SEND_KEY)).toBe("1");
    expect(cfg.saveConfig).toHaveBeenCalledTimes(1);
  });

  it("Shortcuts saves voice.web_shortcut (default F8) and notes that Esc cancels", async () => {
    await render(<ShortcutsSettingsPage />);
    const input = container.querySelector<HTMLInputElement>('[data-testid="shortcut-dictation"] input')!;
    expect(input.value).toBe("");
    expect(input.placeholder).toBe("F8");
    expect(container.textContent).toContain(enPanels.shortcutsEscNote);
    await commit("shortcut-dictation", "F9");
    expect(cfg.saveConfig).toHaveBeenCalledTimes(1);
    expect(cfg.saveConfig).toHaveBeenLastCalledWith({ voice: { web_shortcut: "F9" } });
    expect(input.value).toBe("F9");
  });

  it("Shortcuts shows the saved shortcut", async () => {
    cfg.getConfig.mockResolvedValue({ voice: { web_shortcut: "Ctrl+Shift+M" } });
    await render(<ShortcutsSettingsPage />);
    expect(container.querySelector<HTMLInputElement>('[data-testid="shortcut-dictation"] input')!.value).toBe("Ctrl+Shift+M");
  });

  it("Settings lists a Shortcuts page with a keyboard icon", () => {
    const item = SHELL_SETTINGS_NAV.find((i) => i.path === "/settings/shortcuts");
    expect(item?.labelKey).toBe("navShortcuts");
    expect(enShell.navShortcuts).toBe("Shortcuts");
    expect(item?.icon).toBe(Keyboard);
    expect(SHELL_SETTINGS_ROUTES["/settings/shortcuts"]).toBeTruthy();
  });

  it("Computer saves the desktop geometry and idle stop", async () => {
    await render(<ComputerSettingsPage />);
    await choose("computer-geometry", "1280x720");
    expect(cfg.saveConfig).toHaveBeenLastCalledWith({ bot_desktop: { geometry: "1280x720" } });
    await choose("computer-idle", "0");
    expect(cfg.saveConfig).toHaveBeenLastCalledWith({ bot_desktop: { idle_stop_minutes: 0 } });
  });
});

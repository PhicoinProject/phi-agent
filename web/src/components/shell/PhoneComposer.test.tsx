// @vitest-environment jsdom
import { act, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { enShell } from "@/i18n/en";
import { registerComposer } from "@/components/voice/composer-bridge";
import { useVoiceStatusSlot } from "@/components/voice/voice-status-slot";
import { PhoneComposer } from "./PhoneComposer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;
let unregister: (() => void) | null = null;

async function render(ui: ReactNode) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => root.render(ui));
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  unregister?.();
  unregister = null;
});

const bar = () => container.querySelector<HTMLElement>('[data-testid="phone-bar"]')!;
const button = (label: string) => bar().querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`);

function setup(props: { mic?: ReactNode } = {}) {
  const onAddFile = vi.fn(async (file: File) => `/rooms/abc/${file.name}`);
  const onWrite = vi.fn((_data: string) => true);
  // The terminal is the composer: dictation and uploaded paths go to it.
  const typed: string[] = [];
  unregister = registerComposer("pty", { insert: (t) => typed.push(t), submit: () => typed.push("<submit>") });
  return {
    onAddFile,
    onWrite,
    typed,
    ui: <PhoneComposer onAddFile={onAddFile} onWrite={onWrite} mic={props.mic ?? <button type="button" aria-label="mic" />} />,
  };
}

/** A mic stand-in that shows its recording status where the row tells it to. */
function StatusProbe() {
  const slot = useVoiceStatusSlot();
  const [on, setOn] = useState(false);
  return (
    <>
      <button type="button" aria-label="mic" onClick={() => setOn(true)} />
      {on && slot && createPortal(<span data-testid="probe-status">0:01</span>, slot)}
    </>
  );
}

describe("PhoneComposer (the phone's one control row)", () => {
  it("is one row [+] [Esc] [↑] [↓] … [mic] [Send]; no text field, no Tab/Ctrl/slash", async () => {
    const { ui } = setup();
    await render(ui);
    const labels = Array.from(bar().querySelectorAll("button")).map((b) => b.getAttribute("aria-label"));
    expect(labels).toEqual([enShell.addPhotoOrFile, enShell.keyEsc, enShell.keyUp, enShell.keyDown, "mic", enShell.sendEnter]);
    expect(container.querySelector("textarea")).toBeNull();
    expect(container.querySelector('[data-testid="composer-pill"]')).toBeNull();
    expect(bar().querySelector('[data-key="tab"], [data-key="ctrl"], [data-key="slash"]')).toBeNull();
  });

  it("each key writes its terminal bytes: Esc, up, down, Enter", async () => {
    const { onWrite, ui } = setup();
    await render(ui);
    for (const label of [enShell.keyEsc, enShell.keyUp, enShell.keyDown, enShell.sendEnter]) {
      await act(async () => button(label)!.click());
    }
    expect(onWrite.mock.calls).toEqual([["\x1b"], ["\x1b[A"], ["\x1b[B"], ["\r"]]);
  });

  it("[+] uploads a picked file and types its path into the terminal, without running it", async () => {
    const { onAddFile, onWrite, typed, ui } = setup();
    await render(ui);
    const input = bar().querySelector<HTMLInputElement>('input[type="file"]')!;
    const click = vi.spyOn(input, "click").mockImplementation(() => undefined);
    await act(async () => button(enShell.addPhotoOrFile)!.click());
    expect(click).toHaveBeenCalledTimes(1);
    const file = new File(["x"], "photo.png", { type: "image/png" });
    Object.defineProperty(input, "files", { value: [file], configurable: true });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    expect(onAddFile).toHaveBeenCalledWith(file);
    expect(typed).toEqual(["/rooms/abc/photo.png"]);
    expect(onWrite).not.toHaveBeenCalled();
    expect(button(enShell.newChat)).toBeNull();
  });

  it("shows the mic's recording status in the row's middle", async () => {
    await render(<PhoneComposer onWrite={() => true} mic={<StatusProbe />} />);
    await act(async () => bar().querySelector<HTMLButtonElement>('button[aria-label="mic"]')!.click());
    const status = container.querySelector('[data-testid="probe-status"]');
    expect(status?.parentElement?.getAttribute("data-testid")).toBe("voice-status-slot");
  });

  it("every control is a ghost round button; only Send is a filled brand-blue circle", async () => {
    const { ui } = setup();
    await render(ui);
    for (const label of [enShell.addPhotoOrFile, enShell.keyEsc, enShell.keyUp, enShell.sendEnter]) {
      const b = button(label)!;
      expect(b.className).toMatch(/\bshadow-none\b/);
      expect(b.className).toMatch(/\brounded-full\b/);
      expect(b.className).not.toMatch(/inset_/);
    }
    expect(button(enShell.keyEsc)!.querySelector("[data-round-face]")!.className).toMatch(/bg-midground\/10/);
    const send = button(enShell.sendEnter)!.querySelector("[data-round-face]")!;
    expect(send.className).toMatch(/\bbg-brand\b/);
  });
});

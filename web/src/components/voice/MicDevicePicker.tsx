/**
 * Microphone choice beside the composer mic: a menu of audio inputs, "System default" first. The
 * pick is kept in this browser (`phi-mic-device-id`) and `useDictation` asks for exactly that
 * device; the phone's hold-to-talk uses the same saved choice without a menu.
 */
import { Button } from "@phi/ui/ui/components/button";
import { Check, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { MENU_ITEM_CLASS } from "@/components/shell/ActionMenu";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import { cn } from "@/lib/utils";

import type { DictationDeps } from "./useDictation";
import { readMicDeviceId, writeMicDeviceId } from "./voice-prefs";

interface MicDevice {
  id: string;
  label: string;
}

/** Chromium lists the current default twice more under these ids; "System default" covers them. */
const ALIAS_IDS = new Set(["", "default", "communications"]);

/** Labelled audio inputs; labels stay empty until the page has had microphone permission. */
function micDevices(all: MediaDeviceInfo[]): MicDevice[] {
  return all
    .filter((d) => d.kind === "audioinput" && d.label && !ALIAS_IDS.has(d.deviceId))
    .map((d) => ({ id: d.deviceId, label: d.label }));
}

function defaultOnDeviceChange(listener: () => void): () => void {
  const media = navigator.mediaDevices;
  media?.addEventListener?.("devicechange", listener);
  return () => media?.removeEventListener?.("devicechange", listener);
}

export interface MicDevicePickerProps {
  deps?: DictationDeps;
  /** Why the mic cannot be used (insecure page, no capture API); disables the menu too. */
  disabledText?: string | null;
  className?: string;
}

export function MicDevicePicker({ className, deps, disabledText }: MicDevicePickerProps) {
  const { t } = useI18n();
  const s = { ...en.voiceComputer!, ...t.voiceComputer };
  const [open, setOpen] = useState(false);
  const [devices, setDevices] = useState<MicDevice[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const ref = useRef<HTMLSpanElement>(null);
  const depsRef = useRef(deps);
  depsRef.current = deps;
  const isOpen = open && !disabledText;

  const refresh = useCallback(async () => {
    const enumerate = depsRef.current?.enumerateDevices ?? (() => navigator.mediaDevices.enumerateDevices());
    try {
      setDevices(micDevices(await enumerate()));
    } catch {
      setDevices([]);
    }
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    setSelected(readMicDeviceId());
    void refresh();
    const unsubscribe = (depsRef.current?.onDeviceChange ?? defaultOnDeviceChange)(() => void refresh());
    const onDown = (e: Event) => {
      if (!ref.current?.contains(e.target as Node | null)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("touchstart", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      unsubscribe();
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("touchstart", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [isOpen, refresh]);

  const choose = (id: string | null) => {
    writeMicDeviceId(id);
    setSelected(id);
    setOpen(false);
  };

  // One permission prompt so the browser reveals device labels; the stream is closed at once.
  const allow = async () => {
    const getUserMedia = depsRef.current?.getUserMedia ?? ((c: MediaStreamConstraints) => navigator.mediaDevices.getUserMedia(c));
    try {
      const stream = await getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
    } catch {
      // Denied or no microphone: the list stays as it was.
    }
    await refresh();
  };

  // A saved device that is not plugged in is not what capture will get; show the default as current.
  const current = selected && devices.some((d) => d.id === selected) ? selected : null;
  const item = (id: string | null, label: string) => (
    <button
      aria-checked={current === id}
      className={MENU_ITEM_CLASS}
      key={id ?? ""}
      onClick={() => choose(id)}
      role="menuitemradio"
      type="button"
    >
      <span className="flex size-3.5 shrink-0 items-center">{current === id && <Check className="size-3.5" />}</span>
      <span className="truncate">{label}</span>
    </button>
  );

  return (
    <span className={cn("relative flex", className)} ref={ref}>
      <Button
        aria-expanded={isOpen}
        aria-haspopup="menu"
        aria-label={s.chooseMic}
        className="aspect-auto px-0.5"
        data-testid="mic-device-button"
        disabled={Boolean(disabledText)}
        ghost
        onClick={() => setOpen((v) => !v)}
        size="icon"
        title={disabledText ?? s.chooseMic}
        type="button"
      >
        <ChevronDown />
      </Button>
      {isOpen && (
        <div
          aria-label={s.chooseMic}
          className="absolute bottom-full left-0 z-50 mb-1 min-w-[220px] max-w-[min(320px,90vw)] border border-border bg-card py-1 text-foreground shadow-lg"
          role="menu"
        >
          {item(null, s.systemDefaultMic)}
          {devices.map((d) => item(d.id, d.label))}
          {devices.length === 0 && (
            <button className={MENU_ITEM_CLASS} onClick={() => void allow()} role="menuitem" type="button">
              {s.allowMicDevices}
            </button>
          )}
        </div>
      )}
    </span>
  );
}

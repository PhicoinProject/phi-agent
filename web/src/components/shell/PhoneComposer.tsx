// The phone's one control row under the terminal (the terminal itself is the input):
//   [+ add photo or file] [Esc] [↑] [↓]   …voice status…   [mic] [Send ⏎]
// [+] uploads into the room's folder and types the saved path into the terminal; the mic's
// dictation is typed into the terminal too (bracketed paste, never run on its own); Send is
// Enter. Esc cancels/interrupts (twice = stop), ↑/↓ walk history and menus. Tab, Ctrl and "/"
// are left to the soft keyboard. New chat lives in the drawer, next to Create space.

import { useRef, useState, type ChangeEvent, type PointerEvent, type ReactNode } from "react";
import { ArrowDown, ArrowUp, CornerDownLeft, Plus } from "lucide-react";
import { activeComposer } from "@/components/voice/composer-bridge";
import { VoiceStatusSlot } from "@/components/voice/voice-status-slot";
import { cn } from "@/lib/utils";
import { RoundIconButton } from "./RoundIconButton";
import { useShellStrings } from "./use-shell-strings";

// Terminal bytes for the keys the row keeps.
const ESC = "\x1b";
const UP = "\x1b[A";
const DOWN = "\x1b[B";
const ENTER = "\r";

// Keep the soft keyboard and the terminal's focus while tapping a key.
const keepFocus = (e: PointerEvent<HTMLElement>) => e.preventDefault();

export function PhoneComposer({
  onAddFile,
  onWrite,
  mic,
  notices,
}: {
  /** Upload the picked file into the room; resolves to the saved path. Absent: no [+]. */
  onAddFile?: (file: File) => Promise<string>;
  /** Raw bytes to the terminal, without focusing it. */
  onWrite: (data: string) => boolean | void;
  mic?: ReactNode;
  /** The model's notices, on their own line above the row. */
  notices?: ReactNode;
}) {
  const s = useShellStrings();
  const [slot, setSlot] = useState<HTMLElement | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState(false);

  const pick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !onAddFile) return;
    setUploading(true);
    try {
      activeComposer()?.insert(await onAddFile(file));
    } finally {
      setUploading(false);
    }
  };

  const key = (label: string, data: string, icon: ReactNode, testId: string) => (
    <RoundIconButton aria-label={label} title={label} data-key={testId} onPointerDown={keepFocus} onClick={() => onWrite(data)}>
      {icon}
    </RoundIconButton>
  );

  return (
    <div data-testid="phone-composer" className="flex w-full shrink-0 flex-col gap-1 pb-[max(0.5rem,env(safe-area-inset-bottom))]">
      {notices}
      <div data-testid="phone-bar" role="toolbar" aria-label={s.keyBar} className="flex items-center gap-1 rounded-lg border border-current/10 bg-midground/5 p-1">
        {onAddFile && (
          <>
            <RoundIconButton
              aria-label={s.addPhotoOrFile}
              title={s.addPhotoOrFile}
              disabled={uploading}
              onPointerDown={keepFocus}
              onClick={() => fileInput.current?.click()}
            >
              <Plus />
            </RoundIconButton>
            <input ref={fileInput} type="file" hidden data-testid="composer-file-input" onChange={(e) => void pick(e)} />
          </>
        )}
        <RoundIconButton aria-label={s.keyEsc} title={s.keyEsc} data-key="esc" onPointerDown={keepFocus} onClick={() => onWrite(ESC)}>
          <span className="text-xs font-normal normal-case tracking-normal">Esc</span>
        </RoundIconButton>
        {key(s.keyUp, UP, <ArrowUp />, "up")}
        {key(s.keyDown, DOWN, <ArrowDown />, "down")}
        <div
          ref={setSlot}
          data-voice-status
          data-testid="voice-status-slot"
          className={cn("flex h-11 min-w-0 flex-1 items-center justify-center overflow-hidden px-1")}
        />
        <div role="group" aria-label={s.micSlot} data-testid="mic-slot" className="flex shrink-0">
          <VoiceStatusSlot.Provider value={slot}>{mic}</VoiceStatusSlot.Provider>
        </div>
        <RoundIconButton tone="primary" aria-label={s.sendEnter} title={s.sendEnter} data-key="enter" onPointerDown={keepFocus} onClick={() => onWrite(ENTER)}>
          <CornerDownLeft />
        </RoundIconButton>
      </div>
    </div>
  );
}

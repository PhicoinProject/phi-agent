// Under column 3's terminal window: on desktop one right-aligned toolbar row
// [A-] [A+] [mic] [model ▾] on the terminal box's bottom edge line; on phones
// one control row ([+] [Esc] [↑] [↓] … [mic] [Send ⏎]); the terminal itself is
// the input, so there is no second text field. Phones drop A-/A+ (the font tiers
// by width and pinch zoom covers the rest) and the model chip (it lives in the
// header's Room sheet). The model card's notices wrap onto a line above.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { PhoneComposer } from "./PhoneComposer";
import { TerminalFontControls } from "./TerminalFontControls";

// The mic button comes from the voice feature; size it like the A-/A+ buttons
// (compact on desktop, inside its fixed-width box).
const MIC_SLOT_CLASS = cn(
  "flex shrink-0 items-center",
  "[&_[data-testid=mic-button]]:size-11 lg:[&_[data-testid=mic-button]]:size-8",
  "lg:[&_[data-testid=mic-button]]:justify-self-center",
);

export interface ChatFooterProps {
  isPhone: boolean;
  /** A session runs in the terminal (kept for callers; the phone row is always shown). */
  session?: boolean;
  onSend: (data: string) => void;
  /** Raw bytes without focusing the terminal (the phone pill keeps the keyboard on its field). */
  onWrite?: (data: string) => boolean | void;
  /** Kept for callers; the phone row no longer has a sticky Ctrl. */
  ctrlActive?: boolean;
  onCtrlChange?: (active: boolean) => void;
  onFontAdjust: (adjust: number) => void;
  composerAccessory?: ReactNode;
  /** Phone [+]: upload a file into the room folder, resolving to its saved path. */
  onAddFile?: (file: File) => Promise<string>;
  /** Toolbar items for the model ([status] [model ▾]) and its notices. */
  modelCard: ReactNode;
}

export function ChatFooter({
  isPhone,
  onSend,
  onWrite,
  onFontAdjust,
  composerAccessory,
  onAddFile,
  modelCard,
}: ChatFooterProps) {
  const modelSlot = (
    <div data-testid="chat-model-slot" className="contents">
      {modelCard}
    </div>
  );

  if (isPhone) {
    return (
      <>
        <PhoneComposer onAddFile={onAddFile} onWrite={onWrite ?? onSend} mic={composerAccessory} notices={modelSlot} />
      </>
    );
  }

  return (
    <div data-testid="chat-footer" className="flex shrink-0 flex-wrap items-center justify-end gap-1 pb-2">
      <TerminalFontControls onChange={onFontAdjust} />
      {composerAccessory != null && (
        <div data-testid="chat-mic-slot" className={MIC_SLOT_CLASS}>
          {composerAccessory}
        </div>
      )}
      {modelSlot}
    </div>
  );
}

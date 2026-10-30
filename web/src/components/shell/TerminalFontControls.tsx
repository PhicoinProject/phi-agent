import { useState } from "react";
import { AArrowDown, AArrowUp } from "lucide-react";
import { useShellStrings } from "@/components/shell/use-shell-strings";
import {
  TERMINAL_FONT_MAX,
  TERMINAL_FONT_MIN,
  readTerminalFontAdjust,
  terminalFontSizeForWidth,
  writeTerminalFontAdjust,
} from "@/lib/terminal-appearance";
import { RoundIconButton } from "./RoundIconButton";

/** A- / A+ buttons that step the per-device terminal font size. */
export function TerminalFontControls({
  onChange,
}: {
  onChange: (adjust: number) => void;
}) {
  const s = useShellStrings();
  const [adjust, setAdjust] = useState(readTerminalFontAdjust);
  const size = terminalFontSizeForWidth(0, adjust);

  const step = (delta: number) => {
    const next = writeTerminalFontAdjust(readTerminalFontAdjust() + delta);
    setAdjust(next);
    onChange(next);
  };

  return (
    <div
      className="inline-flex shrink-0 items-center gap-1"
      data-testid="terminal-font-controls"
    >
      <RoundIconButton
        compact
        aria-label={s.fontSmaller}
        title={s.fontSmaller}
        disabled={size <= TERMINAL_FONT_MIN}
        onClick={() => step(-1)}
      >
        <AArrowDown />
      </RoundIconButton>
      <RoundIconButton
        compact
        aria-label={s.fontLarger}
        title={s.fontLarger}
        disabled={size >= TERMINAL_FONT_MAX}
        onClick={() => step(1)}
      >
        <AArrowUp />
      </RoundIconButton>
    </div>
  );
}

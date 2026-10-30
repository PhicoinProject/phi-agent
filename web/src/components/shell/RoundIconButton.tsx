// The chat's one icon-button style: a ghost button showing a round, softly filled face
// (no bevel, no solid fill). Phones: a 40px face inside a 44px touch target, 20px icon.
// `compact` (desktop): a 32px face and button, 16px icon (44px below lg for touch
// tablets). `tone="primary"` is the one filled brand-blue circle (Send); `tone="danger"`
// tints the face destructive (recording). `wide` stretches the circle into a pill
// for an icon with a short label.

import type { ComponentProps } from "react";
import { Button } from "@phi/ui/ui/components/button";
import { cn } from "@/lib/utils";

export type RoundTone = "ghost" | "primary" | "danger";

const TONE_CLASS: Record<RoundTone, string> = {
  ghost: "bg-midground/10 group-hover:bg-midground/15 group-active:bg-midground/20",
  primary: "bg-brand text-brand-foreground group-hover:bg-brand-hover group-active:opacity-80",
  danger: "bg-destructive/15 text-destructive group-hover:bg-destructive/20 group-active:bg-destructive/25",
};

/** Classes for the round face; exported for controls that are not a RoundIconButton. */
export function roundFaceClass(tone: RoundTone = "ghost", compact = false, wide = false) {
  const size = compact ? (wide ? "h-11 lg:h-8" : "size-11 lg:size-8") : wide ? "h-10" : "size-10";
  return cn(
    "grid shrink-0 place-items-center rounded-full transition-colors",
    size,
    wide && "grid-flow-col gap-1 px-3",
    compact ? "[&>svg]:size-4" : "[&>svg]:size-5",
    TONE_CLASS[tone],
  );
}

/** Classes for the button around the face: transparent, round, the touch target. */
export function roundButtonClass(compact = false, wide = false) {
  const size = compact ? (wide ? "h-11 lg:h-8" : "size-11 lg:size-8") : wide ? "h-11" : "size-11";
  return cn(
    "shrink-0 rounded-full p-0 hover:bg-transparent disabled:bg-transparent disabled:opacity-40",
    size,
    wide && "aspect-auto w-auto",
  );
}

export function RoundIconButton({
  tone = "ghost",
  compact = false,
  wide = false,
  className,
  children,
  ...props
}: Omit<ComponentProps<typeof Button>, "ghost" | "size" | "destructive"> & {
  tone?: RoundTone;
  compact?: boolean;
  wide?: boolean;
}) {
  return (
    <Button type="button" ghost size="icon" className={cn(roundButtonClass(compact, wide), className)} {...props}>
      <span aria-hidden data-round-face={tone} className={roundFaceClass(tone, compact, wide)}>
        {children}
      </span>
    </Button>
  );
}

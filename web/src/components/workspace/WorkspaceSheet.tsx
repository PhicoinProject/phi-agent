// Container for the chat panels: a right-hand sheet on desktop, a bottom sheet
// on phones, a full-screen sheet on phones (the Computer view), or a floating
// widescreen window over the page on desktop (the Computer view).

import { useEffect, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { BottomSheet } from "@phi/ui/ui/components/bottom-sheet";
import { Button } from "@phi/ui/ui/components/button";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import { cn } from "@/lib/utils";

export type SheetMode = "right" | "bottom" | "full" | "window";

function SheetHeader({ title, onClose }: { title: string; onClose: () => void }) {
  const p = usePanelStrings();
  return (
    <header className="flex min-h-12 shrink-0 items-center gap-2 border-b border-current/10 px-3">
      <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{title}</h2>
      <Button type="button" ghost size="icon" aria-label={p.close} title={p.close} className="min-h-11 min-w-11" onClick={onClose}>
        <X className="h-4 w-4" />
      </Button>
    </header>
  );
}

/**
 * Window mode: a centred 16:9 window over a dimmed page. Its width is the largest that fits the
 * viewport once the panel's own header and toolbars (WINDOW_CHROME) are added under a 16:9 screen.
 */
export const WINDOW_CHROME = "11rem";
export const WINDOW_WIDTH = `min(94vw, calc((90vh - ${WINDOW_CHROME}) * 16 / 9))`;

export function WorkspaceSheet({
  open,
  mode,
  title,
  sheetId,
  onClose,
  header = true,
  children,
}: {
  open: boolean;
  mode: SheetMode;
  title: string;
  sheetId: string;
  onClose: () => void;
  /** False when the content brings its own header and close button. */
  header?: boolean;
  children: ReactNode;
}) {
  const p = usePanelStrings();

  useEffect(() => {
    // In the window, Esc belongs to the remote desktop; it closes from its own button.
    if (!open || mode === "bottom" || mode === "window") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !e.defaultPrevented) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, mode, onClose]);

  if (mode === "bottom") {
    return (
      <BottomSheet open={open} onClose={onClose} title={title} backdropDismissLabel={p.dismiss}>
        <div data-sheet={sheetId} data-sheet-mode="bottom" className="min-h-0 overflow-y-auto">
          {children}
        </div>
      </BottomSheet>
    );
  }
  if (!open) return null;
  if (mode === "window") {
    return createPortal(
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-[2vh]" data-sheet-backdrop={sheetId}>
        <div
          role="dialog"
          aria-modal="true"
          aria-label={title}
          data-sheet={sheetId}
          data-sheet-mode="window"
          className="flex max-h-full w-[var(--phi-window-width)] flex-col overflow-hidden rounded-lg border border-current/15 bg-background-base text-foreground shadow-2xl"
          style={{ "--phi-window-width": WINDOW_WIDTH } as CSSProperties}
        >
          {header && <SheetHeader title={title} onClose={onClose} />}
          <div className={cn("min-h-0 flex-1", header && "p-3")}>{children}</div>
        </div>
      </div>,
      document.body,
    );
  }
  return createPortal(
    <aside
      role="dialog"
      aria-label={title}
      data-sheet={sheetId}
      data-sheet-mode={mode}
      className={cn(
        "fixed z-50 flex flex-col bg-background-base text-foreground shadow-xl",
        mode === "right" ? "inset-y-0 right-0 w-full max-w-md border-l border-current/10" : "inset-0",
      )}
    >
      {header && <SheetHeader title={title} onClose={onClose} />}
      <div className={cn("min-h-0 flex-1 overflow-y-auto", header && "p-3")}>{children}</div>
    </aside>,
    document.body,
  );
}

// Small popover action menu (the @phi/ui dropdown is a value selector). Same
// shape as the profile card menu: closes on outside press, Escape or after an item.

import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "@phi/ui/ui/components/button";
import { cn } from "@/lib/utils";

export const MENU_ITEM_CLASS =
  "flex min-h-9 w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-midground/10 disabled:opacity-40 disabled:hover:bg-transparent";

export function ActionMenu({
  label,
  icon,
  open,
  onOpenChange,
  children,
  align = "right",
  triggerClassName,
}: {
  label: string;
  icon: ReactNode;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  align?: "left" | "right";
  triggerClassName?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: Event) => {
      if (!ref.current?.contains(e.target as Node | null)) onOpenChange(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onOpenChange(false);
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("touchstart", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("touchstart", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onOpenChange]);

  return (
    <div className="relative" ref={ref}>
      <Button
        type="button"
        ghost
        size="icon"
        title={label}
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        className={triggerClassName}
        onClick={(e) => {
          e.stopPropagation();
          onOpenChange(!open);
        }}
      >
        {icon}
      </Button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          className={cn(
            "absolute top-full z-50 mt-1.5 min-w-[220px] max-w-[min(320px,90vw)] rounded-lg border border-border bg-popover p-1 text-foreground shadow-xl shadow-black/30",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {children}
        </div>
      )}
    </div>
  );
}

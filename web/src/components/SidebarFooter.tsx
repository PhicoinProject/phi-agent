import { Typography } from "@phi/ui/ui/components/typography/index";
import type { StatusResponse } from "@/lib/api";
import { cn } from "@/lib/utils";

export function SidebarFooter({ status }: SidebarFooterProps) {
  return (
    <div
      className={cn(
        "flex shrink-0 items-center justify-between gap-2",
        "px-5 py-2.5",
        "border-t border-current/10",
      )}
    >
      <Typography
        className="font-mono-ui text-xs tabular-nums tracking-[0.08em] text-text-tertiary lowercase"
      >
        {status?.version != null ? `v${status.version}` : "—"}
      </Typography>

      <a
        href="https://github.com/PhicoinProject/phi-agent"
        target="_blank"
        rel="noopener noreferrer"
        className={cn(
          "font-sans text-xs font-medium text-midground",
          "transition-opacity hover:opacity-90",
          "focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-midground/40",
        )}
      >
        Phi Agent
      </a>
    </div>
  );
}

interface SidebarFooterProps {
  status: StatusResponse | null;
}

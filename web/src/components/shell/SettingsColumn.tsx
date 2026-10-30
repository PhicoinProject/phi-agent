// Column 2 in settings mode: the dashboard's full admin nav (moved here from
// the old App sidebar), the shell's own settings entries, profile switcher,
// system actions, theme / language and the gateway status footer.

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type FocusEvent,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import { NavLink, useNavigate } from "react-router";
import { ArrowLeft, Download, RotateCw } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { ConfirmDialog } from "@phi/ui/ui/components/confirm-dialog";
import { AuthWidget } from "@/components/AuthWidget";
import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { ProfileSwitcher } from "@/components/ProfileSwitcher";
import { SidebarFooter } from "@/components/SidebarFooter";
import { SidebarStatusStrip, gatewayLine } from "@/components/SidebarStatusStrip";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import type { SystemAction } from "@/contexts/system-actions-context";
import { useSystemActions } from "@/contexts/useSystemActions";
import { useI18n } from "@/i18n";
import type { Translations } from "@/i18n/types";
import { api } from "@/lib/api";
import type { StatusResponse, UpdateCheckResponse } from "@/lib/api";
import { sharedGatewayProfiles, sharedGatewayRestartDescription } from "@/lib/shared-gateway";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";
import { SHELL_SETTINGS_NAV } from "./settings-nav";
import { useShellStrings } from "./use-shell-strings";

export interface SettingsColumnProps {
  coreItems: NavItem[];
  pluginItems: NavItem[];
  status: StatusResponse | null;
  /** Called after a nav entry is chosen (closes the phone drawer). */
  onNavigate: () => void;
  /** Phone drawer: back to the space tree. */
  onBack?: () => void;
}

export function SettingsColumn({ coreItems, pluginItems, status, onNavigate, onBack }: SettingsColumnProps) {
  const { t } = useI18n();
  const s = useShellStrings();
  const tooltipWarmRef = useRef(0);
  const shellItems: NavItem[] = SHELL_SETTINGS_NAV.map((item) => ({
    path: item.path,
    label: s[item.labelKey],
    icon: item.icon,
  }));
  const navList = (items: NavItem[]) => (
    <ul className="flex flex-col">
      {items.map((item) => (
        <SidebarNavLink
          closeMobile={onNavigate}
          collapsed={false}
          item={item}
          key={item.path}
          t={t}
          tooltipWarmRef={tooltipWarmRef}
        />
      ))}
    </ul>
  );

  return (
    <section aria-label={s.settings} data-testid="settings-column" className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-11 shrink-0 items-center gap-2 border-b border-current/10 px-2">
        {onBack && (
          <Button type="button" ghost size="icon" aria-label={s.backToRooms} title={s.backToRooms} onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
        )}
        <h2 className="truncate px-2 text-sm font-semibold">{s.settings}</h2>
      </div>

      <ProfileSwitcher collapsed={false} />

      <nav
        className="min-h-0 w-full flex-1 overflow-y-auto overflow-x-hidden border-t border-current/10 py-2"
        aria-label={t.app.navigation}
      >
        {/* Chat is the rooms view, opened from column 1; the /chat route stays. */}
        {navList(coreItems.filter((item) => item.path !== "/chat"))}
        <div role="group" aria-label={s.settings} className="flex flex-col border-t border-current/10 pt-1">
          {navList(shellItems)}
        </div>
        {pluginItems.length > 0 && (
          <div
            aria-labelledby="phi-sidebar-plugin-nav-heading"
            className="flex flex-col border-t border-current/10 pb-2"
            role="group"
          >
            <span
              className="px-5 pt-3 pb-1 font-sans text-xs font-medium text-text-tertiary"
              id="phi-sidebar-plugin-nav-heading"
            >
              {t.app.pluginNavSection}
            </span>
            {navList(pluginItems)}
          </div>
        )}
      </nav>

      <SidebarSystemActions
        collapsed={false}
        onNavigate={onNavigate}
        status={status}
        tooltipWarmRef={tooltipWarmRef}
      />

      <div className="flex shrink-0 items-center justify-between gap-2 border-t border-current/10 px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          <PluginSlot name="header-right" />
          <ThemeSwitcher collapsed={false} dropUp />
          <LanguageSwitcher collapsed={false} dropUp />
        </div>
      </div>

      <div className="flex shrink-0 flex-col">
        <AuthWidget />
        <SidebarFooter status={status} />
      </div>
    </section>
  );
}

function SidebarNavLink({
  closeMobile,
  collapsed,
  item,
  tooltipWarmRef,
  t,
}: SidebarNavLinkProps) {
  const { path, label, labelKey, icon: Icon } = item;
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);

  const navLabel = labelKey
    ? ((t.app.nav as Record<string, string>)[labelKey] ?? label)
    : label;
  const showTooltip = (event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <li
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
    >
      <NavLink
        to={path}
        end={path === "/sessions"}
        onClick={closeMobile}
        aria-label={collapsed ? navLabel : undefined}
        onFocus={collapsed ? showTooltip : undefined}
        onBlur={collapsed ? hideTooltip : undefined}
        className={({ isActive }) =>
          cn(
            "group/nav relative mx-2 flex items-center gap-3 rounded-md",
            "px-3 py-2",
            "font-sans text-sm",
            "whitespace-nowrap transition-colors cursor-pointer",
            isActive
              ? "phi-nav-selected bg-midground/10 text-midground"
              : "text-text-secondary hover:bg-midground/5 hover:text-midground",
          )
        }
      >
        {() => (
          <>
            <Icon className="h-4 w-4 shrink-0" />

            <span
              className={cn(
                "truncate transition-opacity duration-300",
                collapsed ? "lg:opacity-0" : "lg:opacity-100",
              )}
            >
              {navLabel}
            </span>

          </>
        )}
      </NavLink>

      {collapsed && hovered && tooltipAnchor && (
        <SidebarTooltip anchor={tooltipAnchor} label={navLabel} warmRef={tooltipWarmRef} />
      )}
    </li>
  );
}

function SidebarSystemActions({
  collapsed,
  onNavigate,
  status,
  tooltipWarmRef,
}: SidebarSystemActionsProps) {
  const { t } = useI18n();
  const navigate = useNavigate();
  const { activeAction, isBusy, isRunning, pendingAction, runAction } =
    useSystemActions();
  const canUpdatePhi = status?.can_update_phi === true;
  // Served by the shared multiplexer: a restart blips every bot on this device — say which.
  const sharedGateway = sharedGatewayProfiles(status);
  const [restartConfirmOpen, setRestartConfirmOpen] = useState(false);
  const [updateConfirmOpen, setUpdateConfirmOpen] = useState(false);
  const [updateConfirmInfo, setUpdateConfirmInfo] =
    useState<UpdateCheckResponse | null>(null);
  const [updateConfirmChecking, setUpdateConfirmChecking] = useState(false);

  useEffect(() => {
    if (!updateConfirmOpen) {
      setUpdateConfirmInfo(null);
      return;
    }
    let cancelled = false;
    setUpdateConfirmChecking(true);
    api
      .checkPhiUpdate(false)
      .then((info) => {
        if (!cancelled) setUpdateConfirmInfo(info);
      })
      .catch(() => {
        if (!cancelled) setUpdateConfirmInfo(null);
      })
      .finally(() => {
        if (!cancelled) setUpdateConfirmChecking(false);
      });
    return () => {
      cancelled = true;
    };
  }, [updateConfirmOpen]);

  const updateConfirmDescription = useMemo(() => {
    if (updateConfirmInfo?.behind && updateConfirmInfo.behind > 0) {
      const cmd = updateConfirmInfo.update_command;
      const n = updateConfirmInfo.behind;
      return `This will run 'phi update' (${cmd}) and pull ${n} new commit${n === 1 ? "" : "s"}. The gateway restarts when the update finishes; the current session keeps its prompt cache until then.`;
    }
    const cmd = updateConfirmInfo?.update_command ?? "phi update";
    return (
      t.status.updatePhiConfirmMessage ??
      `This will run 'phi update' (${cmd}) and restart the gateway when it finishes.`
    );
  }, [t.status.updatePhiConfirmMessage, updateConfirmInfo]);

  const items: SystemActionItem[] = [
    {
      action: "restart",
      icon: RotateCw,
      label: t.status.restartGateway,
      runningLabel: t.status.restartingGateway,
      spin: true,
    },
  ];
  if (canUpdatePhi) {
    items.push({
      action: "update",
      icon: Download,
      label: t.status.updatePhi,
      runningLabel: t.status.updatingPhi,
      spin: false,
    });
  }

  const handleClick = (action: SystemAction) => {
    if (isBusy) return;
    if (action === "restart") {
      setRestartConfirmOpen(true);
      return;
    }
    if (action === "update") {
      setUpdateConfirmOpen(true);
      return;
    }
    void runAction(action);
    navigate("/sessions");
    onNavigate();
  };

  const confirmRestart = () => {
    setRestartConfirmOpen(false);
    void runAction("restart");
    navigate("/sessions");
    onNavigate();
  };

  const confirmUpdate = () => {
    setUpdateConfirmOpen(false);
    void runAction("update");
    navigate("/sessions");
    onNavigate();
  };

  return (
    <>
    <div
      className={cn(
        "shrink-0 flex flex-col",
        "border-t border-current/10",
        "py-1",
      )}
    >
      <span
        className={cn(
          "px-5 pt-0.5 pb-0.5",
          "font-sans text-xs font-medium text-text-tertiary",
          collapsed && "lg:hidden",
        )}
      >
        {t.app.system}
      </span>

      <div className={cn(collapsed && "lg:hidden")}>
        <SidebarStatusStrip status={status} />
      </div>

      <GatewayDot collapsed={collapsed} status={status} tooltipWarmRef={tooltipWarmRef} />

      <ul className="flex flex-col">
        {items.map((item) => (
          <SystemActionButton
            key={item.action}
            collapsed={collapsed}
            disabled={isBusy && !(pendingAction === item.action || (activeAction === item.action && isRunning))}
            tooltipWarmRef={tooltipWarmRef}
            isPending={pendingAction === item.action}
            isRunning={activeAction === item.action && isRunning && pendingAction !== item.action}
            item={item}
            onClick={() => handleClick(item.action)}
          />
        ))}
      </ul>
    </div>

    <ConfirmDialog
      cancelLabel={t.common.cancel}
      confirmLabel={sharedGateway ? "Restart all" : t.status.restartGateway}
      description={
        sharedGateway
          ? sharedGatewayRestartDescription(sharedGateway)
          : (t.status.restartGatewayConfirmMessage ??
            "This restarts the Phi gateway process. Connected channels and active sessions will reconnect afterward.")
      }
      loading={pendingAction === "restart"}
      onCancel={() => setRestartConfirmOpen(false)}
      onConfirm={confirmRestart}
      open={restartConfirmOpen}
      title={
        sharedGateway
          ? "Restart the shared gateway?"
          : (t.status.restartGatewayConfirmTitle ?? `${t.status.restartGateway}?`)
      }
    />

    <ConfirmDialog
      cancelLabel={t.common.cancel}
      confirmLabel={t.status.updatePhiConfirmNow ?? "Update now"}
      description={
        updateConfirmChecking ? t.common.loading : updateConfirmDescription
      }
      loading={pendingAction === "update" || updateConfirmChecking}
      onCancel={() => setUpdateConfirmOpen(false)}
      onConfirm={confirmUpdate}
      open={updateConfirmOpen}
      title={t.status.updatePhiConfirmTitle ?? `${t.status.updatePhi}?`}
    />
    </>
  );
}

function SystemActionButton({
  collapsed,
  disabled,
  isPending,
  isRunning: isActionRunning,
  item,
  onClick,
  tooltipWarmRef,
}: SystemActionButtonProps) {
  const { icon: Icon, label, runningLabel, spin } = item;
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);
  const busy = isPending || isActionRunning;
  const displayLabel = isActionRunning ? runningLabel : label;
  const showTooltip = (event: MouseEvent<HTMLElement> | FocusEvent<HTMLElement>) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <li
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
    >
      <button
        onClick={onClick}
        disabled={disabled}
        aria-busy={busy}
        aria-label={collapsed ? displayLabel : undefined}
        onFocus={collapsed ? showTooltip : undefined}
        onBlur={collapsed ? hideTooltip : undefined}
        type="button"
        className={cn(
          "group/action relative mx-2 flex w-[calc(100%-1rem)] items-center gap-3 rounded-md",
          "px-3 py-2",
          "font-sans text-sm",
          "whitespace-nowrap transition-colors cursor-pointer",
          busy
            ? "bg-brand/10 text-midground"
            : "text-text-secondary hover:bg-midground/5 hover:text-midground",
          "disabled:text-text-disabled disabled:cursor-not-allowed",
        )}
      >
        {isPending ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : isActionRunning && spin ? (
          <Spinner className="shrink-0 text-[0.875rem]" />
        ) : (
          <Icon
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              isActionRunning && !spin && "animate-pulse",
            )}
          />
        )}

        <span className={cn(
          "truncate transition-opacity duration-300",
          collapsed ? "lg:opacity-0" : "lg:opacity-100",
        )}>
          {displayLabel}
        </span>
      </button>

      {collapsed && hovered && tooltipAnchor && (
        <SidebarTooltip anchor={tooltipAnchor} label={displayLabel} warmRef={tooltipWarmRef} />
      )}
    </li>
  );
}


function GatewayDot({ collapsed, status, tooltipWarmRef }: GatewayDotProps) {
  const { t } = useI18n();
  const [hovered, setHovered] = useState(false);
  const [tooltipAnchor, setTooltipAnchor] = useState<HTMLElement | null>(null);

  const toneToColor: Record<string, string> = {
    "text-success": "bg-success",
    "text-warning": "bg-warning",
    "text-destructive": "bg-destructive",
    "text-muted-foreground": "bg-muted-foreground",
  };

  let color: string;
  let label: string;

  if (!status) {
    color = "bg-midground/20";
    label = t.status.gateway;
  } else {
    const gw = gatewayLine(status, t);
    color = toneToColor[gw.tone] ?? "bg-muted-foreground";
    label = `${t.status.gateway} ${gw.label}`;
  }
  const showTooltip = (event: MouseEvent<HTMLDivElement> | FocusEvent<HTMLDivElement>) => {
    setHovered(true);
    setTooltipAnchor(event.currentTarget);
  };
  const hideTooltip = () => {
    setHovered(false);
    setTooltipAnchor(null);
  };

  return (
    <div
      className={cn(
        "hidden lg:flex py-3 pl-[1.625rem] transition-opacity duration-300",
        collapsed ? "lg:opacity-100" : "lg:opacity-0 lg:h-0 lg:py-0 lg:overflow-hidden",
      )}
      role="status"
      aria-label={label}
      tabIndex={collapsed ? 0 : -1}
      onMouseEnter={collapsed ? showTooltip : undefined}
      onMouseLeave={collapsed ? hideTooltip : undefined}
      onFocus={collapsed ? showTooltip : undefined}
      onBlur={collapsed ? hideTooltip : undefined}
    >
      <span
        aria-hidden
        className={cn("h-1.5 w-1.5 rounded-full", color)}
      />

      {hovered && tooltipAnchor && (
        <SidebarTooltip anchor={tooltipAnchor} label={label} warmRef={tooltipWarmRef} />
      )}
    </div>
  );
}

function SidebarTooltip({ anchor, label, warmRef }: SidebarTooltipProps) {
  const rect = anchor.getBoundingClientRect();
  const sidebar = document.getElementById("app-sidebar");
  const sidebarRight = sidebar?.getBoundingClientRect().right ?? rect.right;
  const [isWarm, setIsWarm] = useState(false);

  useEffect(() => {
    if (!warmRef) {
      setIsWarm(false);
      return;
    }
    const now = Date.now();
    setIsWarm(now - warmRef.current < 300);
    warmRef.current = now;
    return () => {
      if (warmRef) warmRef.current = Date.now();
    };
  }, [warmRef]);

  return createPortal(
    <span
      className={cn(
        "fixed z-[100] pointer-events-none",
        "px-2 py-1",
        "rounded-lg bg-background-base border border-current/15 shadow-lg",
        "font-sans text-xs font-medium text-midground",
      )}
      style={{
        top: rect.top + rect.height / 2,
        left: sidebarRight + 8,
        transform: "translateY(-50%)",
        opacity: isWarm ? 1 : undefined,
        animation: isWarm ? "none" : "sidebar-tooltip-in 120ms ease-out",
      }}
    >
      {label}
    </span>,
    document.body,
  );
}

type TooltipWarmRef = React.RefObject<number>;

interface GatewayDotProps {
  collapsed: boolean;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}

export interface NavItem {
  icon: ComponentType<{ className?: string }>;
  label: string;
  labelKey?: string;
  path: string;
}


interface SidebarNavLinkProps {
  closeMobile: () => void;
  collapsed: boolean;
  item: NavItem;
  t: Translations;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarSystemActionsProps {
  collapsed: boolean;
  onNavigate: () => void;
  status: StatusResponse | null;
  tooltipWarmRef: TooltipWarmRef;
}

interface SidebarTooltipProps {
  anchor: HTMLElement;
  label: string;
  warmRef?: TooltipWarmRef;
}

interface SystemActionButtonProps {
  collapsed: boolean;
  disabled: boolean;
  isPending: boolean;
  isRunning: boolean;
  item: SystemActionItem;
  onClick: () => void;
  tooltipWarmRef: TooltipWarmRef;
}

interface SystemActionItem {
  action: SystemAction;
  icon: ComponentType<{ className?: string }>;
  label: string;
  runningLabel: string;
  spin: boolean;
}

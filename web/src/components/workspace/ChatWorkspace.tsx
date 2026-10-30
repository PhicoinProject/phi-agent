// The chat route with its workspace extras around ChatPage: dictation (mic +
// F8 on desktop, hold-to-talk on phones), the Plan / Ledger / Rules sheets, the
// Computer view (a floating widescreen window on desktop, full screen on
// phones) and the "needs you on the computer" card. ChatPage only gets props;
// the plan and help requests come from the chat channel's events feed.

import { useCallback, useEffect, useMemo, useState } from "react";
import { X } from "lucide-react";
import type { PlanUpdatedPayload } from "@phi/shared";
import { useBelowBreakpoint } from "@phi/ui/hooks/use-below-breakpoint";
import { Button } from "@phi/ui/ui/components/button";
import { ComputerPanel } from "@/components/computer/ComputerPanel";
import { LedgerPanel } from "@/components/ledger/LedgerPanel";
import { PlanPanel, planLabel, planView, usePlanUpdates } from "@/components/plan/PlanPanel";
import { useShellStrings } from "@/components/shell/use-shell-strings";
import { activeComposer, bracketedPaste, useComposerSink } from "@/components/voice/composer-bridge";
import { HoldToTalk } from "@/components/voice/HoldToTalk";
import { DEFAULT_VOICE_SHORTCUT, MicButton } from "@/components/voice/MicButton";
import type { DictationDeps } from "@/components/voice/useDictation";
import { VOICE_AUTO_SEND_KEY, readFlag } from "@/components/voice/voice-prefs";
import { RulesPanel } from "@/components/workspace/RulesPanel";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import { WorkspaceSheet } from "@/components/workspace/WorkspaceSheet";
import ChatPage, { type ChatBridge } from "@/pages/ChatPage";
import { api } from "@/lib/api";
import { EventsFeedClient } from "@/lib/eventsFeedClient";
import { EVENTS_MAX_RECONNECT_ATTEMPTS, eventsReconnectDelayMs, shouldRetryEventsClose } from "@/lib/events-reconnect";
import { GatewayClient } from "@/lib/gatewayClient";

type Sheet = "plan" | "ledger" | "rules" | "computer" | null;

/** Approval / clarify requests that are about the agent's desktop (`computer_use`). */
export function isComputerRequest(method: string, params: Record<string, unknown>): boolean {
  if (method !== "approval" && method !== "clarify") return false;
  if (typeof params.pattern_key === "string" && params.pattern_key.startsWith("cua:")) return true;
  const text = [params.description, params.question, params.command].filter((v) => typeof v === "string").join(" ");
  return /\bcomputer_use\b|\bdesktop\b|\bcomputer\b/i.test(text);
}

/** A field outside the chat (e.g. the Ctrl+K room search) owns the keyboard. */
function focusElsewhere(): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el || el === document.body) return false;
  const editable = el.isContentEditable || el.matches("input, textarea, select");
  return editable && !el.closest("[data-chat-scope]");
}

/** The chat channel's `/api/events` feed with the usual bounded reconnect ladder. */
function useEventsFeed(channel: string | null): EventsFeedClient | null {
  const [feed, setFeed] = useState<EventsFeedClient | null>(null);
  useEffect(() => {
    if (!channel) return;
    const client = new EventsFeedClient();
    let unmounting = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    const schedule = () => {
      if (unmounting || timer || attempt >= EVENTS_MAX_RECONNECT_ATTEMPTS) return;
      const delay = eventsReconnectDelayMs(attempt);
      attempt += 1;
      timer = setTimeout(() => {
        timer = null;
        void connect();
      }, delay);
    };
    const connect = async () => {
      if (unmounting) return;
      try {
        await client.connect(channel);
      } catch {
        if (!unmounting && client.lastCloseCode === null) schedule();
      }
    };
    const offClose = client.onClose((code) => {
      if (!unmounting && shouldRetryEventsClose(code)) schedule();
    });
    const offState = client.onState((state) => {
      if (state === "open") attempt = 0;
    });
    setFeed(client);
    void connect();
    return () => {
      unmounting = true;
      if (timer) clearTimeout(timer);
      offClose();
      offState();
      client.close();
      setFeed(null);
    };
  }, [channel]);
  return feed;
}

/** "The agent needs you on the computer": the open request's id, until answered or withdrawn. */
function useComputerHelp(feed: EventsFeedClient | null): [string | null, () => void] {
  const [help, setHelp] = useState<string | null>(null);
  useEffect(() => {
    setHelp(null);
    if (!feed) return;
    const offRequest = feed.onRequest((req) => {
      if (!isComputerRequest(req.method, req.params ?? {})) return false;
      setHelp(req.id);
      // The events feed only mirrors the request; the terminal answers it.
      return true;
    });
    const offCancel = feed.on("request.cancel", (ev) => {
      const id = ev.payload?.id;
      if (id) setHelp((cur) => (cur === id ? null : cur));
    });
    return () => {
      offRequest();
      offCancel();
    };
  }, [feed]);
  return [help, useCallback(() => setHelp(null), [])];
}

/** One gateway connection for the Computer sheet, dialed on first open. */
function useComputerGateway(wanted: boolean): GatewayClient | null {
  const [gateway, setGateway] = useState<GatewayClient | null>(null);
  useEffect(() => {
    if (!wanted) return;
    const gw = new GatewayClient();
    let alive = true;
    gw.connect().then(
      () => alive && setGateway(gw),
      () => undefined,
    );
    return () => {
      alive = false;
      gw.close();
      setGateway(null);
    };
  }, [wanted]);
  return gateway;
}

export default function ChatWorkspace({ isActive = true, voiceDeps }: { isActive?: boolean; voiceDeps?: DictationDeps }) {
  const p = usePanelStrings();
  const s = useShellStrings();
  const isPhone = useBelowBreakpoint(768);
  const [bridge, setBridge] = useState<ChatBridge | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [computerOpened, setComputerOpened] = useState(false);
  const [shortcut, setShortcut] = useState(DEFAULT_VOICE_SHORTCUT);

  useEffect(() => {
    let alive = true;
    api.getConfig().then(
      (cfg) => {
        const voice = (cfg as { voice?: { web_shortcut?: unknown } }).voice;
        if (alive && typeof voice?.web_shortcut === "string" && voice.web_shortcut) setShortcut(voice.web_shortcut);
      },
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, []);

  // The PTY is the composer while no richer one is mounted.
  const ptySink = useMemo(
    () =>
      bridge
        ? {
            insert: (text: string) => void bridge.writePty(bracketedPaste(text)),
            submit: () => void bridge.writePty("\r"),
          }
        : null,
    [bridge],
  );
  useComposerSink("pty", ptySink);

  const feed = useEventsFeed(bridge?.channel ?? null);
  const plan: PlanUpdatedPayload | null = usePlanUpdates(feed);
  const view = planView(plan);
  const [help, dismissHelp] = useComputerHelp(feed);

  const roomId = bridge?.roomId ?? null;
  useEffect(() => {
    if (!isActive || (!roomId && (sheet === "ledger" || sheet === "rules"))) setSheet(null);
  }, [isActive, roomId, sheet]);

  const openComputer = useCallback(() => {
    setComputerOpened(true);
    setSheet("computer");
  }, []);
  const gateway = useComputerGateway(computerOpened);
  const closeSheet = useCallback(() => setSheet(null), []);

  const insert = (text: string) => activeComposer()?.insert(text);
  const submit = () => activeComposer()?.submit();
  const shortcutEnabled = useCallback(() => isActive && !focusElsewhere(), [isActive]);

  const accessory = isPhone ? (
    // The phone's mic sits in the composer pill and only ever fills it; Send is the user's.
    <HoldToTalk deps={voiceDeps} releaseAction="fill" onFill={insert} />
  ) : (
    <MicButton
      deps={voiceDeps}
      shortcut={shortcut}
      autoSend={readFlag(VOICE_AUTO_SEND_KEY)}
      shortcutEnabled={shortcutEnabled}
      onFinal={insert}
      onSend={submit}
    />
  );

  const headerActions = {
    planLabel: view ? planLabel(view, p) : undefined,
    onOpenPlan: view ? () => setSheet("plan") : undefined,
    onOpenComputer: openComputer,
    onOpenLedger: roomId ? () => setSheet("ledger") : undefined,
    onOpenRules: roomId ? () => setSheet("rules") : undefined,
  };

  const panelMode = isPhone ? "bottom" : "right";
  return (
    <>
      {/* The Computer window floats over the page, so opening it never remounts the terminal. */}
      <div className="flex min-h-0 min-w-0 flex-1">
        <div data-chat-scope className="flex min-h-0 min-w-0 flex-1 flex-col">
          <ChatPage isActive={isActive} composerAccessory={accessory} headerActions={headerActions} onBridge={setBridge} />
        </div>
        <WorkspaceSheet
          open={sheet === "computer"}
          mode={isPhone ? "full" : "window"}
          sheetId="computer"
          title={s.computer}
          header={!gateway}
          onClose={closeSheet}
        >
          {gateway ? (
            <ComputerPanel gateway={gateway} mobile={isPhone} onClose={closeSheet} className="h-full" />
          ) : (
            <p className="text-sm opacity-70">{p.connecting}</p>
          )}
        </WorkspaceSheet>
      </div>

      {isActive && help && (
        <div
          role="alert"
          data-testid="computer-help"
          className="fixed bottom-24 left-1/2 z-40 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-current/15 bg-background-base px-3 py-2 text-sm shadow-lg"
        >
          <span>{p.needsComputer}</span>
          <Button
            type="button"
            size="sm"
            onClick={() => {
              dismissHelp();
              openComputer();
            }}
          >
            {p.open}
          </Button>
          <Button type="button" ghost size="icon" aria-label={p.dismiss} title={p.dismiss} onClick={dismissHelp}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      <WorkspaceSheet open={sheet === "plan"} mode={panelMode} sheetId="plan" title={s.plan} onClose={closeSheet}>
        <PlanPanel payload={plan} />
      </WorkspaceSheet>
      {roomId && (
        <>
          <WorkspaceSheet open={sheet === "ledger"} mode={panelMode} sheetId="ledger" title={s.ledger} onClose={closeSheet}>
            <LedgerPanel roomId={roomId} />
          </WorkspaceSheet>
          <WorkspaceSheet open={sheet === "rules"} mode={panelMode} sheetId="rules" title={s.rules} onClose={closeSheet}>
            <RulesPanel roomId={roomId} />
          </WorkspaceSheet>
        </>
      )}
    </>
  );
}

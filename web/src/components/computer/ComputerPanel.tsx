/**
 * Computer panel: co-drive the bot desktop with the agent over noVNC and a shared display lease.
 *
 * Opening the panel goes straight into a session: a stopped desktop is started once (Retry only
 * after that fails) and, once live, Take over (the default) acquires the shared lease with no
 * confirmation, so the user and the agent can act at the same time. Watch releases it and is view
 * only; Hand back releases it and gives the optional note to the caller. When another viewer holds
 * control the panel opens in Watch and taking over from them asks first; when another viewer takes
 * control the bridge closes our stream with 4000 and the panel re-attaches in Watch. Below 768 px
 * the panel goes full screen with panzoom (pinch, pan, double-tap 2x) and a key bar, and asks for
 * landscape. On desktop the header toggles full screen (the Fullscreen API, else a fixed overlay).
 */
import type {
  DisplayLease,
  DisplayLeasePayload,
  DisplayLeaseResult,
  DisplayObserveResult,
  DisplayStatus,
  DisplayStatusPayload,
} from "@phi/shared";
import { buildPhiWebSocketUrl } from "@phi/shared";
import Panzoom, { type PanzoomOptions } from "@panzoom/panzoom";
import { useBelowBreakpoint } from "@phi/ui/hooks/use-below-breakpoint";
import { Button } from "@phi/ui/ui/components/button";
import { Segmented } from "@phi/ui/ui/components/segmented";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, ChevronLeft, Maximize2, Minimize2, Minus, Plus, X } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent as ReactClipboardEvent,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import { PHI_BASE_PATH } from "@/lib/api";
import { cn } from "@/lib/utils";

import {
  CLOSE_CONTROL_TAKEN,
  correctForPanzoom,
  EVICTION_LOOP_WINDOW_MS,
  KEYSYM,
  keysymForChar,
  leaseHeldBy,
  MAX_PASTE_CUT_TEXT,
  MAX_RAPID_EVICTIONS,
  MOBILE_BREAKPOINT,
  parseGeometry,
  SPECIAL_KEYS,
} from "./computerModel";

/** The slice of GatewayClient the panel needs. */
export interface ComputerGateway {
  request<T>(method: string, params?: Record<string, unknown>): Promise<T>;
  on(type: "display.lease" | "display.status", handler: (event: { payload?: unknown }) => void): () => void;
}

/** The slice of noVNC's RFB the panel drives. */
export interface RfbClient extends EventTarget {
  viewOnly: boolean;
  scaleViewport: boolean;
  resizeSession: boolean;
  focusOnClick: boolean;
  background: string;
  qualityLevel: number;
  disconnect(): void;
  sendKey(keysym: number, code: string | null, down?: boolean): void;
  sendCtrlAltDel(): void;
  focus(): void;
  clipboardPasteFrom(text: string): void;
}

export type RfbConstructor = new (target: HTMLElement, channel: WebSocket, options?: { shared?: boolean }) => RfbClient;

export interface PanzoomLike {
  getScale(): number;
  reset(): void;
  setOptions(options: { disablePan?: boolean }): void;
  zoomToPoint(scale: number, point: { clientX: number; clientY: number }): void;
  destroy(): void;
}

export interface ComputerPanelProps {
  gateway: ComputerGateway;
  profile?: string;
  /** Force the phone layout; defaults to viewport width below 768 px. */
  mobile?: boolean;
  loadRfb?: () => Promise<RfbConstructor>;
  createSocket?: (url: string) => WebSocket;
  createPanzoom?: (elem: HTMLElement, options: PanzoomOptions) => PanzoomLike;
  /** Called after a successful hand back with the (possibly empty) note for the agent. */
  onHandBack?: (note: string) => void;
  onClose?: () => void;
  className?: string;
}

type Conn = "idle" | "attaching" | "live" | "error";
type Mode = "takeover" | "watch";

const loadNoVnc = () => import("@novnc/novnc").then((m): RfbConstructor => m.default);
const openSocket = (url: string) => new WebSocket(url);
const startPanzoom = (elem: HTMLElement, options: PanzoomOptions): PanzoomLike => Panzoom(elem, options);

const PANZOOM_OPTIONS: PanzoomOptions = {
  contain: "outside",
  // Let the pointer reach noVNC too; panning is switched off per gesture while holding instead.
  handleStartEvent: () => undefined,
  maxScale: 5,
  minScale: 1,
  panOnlyWhenZoomed: true,
  pinchAndPan: true,
};
const DOUBLE_TAP_MS = 350;
const DOUBLE_TAP_PX = 50;
const ZOOM_STEP = 1.25;

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));
const clampZoom = (z: number) => Math.min(4, Math.max(0.25, z));

// lib.dom dropped ScreenOrientation.lock (it is missing on iOS); it is still there on Android.
type LockableOrientation = ScreenOrientation & { lock?: (orientation: "landscape") => Promise<void> };

/** True when the phone is now held in landscape for us. Browsers only lock the orientation of a
 *  full-screen document, so the page goes full screen first (Android Chrome). iOS Safari has
 *  neither API: there the panel stays edge to edge and asks once to turn the phone. */
async function lockLandscape(): Promise<boolean> {
  const orientation = screen.orientation as LockableOrientation | undefined;
  if (!orientation?.lock) return false;
  try {
    if (!document.fullscreenElement && typeof document.documentElement.requestFullscreen === "function") {
      await document.documentElement.requestFullscreen({ navigationUI: "hide" }).catch(() => undefined);
    }
    await orientation.lock("landscape");
    return true;
  } catch {
    return false;
  }
}

export function ComputerPanel({
  className,
  createPanzoom = startPanzoom,
  createSocket = openSocket,
  gateway,
  loadRfb = loadNoVnc,
  mobile: mobileProp,
  onClose,
  onHandBack,
  profile,
}: ComputerPanelProps) {
  const { t } = useI18n();
  const s = { ...en.voiceComputer!, ...t.voiceComputer };
  const belowBreakpoint = useBelowBreakpoint(MOBILE_BREAKPOINT);
  const mobile = mobileProp ?? belowBreakpoint;

  const [status, setStatus] = useState<DisplayStatus | null>(null);
  const [lease, setLease] = useState<DisplayLease | null>(null);
  // The lease names its holder by viewer_hash; this is the hash our own acquire came back with.
  const [heldHash, setHeldHash] = useState<string | null>(null);
  const [viewerId, setViewerId] = useState<string | null>(null);
  const [conn, setConn] = useState<Conn>("idle");
  const [error, setError] = useState<string | null>(null);
  const [evicted, setEvicted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // What the user asked for; Take over holds the shared lease whenever nobody else does.
  const [mode, setMode] = useState<Mode>("takeover");
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);
  // The profile_key whose stopped desktop this panel already started once.
  const [autoStarted, setAutoStarted] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [zoom, setZoom] = useState<"fit" | number>("fit");
  const [latched, setLatched] = useState({ alt: false, ctrl: false });
  // Full screen pins the panel over the page; "native" also has the browser hide its own UI.
  const [fullscreen, setFullscreen] = useState<"off" | "native" | "overlay">("off");
  const [sidewaysHint, setSidewaysHint] = useState(false);

  const stageRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLDivElement>(null);
  const kbdRef = useRef<HTMLInputElement>(null);
  const rfbRef = useRef<RfbClient | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const panzoomRef = useRef<PanzoomLike | null>(null);
  const pointersRef = useRef(new Set<number>());
  const genRef = useRef(0);
  // observe must re-present the viewer id minted on this gateway connection.
  const viewerIdRef = useRef<string | null>(null);
  const evictionsRef = useRef<number[]>([]);
  const iHoldRef = useRef(false);
  // Our acquire's own display.lease broadcast can land before its answer names us as the holder.
  const acquiringRef = useRef(false);

  const iHold = leaseHeldBy(lease, heldHash);
  const otherHolds = Boolean(lease && lease.holder !== "agent" && !iHold);
  const running = Boolean(status?.running);
  const profileKey = status?.profile_key ?? null;
  const geometry = parseGeometry(status?.geometry);

  const withProfile = (params: Record<string, unknown> = {}) => (profile ? { ...params, profile } : params);

  const refresh = async () => {
    try {
      const next = await gateway.request<DisplayStatus>("display.status", withProfile());
      setStatus(next);
      setLease(next.lease);
    } catch (e) {
      setError(errorText(e));
    }
  };

  /** Tear the stream down. Only a deliberate close (1000) makes the bridge hand control back. */
  const detach = (release: boolean) => {
    genRef.current += 1;
    const rfb = rfbRef.current;
    const ws = wsRef.current;
    rfbRef.current = null;
    wsRef.current = null;
    if (release) ws?.close(1000);
    rfb?.disconnect();
    return genRef.current;
  };

  const attach = async () => {
    const gen = detach(false);
    setConn("attaching");
    setError(null);
    let Rfb: RfbConstructor;
    let observed: DisplayObserveResult;
    try {
      Rfb = await loadRfb();
      if (gen !== genRef.current) return;
      const prior = viewerIdRef.current;
      observed = await gateway.request<DisplayObserveResult>("display.observe", withProfile(prior ? { viewer_id: prior } : {}));
    } catch (e) {
      if (gen === genRef.current) {
        setConn("error");
        setError(errorText(e));
      }
      return;
    }
    const target = targetRef.current;
    if (gen !== genRef.current || !target) return;
    const { path, ticket, viewer_id: minted, ...next } = observed;
    if (minted !== viewerIdRef.current) {
      viewerIdRef.current = minted;
      setViewerId(minted);
      setHeldHash(null);
    }
    setStatus(next);
    setLease(next.lease);

    const ws = createSocket(buildPhiWebSocketUrl({ basePath: PHI_BASE_PATH, params: { display_ticket: ticket }, path }));
    ws.binaryType = "arraybuffer";
    let closeCode = 0;
    let closeReason = "";
    ws.addEventListener("close", (ev) => {
      closeCode = ev.code;
      closeReason = ev.reason;
    });
    const rfb = new Rfb(target, ws, { shared: true });
    rfb.viewOnly = true;
    rfb.scaleViewport = true;
    rfb.resizeSession = false;
    rfb.focusOnClick = true;
    rfb.background = "transparent";
    rfb.qualityLevel = 7;
    rfbRef.current = rfb;
    wsRef.current = ws;

    rfb.addEventListener("connect", () => {
      if (gen !== genRef.current) return;
      setConn("live");
      setEvicted(false);
      setError(null);
    });
    rfb.addEventListener("disconnect", () => {
      if (gen !== genRef.current) return;
      rfbRef.current = null;
      wsRef.current = null;
      if (closeCode === CLOSE_CONTROL_TAKEN || closeReason.includes("control-taken")) {
        const now = Date.now();
        const recent = [...evictionsRef.current.filter((at) => now - at < EVICTION_LOOP_WINDOW_MS), now];
        evictionsRef.current = recent;
        if (recent.length > MAX_RAPID_EVICTIONS) {
          setConn("error");
          setError(s.controlTaken);
          return;
        }
        setMode("watch");
        setEvicted(true);
        void attach();
        return;
      }
      setConn("error");
      setError(s.streamLost);
      // A stopped desktop then shows as stopped rather than as a lost stream.
      void refresh();
    });
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gateway, profile]);

  useEffect(() => {
    if (profileKey === null) return;
    const ours = (key: unknown) => key === profileKey;
    const offLease = gateway.on("display.lease", (event) => {
      const payload = event.payload as DisplayLeasePayload | undefined;
      if (payload?.lease && ours(payload.profile_key)) setLease(payload.lease);
    });
    const offStatus = gateway.on("display.status", (event) => {
      const payload = event.payload as DisplayStatusPayload | undefined;
      if (!payload || !ours(payload.profile_key)) return;
      setStatus(payload);
      setLease(payload.lease);
    });
    return () => {
      offLease();
      offStatus();
    };
  }, [gateway, profileKey]);

  useEffect(() => {
    if (running) void attach();
    else detach(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [running]);

  useEffect(
    () => () => {
      detach(true);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  useEffect(() => {
    iHoldRef.current = iHold;
    panzoomRef.current?.setOptions({ disablePan: iHold && pointersRef.current.size < 2 });
    const rfb = rfbRef.current;
    if (!rfb) return;
    rfb.viewOnly = !iHold;
    if (iHold) rfb.focus();
  }, [iHold, conn]);

  useEffect(() => {
    if (!notice) return;
    const id = window.setTimeout(() => setNotice(null), 4000);
    return () => window.clearTimeout(id);
  }, [notice]);

  useEffect(() => {
    if (fullscreen === "off") return;
    // Leaving native full screen (Esc, browser UI) only shows up as fullscreenchange.
    const onChange = () => {
      if (fullscreen === "native" && !document.fullscreenElement) setFullscreen("off");
    };
    const onKey = (e: KeyboardEvent) => {
      if (fullscreen !== "overlay" || e.key !== "Escape" || e.defaultPrevented) return;
      e.preventDefault();
      setFullscreen("off");
    };
    document.addEventListener("fullscreenchange", onChange);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("fullscreenchange", onChange);
      window.removeEventListener("keydown", onKey);
      // Toggled off, or the panel closed while full screen: give the page back.
      if (fullscreen === "native" && document.fullscreenElement) void document.exitFullscreen().catch(() => undefined);
    };
  }, [fullscreen]);

  // Phones: ask for landscape; where the browser refuses and the phone is upright, say so once.
  useEffect(() => {
    if (!mobile) return;
    let alive = true;
    let locked = false;
    void lockLandscape().then((ok) => {
      locked = ok;
      if (alive && !ok && window.innerHeight > window.innerWidth) setSidewaysHint(true);
    });
    const onResize = () => {
      if (window.innerWidth >= window.innerHeight) setSidewaysHint(false);
    };
    window.addEventListener("resize", onResize);
    return () => {
      alive = false;
      window.removeEventListener("resize", onResize);
      if (locked) screen.orientation.unlock();
    };
  }, [mobile]);

  // Phone layout: panzoom on the noVNC target. One finger drives noVNC only while holding; in Watch
  // it pans. noVNC maps gestures with the transformed canvas rect, so correct them for the zoom.
  useEffect(() => {
    const stage = stageRef.current;
    const target = targetRef.current;
    if (!mobile || !running || !stage || !target) return;
    const pz = createPanzoom(target, PANZOOM_OPTIONS);
    panzoomRef.current = pz;
    const pointers = pointersRef.current;
    const syncPan = () => pz.setOptions({ disablePan: iHoldRef.current && pointers.size < 2 });
    const onPointerDown = (e: PointerEvent) => {
      pointers.add(e.pointerId);
      syncPan();
    };
    const onPointerUp = (e: PointerEvent) => {
      pointers.delete(e.pointerId);
      syncPan();
    };
    let lastTap: { at: number; x: number; y: number } | null = null;
    const onGesture = (e: Event) => {
      const detail = (e as CustomEvent<{ type: string; clientX: number; clientY: number }>).detail;
      if (detail.type === "twodrag" || detail.type === "pinch") {
        e.stopPropagation();
        return;
      }
      if (!iHoldRef.current) {
        if (e.type !== "gesturestart" || detail.type !== "onetap") return;
        const now = Date.now();
        const tap = { at: now, x: detail.clientX, y: detail.clientY };
        if (lastTap && now - lastTap.at < DOUBLE_TAP_MS && Math.hypot(tap.x - lastTap.x, tap.y - lastTap.y) < DOUBLE_TAP_PX) {
          pz.zoomToPoint(2, { clientX: tap.x, clientY: tap.y });
          lastTap = null;
        } else {
          lastTap = tap;
        }
        return;
      }
      const rect = (e.target as HTMLElement).getBoundingClientRect();
      const fixed = correctForPanzoom(detail, rect, pz.getScale());
      detail.clientX = fixed.clientX;
      detail.clientY = fixed.clientY;
    };
    const gestures = ["gesturestart", "gesturemove", "gestureend"];
    stage.addEventListener("pointerdown", onPointerDown, true);
    stage.addEventListener("pointerup", onPointerUp, true);
    stage.addEventListener("pointercancel", onPointerUp, true);
    gestures.forEach((type) => stage.addEventListener(type, onGesture, true));
    return () => {
      stage.removeEventListener("pointerdown", onPointerDown, true);
      stage.removeEventListener("pointerup", onPointerUp, true);
      stage.removeEventListener("pointercancel", onPointerUp, true);
      gestures.forEach((type) => stage.removeEventListener(type, onGesture, true));
      pointers.clear();
      pz.reset();
      pz.destroy();
      panzoomRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mobile, running]);

  const start = async () => {
    setStarting(true);
    setStartError(null);
    try {
      const next = await gateway.request<DisplayStatus>("display.start", withProfile());
      setStatus(next);
      setLease(next.lease);
    } catch (e) {
      setStartError(errorText(e));
    } finally {
      setStarting(false);
    }
  };

  /** Take the shared lease: the agent keeps acting while this panel sends input too. */
  const acquire = async () => {
    const vid = viewerIdRef.current;
    if (!vid || acquiringRef.current) return;
    acquiringRef.current = true;
    setBusy(true);
    try {
      const res = await gateway.request<DisplayLeaseResult>("display.lease.acquire", withProfile({ mode: "shared", viewer_id: vid }));
      setLease(res.lease);
      if (res.lease.holder !== "agent" && res.lease.viewer_hash) setHeldHash(res.lease.viewer_hash);
      if (!rfbRef.current) void attach();
    } catch (e) {
      // Back to Watch, or Take over would retry the refused acquire on every render.
      setMode("watch");
      setNotice(errorText(e));
    } finally {
      acquiringRef.current = false;
      setBusy(false);
    }
  };

  /** Release the lease (Watch, or Hand back with a note for the agent when `handBackNote` is set). */
  const release = async (handBackNote: string | null) => {
    const vid = viewerIdRef.current;
    // Watch first: the agent lease broadcast must not look like a free desktop to Take over.
    setMode("watch");
    setBusy(true);
    try {
      const res = await gateway.request<DisplayLeaseResult>("display.lease.release", withProfile(vid ? { viewer_id: vid } : {}));
      setLease(res.lease);
      if (handBackNote !== null) {
        onHandBack?.(handBackNote.trim());
        setNote("");
      }
    } catch (e) {
      setMode("takeover");
      setNotice(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const changeMode = (next: Mode) => {
    if (busy || next === mode) return;
    if (next === "watch") {
      if (iHold) void release(null);
      else setMode("watch");
    } else if (otherHolds) {
      setConfirmOpen(true);
    } else {
      setMode("takeover");
    }
  };

  const confirmTakeOver = () => {
    setConfirmOpen(false);
    setMode("takeover");
    void acquire();
  };

  // Opening the panel goes straight into a session: a stopped desktop is started once per screen.
  useEffect(() => {
    if (!status?.installed || status.running || autoStarted === status.profile_key) return;
    setAutoStarted(status.profile_key);
    void start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, autoStarted]);

  // Take over holds the shared lease whenever nobody else does; another viewer's lease means Watch.
  useEffect(() => {
    if (mode !== "takeover" || iHold || acquiringRef.current) return;
    if (otherHolds) setMode("watch");
    else if (running && conn === "live" && viewerId) void acquire();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, running, conn, viewerId, iHold, otherHolds]);

  const reconnect = () => {
    evictionsRef.current = [];
    void attach();
  };

  const sendText = (text: string) => {
    const rfb = rfbRef.current;
    if (!rfb || !iHold) return;
    if (new TextEncoder().encode(text).length > MAX_PASTE_CUT_TEXT) {
      setNotice(s.pasteTooLong);
      return;
    }
    rfb.clipboardPasteFrom(text);
    setNotice(s.pasteSent);
  };

  const paste = async () => {
    let text: string | null;
    try {
      text = await navigator.clipboard.readText();
    } catch {
      // No async clipboard (plain HTTP, or permission denied): ask for the text instead.
      text = window.prompt(s.pastePrompt);
    }
    if (text) sendText(text);
  };

  const onStagePaste = (e: ReactClipboardEvent<HTMLDivElement>) => {
    const text = e.clipboardData.getData("text/plain");
    if (text) sendText(text);
  };

  const sendKey = (keysym: number, code: string | null) => {
    const rfb = rfbRef.current;
    if (!rfb || !iHold) return;
    const mods: Array<[number, string]> = [];
    if (latched.ctrl) mods.push([KEYSYM.Control, "ControlLeft"]);
    if (latched.alt) mods.push([KEYSYM.Alt, "AltLeft"]);
    mods.forEach(([sym, c]) => rfb.sendKey(sym, c, true));
    rfb.sendKey(keysym, code);
    mods.reverse().forEach(([sym, c]) => rfb.sendKey(sym, c, false));
    if (mods.length) setLatched({ alt: false, ctrl: false });
  };

  const onKbdInput = (e: FormEvent<HTMLInputElement>) => {
    const input = e.currentTarget;
    const chars = Array.from(input.value);
    input.value = "";
    const rfb = rfbRef.current;
    if (!rfb || !iHold || !chars.length) return;
    sendKey(keysymForChar(chars[0]), null);
    chars.slice(1).forEach((ch) => rfb.sendKey(keysymForChar(ch), null));
  };

  const onKbdKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    const special = SPECIAL_KEYS[e.key];
    if (!special) return;
    e.preventDefault();
    sendKey(special.keysym, special.code);
  };

  const zoomBy = (factor: number) => {
    const fitScale = (stageRef.current?.clientWidth || geometry.width) / geometry.width;
    setZoom((z) => clampZoom((z === "fit" ? fitScale : z) * factor));
  };

  // The whole page goes full screen, not just the panel, so dialogs portalled to <body> (Take over)
  // stay visible; the panel covers the page as the overlay either way.
  const toggleFullscreen = async () => {
    if (fullscreen !== "off") {
      setFullscreen("off");
      return;
    }
    const page = document.documentElement;
    if (typeof page.requestFullscreen === "function") {
      try {
        await page.requestFullscreen();
        setFullscreen("native");
        return;
      } catch {
        // Refused (iframe, permissions policy): fall back to the overlay alone.
      }
    }
    setFullscreen("overlay");
  };

  const geometryText = `${geometry.width}x${geometry.height}`;
  const otherDriving = s.otherDriving.replace("{viewer}", lease?.viewer_hash || "?");

  const modeSwitch = running && (
    <Segmented
      className={mobile ? undefined : "ml-2"}
      onChange={changeMode}
      options={[
        { label: s.takeOver, value: "takeover" },
        { label: s.watch, value: "watch" },
      ]}
      value={mode}
    />
  );

  const desktopHeader = (
    <header className="flex items-center gap-2 border-b border-border px-3 py-2 text-sm">
      <span className="font-semibold">{s.computer}</span>
      <span className="text-muted-foreground">
        · {s.botDesktop} {geometryText}
      </span>
      {modeSwitch}
      <div className="ml-auto flex items-center gap-1">
        <Button aria-pressed={zoom === "fit"} ghost onClick={() => setZoom("fit")} size="sm" type="button">
          {s.fit}
        </Button>
        <Button aria-pressed={zoom === 1} ghost onClick={() => setZoom(1)} size="sm" type="button">
          {s.actualSize}
        </Button>
        <Button aria-label={s.zoomOut} ghost onClick={() => zoomBy(1 / ZOOM_STEP)} size="icon" type="button">
          <Minus />
        </Button>
        <Button aria-label={s.zoomIn} ghost onClick={() => zoomBy(ZOOM_STEP)} size="icon" type="button">
          <Plus />
        </Button>
        <Button
          aria-label={fullscreen === "off" ? s.fullScreen : s.exitFullScreen}
          aria-pressed={fullscreen !== "off"}
          data-testid="computer-fullscreen"
          ghost
          onClick={() => void toggleFullscreen()}
          size="icon"
          type="button"
        >
          {fullscreen === "off" ? <Maximize2 /> : <Minimize2 />}
        </Button>
        {onClose && (
          <Button aria-label={s.close} ghost onClick={onClose} size="icon" type="button">
            <X />
          </Button>
        )}
      </div>
    </header>
  );

  const mobileHeader = (
    <header className="flex items-center gap-2 border-b border-border px-2 py-2 text-sm">
      {onClose ? (
        <Button aria-label={s.back} ghost onClick={onClose} size="sm" type="button">
          <ChevronLeft className="size-3.5" /> {s.computer}
        </Button>
      ) : (
        <span className="font-semibold">{s.computer}</span>
      )}
      <span className={cn("min-w-0 truncate", iHold ? "text-midground" : "text-muted-foreground")}>
        {iHold ? s.youControlShort : otherHolds ? otherDriving : s.watching}
      </span>
      <div className="ml-auto flex items-center gap-1">
        {modeSwitch}
        {iHold && (
          <Button outlined disabled={busy} onClick={() => void release("")} size="sm" type="button">
            {s.handBack}
          </Button>
        )}
      </div>
    </header>
  );

  const statusLine = (
    <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2 text-sm">
      <span
        className={cn(
          "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
          iHold ? "bg-brand/15 text-midground" : "text-muted-foreground",
        )}
      >
        {iHold && <span aria-hidden className="size-1.5 rounded-full bg-brand" />}
        {iHold ? s.youControl : otherHolds ? otherDriving : s.agentDriving}
      </span>
      {iHold && (
        <>
          <label className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            {s.noteToAgent}:
            <input
              aria-label={s.noteToAgent}
              className="h-8 w-48 rounded-md border border-border border-b-midground/30 bg-midground/5 px-2 text-foreground focus-visible:border-b-2 focus-visible:border-b-brand focus-visible:outline-none"
              data-testid="computer-note"
              onChange={(e) => setNote(e.target.value)}
              value={note}
            />
          </label>
          <Button outlined disabled={busy} onClick={() => void release(note)} size="sm" type="button">
            {s.handBack}
          </Button>
        </>
      )}
    </div>
  );

  const keyButton = (label: string, keysym: number, code: string) => (
    <Button disabled={!iHold} key={code} onClick={() => sendKey(keysym, code)} outlined size="sm" type="button">
      {label}
    </Button>
  );

  const arrows: Array<[string, typeof ArrowUp, number, string]> = [
    [s.arrowUp, ArrowUp, KEYSYM.Up, "ArrowUp"],
    [s.arrowDown, ArrowDown, KEYSYM.Down, "ArrowDown"],
    [s.arrowLeft, ArrowLeft, KEYSYM.Left, "ArrowLeft"],
    [s.arrowRight, ArrowRight, KEYSYM.Right, "ArrowRight"],
  ];

  const latchButton = (label: string, key: "alt" | "ctrl") => (
    <Button
      aria-pressed={latched[key]}
      className={latched[key] ? "border-brand bg-brand/15 text-midground" : undefined}
      onClick={() => setLatched((l) => ({ ...l, [key]: !l[key] }))}
      outlined
      size="sm"
      type="button"
    >
      {label}
    </Button>
  );

  const mobileKeyRow = (
    <div className="flex flex-wrap items-center gap-1 border-b border-border px-2 py-1">
      {keyButton("Esc", KEYSYM.Escape, "Escape")}
      {keyButton("Tab", KEYSYM.Tab, "Tab")}
      {latchButton("Ctrl", "ctrl")}
      {latchButton("Alt", "alt")}
      {arrows.map(([label, Icon, keysym, code]) => (
        <Button aria-label={label} key={code} onClick={() => sendKey(keysym, code)} outlined size="icon" type="button">
          <Icon />
        </Button>
      ))}
    </div>
  );

  const desktopToolbar = (
    <div className="flex flex-wrap items-center gap-1 border-t border-border px-3 py-2">
      <Button disabled={!iHold} onClick={() => rfbRef.current?.sendCtrlAltDel()} outlined size="sm" type="button">
        Ctrl+Alt+Del
      </Button>
      {keyButton("Esc", KEYSYM.Escape, "Escape")}
      {keyButton("Tab", KEYSYM.Tab, "Tab")}
      <Button disabled={!iHold} onClick={() => void paste()} outlined size="sm" type="button">
        {s.paste}
      </Button>
    </div>
  );

  const mobileBottomBar = (
    <div className="flex items-center gap-2 border-t border-border px-2 py-2">
      <Button onClick={() => panzoomRef.current?.reset()} outlined size="sm" type="button">
        {s.fit}
      </Button>
      <Button
        aria-label={s.keyboardHint}
        className="ml-auto"
        disabled={!iHold}
        onClick={() => kbdRef.current?.focus()}
        outlined
        size="sm"
        type="button"
      >
        {s.keyboard}
      </Button>
    </div>
  );

  let body: ReactNode;
  if (!status) {
    body = <p className="p-4 text-sm text-muted-foreground">{error ?? s.connecting}</p>;
  } else if (!status.installed) {
    body = (
      <div className="flex flex-col gap-2 p-4 text-sm">
        <p>{s.notInstalled}</p>
        {status.blocker && <p className="text-muted-foreground">{status.blocker}</p>}
        {status.install_command ? (
          <p className="text-muted-foreground">
            {s.installWith} <span className="font-courier break-all text-foreground select-all">{status.install_command}</span>
          </p>
        ) : (
          status.missing.length > 0 && <p className="font-mono text-xs text-muted-foreground">{status.missing.join(", ")}</p>
        )}
      </div>
    );
  } else if (!running) {
    body = (
      <div className="flex flex-col items-start gap-2 p-4 text-sm">
        <p>
          {startError
            ? s.startFailed.replace("{error}", startError)
            : starting || autoStarted !== status.profile_key
              ? s.starting
              : s.stopped}
        </p>
        {status.blocker && <p className="text-muted-foreground">{status.blocker}</p>}
        {!starting && autoStarted === status.profile_key && (
          <Button onClick={() => void start()} size="sm" type="button">
            {s.retry}
          </Button>
        )}
      </div>
    );
  } else {
    body = (
      <div
        className={cn(
          "relative min-h-0 bg-black/80",
          mobile ? "flex-1 overflow-hidden" : "overflow-auto",
          // Desktop window: the screen keeps the desktop's aspect (16:9 for 1920x1080) at the window's
          // width; full screen gives it the whole remaining height instead.
          !mobile && (fullscreen === "off" ? "w-full shrink-0" : "flex-1"),
        )}
        data-testid="computer-stage"
        ref={stageRef}
        style={!mobile && fullscreen === "off" ? { aspectRatio: `${geometry.width} / ${geometry.height}` } : undefined}
      >
        <div
          onPaste={onStagePaste}
          ref={targetRef}
          style={zoom === "fit" || mobile ? { height: "100%", width: "100%" } : { height: geometry.height * zoom, width: geometry.width * zoom }}
        />
        {conn === "attaching" && !evicted && (
          <p className="absolute left-3 top-3 text-xs text-muted-foreground">{s.connecting}</p>
        )}
      </div>
    );
  }

  return (
    <section
      className={cn(
        "flex flex-col bg-background-base",
        mobile || fullscreen !== "off" ? "fixed inset-0 z-50" : "max-h-full",
        // Phones go edge to edge (rounded corners would clip any frame). Desktop: one quiet 8px
        // layer whether or not you hold control; the status pill says who drives, not a red frame.
        !mobile && "overflow-hidden rounded-lg border border-border shadow-2xl",
        className,
      )}
      data-holding={iHold}
      data-fullscreen={fullscreen}
      data-testid="computer-panel"
    >
      {mobile ? mobileHeader : desktopHeader}
      {mobile && sidewaysHint && (
        <div className="flex items-center gap-2 pl-3 text-xs text-muted-foreground" data-testid="computer-sideways-hint">
          <span className="min-w-0 flex-1 truncate">{s.sidewaysHint}</span>
          <Button aria-label={s.close} ghost onClick={() => setSidewaysHint(false)} size="icon" type="button">
            <X />
          </Button>
        </div>
      )}
      {running && (mobile ? iHold && mobileKeyRow : statusLine)}
      {running && error && (
        <div className="flex items-center gap-2 px-3 py-2 text-sm text-destructive" role="alert">
          <span>{error}</span>
          <Button className="ml-auto" onClick={reconnect} outlined size="sm" type="button">
            {s.reconnect}
          </Button>
        </div>
      )}
      {running && evicted && (
        <p className="px-3 py-1 text-xs text-muted-foreground" role="status">
          {s.evicted}
        </p>
      )}
      {notice && (
        <p className="px-3 py-1 text-xs text-muted-foreground" role="status">
          {notice}
        </p>
      )}
      {body}
      {running && (mobile ? mobileBottomBar : desktopToolbar)}
      {!mobile && <p className="border-t border-border px-3 py-1 text-xs text-muted-foreground">{s.leaseCaveat}</p>}
      {mobile && (
        <input
          aria-label={s.keyboardHint}
          autoCapitalize="off"
          autoComplete="off"
          autoCorrect="off"
          className="sr-only"
          data-testid="computer-kbd-input"
          onInput={onKbdInput}
          onKeyDown={onKbdKeyDown}
          ref={kbdRef}
          spellCheck={false}
        />
      )}
      <ConfirmDialog
        cancelLabel={t.common.cancel}
        confirmLabel={s.takeOver}
        description={`${s.confirmBody} ${s.leaseCaveat}`}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={confirmTakeOver}
        open={confirmOpen}
        title={s.confirmTitle}
      />
    </section>
  );
}

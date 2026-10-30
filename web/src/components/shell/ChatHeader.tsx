// Column 3's header and top bar (/chat has no page header): room name, its space
// breadcrumb, the room's real directory (click copies it) and the action slots. On
// phones it is the app bar: [≡] room name [⋯], where ⋯ opens the Room sheet with
// the copy/open folder rows, the actions, Add photo or file and the model; the
// path line is hidden.

import { useEffect, useRef, useState, type ChangeEvent, type ComponentType, type ReactNode } from "react";
import {
  BookOpen,
  ChevronRight,
  Copy,
  Cpu,
  FolderOpen,
  ListChecks,
  Menu,
  Monitor,
  MoreHorizontal,
  Paperclip,
  ScrollText,
} from "lucide-react";
import { useNavigate } from "react-router";
import { BottomSheet } from "@phi/ui/ui/components/bottom-sheet";
import { activeComposer } from "@/components/voice/composer-bridge";
import { uploadIntoRoom } from "./room-upload";
import { useI18n } from "@/i18n";
import { errorMessage } from "@/lib/api-error";
import { AGENT_ROOM_ID } from "@/lib/api-workspace";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import type { ShellStrings } from "@/i18n/types";
import { flattenSpaces, parentsOf } from "@/lib/workspace-tree";
import { RoundIconButton } from "./RoundIconButton";
import { fmt, useShellStrings } from "./use-shell-strings";
import { useOptionalWorkspaceShell } from "./WorkspaceShellContext";

/** The chat's model, as the phone's Room sheet shows it: name and the picker. */
export interface ChatModelEntry {
  label: string;
  open: () => void;
}

export interface ChatHeaderActionsProps {
  onOpenPlan?: () => void;
  onOpenComputer?: () => void;
  onOpenLedger?: () => void;
  onOpenRules?: () => void;
  /** Shown on the Plan button, e.g. "Plan 3/6". */
  planLabel?: string;
}

const ACTIONS = [
  { key: "plan", prop: "onOpenPlan", icon: ListChecks },
  { key: "computer", prop: "onOpenComputer", icon: Monitor },
  { key: "ledger", prop: "onOpenLedger", icon: BookOpen },
  { key: "rules", prop: "onOpenRules", icon: ScrollText },
] as const;

/** One button per supplied callback; the panels themselves land with their own tasks. */
export function ChatHeaderActions(props: ChatHeaderActionsProps) {
  const s = useShellStrings();
  const items = ACTIONS.filter((a) => props[a.prop]);
  if (items.length === 0) return null;
  return (
    <div role="toolbar" aria-label={s.chatActions} className="flex shrink-0 items-center gap-1">
      {items.map(({ key, prop, icon: Icon }) => {
        const label = key === "plan" && props.planLabel ? props.planLabel : null;
        return (
          <RoundIconButton
            key={key}
            compact
            wide={Boolean(label)}
            data-action={key}
            aria-label={label ?? s[key]}
            title={label ?? s[key]}
            onClick={() => props[prop]?.()}
          >
            <Icon />
            {label && <span className="font-mono text-xs">{label}</span>}
          </RoundIconButton>
        );
      })}
    </div>
  );
}

function roomTitle(s: ShellStrings, roomId: string | null, roomName?: string) {
  if (!roomId) return null;
  return roomName || (roomId === AGENT_ROOM_ID ? s.agentDm : roomId);
}

function SheetRow({
  action,
  icon: Icon,
  label,
  detail,
  trailing,
  ariaLabel,
  onClick,
}: {
  action: string;
  icon: ComponentType<{ className?: string }>;
  label: string;
  detail?: string;
  trailing?: ReactNode;
  ariaLabel?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      data-action={action}
      aria-label={ariaLabel}
      className="flex min-h-14 w-full items-center gap-3 px-4 text-left text-sm hover:bg-midground/10 active:bg-midground/15"
      onClick={onClick}
    >
      <Icon className="size-5 shrink-0 opacity-80" />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate">{label}</span>
        {detail && <span className="truncate font-mono text-xs opacity-60">{detail}</span>}
      </span>
      {trailing}
    </button>
  );
}

const CARD_CLASS = "overflow-hidden rounded-lg border border-current/10 bg-midground/5 divide-y divide-current/10";

/** The phone's ⋯ Room sheet: everything the desktop header shows as icons, plus upload and model. */
function RoomSheet({
  open,
  onClose,
  roomDir,
  actions,
  model,
  onCopy,
  onAddFile,
}: {
  open: boolean;
  onClose: () => void;
  roomDir: string | null;
  actions?: ChatHeaderActionsProps;
  model?: ChatModelEntry | null;
  onCopy: () => void;
  onAddFile: () => void;
}) {
  const s = useShellStrings();
  const { t } = useI18n();
  const navigate = useNavigate();
  // Close first, then act (a panel or the picker opens over the closed sheet).
  const run = (fn: () => void) => () => {
    onClose();
    fn();
  };
  const items = actions ? ACTIONS.filter((a) => actions[a.prop]) : [];
  return (
    <BottomSheet open={open} onClose={onClose} title={s.roomSheet} backdropDismissLabel={t.common.close}>
      <div className="flex flex-col gap-3 px-3 pb-3">
        {roomDir && (
          <div className={CARD_CLASS}>
            <SheetRow
              action="copy-path"
              icon={Copy}
              label={s.copyDirectory}
              detail={roomDir}
              ariaLabel={`${s.copyDirectory}: ${roomDir}`}
              onClick={run(onCopy)}
            />
            <SheetRow
              action="files"
              icon={FolderOpen}
              label={s.openFolder}
              onClick={run(() => navigate(`/files?path=${encodeURIComponent(roomDir)}`))}
            />
            <SheetRow
              action="add-file"
              icon={Paperclip}
              label={s.addPhotoOrFile}
              // The picker must open inside the tap itself, so it goes before the close.
              onClick={() => {
                onAddFile();
                onClose();
              }}
            />
          </div>
        )}
        {items.length > 0 && (
          <div className={CARD_CLASS}>
            {items.map(({ key, prop, icon }) => (
              <SheetRow
                key={key}
                action={key}
                icon={icon}
                label={(key === "plan" && actions?.planLabel) || s[key]}
                onClick={run(() => actions?.[prop]?.())}
              />
            ))}
          </div>
        )}
        {model && (
          <div className={CARD_CLASS}>
            <SheetRow
              action="model"
              icon={Cpu}
              label={s.model}
              ariaLabel={`${s.model}: ${model.label}`}
              trailing={
                <>
                  <span className="min-w-0 truncate font-mono text-xs opacity-70">{model.label}</span>
                  <ChevronRight className="size-4 shrink-0 opacity-60" />
                </>
              }
              onClick={run(model.open)}
            />
          </div>
        )}
      </div>
    </BottomSheet>
  );
}

/** The room's space breadcrumb and its directory; clicking the directory copies it. */
function RoomPath({ parent, dir, onCopy }: { parent: string | null; dir: string | null; onCopy: () => void }) {
  const s = useShellStrings();
  const shell = useOptionalWorkspaceShell();
  const spaces = shell?.tree?.spaces ?? [];
  const crumb = parent ? (flattenSpaces(spaces).find((sp) => sp.room_id === parent)?.path ?? s.home) : s.home;

  return (
    <div className="flex min-w-0 items-center gap-2 text-xs opacity-70">
      <span data-testid="chat-breadcrumb" className="truncate">{crumb}</span>
      {dir && (
        <button
          type="button"
          title={s.copyDirectory}
          aria-label={`${s.copyDirectory}: ${dir}`}
          className="min-w-0 truncate font-mono hover:underline"
          onClick={onCopy}
        >
          {dir}
        </button>
      )}
    </div>
  );
}

export function ChatHeader({
  roomId,
  title,
  actions,
  onBack,
  model,
}: {
  roomId: string | null;
  /** Shown when no room is open (a resumed session's title). */
  title?: string | null;
  actions?: ChatHeaderActionsProps;
  /** Phones: opens the room drawer; the header is then the app bar. */
  onBack?: () => void;
  /** Phones: the model row of the Room sheet. */
  model?: ChatModelEntry | null;
}) {
  const s = useShellStrings();
  const navigate = useNavigate();
  const shell = useOptionalWorkspaceShell();
  const tree = shell?.tree ?? null;
  const loadRooms = shell?.loadRooms;
  const room = roomId ? shell?.rooms[roomId] : undefined;
  const parent = roomId && tree ? (parentsOf(tree, roomId)[0] ?? null) : null;

  // Opened by URL (reload, link): fetch the room's listing for its name and path.
  useEffect(() => {
    if (roomId && !room && loadRooms) void loadRooms(parent);
  }, [roomId, room, parent, loadRooms]);

  const name = roomTitle(s, roomId, room?.name) ?? title ?? null;
  const roomDir = room?.path ?? null;
  const copyDir = async () => {
    if (roomDir && (await copyTextToClipboard(roomDir))) shell?.notify(s.pathCopied, "success");
  };
  const [sheetOpen, setSheetOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file || !roomDir) return;
    try {
      activeComposer()?.insert(await uploadIntoRoom(roomDir, file));
    } catch (err) {
      shell?.notify(fmt(s.uploadFailed, { error: errorMessage(err) }), "error");
    }
  };
  if (!name && !onBack && !actions) return null;
  const hasSheet = Boolean(roomDir || model || (actions && ACTIONS.some((a) => actions[a.prop])));
  return (
    <header
      data-testid="chat-header"
      className={cn(
        // Bleeds over App's chat padding (px-3 sm:px-6): the border spans column 3 and
        // lines up with the sidebar header's at y=56.
        "-mx-3 flex h-14 shrink-0 items-center border-b border-current/10 sm:-mx-6",
        onBack ? "px-1" : "gap-2 px-3 sm:px-6",
      )}
    >
      {onBack && (
        <RoundIconButton aria-label={s.backToRooms} title={s.backToRooms} onClick={onBack}>
          <Menu />
        </RoundIconButton>
      )}
      <div className={cn("flex min-w-0 flex-1 flex-col", onBack && "px-1")}>
        {name && <h1 className="truncate text-sm font-semibold">{name}</h1>}
        {roomId && !onBack && <RoomPath parent={parent} dir={roomDir} onCopy={() => void copyDir()} />}
      </div>
      {onBack ? (
        hasSheet && (
          <>
            <RoundIconButton
              aria-label={s.chatActions}
              aria-haspopup="dialog"
              aria-expanded={sheetOpen}
              title={s.chatActions}
              onClick={() => setSheetOpen(true)}
            >
              <MoreHorizontal />
            </RoundIconButton>
            <input ref={fileInput} type="file" hidden data-testid="room-file-input" onChange={(e) => void onFile(e)} />
            <RoomSheet
              open={sheetOpen}
              onClose={() => setSheetOpen(false)}
              roomDir={roomDir}
              actions={actions}
              model={model}
              onCopy={() => void copyDir()}
              onAddFile={() => fileInput.current?.click()}
            />
          </>
        )
      ) : (
        <div className="flex shrink-0 items-center gap-1">
          {roomDir && (
            <RoundIconButton
              compact
              data-action="files"
              aria-label={s.openFolder}
              title={s.openFolder}
              onClick={() => navigate(`/files?path=${encodeURIComponent(roomDir)}`)}
            >
              <FolderOpen />
            </RoundIconButton>
          )}
          {actions && <ChatHeaderActions {...actions} />}
        </div>
      )}
    </header>
  );
}

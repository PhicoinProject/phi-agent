// Small dialogs of the workspace shell: name a new space/room/sub-space or rename
// one, and add an existing Home room to a space.

import { useEffect, useState, type ReactNode } from "react";
import { Button } from "@phi/ui/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@phi/ui/ui/components/dialog";
import { Input } from "@phi/ui/ui/components/input";
import { errorMessage } from "@/lib/api-error";
import { orderHome } from "@/lib/workspace-tree";
import { AGENT_ROOM_ID } from "@/lib/api-workspace";
import { useShellStrings } from "./use-shell-strings";
import { useWorkspaceShell } from "./WorkspaceShellContext";

export interface NameDialogProps {
  open: boolean;
  title: string;
  label: string;
  submitLabel: string;
  initial?: string;
  onOpenChange: (open: boolean) => void;
  /** Rejections (e.g. the API's nesting-limit 400) are shown in the dialog. */
  onSubmit: (name: string) => Promise<unknown>;
  /** Extra fields under the name, e.g. Create space's parent picker. */
  children?: ReactNode;
}

export function NameDialog({
  open,
  title,
  label,
  submitLabel,
  initial = "",
  onOpenChange,
  onSubmit,
  children,
}: NameDialogProps) {
  const s = useShellStrings();
  const [name, setName] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(initial);
      setError(null);
    }
  }, [open, initial]);

  const submit = async () => {
    const value = name.trim();
    if (!value || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onSubmit(value);
      onOpenChange(false);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{label}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2 p-4">
          <Input
            autoFocus
            aria-label={label}
            value={name}
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void submit();
            }}
          />
          {children}
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button type="button" outlined disabled={busy} onClick={() => onOpenChange(false)}>
            {s.cancel}
          </Button>
          <Button type="button" disabled={busy || !name.trim()} onClick={() => void submit()}>
            {submitLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Lists Home rooms; picking one links it into `space`. */
export function AddExistingRoomDialog({
  open,
  space,
  onOpenChange,
}: {
  open: boolean;
  space: string;
  onOpenChange: (open: boolean) => void;
}) {
  const s = useShellStrings();
  const { tree, rooms, loadRooms, moveRoom } = useWorkspaceShell();
  useEffect(() => {
    if (open) void loadRooms(null);
  }, [open, loadRooms]);
  const candidates = orderHome(tree?.home ?? []).filter((id) => id !== AGENT_ROOM_ID);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm">
        <DialogHeader>
          <DialogTitle>{s.addExistingRoom}</DialogTitle>
        </DialogHeader>
        <ul className="flex max-h-80 flex-col overflow-y-auto p-2">
          {candidates.length === 0 && (
            <li className="px-3 py-2 text-sm text-text-secondary">{s.noRooms}</li>
          )}
          {candidates.map((id) => (
            <li key={id}>
              <button
                type="button"
                className="w-full px-3 py-2 text-left text-sm hover:bg-midground/10"
                onClick={() => {
                  onOpenChange(false);
                  void moveRoom(id, null, space);
                }}
              >
                # {rooms[id]?.name ?? id}
              </button>
            </li>
          ))}
        </ul>
      </DialogContent>
    </Dialog>
  );
}

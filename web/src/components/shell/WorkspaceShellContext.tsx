// Shared state for the workspace shell: the space tree, loaded room records, the
// selected space and which list column 2 shows. Spaces bar, room list and the
// mobile drawer all read it, so a move made in one shows in the others.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Toast } from "@phi/ui/ui/components/toast";
import { useToast } from "@phi/ui/hooks/use-toast";
import { errorMessage } from "@/lib/api-error";
import {
  workspaceApi,
  type WorkspaceRoom,
  type WorkspaceTree,
} from "@/lib/api-workspace";
import { applyMove, findSpace } from "@/lib/workspace-tree";
import { useProfileScope } from "@/contexts/useProfileScope";
import { fmt, useShellStrings } from "./use-shell-strings";

export type ShellMode = "rooms" | "settings";

/** Backend default (workspace_map.DEFAULT_MAX_SPACE_DEPTH) until settings load. */
const DEFAULT_MAX_DEPTH = 3;

export interface WorkspaceShellValue {
  tree: WorkspaceTree | null;
  rooms: Record<string, WorkspaceRoom>;
  maxDepth: number;
  error: string | null;
  /** null = Home. */
  selectedSpace: string | null;
  selectSpace: (id: string | null) => void;
  mode: ShellMode;
  setMode: (mode: ShellMode) => void;
  /** Phone/tablet drawer (columns 1+2); a room's back button reopens it. */
  drawerOpen: boolean;
  setDrawerOpen: (open: boolean) => void;
  refresh: () => Promise<void>;
  loadRooms: (space: string | null) => Promise<void>;
  /** Optimistic for rooms; rolls back and toasts on failure. `from` null = add to another space. Also moves spaces. */
  moveRoom: (roomId: string, from: string | null, to: string | null) => Promise<boolean>;
  createSpace: (name: string, parent: string | null) => Promise<WorkspaceRoom>;
  /** `parent`'s New chat room (reused while empty), listed at once as "New chat". */
  newChat: (parent: string | null) => Promise<WorkspaceRoom>;
  rename: (id: string, name: string) => Promise<void>;
  notify: (message: string, type: "error" | "success") => void;
}

const WorkspaceShellContext = createContext<WorkspaceShellValue | null>(null);

export function useWorkspaceShell(): WorkspaceShellValue {
  const ctx = useContext(WorkspaceShellContext);
  if (!ctx) throw new Error("useWorkspaceShell needs <WorkspaceShellProvider>");
  return ctx;
}

/** For views that also render outside the shell (the chat page in its own tests). */
export function useOptionalWorkspaceShell(): WorkspaceShellValue | null {
  return useContext(WorkspaceShellContext);
}

export function WorkspaceShellProvider({
  children,
  initialMode = "rooms",
}: {
  children: ReactNode;
  initialMode?: ShellMode;
}) {
  const s = useShellStrings();
  const { profile } = useProfileScope();
  const { toast, showToast } = useToast();
  const [tree, setTree] = useState<WorkspaceTree | null>(null);
  const treeRef = useRef<WorkspaceTree | null>(null);
  const [rooms, setRooms] = useState<Record<string, WorkspaceRoom>>({});
  const [maxDepth, setMaxDepth] = useState(DEFAULT_MAX_DEPTH);
  const [error, setError] = useState<string | null>(null);
  const [selectedSpace, selectSpace] = useState<string | null>(null);
  const [mode, setMode] = useState<ShellMode>(initialMode);
  const [drawerOpen, setDrawerOpen] = useState(false);

  const putTree = useCallback((next: WorkspaceTree | null) => {
    treeRef.current = next;
    setTree(next);
  }, []);

  const refresh = useCallback(async () => {
    try {
      putTree(await workspaceApi.getTree());
      setError(null);
    } catch (e) {
      setError(fmt(s.loadFailed, { error: errorMessage(e) }));
    }
  }, [putTree, s.loadFailed]);

  const loadRooms = useCallback(async (space: string | null) => {
    try {
      const res = await workspaceApi.getRooms(space);
      setRooms((prev) => {
        const next = { ...prev };
        for (const room of res.rooms ?? []) next[room.room_id] = room;
        return next;
      });
    } catch {
      /* names fall back to ids; the tree error line already explains outages */
    }
  }, []);

  useEffect(() => {
    // Profile switch: a different workspace map.
    putTree(null);
    setRooms({});
    selectSpace(null);
    void refresh();
    workspaceApi
      .getSettings()
      .then((cfg) => setMaxDepth(cfg.max_space_depth || DEFAULT_MAX_DEPTH))
      .catch(() => setMaxDepth(DEFAULT_MAX_DEPTH));
  }, [profile, putTree, refresh]);

  const moveRoom = useCallback(
    async (roomId: string, from: string | null, to: string | null) => {
      const before = treeRef.current;
      // applyMove only moves rooms; a dragged space shows in its new place after the refresh.
      if (before && !findSpace(before.spaces, roomId)) putTree(applyMove(before, roomId, from, to));
      try {
        await workspaceApi.move(roomId, from, to);
      } catch (e) {
        putTree(before);
        showToast(fmt(s.moveFailed, { error: errorMessage(e) }), "error");
        return false;
      }
      void refresh();
      return true;
    },
    [putTree, refresh, s.moveFailed, showToast],
  );

  const createSpace = useCallback(
    async (name: string, parent: string | null) => {
      const res = await workspaceApi.createSpace(name, parent);
      await refresh();
      return res.space;
    },
    [refresh],
  );

  const newChat = useCallback(
    async (parent: string | null) => {
      const room = await workspaceApi.newChat(parent);
      setRooms((prev) => ({ ...prev, [room.room_id]: room }));
      await refresh();
      return room;
    },
    [refresh],
  );

  const rename = useCallback(
    async (id: string, name: string) => {
      const res = await workspaceApi.rename(id, name);
      setRooms((prev) => ({ ...prev, [id]: res.room }));
      await refresh();
    },
    [refresh],
  );

  const value = useMemo<WorkspaceShellValue>(
    () => ({
      tree,
      rooms,
      maxDepth,
      error,
      selectedSpace,
      selectSpace,
      mode,
      setMode,
      drawerOpen,
      setDrawerOpen,
      refresh,
      loadRooms,
      moveRoom,
      createSpace,
      newChat,
      rename,
      notify: showToast,
    }),
    [tree, rooms, maxDepth, error, selectedSpace, mode, drawerOpen, refresh, loadRooms, moveRoom, createSpace, newChat, rename, showToast],
  );

  return (
    <WorkspaceShellContext.Provider value={value}>
      {children}
      <Toast toast={toast} />
    </WorkspaceShellContext.Provider>
  );
}

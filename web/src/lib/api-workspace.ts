// Workspace (spaces / rooms) API client for the Element-style shell. Kept out of
// api.ts so that facade stays under its code-health line cap. Every route is
// profile-scoped (see PROFILE_SCOPED_PREFIXES in api.ts).

import { fetchJSON } from "./api";

/** The agent DM; Home always lists it first. Mirrors workspace_map.AGENT_ROOM_ID. */
export const AGENT_ROOM_ID = "!local_agent";

/** Mirrors workspace_map.FENCE_MODES. */
export const FENCE_MODES = ["approve", "strict", "off"] as const;
export type FenceMode = (typeof FENCE_MODES)[number];

export interface WorkspaceSpaceNode {
  room_id: string;
  name: string;
  children: WorkspaceSpaceNode[];
  rooms: string[];
}

export interface WorkspaceTree {
  spaces: WorkspaceSpaceNode[];
  home: string[];
}

export interface WorkspaceRoom {
  room_id: string;
  type: "space" | "room" | "dm";
  name: string;
  rel_path?: string | null;
  path?: string | null;
  origin?: string | null;
  fence_mode?: string | null;
  extra_write_paths?: string[];
  created_at?: number | string | null;
  updated_at?: number | string | null;
  archived?: boolean;
  parents?: (string | null)[];
}

export type WorkspaceCheckIssue =
  | { kind: "missing_dir"; room_id: string; path: string }
  | { kind: "unmapped_dir"; path: string };

export interface WorkspaceCheck {
  root: string;
  rooms: number;
  issues: WorkspaceCheckIssue[];
}

export interface WorkspaceSettings {
  root: string;
  configured_root?: string | null;
  max_space_depth: number;
  default_fence: FenceMode;
}

export const LEDGER_KINDS = ["decision", "fact", "result", "blocker", "todo", "note", "step"] as const;
export type LedgerKind = (typeof LEDGER_KINDS)[number];

export interface LedgerEntry {
  id: number | string;
  ts: number | string;
  kind: LedgerKind | string;
  text: string;
  status: string;
  refs: string[];
  superseded_by?: number | string | null;
}

export interface LedgerQuery {
  q?: string;
  kind?: string;
  include_superseded?: boolean;
  limit?: number;
}

export interface RoomRules {
  room_id: string;
  path: string;
  content: string;
  max_chars: number;
}

/** Per-room activity for the room list's Running / Unread filters. */
export interface RoomActivity {
  rooms: Record<string, { running?: boolean; unread?: number }>;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

function send<T>(method: string, url: string, body: unknown): Promise<T> {
  return fetchJSON<T>(url, { method, headers: JSON_HEADERS, body: JSON.stringify(body) });
}

export const workspaceApi = {
  getTree: () => fetchJSON<WorkspaceTree>("/api/workspace/tree"),
  /** Rooms of one space; no space = Home. */
  getRooms: (space?: string | null) =>
    fetchJSON<{ rooms: WorkspaceRoom[] }>(
      space ? `/api/workspace/rooms?space=${encodeURIComponent(space)}` : "/api/workspace/rooms",
    ),
  createSpace: (name: string, parentSpace?: string | null) =>
    send<{ space: WorkspaceRoom }>("POST", "/api/workspace/spaces", {
      name,
      parent_space: parentSpace ?? null,
    }),
  /** Renames rooms and spaces alike. */
  rename: (roomId: string, name: string) =>
    send<{ room: WorkspaceRoom }>("PATCH", `/api/workspace/rooms/${encodeURIComponent(roomId)}`, {
      name,
    }),
  /** `from: null` adds a link (keeps existing parents); `to: null` is Home. */
  move: (roomId: string, from: string | null, to: string | null) =>
    send<{ room: WorkspaceRoom }>("POST", "/api/workspace/move", { room_id: roomId, from, to }),
  check: () => fetchJSON<WorkspaceCheck>("/api/workspace/check"),
  getSettings: () => fetchJSON<WorkspaceSettings>("/api/workspace/settings"),
  putSettings: (patch: Partial<Pick<WorkspaceSettings, "root" | "max_space_depth" | "default_fence">>) =>
    send<WorkspaceSettings>("PUT", "/api/workspace/settings", patch),
  getRules: (roomId: string) => fetchJSON<RoomRules>(`/api/workspace/rooms/${encodeURIComponent(roomId)}/rules`),
  putRules: (roomId: string, content: string) =>
    send<RoomRules>("PUT", `/api/workspace/rooms/${encodeURIComponent(roomId)}/rules`, { content }),
  getLedger: (roomId: string, query: LedgerQuery = {}) => {
    const params = new URLSearchParams();
    if (query.q) params.set("q", query.q);
    if (query.kind) params.set("kind", query.kind);
    if (query.include_superseded) params.set("include_superseded", "true");
    if (query.limit) params.set("limit", String(query.limit));
    const qs = params.toString();
    return fetchJSON<{ entries: LedgerEntry[] }>(
      `/api/workspace/rooms/${encodeURIComponent(roomId)}/ledger${qs ? `?${qs}` : ""}`,
    );
  },
  activity: () => fetchJSON<RoomActivity>("/api/workspace/activity"),
  markSeen: (roomId: string) =>
    fetchJSON<{ room: unknown }>(`/api/workspace/rooms/${encodeURIComponent(roomId)}/seen`, { method: "POST" }),
  markAllSeen: () => fetchJSON<{ marked: number }>("/api/workspace/rooms/seen-all", { method: "POST" }),
  /** Delete a space; its rooms and sub-spaces move up one level, no folder is touched. */
  deleteSpace: (spaceId: string) =>
    fetchJSON<{ deleted: string; moved_up: string[]; into: string[] }>(
      `/api/workspace/spaces/${encodeURIComponent(spaceId)}`,
      { method: "DELETE" },
    ),
  archive: (roomId: string) =>
    send<{ ok?: boolean }>("POST", `/api/workspace/rooms/${encodeURIComponent(roomId)}/archive`, {}),
  /** The New chat room of `parentSpace` (or Home): its empty one if it has one, else a new one. */
  async newChat(parentSpace?: string | null): Promise<WorkspaceRoom> {
    const res = await send<{ room?: WorkspaceRoom }>(
      "POST",
      "/api/workspace/rooms/new-chat",
      parentSpace ? { parent_space: parentSpace } : {},
    );
    if (!res.room?.room_id) throw new Error("No room_id in response");
    return res.room;
  },
};

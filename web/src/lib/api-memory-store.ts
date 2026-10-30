// Tiered memory store (Settings → Memory) API client, served by
// phi_cli/web_routers/memory_store.py. Kept out of api.ts for its code-health
// line cap, like api-workspace.ts. "/api/memory" is profile-scoped in api.ts.

import { fetchJSON } from "./api";

export type MemoryTarget = "memory" | "user";
export type MemoryTier = "hard" | "soft";
export type MemoryKind = "rule" | "skill" | "identity" | "fact" | "preference" | "note";

export interface MemoryEntry {
  id: number;
  target: MemoryTarget;
  tier: MemoryTier;
  kind: MemoryKind;
  text: string;
  /** Pinned when > 0. */
  priority: number;
  use_count: number;
  /** Epoch seconds; null when never retrieved. */
  last_used_at: number | null;
  created_at: number;
  updated_at: number;
  /** Relevance; only present when the list was queried with `q`. */
  score?: number;
}

export interface MemoryBudget {
  used: number;
  limit: number;
}

export interface MemoryUsage {
  hard: Record<MemoryTarget, MemoryBudget>;
  soft_count: number;
}

export interface MemoryEntriesQuery {
  tier: MemoryTier;
  target?: MemoryTarget;
  q?: string;
}

/** Every mutation answers with the (possibly new) entry id. */
export interface MemoryMutation {
  ok: boolean;
  id: number;
}

const JSON_HEADERS = { "Content-Type": "application/json" };

function send<T>(method: string, url: string, body?: unknown): Promise<T> {
  return body === undefined
    ? fetchJSON<T>(url, { method })
    : fetchJSON<T>(url, { method, headers: JSON_HEADERS, body: JSON.stringify(body) });
}

const entryUrl = (id: number, action?: string) =>
  action ? `/api/memory/${encodeURIComponent(id)}/${action}` : `/api/memory/${encodeURIComponent(id)}`;

export const memoryStoreApi = {
  usage: () => fetchJSON<MemoryUsage>("/api/memory/usage"),
  /** Not `/api/memory`: that path is the provider status endpoint. */
  entries: ({ tier, target, q }: MemoryEntriesQuery) => {
    const params = new URLSearchParams({ tier });
    if (target) params.set("target", target);
    if (q) params.set("q", q);
    return fetchJSON<{ entries: MemoryEntry[] }>(`/api/memory/entries?${params.toString()}`);
  },
  /** Edits supersede the entry, so the answer carries a new id. */
  edit: (id: number, text: string) => send<MemoryMutation>("PATCH", entryUrl(id), { text }),
  promote: (id: number) => send<MemoryMutation>("POST", entryUrl(id, "promote")),
  demote: (id: number) => send<MemoryMutation>("POST", entryUrl(id, "demote")),
  archive: (id: number) => send<MemoryMutation>("POST", entryUrl(id, "archive")),
  pin: (id: number, pinned: boolean) => send<MemoryMutation>("POST", entryUrl(id, "pin"), { pinned }),
};

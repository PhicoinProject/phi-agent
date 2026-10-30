// Pure helpers over the workspace tree (GET /api/workspace/tree) for the shell's
// space bar and room list. No React, no I/O.

import { AGENT_ROOM_ID, type WorkspaceRoom, type WorkspaceSpaceNode, type WorkspaceTree } from "./api-workspace";

export interface FlatSpace {
  room_id: string;
  name: string;
  /** Deepest level the space sits at (top-level = 1), as the backend counts it. */
  level: number;
  /** "Projects / Hardware" style path of the first place it appears. */
  path: string;
}

/** Every space once, in tree order, with its deepest level. */
export function flattenSpaces(spaces: WorkspaceSpaceNode[]): FlatSpace[] {
  const byId = new Map<string, FlatSpace>();
  const walk = (nodes: WorkspaceSpaceNode[], level: number, prefix: string) => {
    for (const node of nodes) {
      const path = prefix ? `${prefix} / ${node.name}` : node.name;
      const seen = byId.get(node.room_id);
      if (!seen) byId.set(node.room_id, { room_id: node.room_id, name: node.name, level, path });
      else if (level > seen.level) seen.level = level;
      walk(node.children, level + 1, path);
    }
  };
  walk(spaces, 1, "");
  return [...byId.values()];
}

export function findSpace(spaces: WorkspaceSpaceNode[], id: string): WorkspaceSpaceNode | null {
  for (const node of spaces) {
    if (node.room_id === id) return node;
    const hit = findSpace(node.children, id);
    if (hit) return hit;
  }
  return null;
}

/** Deepest level of a space (1 = top level), or 0 for Home / unknown. */
export function spaceLevel(spaces: WorkspaceSpaceNode[], id: string | null): number {
  if (!id) return 0;
  return flattenSpaces(spaces).find((s) => s.room_id === id)?.level ?? 0;
}

/**
 * A sub-space of a level-L space sits at L+1 and its rooms at L+2; the limit counts the room
 * (workspace_map.max_space_depth), so it is allowed only while L + 2 <= limit.
 */
export function canCreateSubSpace(level: number, maxDepth: number): boolean {
  return level >= 1 && level + 2 <= maxDepth;
}

/** Levels a space's subtree spans: 1 for a space without sub-spaces. */
export function spaceHeight(node: WorkspaceSpaceNode): number {
  return 1 + Math.max(0, ...node.children.map(spaceHeight));
}

/**
 * Why moving space `id` under `to` (null = top level) would be refused, as workspace_map._link
 * checks it: "cycle" into itself or a descendant, "depth" when its deepest rooms pass the limit.
 */
export function spaceDropRefusal(
  spaces: WorkspaceSpaceNode[],
  id: string,
  to: string | null,
  maxDepth: number,
): "cycle" | "depth" | null {
  const node = findSpace(spaces, id);
  if (!node || to === null) return null;
  if (to === id || findSpace(node.children, to)) return "cycle";
  return spaceLevel(spaces, to) + spaceHeight(node) + 1 > maxDepth ? "depth" : null;
}

/** Spaces that directly contain `roomId` (empty = the room is in Home). */
export function parentsOf(tree: WorkspaceTree, roomId: string): string[] {
  const out: string[] = [];
  const walk = (nodes: WorkspaceSpaceNode[]) => {
    for (const node of nodes) {
      if (node.rooms.includes(roomId) && !out.includes(node.room_id)) out.push(node.room_id);
      walk(node.children);
    }
  };
  walk(tree.spaces);
  return out;
}

function mapNodes(
  nodes: WorkspaceSpaceNode[],
  fn: (node: WorkspaceSpaceNode) => WorkspaceSpaceNode,
): WorkspaceSpaceNode[] {
  return nodes.map((node) => fn({ ...node, children: mapNodes(node.children, fn) }));
}

/**
 * Optimistic copy of POST /api/workspace/move: `from` null adds a link, `to` null is Home.
 * A room that ends up with no space shows in Home; one that gains a space leaves Home.
 */
export function applyMove(
  tree: WorkspaceTree,
  roomId: string,
  from: string | null,
  to: string | null,
): WorkspaceTree {
  if (from === to) return tree;
  const spaces = mapNodes(tree.spaces, (node) => {
    let rooms = node.rooms;
    if (from && node.room_id === from) rooms = rooms.filter((r) => r !== roomId);
    if (to && node.room_id === to && !rooms.includes(roomId)) rooms = [...rooms, roomId];
    return rooms === node.rooms ? node : { ...node, rooms };
  });
  const homeless = parentsOf({ spaces, home: tree.home }, roomId).length === 0;
  const home = tree.home.filter((r) => r !== roomId);
  return { spaces, home: homeless ? [...home, roomId] : home };
}

/** Home order: the agent DM always first, then the server's order. */
export function orderHome(ids: string[]): string[] {
  const rest = ids.filter((id) => id !== AGENT_ROOM_ID);
  return ids.includes(AGENT_ROOM_ID) ? [AGENT_ROOM_ID, ...rest] : rest;
}

export function matchesQuery(room: Pick<WorkspaceRoom, "name" | "room_id">, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return room.name.toLowerCase().includes(q) || room.room_id.toLowerCase().includes(q);
}

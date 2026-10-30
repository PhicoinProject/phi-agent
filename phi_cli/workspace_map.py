"""Workspace map: which directory each room uses, how spaces group rooms, which channel ids reach them.

``$PHI_HOME/workspace_map.db`` lives outside the workspace root, so moving the root never moves the
map. Matrix-shaped but channel-neutral (design §五):

* ``rooms`` — spaces, rooms and DMs. A room/dm ``rel_path`` is fixed at creation: relative to the
  workspace root, absolute only for legacy directories imported in place. Rename changes ``name``
  only, and a trigger refuses any later ``rel_path`` update. Spaces have no directory.
* ``space_children`` — parent → child with order; a child (room or space) may have several parents.
* ``channel_links`` — external ids (Matrix room, Telegram chat, ...) that reach a room.
* ``room_conversations`` — the room's current conversation: the session id every linked chat tool
  continues, and when it last moved (epoch seconds).

``rooms.last_seen`` (nullable epoch seconds, added in place) is when the dashboard last showed a room;
assistant replies after it count as unread.

New rooms and spaces get a system id (16 lowercase hex characters); a new room's directory is
``<root>/<id>``, so its display name never names a folder. Older ``!local_`` ids, Matrix ids used as
row ids and their directories stay as they are. ``rooms.name_source`` (added in place; older rows count
as ``user``) says who named a room: ``default`` ("New chat"), ``auto`` (its first chat message, then the
model's session title) or ``user``. Only ``default``/``auto`` names are ever replaced automatically.

Every public function opens a short-lived connection; writes run in one IMMEDIATE transaction.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterator, Optional

from phi_cli.sqlite_util import add_column_if_missing, open_db, write_txn
from phi_cli.workspace_root import (
    RESERVED_DIR_NAMES, agent_dir, workspace_config, workspace_root,
)
from phi_constants import get_phi_home

AGENT_ROOM_ID = "!local_agent"
AGENT_ROOM_NAME = "Phi (agent)"
FENCE_MODES = ("approve", "strict", "off")
DEFAULT_FENCE = "approve"
DEFAULT_MAX_SPACE_DEPTH = 3
ROOM_KINDS = ("room", "dm")
NEW_CHAT_NAME = "New chat"
ROOM_ID_BYTES = 8  # secrets.token_hex(8): 16 lowercase hex characters
_ROOM_ID_TRIES = 20

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS rooms (
    room_id            TEXT PRIMARY KEY,
    type               TEXT NOT NULL CHECK (type IN ('space', 'room', 'dm')),
    name               TEXT NOT NULL,
    rel_path           TEXT,
    origin             TEXT NOT NULL DEFAULT 'local',
    fence_mode         TEXT NOT NULL DEFAULT 'approve',
    extra_write_paths  TEXT NOT NULL DEFAULT '[]',
    created_at         INTEGER NOT NULL,
    updated_at         INTEGER NOT NULL,
    archived           INTEGER NOT NULL DEFAULT 0,
    CHECK ((type = 'space') = (rel_path IS NULL))
);

CREATE TABLE IF NOT EXISTS space_children (
    parent_id  TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    child_id   TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    ord        REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (parent_id, child_id)
);

CREATE INDEX IF NOT EXISTS idx_space_children_child ON space_children(child_id);

CREATE TABLE IF NOT EXISTS channel_links (
    room_id      TEXT NOT NULL REFERENCES rooms(room_id) ON DELETE CASCADE,
    channel      TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    PRIMARY KEY (channel, external_id)
);

CREATE INDEX IF NOT EXISTS idx_channel_links_room ON channel_links(room_id);

CREATE TABLE IF NOT EXISTS room_conversations (
    room_id     TEXT PRIMARY KEY REFERENCES rooms(room_id) ON DELETE CASCADE,
    session_id  TEXT NOT NULL,
    updated_at  REAL NOT NULL
);

CREATE TRIGGER IF NOT EXISTS rooms_rel_path_fixed
BEFORE UPDATE OF rel_path ON rooms
WHEN OLD.rel_path IS NOT NEW.rel_path
BEGIN
    SELECT RAISE(ABORT, 'rooms.rel_path is fixed at creation');
END;
"""

_INITIALIZED_PATHS: set[str] = set()


class WorkspaceMapError(ValueError):
    """A request the map refuses: empty name, wrong row type, cycle, conflicting link..."""


class DepthLimitError(WorkspaceMapError):
    """Creating or moving a space would exceed ``workspace.max_space_depth``."""


class RoomNotFound(LookupError):
    """No row with that room id."""


def map_db_path() -> Path:
    """``$PHI_HOME/workspace_map.db``."""
    return get_phi_home() / "workspace_map.db"


def max_space_depth() -> int:
    """``workspace.max_space_depth``: how many levels a room may sit below the top, counting the room.

    Levels: a top-level space is level 1, a space inside it level 2, and so on (with several parents,
    the deepest path counts); a room is one level below its space. The default 3 therefore means
    space/sub-space/room; plain space/room is 2. Only spaces created or moved through this API are
    checked; ``import_*`` (Matrix) records deeper hierarchies as they are.
    """
    value = workspace_config().get("max_space_depth", DEFAULT_MAX_SPACE_DEPTH)
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return DEFAULT_MAX_SPACE_DEPTH
    try:
        depth = int(value)
    except ValueError:
        return DEFAULT_MAX_SPACE_DEPTH
    return depth if depth >= 1 else DEFAULT_MAX_SPACE_DEPTH


def default_fence() -> str:
    """``workspace.default_fence`` for new rooms (``approve`` unless set to ``strict``/``off``)."""
    value = workspace_config().get("default_fence")
    return value if value in FENCE_MODES else DEFAULT_FENCE


def _connect() -> sqlite3.Connection:
    path = map_db_path()
    resolved = str(path.resolve())

    def initialize(conn: sqlite3.Connection) -> None:
        if resolved in _INITIALIZED_PATHS:
            return
        conn.executescript(SCHEMA_SQL)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(rooms)")}
        if "last_seen" not in columns:
            add_column_if_missing(conn, "rooms", "last_seen", "last_seen REAL")
        if "name_source" not in columns:
            add_column_if_missing(conn, "rooms", "name_source", "name_source TEXT NOT NULL DEFAULT 'user'")
        _INITIALIZED_PATHS.add(resolved)

    return open_db(path, db_label="workspace_map.db", foreign_keys=True, initialize=initialize)


@contextlib.contextmanager
def _read() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def _write() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        with write_txn(conn):
            yield conn
    finally:
        conn.close()


def _now() -> int:
    return int(time.time())


def _clean_name(name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        raise WorkspaceMapError("A name is required.")
    return text


def _abs_path(rel_path: str, root: Path) -> Path:
    path = Path(rel_path)
    return path if path.is_absolute() else root / path


def _json_list(text: Optional[str]) -> list:
    try:
        value = json.loads(text or "[]")
    except ValueError:
        return []
    return value if isinstance(value, list) else []


def _row(conn: sqlite3.Connection, room_id: Optional[str]) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
    if row is None:
        raise RoomNotFound(f"Unknown room or space: {room_id}")
    return row


def _space_row(conn: sqlite3.Connection, space_id: Optional[str]) -> sqlite3.Row:
    row = _row(conn, space_id)
    if row["type"] != "space":
        raise WorkspaceMapError(f"{space_id} is not a space.")
    return row


def _parents(conn: sqlite3.Connection, room_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT parent_id FROM space_children WHERE child_id = ? ORDER BY rowid", (room_id,))]


def _room_dict(row: sqlite3.Row, root: Path, parents: list[str]) -> dict:
    rel = row["rel_path"]
    return {
        "room_id": row["room_id"], "type": row["type"], "name": row["name"], "rel_path": rel,
        "path": str(_abs_path(rel, root)) if rel else None, "origin": row["origin"],
        "fence_mode": row["fence_mode"], "extra_write_paths": _json_list(row["extra_write_paths"]),
        "created_at": row["created_at"], "updated_at": row["updated_at"],
        "archived": bool(row["archived"]), "last_seen": row["last_seen"], "name_source": row["name_source"],
        "parents": parents,
    }


def _load(conn: sqlite3.Connection, room_id: str) -> dict:
    return _room_dict(_row(conn, room_id), workspace_root(), _parents(conn, room_id))


def _space_level(conn: sqlite3.Connection, space_id: str, seen: frozenset = frozenset()) -> int:
    """1 for a top-level space, else 1 + its deepest parent's level (see :func:`max_space_depth`)."""
    if space_id in seen:  # imported hierarchies are not cycle-checked
        return 0
    seen = seen | {space_id}
    return 1 + max((_space_level(conn, p, seen) for p in _parents(conn, space_id)), default=0)


def _space_height(conn: sqlite3.Connection, space_id: str, seen: frozenset = frozenset()) -> int:
    """1 for a space without sub-spaces, else 1 + its tallest sub-space."""
    if space_id in seen:
        return 0
    seen = seen | {space_id}
    subs = [r[0] for r in conn.execute(
        "SELECT sc.child_id FROM space_children sc JOIN rooms r ON r.room_id = sc.child_id "
        "WHERE sc.parent_id = ? AND r.type = 'space'", (space_id,))]
    return 1 + max((_space_height(conn, s, seen) for s in subs), default=0)


def _ancestors(conn: sqlite3.Connection, space_id: str) -> set[str]:
    found: set[str] = set()
    pending = [space_id]
    while pending:
        for parent in _parents(conn, pending.pop()):
            if parent not in found:
                found.add(parent)
                pending.append(parent)
    return found


def _check_depth(deepest_space_level: int) -> None:
    limit = max_space_depth()
    if deepest_space_level + 1 > limit:
        raise DepthLimitError(
            f"That would nest spaces {deepest_space_level} deep; the space nesting limit is {limit} "
            "levels counting the room (Settings → Workspace).")


def _insert_link(conn: sqlite3.Connection, parent_id: str, child_id: str) -> None:
    (ord_,) = conn.execute(
        "SELECT COALESCE(MAX(ord), 0) + 1 FROM space_children WHERE parent_id = ?", (parent_id,)).fetchone()
    conn.execute("INSERT OR IGNORE INTO space_children (parent_id, child_id, ord) VALUES (?, ?, ?)",
                 (parent_id, child_id, ord_))


def _link(conn: sqlite3.Connection, child_id: str, parent_id: str, *, enforce_depth: bool) -> None:
    """Put ``child_id`` into space ``parent_id``. UI-made nesting (``enforce_depth``) of a space is
    cycle- and depth-checked; rooms are leaves and never are."""
    _space_row(conn, parent_id)
    child = _row(conn, child_id)
    if child["type"] == "space" and enforce_depth:
        if child_id == parent_id or child_id in _ancestors(conn, parent_id):
            raise WorkspaceMapError("A space cannot be placed inside itself.")
        _check_depth(_space_level(conn, parent_id) + _space_height(conn, child_id))
    _insert_link(conn, parent_id, child_id)


def _insert_row(conn: sqlite3.Connection, room_id: str, kind: str, name: str, rel_path: Optional[str],
                origin: str, fence: str, name_source: str = "user") -> None:
    now = _now()
    conn.execute(
        "INSERT INTO rooms (room_id, type, name, rel_path, origin, fence_mode, created_at, updated_at, "
        "name_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (room_id, kind, name, rel_path, origin, fence, now, now, name_source))


def new_room_id(conn: sqlite3.Connection, root: Path) -> str:
    """A fresh system id (16 lowercase hex characters) that no row uses and no directory under ``root``
    is named; gives up after a few draws."""
    for _ in range(_ROOM_ID_TRIES):
        room_id = secrets.token_hex(ROOM_ID_BYTES)
        if room_id in RESERVED_DIR_NAMES or (root / room_id).exists():
            continue
        if conn.execute("SELECT 1 FROM rooms WHERE room_id = ? OR rel_path = ?", (room_id, room_id)).fetchone():
            continue
        return room_id
    raise WorkspaceMapError("Could not find a free room id.")


def create_room(name: Optional[str] = None, *, parent_space: Optional[str] = None, kind: str = "room",
                origin: str = "local") -> dict:
    """Create ``<root>/<id>`` for a new room and register it, optionally inside ``parent_space``.

    ``<id>`` is a fresh system id (:func:`new_room_id`) and also the directory name; it never changes.
    ``name`` is only the display name; without one the room is a "New chat" that its first chat
    message may name (``name_source`` ``default``).
    """
    name_source = "default" if name is None else "user"
    name = NEW_CHAT_NAME if name is None else _clean_name(name)
    if kind not in ROOM_KINDS:
        raise WorkspaceMapError(f"Unknown room kind {kind!r}; use 'room' or 'dm'.")
    root, fence = workspace_root(), default_fence()
    created: Optional[Path] = None
    try:
        with _write() as conn:
            if parent_space is not None:
                _space_row(conn, parent_space)
            room_id = new_room_id(conn, root)
            created = root / room_id
            created.mkdir()
            _insert_row(conn, room_id, kind, name, room_id, origin, fence, name_source)
            if parent_space is not None:
                _link(conn, room_id, parent_space, enforce_depth=False)
            room = _room_dict(_row(conn, room_id), root, _parents(conn, room_id))
    except BaseException:
        if created is not None:
            with contextlib.suppress(OSError):
                created.rmdir()
        raise
    return room


def new_chat_room(parent_space: Optional[str] = None) -> dict:
    """The room behind the web's "New chat" (design §B): the newest web-made room in ``parent_space``
    (or Home) that nothing has happened in yet, else a fresh :func:`create_room` (``origin="web"``).

    "Nothing happened yet" (no messages) is read from the map and the disk: the room is still named by
    default (a first message names it at once, and any rename counts too), not archived, and its
    directory is empty. A room made any other way is never handed out.
    """
    root = workspace_root()
    with _read() as conn:
        if parent_space is not None:
            _space_row(conn, parent_space)
        wanted = [parent_space] if parent_space is not None else []
        for row in conn.execute(
                "SELECT * FROM rooms WHERE type = 'room' AND origin = 'web' AND name_source = 'default' "
                "AND archived = 0 ORDER BY created_at DESC, rowid DESC").fetchall():
            parents = _parents(conn, row["room_id"])
            path = _abs_path(row["rel_path"], root)
            if parents == wanted and path.is_dir() and not any(path.iterdir()):
                return _room_dict(row, root, parents)
    return create_room(None, parent_space=parent_space, origin="web")


def create_space(name: str, parent_space: Optional[str] = None) -> dict:
    """Register a new local space (no directory), nesting-limited by :func:`max_space_depth`."""
    name = _clean_name(name)
    with _write() as conn:
        room_id = new_room_id(conn, workspace_root())
        _insert_row(conn, room_id, "space", name, None, "local", DEFAULT_FENCE)
        if parent_space is None:
            _check_depth(1)
        else:
            _link(conn, room_id, parent_space, enforce_depth=True)
        return _load(conn, room_id)


def import_space(name: str, *, parent_space: Optional[str] = None, origin: str = "matrix") -> dict:
    """Register a channel's space under a new system id (no nesting limit); the caller links the
    channel's own id with :func:`link_channel`."""
    name = _clean_name(name)
    with _write() as conn:
        room_id = new_room_id(conn, workspace_root())
        _insert_row(conn, room_id, "space", name, None, origin, DEFAULT_FENCE)
        if parent_space is not None:
            _link(conn, room_id, parent_space, enforce_depth=False)
        return _load(conn, room_id)


def _stored_path(path: Any, root: Path) -> str:
    """A registered directory as stored: relative to the root when inside it, else absolute."""
    text = str(path or "").strip()
    if not text:
        raise WorkspaceMapError("A directory path is required.")
    candidate = Path(os.path.expanduser(text))
    if candidate.is_absolute():
        candidate = Path(os.path.normpath(candidate))
        try:
            candidate = candidate.relative_to(Path(os.path.normpath(root)))
        except ValueError:
            return str(candidate)
    if not candidate.parts or ".." in candidate.parts:
        raise WorkspaceMapError(f"Not a room directory: {text}")
    return candidate.as_posix()


def import_room(room_id: str, name: str, path: str, *, kind: str = "room",
                parent_space: Optional[str] = None, origin: str = "matrix") -> dict:
    """Register an existing directory in place (no mkdir, no move); no nesting limit applies."""
    room_id, name = _clean_name(room_id), _clean_name(name)
    if kind not in ROOM_KINDS:
        raise WorkspaceMapError(f"Unknown room kind {kind!r}; use 'room' or 'dm'.")
    rel_path = _stored_path(path, workspace_root())
    with _write() as conn:
        existing = conn.execute("SELECT type, rel_path FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
        if existing is None:
            _insert_row(conn, room_id, kind, name, rel_path, origin, default_fence())
        elif existing["type"] != kind or existing["rel_path"] != rel_path:
            raise WorkspaceMapError(f"{room_id} is already registered with {existing['rel_path']}.")
        if parent_space is not None:
            _link(conn, room_id, parent_space, enforce_depth=False)
        return _load(conn, room_id)


def ensure_agent_room() -> dict:
    """The main agent's DM, bound to ``<root>/agent`` (design §B "Phi (agent)"), registered on first use."""
    agent_dir()
    query = "SELECT room_id FROM rooms WHERE type = 'dm' AND rel_path = 'agent' ORDER BY created_at, rowid LIMIT 1"
    with _read() as conn:
        row = conn.execute(query).fetchone()
        if row is not None:
            return _load(conn, row[0])
    with _write() as conn:
        row = conn.execute(query).fetchone()
        if row is None:
            _insert_row(conn, AGENT_ROOM_ID, "dm", AGENT_ROOM_NAME, "agent", "local", default_fence())
        return _load(conn, row[0] if row is not None else AGENT_ROOM_ID)


def get_room(room_id: str) -> dict:
    """One row (room, dm or space) with its parent ids; archived rows included."""
    with _read() as conn:
        return _load(conn, room_id)


def rename(room_id: str, name: str) -> dict:
    """Change the display name only; the directory stays where it is. A rename is a user's name and is
    never replaced automatically afterwards."""
    name = _clean_name(name)
    with _write() as conn:
        _row(conn, room_id)
        conn.execute("UPDATE rooms SET name = ?, name_source = 'user', updated_at = ? WHERE room_id = ?",
                     (name, _now(), room_id))
        return _load(conn, room_id)


def auto_nameable(room: dict, expect: Optional[str] = None) -> bool:
    """Whether an automatic name may replace ``room``'s: a "New chat" room always, an auto-named one only
    while it still carries ``expect`` (the instant name the model title was derived alongside)."""
    if room["type"] == "space":
        return False
    if room["name_source"] == "default":
        return True
    return room["name_source"] == "auto" and expect is not None and room["name"] == expect


def auto_name(room_id: str, name: str, *, expect: Optional[str] = None) -> Optional[dict]:
    """Name a room from its chat (``name_source`` ``auto``) if :func:`auto_nameable`; ``None`` when it is
    not (someone named it, or another name got there first). The directory stays where it is."""
    name = _clean_name(name)
    with _write() as conn:
        if not auto_nameable(_load(conn, room_id), expect):
            return None
        conn.execute("UPDATE rooms SET name = ?, name_source = 'auto', updated_at = ? WHERE room_id = ?",
                     (name, _now(), room_id))
        return _load(conn, room_id)


def move(room_id: str, from_parent: Optional[str], to_parent: Optional[str]) -> dict:
    """Move a room or space between spaces; ``None`` on either side is Home (no space)."""
    with _write() as conn:
        _row(conn, room_id)
        if from_parent == to_parent:
            return _load(conn, room_id)
        if from_parent is not None:
            _space_row(conn, from_parent)
            removed = conn.execute("DELETE FROM space_children WHERE parent_id = ? AND child_id = ?",
                                   (from_parent, room_id)).rowcount
            if not removed:
                raise WorkspaceMapError(f"{room_id} is not in {from_parent}.")
        if to_parent is not None:
            _link(conn, room_id, to_parent, enforce_depth=True)
        return _load(conn, room_id)


def add_parent(room_id: str, parent_id: str) -> dict:
    """Also show ``room_id`` inside ``parent_id`` (a room can live in several spaces)."""
    with _write() as conn:
        _link(conn, room_id, parent_id, enforce_depth=True)
        return _load(conn, room_id)


def remove_parent(room_id: str, parent_id: str) -> dict:
    """Take ``room_id`` out of ``parent_id``; with no parent left it shows in Home."""
    with _write() as conn:
        _row(conn, room_id)
        conn.execute("DELETE FROM space_children WHERE parent_id = ? AND child_id = ?", (parent_id, room_id))
        return _load(conn, room_id)


def archive(room_id: str) -> dict:
    """Hide a room or space from listings; its directory, links and bindings stay."""
    with _write() as conn:
        _row(conn, room_id)
        conn.execute("UPDATE rooms SET archived = 1, updated_at = ? WHERE room_id = ?", (_now(), room_id))
        return _load(conn, room_id)


def delete_space(space_id: str) -> dict:
    """Delete a space. Its rooms and sub-spaces move up into the space's own parent(s), or to Home / the
    top level; rooms keep their directories, sessions and links (a space has no directory). Returns the
    ids that moved up."""
    with _write() as conn:
        _space_row(conn, space_id)
        parents = _parents(conn, space_id)
        kids = [r[0] for r in conn.execute(
            "SELECT child_id FROM space_children WHERE parent_id = ? ORDER BY ord, rowid", (space_id,))]
        for parent_id in parents:
            for child_id in kids:
                _insert_link(conn, parent_id, child_id)
        conn.execute("DELETE FROM rooms WHERE room_id = ?", (space_id,))
        return {"deleted": space_id, "moved_up": kids, "into": parents}


def _live_graph(conn: sqlite3.Connection) -> tuple[dict, dict[str, list[str]], dict[str, list[str]]]:
    """Non-archived rows plus parent→children / child→parents among them, children in order."""
    rows = {r["room_id"]: r for r in conn.execute(
        "SELECT * FROM rooms WHERE archived = 0 ORDER BY created_at, rowid")}
    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}
    for parent_id, child_id in conn.execute(
            "SELECT parent_id, child_id FROM space_children ORDER BY ord, rowid"):
        if parent_id in rows and child_id in rows:
            children.setdefault(parent_id, []).append(child_id)
            parents.setdefault(child_id, []).append(parent_id)
    return rows, children, parents


def _home_ids(rows: dict, parents: dict[str, list[str]]) -> list[str]:
    home = [rid for rid, r in rows.items()
            if r["type"] == "dm" or (r["type"] == "room" and not parents.get(rid))]
    # The agent DM first, then other DMs, then rooms, each in creation order.
    return sorted(home, key=lambda rid: (rows[rid]["rel_path"] != "agent", rows[rid]["type"] != "dm"))


def list_rooms(space_id: Optional[str] = None) -> list[dict]:
    """Rooms directly in ``space_id`` in their order, or Home for ``None``: the agent DM (ensured),
    other DMs, then rooms in no space. Archived rows and spaces are not listed."""
    if space_id is None:
        ensure_agent_room()
    root = workspace_root()
    with _read() as conn:
        if space_id is not None:
            _space_row(conn, space_id)
        rows, children, parents = _live_graph(conn)
        if space_id is None:
            ids = _home_ids(rows, parents)
        else:
            ids = [c for c in children.get(space_id, []) if rows[c]["type"] in ROOM_KINDS]
        return [_room_dict(rows[rid], root, parents.get(rid, [])) for rid in ids]


def list_tree() -> dict:
    """``{"spaces": [...], "home": [...]}``: top-level spaces, each ``{room_id, name, children, rooms}``
    with nested sub-spaces under ``children`` and room ids under ``rooms``; a space with several parents
    appears under each. ``home`` is :func:`list_rooms(None) <list_rooms>` as ids."""
    ensure_agent_room()
    with _read() as conn:
        rows, children, parents = _live_graph(conn)

    def node(space_id: str, path: frozenset) -> dict:
        kids = children.get(space_id, [])
        return {
            "room_id": space_id, "name": rows[space_id]["name"],
            "children": [node(k, path | {k}) for k in kids if rows[k]["type"] == "space" and k not in path],
            "rooms": [k for k in kids if rows[k]["type"] in ROOM_KINDS],
        }

    top = [rid for rid, r in rows.items() if r["type"] == "space" and not parents.get(rid)]
    return {"spaces": [node(s, frozenset({s})) for s in top], "home": _home_ids(rows, parents)}


def resolve(room_id: str) -> Path:
    """The absolute directory of a room or DM (``RoomNotFound`` if unregistered)."""
    with _read() as conn:
        row = _row(conn, room_id)
    if row["rel_path"] is None:
        raise WorkspaceMapError(f"{room_id} is a space and has no directory.")
    return _abs_path(row["rel_path"], workspace_root())


def link_channel(room_id: str, channel: str, external_id: str) -> dict:
    """Let ``channel``'s ``external_id`` reach ``room_id``; one external id maps to one room."""
    channel, external_id = _clean_name(channel), _clean_name(external_id)
    with _write() as conn:
        _row(conn, room_id)
        owner = conn.execute("SELECT room_id FROM channel_links WHERE channel = ? AND external_id = ?",
                             (channel, external_id)).fetchone()
        if owner is not None and owner[0] != room_id:
            raise WorkspaceMapError(f"{channel} {external_id} is already linked to {owner[0]}.")
        conn.execute("INSERT OR IGNORE INTO channel_links (room_id, channel, external_id) VALUES (?, ?, ?)",
                     (room_id, channel, external_id))
        return _load(conn, room_id)


def room_for_channel(channel: str, external_id: str) -> Optional[dict]:
    """The room a channel's external id is linked to, or ``None``."""
    with _read() as conn:
        row = conn.execute("SELECT room_id FROM channel_links WHERE channel = ? AND external_id = ?",
                           (channel, external_id)).fetchone()
        return _load(conn, row[0]) if row is not None else None


def room_for_dir(path: Any) -> Optional[dict]:
    """The room or DM whose directory is exactly ``path`` (not a subdirectory of it), or ``None``."""
    text = str(path or "").strip()
    if not text:
        return None
    target = Path(os.path.realpath(os.path.expanduser(text)))
    try:
        stored = target.relative_to(Path(os.path.realpath(workspace_root()))).as_posix()
    except ValueError:
        stored = str(target)
    with _read() as conn:
        row = conn.execute("SELECT room_id FROM rooms WHERE rel_path = ? ORDER BY created_at, rowid LIMIT 1",
                           (stored,)).fetchone()
        return _load(conn, row[0]) if row is not None else None


def check() -> dict:
    """Map/disk drift: live rooms whose directory is missing, and top-level directories under the root
    that no room uses (dot-dirs and reserved names ignored). Read-only."""
    root = workspace_root()
    with _read() as conn:
        rows = conn.execute("SELECT room_id, rel_path, archived FROM rooms WHERE rel_path IS NOT NULL").fetchall()
    issues: list[dict] = []
    used: set[str] = set()
    for row in rows:
        path = _abs_path(row["rel_path"], root)
        with contextlib.suppress(ValueError):
            used.add(path.relative_to(root).parts[0])
        if not row["archived"] and not path.is_dir():
            issues.append({"kind": "missing_dir", "room_id": row["room_id"], "path": str(path)})
    for entry in sorted(root.iterdir()):
        name = entry.name
        if entry.is_dir() and not name.startswith(".") and name not in RESERVED_DIR_NAMES and name not in used:
            issues.append({"kind": "unmapped_dir", "path": name})
    live = sum(1 for row in rows if not row["archived"])
    return {"root": str(root), "rooms": live, "issues": issues}


def export_map() -> dict:
    """The whole map in the :func:`import_draft` shape (paths as stored)."""
    with _read() as conn:
        rows = conn.execute("SELECT * FROM rooms ORDER BY created_at, rowid").fetchall()
        parents: dict[str, list[str]] = {}
        for parent_id, child_id in conn.execute("SELECT parent_id, child_id FROM space_children ORDER BY rowid"):
            parents.setdefault(child_id, []).append(parent_id)
        channels: dict[str, list[dict]] = {}
        for room_id, channel, external_id in conn.execute(
                "SELECT room_id, channel, external_id FROM channel_links ORDER BY rowid"):
            channels.setdefault(room_id, []).append({"channel": channel, "external_id": external_id})
    spaces, rooms = [], []
    for row in rows:
        entry = {"room_id": row["room_id"], "name": row["name"], "origin": row["origin"],
                 "parents": parents.get(row["room_id"], []), "archived": bool(row["archived"])}
        if row["type"] == "space":
            spaces.append(entry)
        else:
            rooms.append({**entry, "type": row["type"], "path": row["rel_path"],
                          "channels": channels.get(row["room_id"], [])})
    return {"root": str(workspace_root()), "spaces": spaces, "rooms": rooms}


def _plan_entry(conn: sqlite3.Connection, kind: str, item: Any, root: Path, draft_spaces: set,
                seen: set) -> dict:
    entry: dict[str, Any] = {"room_id": None, "type": kind, "name": None, "parents": [], "action": "register"}

    def fail(action: str, message: str) -> dict:
        entry.update(action=action, error=message)
        return entry

    if not isinstance(item, dict):
        return fail("error", "Each entry must be an object.")
    room_id, name = str(item.get("room_id") or "").strip(), str(item.get("name") or "").strip()
    entry.update(room_id=room_id or None, name=name or None, origin=str(item.get("origin") or "matrix"))
    if kind != "space":
        entry["type"] = item.get("type", "room")
    if not room_id or not name:
        return fail("error", "room_id and name are required.")
    if room_id in seen:
        return fail("error", "Listed twice in the draft.")
    seen.add(room_id)
    if entry["type"] not in ("space", *ROOM_KINDS):
        return fail("error", f"Unknown room type {entry['type']!r}.")
    parents = item.get("parents") or []
    if not isinstance(parents, list):
        return fail("error", "parents must be a list.")
    entry["parents"] = [str(p) for p in parents]
    for parent in entry["parents"]:
        known = conn.execute("SELECT type FROM rooms WHERE room_id = ?", (parent,)).fetchone()
        if parent not in draft_spaces and (known is None or known["type"] != "space"):
            return fail("error", f"Parent {parent} is not a known space.")
    existing = conn.execute("SELECT type, rel_path FROM rooms WHERE room_id = ?", (room_id,)).fetchone()
    if kind == "space":
        if existing is not None:
            entry["action"] = "exists" if existing["type"] == "space" else "conflict"
        return entry
    try:
        entry["rel_path"] = _stored_path(item.get("path"), root)
    except WorkspaceMapError as exc:
        return fail("error", str(exc))
    entry["dir_exists"] = _abs_path(entry["rel_path"], root).is_dir()
    channels = item.get("channels") or []
    if not isinstance(channels, list) or not all(
            isinstance(c, dict) and c.get("channel") and c.get("external_id") for c in channels):
        return fail("error", "channels must be a list of {channel, external_id}.")
    entry["channels"] = [{"channel": str(c["channel"]), "external_id": str(c["external_id"])} for c in channels]
    for link in entry["channels"]:
        owner = conn.execute("SELECT room_id FROM channel_links WHERE channel = ? AND external_id = ?",
                             (link["channel"], link["external_id"])).fetchone()
        if owner is not None and owner[0] != room_id:
            return fail("conflict", f"{link['channel']} {link['external_id']} is linked to {owner[0]}.")
    if existing is not None:
        if existing["type"] == entry["type"] and existing["rel_path"] == entry["rel_path"]:
            entry["action"] = "exists"
        else:
            return fail("conflict", f"Already registered as a {existing['type']} with {existing['rel_path']}.")
    return entry


def _plan(conn: sqlite3.Connection, draft: Any, root: Path) -> list[dict]:
    if not isinstance(draft, dict):
        raise WorkspaceMapError("The draft must be an object with 'spaces' and 'rooms'.")
    spaces, rooms = draft.get("spaces") or [], draft.get("rooms") or []
    if not isinstance(spaces, list) or not isinstance(rooms, list):
        raise WorkspaceMapError("'spaces' and 'rooms' must be lists.")
    draft_spaces = {str(s.get("room_id") or "").strip() for s in spaces if isinstance(s, dict)}
    seen: set[str] = set()
    return ([_plan_entry(conn, "space", s, root, draft_spaces, seen) for s in spaces]
            + [_plan_entry(conn, "room", r, root, draft_spaces, seen) for r in rooms])


def import_draft(draft: dict, apply: bool = False) -> dict:
    """Register a reviewed migration draft (design §八): existing spaces, rooms and directories as they are.

    Draft shape (what :func:`export_map` produces)::

        {"spaces": [{"room_id", "name", "parents": [...], "origin"?}],
         "rooms":  [{"room_id", "name", "type": "room"|"dm", "path", "parents": [...],
                     "channels": [{"channel", "external_id"}], "origin"?}]}

    ``path`` is relative to the workspace root or absolute; an absolute path inside the root is stored
    relative, one outside stays absolute (legacy directory, left in place). The dry run only reports
    each entry's action (register / exists / conflict / error). ``apply`` inserts rows and links in
    one transaction — it never creates, moves or renames a directory, ignores the nesting limit, and
    writes nothing while any entry is an error or conflict.
    """
    root = workspace_root()
    connection = _write() if apply else _read()
    with connection as conn:
        entries = _plan(conn, draft, root)
        summary = {action: sum(1 for e in entries if e["action"] == action)
                   for action in ("register", "exists", "conflict", "error")}
        if apply:
            if summary["conflict"] or summary["error"]:
                raise WorkspaceMapError(
                    f"The draft has {summary['conflict']} conflict(s) and {summary['error']} error(s); "
                    "nothing was imported.")
            fence = default_fence()
            for e in entries:
                if e["action"] == "register":
                    _insert_row(conn, e["room_id"], e["type"], e["name"], e.get("rel_path"), e["origin"],
                                DEFAULT_FENCE if e["type"] == "space" else fence)
            for e in entries:
                for parent in e["parents"]:
                    _insert_link(conn, parent, e["room_id"])
                for link in e.get("channels", []):
                    conn.execute("INSERT OR IGNORE INTO channel_links (room_id, channel, external_id) "
                                 "VALUES (?, ?, ?)", (e["room_id"], link["channel"], link["external_id"]))
    return {"applied": bool(apply), "root": str(root), "entries": entries, "summary": summary}


# --- Channel mirrors (Matrix space mirror, design §七) -------------------------------------------------
# A channel that writes its own side first validates with check_* before writing, then mirrors what the
# channel holds with import_parent (an edge as it is, any depth) and unarchive (a room rejoined).


def matrix_mirror_enabled() -> bool:
    """``matrix.space_mirror`` (default on): mirror the agent's Matrix spaces and rooms into the map."""
    from phi_cli.config import cfg_get, load_config_readonly
    from utils import is_truthy_value
    return is_truthy_value(cfg_get(load_config_readonly(), "matrix", "space_mirror", default=True), default=True)


def channel_links(channel: str) -> dict[str, str]:
    """``{external_id: room_id}`` for every link of ``channel``, archived rooms included."""
    with _read() as conn:
        return {ext: rid for rid, ext in conn.execute(
            "SELECT room_id, external_id FROM channel_links WHERE channel = ? ORDER BY rowid", (channel,))}


def room_links(room_id: str) -> list[tuple[str, str]]:
    """``(channel, external_id)`` for every link of ``room_id``, in link order."""
    with _read() as conn:
        return [(c, e) for c, e in conn.execute(
            "SELECT channel, external_id FROM channel_links WHERE room_id = ? ORDER BY rowid", (room_id,))]


def _pointer(room_id: str) -> Optional[sqlite3.Row]:
    with _read() as conn:
        return conn.execute("SELECT session_id, updated_at FROM room_conversations WHERE room_id = ?",
                            (room_id,)).fetchone()


def current_conversation(room_id: str) -> Optional[str]:
    """The session id the room's linked chat tools continue, or ``None`` before its first turn."""
    row = _pointer(room_id)
    return row["session_id"] if row is not None else None


def current_conversation_since(room_id: str) -> Optional[float]:
    """When the room's current conversation was last set (epoch seconds), or ``None``."""
    row = _pointer(room_id)
    return row["updated_at"] if row is not None else None


def set_current_conversation(room_id: str, session_id: str) -> None:
    """Make ``session_id`` the room's current conversation as of now; ``RoomNotFound`` for no room."""
    with _write() as conn:
        _row(conn, room_id)
        conn.execute(
            "INSERT INTO room_conversations (room_id, session_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(room_id) DO UPDATE SET session_id = excluded.session_id, updated_at = excluded.updated_at",
            (room_id, session_id, time.time()))


def unarchive(room_id: str) -> dict:
    """Show an archived room or space again (its channel room was rejoined)."""
    with _write() as conn:
        _row(conn, room_id)
        conn.execute("UPDATE rooms SET archived = 0, updated_at = ? WHERE room_id = ?", (_now(), room_id))
        return _load(conn, room_id)


# --- Activity (design §五: running/unread badges) -----------------------------------------------------


def mark_seen(room_id: str, when: Optional[float] = None) -> dict:
    """Record that the dashboard showed ``room_id`` now: replies up to ``when`` are no longer unread."""
    with _write() as conn:
        _row(conn, room_id)
        conn.execute("UPDATE rooms SET last_seen = ? WHERE room_id = ?",
                     (time.time() if when is None else float(when), room_id))
        return _load(conn, room_id)


def mark_all_seen(when: Optional[float] = None) -> int:
    """Mark every live room and DM as seen now (the room list's "mark all as read"); returns how many."""
    with _write() as conn:
        cur = conn.execute("UPDATE rooms SET last_seen = ? WHERE type != 'space' AND archived = 0",
                           (time.time() if when is None else float(when),))
        return cur.rowcount


def activity_inputs() -> tuple[list[tuple[str, str, Optional[float]]], list[tuple[str, str, str]]]:
    """Live rooms/DMs as ``(room_id, absolute dir, last_seen)`` and their links ``(channel, external_id,
    room_id)`` — what the activity query matches sessions against."""
    root = workspace_root()
    with _read() as conn:
        rows = conn.execute("SELECT room_id, rel_path, last_seen FROM rooms "
                            "WHERE archived = 0 AND type != 'space' ORDER BY created_at, rowid").fetchall()
        links = conn.execute(
            "SELECT l.channel, l.external_id, l.room_id FROM channel_links l JOIN rooms r ON r.room_id = l.room_id "
            "WHERE r.archived = 0 AND r.type != 'space' ORDER BY l.rowid").fetchall()
    rooms = [(r["room_id"], str(_abs_path(r["rel_path"], root)), r["last_seen"]) for r in rows]
    return rooms, [(c, e, rid) for c, e, rid in links]


def import_parent(room_id: str, parent_id: str) -> dict:
    """Record a channel's edge ``parent_id`` → ``room_id`` as it is: no nesting limit, no cycle check."""
    with _write() as conn:
        _link(conn, room_id, parent_id, enforce_depth=False)
        return _load(conn, room_id)


def check_space_nesting(parent_space: Optional[str]) -> None:
    """Raise as :func:`create_space` would for a new space in ``parent_space``; writes nothing."""
    with _read() as conn:
        if parent_space is None:
            _check_depth(1)
        else:
            _space_row(conn, parent_space)
            _check_depth(_space_level(conn, parent_space) + 1)


def check_move(room_id: str, from_parent: Optional[str], to_parent: Optional[str]) -> dict:
    """Raise as :func:`move` would for these arguments; writes nothing. Returns the room."""
    with _read() as conn:
        room = _load(conn, room_id)
        if from_parent == to_parent:
            return room
        if from_parent is not None:
            _space_row(conn, from_parent)
            if from_parent not in room["parents"]:
                raise WorkspaceMapError(f"{room_id} is not in {from_parent}.")
        if to_parent is not None:
            _space_row(conn, to_parent)
            if room["type"] == "space":
                if room_id == to_parent or room_id in _ancestors(conn, to_parent):
                    raise WorkspaceMapError("A space cannot be placed inside itself.")
                _check_depth(_space_level(conn, to_parent) + _space_height(conn, room_id))
        return room

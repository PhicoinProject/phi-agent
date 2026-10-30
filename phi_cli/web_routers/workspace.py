"""Workspace map REST: spaces, rooms and their directories (design §五, Settings → Workspace).

Thin wrappers over :mod:`phi_cli.workspace_map`, each run in the ``?profile=`` home. Bad input is
400, an unknown room or space 404. A room's rules are its ``AGENTS.md`` (capped, see
:data:`agent.room_binding.ROOM_RULES_MAX_CHARS`). Changing ``workspace.root`` moves every room directory and is
done by the separate Move-workspace flow; ``PUT /api/workspace/settings`` only accepts the current root.

Create-space, rename and move touching a Matrix-linked room or space go through the running gateway's
Matrix space mirror (design §七): Matrix is written first and the map changes only when it accepts. A new
top-level space is created in Matrix too while the mirror is on; with no gateway running it is map-only.

Archive only hides a room in the map (never leaves the channel room). ``/api/workspace/activity`` counts
running sessions and unseen assistant replies per room in one query, cached briefly. ``/api/workspace/root``
plans and runs Move workspace as a background job (:func:`phi_cli.workspace_root.move_root`).
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from phi_cli.web_deps import late
from phi_cli.web_routers._common import (
    _CONFIG_MUTATION_LOCK, _config_profile_scope, config_write_scope, destructive_profile, http_failure,
    scoped_to_thread,
)

router = APIRouter()
_log = logging.getLogger(__name__)

load_config = late("load_config", "phi_cli.config")
save_config = late("save_config", "phi_cli.config")

MIN_SPACE_DEPTH = 2
MAX_SPACE_DEPTH = 8


class WorkspaceNameBody(BaseModel):
    name: str
    parent_space: Optional[str] = None


class NewChatBody(BaseModel):
    parent_space: Optional[str] = None


class RoomRulesBody(BaseModel):
    content: str


class WorkspaceRenameBody(BaseModel):
    name: Optional[str] = None


class WorkspaceMoveBody(BaseModel):
    room_id: str
    from_space: Optional[str] = Field(default=None, alias="from")
    to_space: Optional[str] = Field(default=None, alias="to")


class WorkspaceRootBody(BaseModel):
    path: str


class WorkspaceSettingsBody(BaseModel):
    root: Optional[str] = None
    max_space_depth: Optional[Any] = None
    default_fence: Optional[str] = None


async def _call(profile: Optional[str], label: str, fn: Callable[[], Any]) -> Any:
    """Run ``fn`` in the profile's home: unknown id → 404, refused input → 400, anything else → 500."""
    def _run():
        try:
            return fn()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    with http_failure(f"{label} failed", 500, "Workspace map error"):
        return await scoped_to_thread(profile, _run)


def _wm():
    from phi_cli import workspace_map
    return workspace_map


def _matrix_write(op: str, args: dict, ids: list) -> Optional[dict]:
    """The mirror's answer when ``ids`` include a Matrix-linked room or space and ``matrix.space_mirror``
    is on, else None (the map alone is edited). Runs inside ``_call``'s thread and profile scope."""
    wm = _wm()
    if not wm.matrix_mirror_enabled():
        return None
    if not set(wm.channel_links("matrix").values()).intersection(i for i in ids if i):
        return None
    from gateway.adapter_actions import call_adapter_action
    answer = call_adapter_action("matrix", f"space_mirror.{op}", args)
    if answer is None:
        raise HTTPException(status_code=503, detail=(
            "Matrix write-back unavailable: no running gateway answered. Start the gateway, "
            "or set matrix.space_mirror: false to edit the map only."))
    if answer.get("error"):
        raise HTTPException(status_code=int(answer.get("status") or 502), detail=str(answer["error"]))
    return answer


@router.get("/api/workspace/tree")
async def get_workspace_tree(profile: Optional[str] = None):
    """Top-level spaces with nested sub-spaces and room ids, plus Home."""
    return await _call(profile, "GET /api/workspace/tree", lambda: _wm().list_tree())


@router.get("/api/workspace/rooms")
async def list_workspace_rooms(space: Optional[str] = None, profile: Optional[str] = None):
    """Rooms directly in ``space``, or Home (agent DM, DMs, unfiled rooms) when omitted."""
    return await _call(profile, "GET /api/workspace/rooms",
                       lambda: {"rooms": _wm().list_rooms((space or "").strip() or None)})


@router.post("/api/workspace/rooms")
async def create_workspace_room(body: WorkspaceNameBody, profile: Optional[str] = None):
    """Create a room and its directory under the workspace root."""
    return await _call(profile, "POST /api/workspace/rooms", lambda: {
        "room": _wm().create_room(body.name, parent_space=body.parent_space or None)})


@router.post("/api/workspace/rooms/new-chat")
async def new_chat_room(body: NewChatBody, profile: Optional[str] = None):
    """The room for "New chat" in ``parent_space`` (or Home): the newest web-made "New chat" room that has
    no messages yet, else a new one. "No messages" means still default-named (a first message names it
    at once) with an empty directory; see :func:`phi_cli.workspace_map.new_chat_room`."""
    return await _call(profile, "POST /api/workspace/rooms/new-chat", lambda: {
        "room": _wm().new_chat_room(body.parent_space or None)})


def _rules_file(room_id: str):
    return _wm().resolve(room_id) / "AGENTS.md"


@router.get("/api/workspace/rooms/{room_id}/rules")
async def get_room_rules(room_id: str, profile: Optional[str] = None):
    """The room's ``AGENTS.md`` (empty when it has none) and its size limit."""
    from agent.room_binding import ROOM_RULES_MAX_CHARS

    def _run():
        path = _rules_file(room_id)
        content = path.read_text(encoding="utf-8") if path.is_file() else ""
        return {"room_id": room_id, "path": str(path), "content": content, "max_chars": ROOM_RULES_MAX_CHARS}

    return await _call(profile, "GET /api/workspace/rooms/rules", _run)


@router.put("/api/workspace/rooms/{room_id}/rules")
async def put_room_rules(room_id: str, body: RoomRulesBody, profile: Optional[str] = None):
    """Replace the room's ``AGENTS.md`` atomically; longer than the limit is 413."""
    from agent.room_binding import ROOM_RULES_MAX_CHARS
    from utils import atomic_write_text

    if len(body.content) > ROOM_RULES_MAX_CHARS:
        raise HTTPException(status_code=413, detail=(
            f"Room rules are limited to {ROOM_RULES_MAX_CHARS} characters; shorten them."))

    def _run():
        path = _rules_file(room_id)
        atomic_write_text(path, body.content)
        return {"room_id": room_id, "path": str(path), "content": body.content, "max_chars": ROOM_RULES_MAX_CHARS}

    return await _call(profile, "PUT /api/workspace/rooms/rules", _run)


@router.post("/api/workspace/spaces")
async def create_workspace_space(body: WorkspaceNameBody, profile: Optional[str] = None):
    """Create a space (no directory), within the nesting limit."""
    def _run():
        parent = body.parent_space or None
        if parent is None:
            return _create_top_level_space(body.name)
        answer = _matrix_write("create_space", {"name": body.name, "parent_space": parent}, [parent])
        if answer is not None:
            return {"space": answer["space"]}
        return {"space": _wm().create_space(body.name, parent_space=parent)}

    return await _call(profile, "POST /api/workspace/spaces", _run)


def _create_top_level_space(name: str) -> dict:
    """With the mirror on, the gateway creates the space in Matrix and records it; no gateway, or Matrix
    not connected, is map-only and says why in ``matrix``. Other Matrix refusals are the answer."""
    wm = _wm()
    if not wm.matrix_mirror_enabled():
        return {"space": wm.create_space(name)}
    if not name.strip():
        raise ValueError("A space needs a name.")
    wm.check_space_nesting(None)
    from gateway.adapter_actions import call_adapter_action
    answer = call_adapter_action("matrix", "space_mirror.create_space", {"name": name, "parent_space": None})
    if answer is None:
        return {"space": wm.create_space(name), "matrix": "skipped: gateway not running"}
    if answer.get("error"):
        status = int(answer.get("status") or 502)
        if status in (404, 503):  # an older gateway without the action, or Matrix not connected
            return {"space": wm.create_space(name), "matrix": f"skipped: {answer['error']}"}
        raise HTTPException(status_code=status, detail=str(answer["error"]))
    return {"space": answer["space"], "matrix": "created"}


@router.patch("/api/workspace/rooms/{room_id}")
async def update_workspace_room(room_id: str, body: WorkspaceRenameBody, profile: Optional[str] = None):
    """Rename a room or space; its directory keeps its name."""
    def _run():
        wm = _wm()
        if body.name is None:
            return {"room": wm.get_room(room_id)}
        answer = _matrix_write("rename", {"room_id": room_id, "name": body.name}, [room_id])
        if answer is not None:
            return {"room": answer["room"]}
        return {"room": wm.rename(room_id, body.name)}

    return await _call(profile, "PATCH /api/workspace/rooms", _run)


@router.post("/api/workspace/move")
async def move_workspace_room(body: WorkspaceMoveBody, profile: Optional[str] = None):
    """Move a room or space between spaces; ``null`` is Home."""
    def _run():
        src, dst = body.from_space or None, body.to_space or None
        answer = _matrix_write("move", {"room_id": body.room_id, "from_space": src, "to_space": dst},
                               [body.room_id, src, dst])
        if answer is not None:
            return {"room": answer["room"]}
        return {"room": _wm().move(body.room_id, src, dst)}

    return await _call(profile, "POST /api/workspace/move", _run)


@router.post("/api/workspace/rooms/{room_id}/archive")
async def archive_workspace_room(room_id: str, profile: Optional[str] = None):
    """Hide a room or space from the tree; its directory and channel links stay (map only)."""
    return await _call(profile, "POST /api/workspace/rooms/archive", lambda: {"room": _wm().archive(room_id)})


@router.delete("/api/workspace/spaces/{space_id}")
async def delete_workspace_space(space_id: str, profile: Optional[str] = None):
    """Delete a space; its rooms and sub-spaces move up one level and no directory is touched. A space
    mirrored from Matrix is removed in Matrix instead (the mirror would bring it back)."""
    def _run():
        wm = _wm()
        if wm.matrix_mirror_enabled() and space_id in set(wm.channel_links("matrix").values()):
            raise ValueError("This space mirrors a Matrix space. Remove it in Matrix (Element) and it "
                             "disappears here; or set matrix.space_mirror: false to edit the map only.")
        return wm.delete_space(space_id)

    return await _call(profile, "DELETE /api/workspace/spaces", _run)


@router.post("/api/workspace/rooms/{room_id}/unarchive")
async def unarchive_workspace_room(room_id: str, profile: Optional[str] = None):
    """Show an archived room or space in the tree again."""
    return await _call(profile, "POST /api/workspace/rooms/unarchive", lambda: {"room": _wm().unarchive(room_id)})


_ACTIVITY_TTL = 5.0
_ACTIVITY_CACHE: dict[str, tuple[float, dict]] = {}


def _home_key() -> str:
    from phi_constants import get_phi_home
    return str(get_phi_home())


@router.post("/api/workspace/rooms/seen-all")
async def mark_workspace_rooms_all_seen(profile: Optional[str] = None):
    """Mark all as read: every room's replies so far are no longer unread."""
    def _run():
        count = _wm().mark_all_seen()
        _ACTIVITY_CACHE.pop(_home_key(), None)
        return {"marked": count}

    return await _call(profile, "POST /api/workspace/rooms/seen-all", _run)


@router.post("/api/workspace/rooms/{room_id}/seen")
async def mark_workspace_room_seen(room_id: str, profile: Optional[str] = None):
    """The dashboard showed this room: its replies so far are no longer unread."""
    def _run():
        room = _wm().mark_seen(room_id)
        _ACTIVITY_CACHE.pop(_home_key(), None)
        return {"room": room}

    return await _call(profile, "POST /api/workspace/rooms/seen", _run)


def _activity_sql() -> str:
    """Per room: running sessions (``/api/sessions`` is_active) and assistant replies newer than ``last_seen``.

    A session belongs to the room its web chat was opened in (local policy receipt, by id then by owner
    chat id), else its channel link (source, chat id), else the room whose directory is its exact cwd.
    Subagent runs are not counted. The room/link lists are MATERIALIZED: inlined, SQLite re-parses the
    JSON for every session row (24 s on a 2,500-session store with 70 rooms; 0.02 s materialized)."""
    from phi_cli.web_routers.sessions import _ACTIVE_WINDOW_S
    from phi_state_common import _ephemeral_child_sql, _sql_json_extract, _sql_session_last_active

    def policy_room(key_expr: str) -> str:
        request = _sql_json_extract("pm.value", "$.policy.request_json")
        return (f"(SELECT r.room_id FROM ws_room r WHERE r.room_id = (SELECT {_sql_json_extract(request, '$.room_id')}"
                f" FROM state_meta pm WHERE pm.key = :prefix || {key_expr}))")

    return f"""
WITH ws_room(room_id, dir, last_seen) AS MATERIALIZED (
    SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]')
    FROM json_each(:rooms)),
ws_link(channel, external_id, room_id) AS MATERIALIZED (
    SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]')
    FROM json_each(:links)),
bound AS (
    SELECT s.id, s.ended_at, {_sql_session_last_active('s')} AS last_active,
        COALESCE({policy_room('s.id')}, {policy_room('s.chat_id')},
            (SELECT l.room_id FROM ws_link l WHERE l.channel = s.source AND l.external_id = s.chat_id),
            (SELECT r.room_id FROM ws_room r WHERE r.dir = s.cwd)) AS room_id
    FROM sessions s WHERE NOT {_ephemeral_child_sql('s')})
SELECT b.room_id,
    SUM(CASE WHEN b.ended_at IS NULL AND :now - b.last_active < {_ACTIVE_WINDOW_S} THEN 1 ELSE 0 END),
    SUM((SELECT COUNT(*) FROM messages m INDEXED BY idx_messages_session
         WHERE m.session_id = b.id AND m.timestamp > COALESCE(r.last_seen, 0)
         AND m.role = 'assistant' AND m.active = 1))
FROM bound b JOIN ws_room r ON r.room_id = b.room_id
GROUP BY b.room_id"""


def _room_sessions_sql() -> str:
    """Ids of the top-level sessions bound to ``:room`` (same binding rules as :func:`_activity_sql`),
    newest activity first. Only dashboard chats (a ``local-`` chat or a local creation receipt): the
    session authority restores those for the web terminal; a channel or CLI session there would come
    back ``not_found``."""
    from phi_state_common import _ephemeral_child_sql, _sql_json_extract, _sql_session_last_active

    def policy_room(key_expr: str) -> str:
        request = _sql_json_extract("pm.value", "$.policy.request_json")
        return f"(SELECT {_sql_json_extract(request, '$.room_id')} FROM state_meta pm WHERE pm.key = :prefix || {key_expr})"

    return f"""
WITH ws_link(channel, external_id, room_id) AS MATERIALIZED (
    SELECT json_extract(value, '$[0]'), json_extract(value, '$[1]'), json_extract(value, '$[2]')
    FROM json_each(:links))
SELECT s.id FROM sessions s
WHERE s.parent_session_id IS NULL AND NOT {_ephemeral_child_sql('s')} AND s.message_count > 0
  AND (s.chat_id LIKE 'local-%' OR EXISTS (SELECT 1 FROM state_meta lm WHERE lm.key IN (:prefix || s.id, :legacy || s.id)))
  AND COALESCE({policy_room('s.id')}, {policy_room('s.chat_id')},
        (SELECT l.room_id FROM ws_link l WHERE l.channel = s.source AND l.external_id = s.chat_id),
        CASE WHEN s.cwd = :dir THEN :room END) = :room
ORDER BY {_sql_session_last_active('s')} DESC LIMIT 1"""


def latest_room_session(room_id: str, profile: Optional[str]) -> Optional[str]:
    """The room's current conversation (the one its linked chat tools continue) while it is a chat with
    messages, else its most recent conversation, so opening a room resumes it instead of a blank chat.

    Runs inside the caller's profile scope (the map and the session store are per profile). None when
    the room has no conversation yet, is unknown, or the session store is absent."""
    from phi_cli.web_server_sessions import _open_session_db_at_path, _session_db_path_for_profile
    from phi_state_local import POLICY_PREFIX
    from phi_state_local_migration import LEGACY_PREFIX

    rooms, links = _wm().activity_inputs()
    target = next((d for rid, d, _seen in rooms if rid == room_id), None)
    if target is None:
        return None
    path = _session_db_path_for_profile(profile)
    try:
        if path.stat().st_size == 0:
            return None
    except FileNotFoundError:
        return None
    pointer = _wm().current_conversation(room_id)
    db = _open_session_db_at_path(path, read_only=True)
    try:
        if _is_room_conversation(db, pointer):
            return pointer
        row = db._conn.execute(_room_sessions_sql(), {
            "room": room_id, "dir": target, "prefix": POLICY_PREFIX, "legacy": LEGACY_PREFIX,
            "links": json.dumps([link for link in links if link[2] == room_id])}).fetchone()
    finally:
        db.close()
    return row[0] if row else None


def _is_room_conversation(db, session_id: Optional[str]) -> bool:
    """Whether a room's pointer names a chat with messages, not a gone session or a background run."""
    from gateway.room_conversation import BACKGROUND_SOURCES
    if not session_id:
        return False
    row = db._conn.execute("SELECT source, message_count FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return row is not None and row[0] not in BACKGROUND_SOURCES and (row[1] or 0) > 0


def _activity(profile: Optional[str]) -> dict:
    from phi_cli.web_server_sessions import _open_session_db_at_path, _session_db_path_for_profile
    from phi_state_local import POLICY_PREFIX

    rooms, links = _wm().activity_inputs()
    result = {rid: {"running": 0, "unread": 0} for rid, _dir, _seen in rooms}
    path = _session_db_path_for_profile(profile)
    try:
        if not rooms or path.stat().st_size == 0:
            return {"rooms": result}
    except FileNotFoundError:
        return {"rooms": result}
    db = _open_session_db_at_path(path, read_only=True)
    try:
        rows = db._conn.execute(_activity_sql(), {
            "rooms": json.dumps(rooms), "links": json.dumps(links), "prefix": POLICY_PREFIX,
            "now": time.time()}).fetchall()
    finally:
        db.close()
    for room_id, running, unread in rows:
        result[room_id] = {"running": int(running or 0), "unread": int(unread or 0)}
    return {"rooms": result}


@router.get("/api/workspace/activity")
async def get_workspace_activity(profile: Optional[str] = None):
    """``{rooms: {room_id: {running, unread}}}`` for every live room, cached for a few seconds."""
    def _run():
        key = _home_key()
        hit = _ACTIVITY_CACHE.get(key)
        if hit is not None and time.monotonic() - hit[0] < _ACTIVITY_TTL:
            return hit[1]
        answer = _activity(profile)
        _ACTIVITY_CACHE[key] = (time.monotonic(), answer)
        return answer

    return await _call(profile, "GET /api/workspace/activity", _run)


@router.get("/api/workspace/check")
async def check_workspace(profile: Optional[str] = None):
    """Rooms whose directory is gone and directories no room uses (read-only)."""
    return await _call(profile, "GET /api/workspace/check", lambda: _wm().check())


def _settings() -> dict:
    from phi_cli.workspace_root import configured_root, workspace_root
    wm = _wm()
    return {"root": str(workspace_root()), "configured_root": configured_root(),
            "max_space_depth": wm.max_space_depth(), "default_fence": wm.default_fence()}


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _save_settings(body: WorkspaceSettingsBody) -> dict:
    from phi_cli.config import format_managed_message, is_managed
    from phi_cli.workspace_root import root_for, workspace_root
    wm = _wm()

    depth = body.max_space_depth
    if depth is not None and (isinstance(depth, bool) or not isinstance(depth, int)
                              or not MIN_SPACE_DEPTH <= depth <= MAX_SPACE_DEPTH):
        raise _bad(f"max_space_depth must be a whole number from {MIN_SPACE_DEPTH} to {MAX_SPACE_DEPTH}.")
    fence = body.default_fence
    if fence is not None and fence not in wm.FENCE_MODES:
        raise _bad(f"default_fence must be one of: {', '.join(wm.FENCE_MODES)}.")
    if body.root is not None:
        current = os.path.normpath(workspace_root())
        if os.path.normpath(root_for(body.root)) != current:
            raise _bad("Changing the workspace root moves every room directory; "
                       "use Move workspace in Settings → Workspace.")
    if depth is None and fence is None:
        return _settings()
    if is_managed():
        raise HTTPException(status_code=409, detail=format_managed_message("save workspace settings"))
    config = load_config()
    section = config.get("workspace")
    if not isinstance(section, dict):
        section = config["workspace"] = {}
    if depth is not None:
        section["max_space_depth"] = depth
    if fence is not None:
        section["default_fence"] = fence
    save_config(config)
    return _settings()


@router.get("/api/workspace/settings")
async def get_workspace_settings(profile: Optional[str] = None):
    """Resolved and configured root, nesting limit and the fence new rooms start with."""
    return await _call(profile, "GET /api/workspace/settings", _settings)


@router.put("/api/workspace/settings")
async def put_workspace_settings(body: WorkspaceSettingsBody, profile: Optional[str] = None):
    """Store ``max_space_depth`` / ``default_fence``; ``root`` may only repeat the current root."""
    def _run():
        with config_write_scope(profile):
            return _save_settings(body)

    with http_failure("PUT /api/workspace/settings failed", 500, "Failed to save workspace settings"):
        return await asyncio.to_thread(_run)


# --- Move workspace (design §二 H) ---------------------------------------------------------------------

_MOVE_JOBS: dict[str, dict] = {}  # PHI_HOME → the last move's progress
_MOVE_JOBS_LOCK = threading.Lock()


def _move_job(profile: Optional[str], path: str, job: dict) -> None:
    from phi_cli.workspace_root import MoveError, move_root

    def progress(state: str, done: int, total: int) -> None:
        with _MOVE_JOBS_LOCK:
            job.update(state=state, done_bytes=done, total_bytes=total)

    try:
        # Home and secret scope only: the move can take minutes, ``_profile_scope`` holds a global lock.
        with _config_profile_scope(profile):
            move_root(path, progress=progress, config_lock=_CONFIG_MUTATION_LOCK)
    except Exception as exc:
        if not isinstance(exc, MoveError):
            _log.exception("Workspace move to %s failed", path)
        with _MOVE_JOBS_LOCK:
            job.update(state="failed", error=str(exc) if isinstance(exc, MoveError)
                       else "The workspace move failed; the workspace root was not changed. See the log.")
    else:
        with _MOVE_JOBS_LOCK:
            job.update(state="done", error=None)


@router.post("/api/workspace/root/plan")
async def plan_workspace_move(body: WorkspaceRootBody, profile: Optional[str] = None):
    """Check a move of every room directory to ``path``: ``{same_fs, bytes, files, from, to}``; refused is 400."""
    def _run():
        from phi_cli.workspace_root import plan_move
        return plan_move(body.path)

    return await _call(profile, "POST /api/workspace/root/plan", _run)


@router.post("/api/workspace/root/move")
async def start_workspace_move(body: WorkspaceRootBody, profile: Optional[str] = None):
    """Start moving the workspace to ``path`` in the background; poll ``GET /api/workspace/root/move``."""
    profile = destructive_profile(profile, "POST /api/workspace/root/move")

    def _run():
        from phi_cli.workspace_root import move_in_progress, plan_move
        plan = plan_move(body.path)
        key = _home_key()
        with _MOVE_JOBS_LOCK:
            running = _MOVE_JOBS.get(key)
            if (running is not None and running["state"] not in ("done", "failed")) or move_in_progress():
                raise HTTPException(status_code=409, detail="A workspace move is already running.")
            job = _MOVE_JOBS[key] = {"state": "switching" if plan["same_fs"] else "copying",
                                     "done_bytes": 0, "total_bytes": plan["bytes"], "error": None}
            started = dict(job)
        # The request's context, so the job resolves the same home even under a task-local override.
        threading.Thread(target=contextvars.copy_context().run, args=(_move_job, profile, body.path, job),
                         name="workspace-move", daemon=True).start()
        return {**plan, "move": started}

    return await _call(profile, "POST /api/workspace/root/move", _run)


@router.get("/api/workspace/root/move")
async def get_workspace_move(profile: Optional[str] = None):
    """``{state: idle|copying|verifying|switching|done|failed, done_bytes, total_bytes, error}``."""
    def _run():
        with _MOVE_JOBS_LOCK:
            job = _MOVE_JOBS.get(_home_key())
            return dict(job) if job is not None else {
                "state": "idle", "done_bytes": 0, "total_bytes": 0, "error": None}

    return await _call(profile, "GET /api/workspace/root/move", _run)

"""Matrix space mirror (design §七): the spaces and rooms the agent account joined, their hierarchy
(``m.space.child`` / ``m.space.parent``) and their names are mirrored into the workspace map; a move,
rename or create-space made in the dashboard is written to Matrix first and reaches the map only once the
homeserver accepted it.

Only shared room state the agent can see is read or written, never per-user account data (tags,
``m.direct``, client settings): Phi is not the human user. DMs stay out (they bind to the agent room).
The map never loses a row: a room the agent left is archived, and a directory is never moved or renamed.
A room new to the map gets a system id and the folder ``<root>/<id>``; its Matrix id lives only in
``channel_links`` (rows from before system ids keep the Matrix id as their row id). A nameless Matrix
room starts as "New chat" and is named by its first message like a web chat.
One lock serialises imports, live events and write-backs; every live change bumps ``_gen`` so an import
that read Matrix before it lands is dropped and read again instead of reverting it.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import quote

from phi_cli import workspace_map as wm

logger = logging.getLogger(__name__)

CHANNEL = "matrix"
V3 = "/_matrix/client/v3"
RESYNC_SECONDS = 3600
DEFAULT_POWER = 50
MEGOLM = "m.megolm.v1.aes-sha2"
CHILD, PARENT, NAME, MEMBER = "m.space.child", "m.space.parent", "m.room.name", "m.room.member"
OFF = {"error": "Matrix space mirror is off or not connected.", "status": 503}

_MIRRORS: dict[Any, "SpaceMirror"] = {}  # adapter -> its live mirror; stop() removes the entry


class MatrixWriteError(Exception):
    """Matrix refused or could not be reached; ``status`` is the HTTP status the dashboard gets."""

    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


def _http_method(name: str) -> Any:
    try:
        from mautrix.api import Method
    except ImportError:  # no matrix extra: only a test homeserver can be talking to us
        return name
    return Method[name]


def _event_type(name: str) -> Any:
    try:
        from mautrix.types import EventType
    except ImportError:
        return name
    return EventType.find(name, EventType.Class.STATE)


def _content(event: Any) -> dict:
    content = getattr(event, "content", None)
    if hasattr(content, "serialize"):
        content = content.serialize()
    return content if isinstance(content, dict) else {}


def _has_via(content: Any) -> bool:
    """A space edge is live while its state event lists servers to join through (spec: ``via``)."""
    via = content.get("via") if isinstance(content, dict) else None
    return isinstance(via, list) and bool(via)


def _q(part: str) -> str:
    return quote(part, safe="")


def _state_path(room: str, event_type: str, key: str = "") -> str:
    return f"/rooms/{_q(room)}/state/{_q(event_type)}/{_q(key)}"


def _fail(message: str, status: int) -> dict:
    return {"error": message, "status": status}


def _is_network_error(exc: BaseException) -> bool:
    return isinstance(exc, OSError) or any(
        k.__name__ in ("MatrixConnectionError", "ClientError") for k in type(exc).__mro__)


def _parse_state(events: Any, me: str) -> dict:
    """What the mirror needs from a room's full state: kind, name, live space edges, own DM flag."""
    info: dict = {"space": False, "name": "", "alias": "", "children": [], "parents": [], "direct": False}
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        kind, key = event.get("type"), str(event.get("state_key") or "")
        content = event.get("content") if isinstance(event.get("content"), dict) else {}
        if kind == "m.room.create":
            info["space"] = content.get("type") == "m.space"
        elif kind == NAME:
            info["name"] = str(content.get("name") or "").strip()
        elif kind == "m.room.canonical_alias":
            info["alias"] = str(content.get("alias") or "").strip()
        elif kind in (CHILD, PARENT) and key and _has_via(content):
            info["children" if kind == CHILD else "parents"].append(key)
        elif kind == MEMBER and key == me:
            info["direct"] = bool(content.get("is_direct"))
    return info


def _known_row(room_id: str) -> Optional[str]:
    try:
        return wm.get_room(room_id)["room_id"]
    except wm.RoomNotFound:
        return None


class SpaceMirror:
    """The mirror of one connected Matrix account (one profile's adapter) into that profile's map."""

    def __init__(self, client: Any, adapter: Any, home: Any):
        self.client, self.adapter, self.home = client, adapter, Path(home)
        self.user_id = str(getattr(adapter, "_user_id", "") or "")
        self.server = self.user_id.split(":", 1)[1] if ":" in self.user_id else ""
        self.lock = asyncio.Lock()
        self.imported = asyncio.Event()
        self._wake = asyncio.Event()
        self._gen = 0
        self.task: Optional[asyncio.Task] = None
        self._handlers: list[tuple[Any, Callable]] = []

    @property
    def api(self) -> Any:
        return self.client.api

    # --- plumbing ------------------------------------------------------------------------------------

    def _in_home(self, fn: Callable, *args: Any) -> Any:
        from phi_constants import reset_phi_home_override, set_phi_home_override
        token = set_phi_home_override(str(self.home))
        try:
            return fn(*args)
        finally:
            reset_phi_home_override(token)

    async def _map(self, fn: Callable, *args: Any) -> Any:
        """Run a blocking map call in this mirror's profile home, off the loop."""
        return await asyncio.to_thread(self._in_home, fn, *args)

    async def _enabled(self) -> bool:
        return await self._map(wm.matrix_mirror_enabled)

    async def _call(self, method: str, path: str, content: Any = None) -> Any:
        return await self.client.api.request(_http_method(method), V3 + path, content)

    @staticmethod
    def _matrix_ids() -> dict[str, str]:
        return {rid: mx for mx, rid in wm.channel_links(CHANNEL).items()}

    # --- import --------------------------------------------------------------------------------------

    async def import_all(self) -> None:
        """Read every joined non-DM room's state and make the map match it (never writes to Matrix)."""
        if not await self._enabled():
            return
        gen = self._gen
        joined = await self._joined_rooms()
        if joined is None:
            return
        dms = getattr(self.adapter, "_dm_rooms", None) or {}
        rooms = {}
        for mx in joined:
            info = None if dms.get(mx) else await self._room_state(mx)
            if info is not None and not info["direct"]:
                rooms[mx] = info
        async with self.lock:
            if gen != self._gen:  # a live change landed while we read: read again rather than revert it
                self._wake.set()
                return
            await self._map(self._apply, set(joined), rooms)
        self.imported.set()

    async def _joined_rooms(self) -> Optional[list[str]]:
        try:
            answer = await self._call("GET", "/joined_rooms")
        except Exception as exc:
            logger.warning("Matrix space mirror: could not list joined rooms: %s", exc)
            return None
        rooms = answer.get("joined_rooms") if isinstance(answer, dict) else None
        return [r for r in rooms or [] if isinstance(r, str)]

    async def _room_state(self, mx: str) -> Optional[dict]:
        try:
            events = await self._call("GET", f"/rooms/{_q(mx)}/state")
        except Exception as exc:
            logger.info("Matrix space mirror: skipped %s this round: %s", mx, exc)
            return None
        return _parse_state(events, self.user_id)

    def _apply(self, joined: set[str], rooms: dict[str, dict]) -> None:
        links = wm.channel_links(CHANNEL)
        ids = {}
        for mx, info in rooms.items():
            row = self._ensure_row(links, mx, info)
            if row is not None:
                ids[mx] = row
        spaces = {ids[mx] for mx, info in rooms.items() if mx in ids and info["space"]}
        for child, wanted in self._wanted_parents(ids, rooms).items():
            self._sync_parents(child, wanted, spaces)
        for mx, row in links.items():
            if mx not in joined:
                self._archive_left(row)

    @staticmethod
    def _ensure_row(links: dict[str, str], mx: str, info: dict) -> Optional[str]:
        """The map row of ``mx``: its link wins (directory kept), then a legacy row whose id is ``mx``,
        else a new row with a system id (a room's folder is ``<root>/<id>``), linked to ``mx``."""
        name = info["name"]
        try:
            row_id = links.get(mx) or _known_row(mx)
            if row_id is None:
                label = name or info["alias"]
                row_id = (wm.import_space(label or "Matrix space") if info["space"]
                          else wm.create_room(label or None, origin=CHANNEL))["room_id"]
            if mx not in links:
                wm.link_channel(row_id, CHANNEL, mx)
            row = wm.get_room(row_id)
            if row["archived"]:
                wm.unarchive(row_id)
            if name and name != row["name"]:
                wm.rename(row_id, name)
            return row_id
        except (wm.WorkspaceMapError, wm.RoomNotFound) as exc:
            logger.warning("Matrix space mirror: could not import %s: %s", mx, exc)
            return None

    @staticmethod
    def _wanted_parents(ids: dict[str, str], rooms: dict[str, dict]) -> dict[str, list[str]]:
        """Row → parent rows. P holds C when space P lists C or C claims space P, both read this round."""
        wanted: dict[str, list[str]] = {row: [] for row in ids.values()}
        for mx, info in rooms.items():
            if mx not in ids:
                continue
            claims = [p for p in info["parents"] if p in ids and rooms[p]["space"]]
            listed_by = [p for p, other in rooms.items() if p in ids and other["space"] and mx in other["children"]]
            for parent in dict.fromkeys(listed_by + claims):
                if ids[parent] != ids[mx] and ids[parent] not in wanted[ids[mx]]:
                    wanted[ids[mx]].append(ids[parent])
        return wanted

    @staticmethod
    def _sync_parents(child: str, wanted: list[str], spaces: set[str]) -> None:
        """Add the wanted edges; drop edges to spaces read this round that no longer hold the child.
        Edges to local spaces (not on Matrix) are the user's own and stay."""
        current = wm.get_room(child)["parents"]
        for parent in current:
            if parent in spaces and parent not in wanted:
                wm.remove_parent(child, parent)
        for parent in wanted:
            if parent in current:
                continue
            try:
                wm.import_parent(child, parent)
            except wm.WorkspaceMapError as exc:
                logger.info("Matrix space mirror: kept %s out of %s: %s", child, parent, exc)

    @staticmethod
    def _archive_left(row_id: str) -> None:
        try:
            row = wm.get_room(row_id)
        except wm.RoomNotFound:
            return
        if row["origin"] == CHANNEL and not row["archived"]:
            wm.archive(row_id)

    # --- live updates --------------------------------------------------------------------------------
    # Each handler takes the lock first: events are dispatched as tasks, and the lock's FIFO keeps them
    # in the order the sync delivered them.

    async def on_child(self, event: Any) -> None:
        room, key = str(event.room_id), str(event.state_key or "")
        await self._on_edge(room, key, _content(event), (key, PARENT, room))

    async def on_parent(self, event: Any) -> None:
        room, key = str(event.room_id), str(event.state_key or "")
        await self._on_edge(key, room, _content(event), (key, CHILD, room))

    async def _on_edge(self, parent_mx: str, child_mx: str, content: dict, other: tuple[str, str, str]) -> None:
        if not parent_mx or not child_mx:
            return
        async with self.lock:
            if not await self._enabled():
                return
            links = await self._map(wm.channel_links, CHANNEL)
            parent, child = links.get(parent_mx), links.get(child_mx)
            if parent is None or child is None:
                return  # a room the agent has not joined (or a DM): the next import decides
            linked = _has_via(content) or await self._other_side(*other)
            if linked is None:
                return
            self._gen += 1
            try:
                await self._map(wm.import_parent if linked else wm.remove_parent, child, parent)
            except (wm.WorkspaceMapError, wm.RoomNotFound) as exc:
                logger.info("Matrix space mirror: edge %s → %s not mirrored: %s", parent_mx, child_mx, exc)

    async def _other_side(self, room_mx: str, event_type: str, key: str) -> Optional[bool]:
        """Whether the other end still states the edge; None when Matrix could not tell."""
        try:
            return _has_via(await self._call("GET", _state_path(room_mx, event_type, key)))
        except Exception as exc:
            if getattr(exc, "http_status", None) in (403, 404):
                return False
            logger.info("Matrix space mirror: could not read %s %s: %s", room_mx, event_type, exc)
            return None

    async def on_name(self, event: Any) -> None:
        """A name set in Matrix becomes the display name. Our own write echoing back while the room is
        still auto-named is skipped: the map already has that name, or a newer model title."""
        name = str(_content(event).get("name") or "").strip()
        if not name:
            return
        async with self.lock:
            if not await self._enabled():
                return
            row = await self._map(wm.room_for_channel, CHANNEL, str(event.room_id))
            if row is None or row["name"] == name:
                return
            if str(getattr(event, "sender", "") or "") == self.user_id and row.get("name_source") == "auto":
                return
            self._gen += 1
            await self._map(wm.rename, row["room_id"], name)

    async def on_member(self, event: Any) -> None:
        if str(event.state_key or "") != self.user_id:
            return
        membership = _content(event).get("membership")
        async with self.lock:
            if not await self._enabled():
                return
            row = await self._map(wm.room_for_channel, CHANNEL, str(event.room_id))
            if membership == "join":
                if row is None or row["archived"]:
                    self._gen += 1
                    self._wake.set()  # read its state and place it on the next import
            elif membership in ("leave", "ban") and row is not None:
                self._gen += 1
                await self._map(self._archive_left, row["room_id"])

    # --- write-back ----------------------------------------------------------------------------------

    async def _guarded(self, work: Callable) -> dict:
        try:
            return await work()
        except MatrixWriteError as exc:
            return _fail(str(exc), exc.status)
        except wm.RoomNotFound as exc:
            return _fail(str(exc), 404)
        except wm.WorkspaceMapError as exc:
            return _fail(str(exc), 400)

    async def _write(self, done: list, room_mx: str, event_type: str, key: str, content: dict) -> None:
        """PUT one state event, remembering what it replaced so a later failure can put it back."""
        path = _state_path(room_mx, event_type, key)
        previous = await self._previous(path)
        try:
            await self._call("PUT", path, content)
        except Exception as exc:
            error = await self._refusal(exc, room_mx, event_type)
            if error is None:
                raise
            raise error from exc
        done.append((path, previous))

    async def _previous(self, path: str) -> dict:
        try:
            answer = await self._call("GET", path)
        except Exception as exc:
            if _is_network_error(exc):
                raise MatrixWriteError(f"Matrix unreachable: {exc}", 502) from exc
            return {}  # not set yet (404): "taking it back" is the empty content
        return answer if isinstance(answer, dict) else {}

    async def _undo(self, done: list) -> None:
        for path, previous in reversed(done):
            try:
                await self._call("PUT", path, previous)
            except Exception as exc:
                logger.warning("Matrix space mirror: could not take back %s: %s", path, exc)

    async def _refusal(self, exc: Exception, room_mx: Optional[str] = None,
                       event_type: Optional[str] = None) -> Optional[MatrixWriteError]:
        if _is_network_error(exc):
            return MatrixWriteError(f"Matrix unreachable: {exc}", 502)
        status = getattr(exc, "http_status", None)
        if not isinstance(status, int):
            return None
        if status == 403 and room_mx and event_type:
            level = await self._needed_power(room_mx, event_type)
            row = await self._map(wm.room_for_channel, CHANNEL, room_mx)
            where = row["name"] if row else room_mx
            return MatrixWriteError(f"Matrix refused: needs power level {level} in {where}", 409)
        return MatrixWriteError(f"Matrix refused: {getattr(exc, 'message', None) or exc}", 409)

    async def _needed_power(self, room_mx: str, event_type: str) -> int:
        try:
            levels = await self._call("GET", _state_path(room_mx, "m.room.power_levels"))
        except Exception:
            return DEFAULT_POWER
        levels = levels if isinstance(levels, dict) else {}
        events = levels.get("events") if isinstance(levels.get("events"), dict) else {}
        value = events.get(event_type, levels.get("state_default", DEFAULT_POWER))
        return value if isinstance(value, int) else DEFAULT_POWER

    async def move(self, room_id: str, from_space: Optional[str], to_space: Optional[str]) -> dict:
        """Move in Matrix (child in the new space, out of the old, then the room's parent), then the map."""
        return await self._guarded(lambda: self._move(room_id, from_space, to_space))

    async def _move(self, room_id: str, from_space: Optional[str], to_space: Optional[str]) -> dict:
        async with self.lock:
            room = await self._map(wm.check_move, room_id, from_space, to_space)
            if from_space == to_space:
                return {"room": room}
            mx = await self._map(self._matrix_ids)
            done: list = []
            try:
                await self._write_move(done, mx.get(room_id), mx.get(from_space), mx.get(to_space))
                room = await self._map(wm.move, room_id, from_space, to_space)
            except Exception:
                await self._undo(done)
                raise
            self._gen += 1
            return {"room": room}

    async def _write_move(self, done: list, room: Optional[str], src: Optional[str], dst: Optional[str]) -> None:
        if room is None:
            return  # a local room: the map alone holds it
        via = {"via": [self.server]}
        if dst is not None:
            await self._write(done, dst, CHILD, room, via)
        if src is not None:
            await self._write(done, src, CHILD, room, {})
        if dst is not None:
            await self._write(done, room, PARENT, dst, {**via, "canonical": True})
        if src is not None:
            await self._write(done, room, PARENT, src, {})

    async def rename(self, room_id: str, name: str, auto: bool = False, expect: Optional[str] = None) -> dict:
        """Set ``m.room.name`` in Matrix, then the map's display name (the directory stays).

        ``auto`` is a name from the chat itself (first message, then model title): it is written only
        while :func:`phi_cli.workspace_map.auto_nameable` still allows it (``expect`` is the map's current
        auto name), so it never overwrites a person's rename or a newer title."""
        return await self._guarded(lambda: self._rename(room_id, name, auto, expect))

    async def _rename(self, room_id: str, name: str, auto: bool = False, expect: Optional[str] = None) -> dict:
        name = str(name or "").strip()
        if not name:
            raise wm.WorkspaceMapError("A name is required.")
        async with self.lock:
            room = await self._map(wm.get_room, room_id)
            if auto and not wm.auto_nameable(room, expect):
                return {"room": room}
            mx = (await self._map(self._matrix_ids)).get(room_id)
            done: list = []
            try:
                if mx is not None:
                    await self._write(done, mx, NAME, "", {"name": name})
                if auto:
                    room = (await self._map(lambda: wm.auto_name(room_id, name, expect=expect))
                            or await self._map(wm.get_room, room_id))
                else:
                    room = await self._map(wm.rename, room_id, name)
            except Exception:
                await self._undo(done)
                raise
            self._gen += 1
            return {"room": room}

    async def create_space(self, name: str, parent: Optional[str]) -> dict:
        """Create an encrypted space in Matrix (top level, or inside ``parent``'s space linked both ways),
        then map it. A parent space that is not in Matrix keeps the new space in the map only."""
        return await self._guarded(lambda: self._create_space(name, parent))

    async def _create_space(self, name: str, parent: Optional[str]) -> dict:
        name = str(name or "").strip()
        if not name:
            raise wm.WorkspaceMapError("A name is required.")
        async with self.lock:
            await self._map(wm.check_space_nesting, parent)
            parent_mx = (await self._map(self._matrix_ids)).get(parent) if parent else None
            if parent is None:
                new = await self._create_matrix_space(name, None)
                try:
                    space = await self._map(self._record_space, new, name, None)
                except Exception:
                    await self._leave(new)
                    raise
                self._gen += 1
                return {"space": space}
            if parent_mx is None:
                return {"space": await self._map(wm.create_space, name, parent)}
            new = await self._create_matrix_space(name, parent_mx)
            done: list = []
            via = {"via": [self.server]}
            try:
                await self._write(done, parent_mx, CHILD, new, via)
                await self._write(done, new, PARENT, parent_mx, {**via, "canonical": True})
                space = await self._map(self._record_space, new, name, parent)
            except Exception:
                await self._undo(done)
                await self._leave(new)
                raise
            self._gen += 1
            return {"space": space}

    async def _create_matrix_space(self, name: str, parent_mx: Optional[str]) -> str:
        state = [
            {"type": "m.room.encryption", "state_key": "", "content": {"algorithm": MEGOLM}},
            {"type": "m.room.history_visibility", "state_key": "", "content": {"history_visibility": "invited"}},
        ]
        if parent_mx is not None:
            # Members of the parent space can see and join it, as a sub-space made in a Matrix client.
            state.append({"type": "m.room.join_rules", "state_key": "",
                          "content": {"join_rule": "restricted",
                                      "allow": [{"type": "m.room_membership", "room_id": parent_mx}]}})
        body = {"name": name, "preset": "private_chat", "creation_content": {"type": "m.space"}, "initial_state": state}
        try:
            answer = await self._call("POST", "/createRoom", body)
        except Exception as exc:
            error = await self._refusal(exc)
            if error is None:
                raise
            raise error from exc
        new = answer.get("room_id") if isinstance(answer, dict) else None
        if not isinstance(new, str) or not new:
            raise MatrixWriteError("Matrix refused: the homeserver returned no space id.", 502)
        return new

    async def _leave(self, room_mx: str) -> None:
        try:
            await self._call("POST", f"/rooms/{_q(room_mx)}/leave", {})
        except Exception as exc:
            logger.warning("Matrix space mirror: could not leave the unused space %s: %s", room_mx, exc)

    @staticmethod
    def _record_space(room_mx: str, name: str, parent: Optional[str]) -> dict:
        row = wm.import_space(name, parent_space=parent)
        return wm.link_channel(row["room_id"], CHANNEL, room_mx)

    # --- life cycle ----------------------------------------------------------------------------------

    def start(self) -> None:
        for name, handler in ((CHILD, self.on_child), (PARENT, self.on_parent),
                              (NAME, self.on_name), (MEMBER, self.on_member)):
            event_type = _event_type(name)
            self.client.add_event_handler(event_type, handler)
            self._handlers.append((event_type, handler))
        _MIRRORS[self.adapter] = self
        self.task = asyncio.get_running_loop().create_task(self.run())

    def connected(self) -> bool:
        return getattr(self.adapter, "_client", self.client) is self.client

    async def run(self) -> None:
        """Import now, then again every RESYNC_SECONDS or when a join asks for it, while connected."""
        while True:
            self._wake.clear()
            try:
                await self.import_all()
            except Exception:
                logger.exception("Matrix space mirror: import failed")
            if not self.connected():
                self.stop()  # disconnected or reconnected: the new client has its own mirror
                return
            try:
                await asyncio.wait_for(self._wake.wait(), RESYNC_SECONDS)
            except TimeoutError:
                pass

    def stop(self) -> None:
        for event_type, handler in self._handlers:
            self.client.remove_event_handler(event_type, handler)
        self._handlers.clear()
        if _MIRRORS.get(self.adapter) is self:
            del _MIRRORS[self.adapter]
        task, self.task = self.task, None
        if task is not None and task is not _current_task():
            task.cancel()


def _current_task() -> Optional[asyncio.Task]:
    try:
        return asyncio.current_task()
    except RuntimeError:  # called off the loop (plugin unload on a stopped loop)
        return None


def mirror_for(adapter: Any) -> Optional[SpaceMirror]:
    return _MIRRORS.get(adapter)


def wire(client: Any, adapter: Any) -> None:
    """Handler factory (``ctx.register_platform_handler("matrix", ...)``): start this account's mirror.
    Runs on the gateway loop inside the profile scope; a new client (reconnect) replaces the mirror."""
    from phi_constants import get_phi_home
    old = _MIRRORS.get(adapter)
    if old is not None and old.client is client:
        return
    home = old.home if old is not None else Path(get_phi_home())
    if old is not None:
        old.stop()
    mirror = SpaceMirror(client, adapter, home)
    if mirror._in_home(wm.matrix_mirror_enabled):
        mirror.start()


def _live_mirror(adapter: Any) -> Optional[SpaceMirror]:
    mirror = _MIRRORS.get(adapter)
    return mirror if mirror is not None and mirror.connected() else None


async def action_move(adapter: Any, args: dict) -> dict:
    mirror = _live_mirror(adapter)
    if mirror is None:
        return dict(OFF)
    return await mirror.move(args.get("room_id"), args.get("from_space"), args.get("to_space"))


async def action_rename(adapter: Any, args: dict) -> dict:
    mirror = _live_mirror(adapter)
    if mirror is None:
        return dict(OFF)
    return await mirror.rename(args.get("room_id"), args.get("name"), auto=bool(args.get("auto")),
                               expect=args.get("expect"))


async def action_create_space(adapter: Any, args: dict) -> dict:
    mirror = _live_mirror(adapter)
    if mirror is None:
        return dict(OFF)
    return await mirror.create_space(args.get("name"), args.get("parent_space"))


def _on_loop(loop: Optional[asyncio.AbstractEventLoop], fn: Callable[[], None]) -> None:
    try:
        here = asyncio.get_running_loop()
    except RuntimeError:
        here = None
    if loop is None or here is loop or loop.is_closed() or not loop.is_running():
        fn()
    else:
        loop.call_soon_threadsafe(fn)


def _unload() -> None:
    # Runs on the thread that discovers plugins; the handlers live on the gateway loop.
    for mirror in list(_MIRRORS.values()):
        _on_loop(mirror.task.get_loop() if mirror.task is not None else None, mirror.stop)


def register(ctx: Any) -> None:
    from gateway.adapter_actions import register_adapter_action
    ctx.register_platform_handler(CHANNEL, wire)
    ctx.on_unload(_unload)
    register_adapter_action(CHANNEL, "space_mirror.move", action_move)
    register_adapter_action(CHANNEL, "space_mirror.rename", action_rename)
    register_adapter_action(CHANNEL, "space_mirror.create_space", action_create_space)

"""Session → room binding (design §B): a turn works inside one room directory of the workspace map.

Messaging turns resolve their room from the channel: a channel linked in the map wins; an unlinked
DM works in the agent's own directory (``<root>/agent``) and is never registered; an unlinked group
gets a room created and linked on its first message. Threads work in their parent channel's room.
Web chats name their room explicitly (:func:`bind_room_id`). An archived linked room keeps its link,
but its turns work in the agent directory. While the workspace root is moving
(``workspace_move.lock``), new turns run unbound.

The bound room lives in a ContextVar next to the session cwd, so the prompt builder can say where
the turn works (:func:`room_context_block`) and which ``AGENTS.md`` is room rules.

A room still called "New chat" is named by its chat's first message, and that name is replaced by
the model's session title (:func:`name_room_for_turn`); a Matrix-linked room's name goes to Matrix too.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

logger = logging.getLogger(__name__)

# Room rules (``<room>/AGENTS.md``) are capped well below the general context-file budget.
ROOM_RULES_MAX_CHARS = 8000
ROOM_MEMORY_MAX_CHARS = 4000
ROOM_RULES_REMEDY = (f"Room rules are limited to {ROOM_RULES_MAX_CHARS} characters; "
                     "shorten the room's AGENTS.md so nothing is cut.")

_DM_TYPES = frozenset({"dm", "direct", "private"})
_FENCE_TEXT = {
    "approve": "writes outside need approval",
    "strict": "writes outside are blocked",
    "off": "writes outside are not fenced",
}
_MAX_SPACE_WALK = 16
# One gateway process creates a group's room once even when its first messages arrive together.
_CREATE_LOCK = threading.Lock()


@dataclass(frozen=True)
class RoomBinding:
    """The room a turn works in. ``source``: link | agent | created | web."""

    room_id: str
    name: str
    dir: Path
    fence_mode: str
    extra_write_paths: tuple = ()
    source: str = "link"
    space_path: str = "Home"


_CURRENT_ROOM: ContextVar[Optional[RoomBinding]] = ContextVar("phi_current_room", default=None)


def current_room() -> Optional[RoomBinding]:
    """The room bound to this turn, or ``None``."""
    return _CURRENT_ROOM.get()


def set_current_room(binding: Optional[RoomBinding]) -> Token:
    """Bind the room and its write fence for this context (``None`` unbinds both)."""
    _set_fence(binding)
    return _CURRENT_ROOM.set(binding)


def reset_current_room(token: Token) -> None:
    _CURRENT_ROOM.reset(token)


# Paths the user approved outside a room, per (session key, room id): kept for the session, not the turn.
_APPROVED: dict[tuple[str, str], list[str]] = {}


def _set_fence(binding: Optional[RoomBinding]) -> Token:
    """The room's write fence (design §六): the room dir, its extra paths and the temp dir."""
    import tempfile
    from agent.file_safety import set_session_write_roots

    if binding is None:
        return set_session_write_roots([], mode="off")
    from gateway.session_context import get_session_env

    key = get_session_env("PHI_SESSION_KEY", "") or get_session_env("PHI_SESSION_ID", "")
    approved = _APPROVED.setdefault((key, binding.room_id), []) if key else []
    roots = [str(binding.dir), *binding.extra_write_paths, tempfile.gettempdir()]
    return set_session_write_roots(roots, mode=binding.fence_mode, approved=approved)


def bind_turn_room(task_id: str) -> None:
    """A messaging turn's terminal and file tools start in the bound room (local backend only).

    Registered like ``gateway.session_policy.bind_turn_workspace``: only when the room changed, so
    an agent's ``cd`` inside the session survives later turns; teardown drops it (``workspace_key``)."""
    binding = current_room()
    if binding is None or not task_id:
        return
    from tools.terminal_scope import terminal_env

    if (terminal_env("TERMINAL_ENV", "local").strip().lower() or "local") != "local":
        return
    from tools.terminal_tool import register_task_env_overrides, resolve_task_overrides, workspace_key_for

    room_dir = str(binding.dir)
    current = resolve_task_overrides(task_id)
    if current.get("cwd") == room_dir and current.get("cwd_source") == "room":
        return
    register_task_env_overrides(task_id, {**current, "cwd": room_dir, "cwd_source": "room",
                                          "workspace_key": workspace_key_for(room_dir)})


def _space_path(room: dict) -> str:
    """``Projects/Hardware`` for a room filed under spaces (first parent at each level), else ``Home``."""
    from phi_cli import workspace_map as wm

    names: list[str] = []
    seen: set[str] = set()
    parents = room.get("parents") or []
    while parents and parents[0] not in seen and len(names) < _MAX_SPACE_WALK:
        seen.add(parents[0])
        space = wm.get_room(parents[0])
        names.append(space["name"])
        parents = space.get("parents") or []
    return "/".join(reversed(names)) or "Home"


def _binding(room: dict, source: str) -> RoomBinding:
    from phi_cli import workspace_map as wm

    path = Path(room["path"]) if room.get("path") else None
    if path is None or not path.is_dir():
        raise wm.WorkspaceMapError(f"{room['room_id']} has no directory to work in.")
    return RoomBinding(
        room_id=room["room_id"], name=room["name"], dir=path, fence_mode=room["fence_mode"],
        extra_write_paths=tuple(room.get("extra_write_paths") or ()), source=source,
        space_path=_space_path(room),
    )


def _linked_binding(room: dict) -> RoomBinding:
    if room.get("archived"):
        from phi_cli import workspace_map as wm

        logger.warning("Workspace room %s is archived; the turn works in the agent directory.", room["room_id"])
        return _binding(wm.ensure_agent_room(), "agent")
    return _binding(room, "link")


def bind_for_channel(platform: str, chat_id: str, chat_type: str, chat_name: str, *,
                     thread_id: Optional[str] = None, parent_chat_id: Optional[str] = None) -> RoomBinding:
    """The room for a messaging chat: linked room > unlinked DM → agent dir > unlinked group → new room.

    A thread works in its parent's room: Telegram/Slack/Matrix threads keep the parent ``chat_id``
    (``thread_id`` aside); Discord threads arrive with their own ``chat_id`` and a ``parent_chat_id``.
    """
    from phi_cli import workspace_map as wm

    key = str(parent_chat_id or chat_id)
    linked = wm.room_for_channel(platform, key)
    if linked is not None:
        return _linked_binding(linked)
    if str(chat_type or "").lower() in _DM_TYPES:
        return _binding(wm.ensure_agent_room(), "agent")
    with _CREATE_LOCK:
        linked = wm.room_for_channel(platform, key)
        if linked is not None:
            return _linked_binding(linked)
        room = wm.create_room(chat_name or None, origin=platform)
        return _binding(wm.link_channel(room["room_id"], platform, key), "created")


def bind_room_id(room_id: str) -> RoomBinding:
    """The binding for a room picked by id (web chats). ``RoomNotFound`` / ``WorkspaceMapError`` for a space."""
    from phi_cli import workspace_map as wm

    room = wm.get_room(room_id)
    if room["type"] == "space":
        raise wm.WorkspaceMapError(f"{room_id} is a space; pick a room.")
    return _binding(room, "web")


def room_context_block(binding: RoomBinding) -> str:
    """One prompt line: where the turn works and what the fence does outside it."""
    fence = _FENCE_TEXT.get(binding.fence_mode, _FENCE_TEXT["approve"])
    return f"Workspace: bound to {binding.space_path}/{binding.name} -> {binding.dir} ({fence})."


def room_memory_path(room_dir: Path | str) -> Path:
    """``<room>/.phi/memory.md``: the room's short memory, rewritten from its ledger at session end."""
    return Path(room_dir) / ".phi" / "memory.md"


def room_memory_enabled() -> bool:
    from phi_cli.workspace_root import workspace_config
    from utils import is_truthy_value

    return is_truthy_value(workspace_config().get("room_memory", True), default=True)


def room_memory_block(binding: RoomBinding) -> str:
    """The room memory for the system prompt (read once per session, so the prompt cache holds)."""
    try:
        if not room_memory_enabled():
            return ""
        text = room_memory_path(binding.dir).read_text(encoding="utf-8")
        if text.startswith("<!-- ledger:"):
            text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.strip()
    except (OSError, UnicodeDecodeError):
        return ""
    except Exception:
        logger.debug("Room memory of %s unreadable", binding.room_id, exc_info=True)
        return ""
    if not text:
        return ""
    return (f"Room memory ({binding.name}; only this room sees it; each line cites its ledger entry; "
            "an index, not the truth: check the current code and command output, and `ledger search` "
            f"the cited entry for detail):\n{text[:ROOM_MEMORY_MAX_CHARS]}")


def active_room_lines() -> list[str]:
    binding = current_room()
    if binding is None:
        return []
    memory = room_memory_block(binding)
    return [room_context_block(binding), memory] if memory else [room_context_block(binding)]


def bind_sessions_enabled() -> bool:
    from phi_cli.workspace_root import workspace_config
    from utils import is_truthy_value

    return is_truthy_value(workspace_config().get("bind_sessions", True), default=True)


def _workspace_moving() -> bool:
    from phi_cli.workspace_root import move_in_progress

    return move_in_progress()


def session_room_vars(source: Any) -> dict:
    """``{"cwd", "room"}`` for a gateway turn's ``set_session_vars``, or ``{}`` (flag off, not a
    messaging surface, the workspace moving, or the map failed — the turn then runs unbound)."""
    from gateway.session_context import NON_MESSAGING_SESSION_SURFACES

    platform = getattr(getattr(source, "platform", None), "value", "") or ""
    if platform in NON_MESSAGING_SESSION_SURFACES:
        return {}
    try:
        if not bind_sessions_enabled():
            return {}
        if _workspace_moving():
            logger.warning("The workspace is moving; this %s turn runs unbound.", platform)
            return {}
        binding = bind_for_channel(
            platform, str(source.chat_id or ""), str(source.chat_type or ""), source.chat_name or "",
            thread_id=source.thread_id, parent_chat_id=getattr(source, "parent_chat_id", None))
    except Exception:
        logger.warning("Workspace room binding failed for a %s chat; the turn runs unbound.", platform,
                       exc_info=True)
        return {}
    return {"cwd": str(binding.dir), "room": binding}


@contextmanager
def room_scope(room_id: Optional[str]) -> Iterator[Optional[RoomBinding]]:
    """Bind ``room_id``'s room for the block (a web session's turn); unbound when absent or unusable."""
    binding = None
    if room_id:
        try:
            if _workspace_moving():
                logger.warning("The workspace is moving; room %s is not bound and the turn runs unbound.", room_id)
            else:
                binding = bind_room_id(room_id)
        except Exception:
            logger.warning("Workspace room %s could not be bound; the turn runs unbound.", room_id,
                           exc_info=True)
    from agent.file_safety import reset_session_write_roots

    fence_token = _set_fence(binding)
    token = _CURRENT_ROOM.set(binding)
    try:
        yield binding
    finally:
        _CURRENT_ROOM.reset(token)
        reset_session_write_roots(fence_token)


def _push_room_name(room_id: str, name: str) -> None:
    """Send a Matrix-linked room's automatic name to Matrix through the running gateway's mirror, off
    the turn. No gateway running, or ``matrix.space_mirror: false``: the name stays in the map only."""
    from phi_cli import workspace_map as wm

    if room_id not in wm.channel_links("matrix").values() or not wm.matrix_mirror_enabled():
        return
    from agent.memory_provider import spawn_context_thread

    spawn_context_thread(_send_room_name, name="room-name-push", args=(room_id, name)).start()


def _send_room_name(room_id: str, name: str) -> None:
    try:
        from gateway.adapter_actions import call_adapter_action

        call_adapter_action("matrix", "space_mirror.rename",
                            {"room_id": room_id, "name": name, "auto": True, "expect": name})
    except Exception:
        logger.debug("Could not send room %s's name to Matrix", room_id, exc_info=True)


def name_room_for_turn(user_text: str, title_callback: Optional[Callable[[str, str], None]] = None):
    """Name this turn's room after its message if the room is still "New chat", and return the title
    callback for ``maybe_auto_title``: it renames the room to the model's title (unless someone renamed
    it meanwhile) before passing the title on. Returns ``title_callback`` itself when nothing was named.

    The room is the bound one, else the room whose directory is the working directory (a web terminal
    chat). Never fatal, never creates the map."""
    try:
        from phi_cli import workspace_map as wm

        if not wm.map_db_path().exists():
            return title_callback
        binding = current_room()
        if binding is not None:
            room = wm.get_room(binding.room_id)
        else:
            from agent.runtime_cwd import resolve_agent_cwd

            room = wm.room_for_dir(resolve_agent_cwd())
        if room is None or room["rel_path"] in (None, "agent") or not wm.auto_nameable(room):
            return title_callback
        from agent.title_generator import derive_room_name, is_titleable_user_message

        instant = derive_room_name(user_text) if is_titleable_user_message(user_text) else None
        named = wm.auto_name(room["room_id"], instant) if instant else None
        if named is None:
            return title_callback
        room_id, instant = named["room_id"], named["name"]
        _push_room_name(room_id, instant)
    except Exception:
        logger.debug("Could not name the room from the chat's first message", exc_info=True)
        return title_callback

    def on_title(title: str, source: str) -> None:
        if source == "llm":
            try:
                renamed = wm.auto_name(room_id, title, expect=instant)
                if renamed is not None:
                    _push_room_name(room_id, renamed["name"])
            except Exception:
                logger.debug("Could not rename room %s to the session title", room_id, exc_info=True)
        if title_callback is not None:
            title_callback(title, source)

    return on_title


def is_room_rules_file(path: Path) -> bool:
    """Whether ``path`` is a room's rules file: in the bound room's dir or a room dir under the root."""
    try:
        from phi_cli.workspace_root import configured_root, root_for

        parent = Path(path).resolve().parent
        binding = current_room()
        if binding is not None and parent == binding.dir.resolve():
            return True
        return parent.parent == root_for(configured_root()).resolve()
    except Exception:
        logger.debug("Could not tell whether %s is room rules", path, exc_info=True)
        return False

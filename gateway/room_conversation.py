"""One conversation per workspace room across every chat tool linked to it (design: room conversation v2).

The workspace map keeps each room's current conversation (``room_conversations``). A human main-lane
message from any linked chat continues it: before the lane reserves its route, ``repoint_route``
switches the lane's routing entry onto that session (a lane's very first message joins it too); at each
turn boundary the conversation's live binding moves to the lane whose message runs next
(``follow_talking_lane``). Only a chat-bound conversation is joined: the session authority runs a chat's
messages on a chat lane, never on a web/TUI, API or background binding. A lane whose entry is newer
than the pointer — it ran ``/new`` or ``/resume`` after the room moved — leads instead; once its turn
is recorded the other lanes follow it. After each turn the answer is mirrored to
the room's other chat tools under a one-line quote of the question, never back to the asking chat and
never to email/SMS. Threads, ``system:`` users (cron and other automation), unlinked chats and
non-messaging surfaces are never touched. Routing and recording never raise into the turn.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)

MIRROR_EXCLUDED_PLATFORMS = frozenset({"email", "sms"})
# Local session sources that are background runs, not a person chatting in the room.
BACKGROUND_SOURCES = frozenset({"oneshot", "cron", "tool", "kanban"})
WEB_LABEL = "Web"
QUOTE_LIMIT = 80


def _platform(source) -> str:
    platform = getattr(source, "platform", None)
    return str(getattr(platform, "value", platform) or "")


def room_for_source(source) -> Optional[str]:
    """The room a human main-lane message from ``source`` belongs to, or ``None``."""
    from gateway.session_context import NON_MESSAGING_SESSION_SURFACES
    from phi_cli import workspace_map as wm
    platform = _platform(source)
    if platform in NON_MESSAGING_SESSION_SURFACES or getattr(source, "thread_id", None):
        return None
    if str(getattr(source, "user_id", None) or "").startswith("system:"):
        return None
    chat = getattr(source, "parent_chat_id", None) or getattr(source, "chat_id", None)
    if not chat or not wm.map_db_path().exists():  # no workspace: a chat message never creates the map
        return None
    room = wm.room_for_channel(platform, str(chat))
    return room["room_id"] if room is not None else None


def repoint_route(store, source, session_key) -> Optional[str]:
    """Switch the lane ``session_key`` onto its room's current conversation; the session id joined, or
    ``None`` when nothing moved (not the room's lane, already there, lane newer than the pointer, no such
    session). Never raises."""
    try:
        return _repoint(store, source, session_key)
    except Exception:
        logger.warning("Room conversation: could not repoint %s", session_key, exc_info=True)
        return None


def _repoint(store, source, session_key) -> Optional[str]:
    from phi_cli import workspace_map as wm
    room = room_for_source(source)
    target = wm.current_conversation(room) if room is not None else None
    since = wm.current_conversation_since(room) if target is not None else None
    if target is None or since is None:
        return None
    db = store._db_for_key(session_key)
    if db is None or not _is_chat_conversation(db.get_session(target)):
        return None
    entry = store.lookup_by_session_key(session_key)
    if entry is None:
        entry = store.get_or_create_session(source)  # the lane's first message continues the room
    elif entry.created_at.timestamp() >= since:
        return None  # the lane started this conversation after the room moved: it leads
    if target in (db.get_compression_lineage(entry.session_id) or [entry.session_id]):
        return None
    tip = db.get_compression_tip(target) or target
    switched = store.switch_session(session_key, tip, expected_session_id=entry.session_id,
                                    preserve_prompt_pin=False)
    if switched is None:
        return None
    logger.info("Room conversation: %s joined %s (room %s)", session_key, target, room)
    return target


def _is_chat_conversation(row) -> bool:
    """A stored conversation a chat lane can continue: started by a chat tool, not a web/TUI, API or
    background run (``None`` for a gone session)."""
    from gateway.session_context import NON_MESSAGING_SESSION_SURFACES
    source = str((row or {}).get("source") or "")
    return source not in NON_MESSAGING_SESSION_SURFACES | BACKGROUND_SOURCES | {"web"}


def follow_talking_lane(authority, ref, live, row) -> None:
    """At a turn boundary (``SessionAuthority._claim_next``, before the head's route preflight): a
    conversation several chat lanes of one room share runs each chat's message on that chat's lane, so
    the live binding moves to the head row's lane. Only a chat binding moves, only to a lane of the same
    room whose routing entry names this conversation; automation rows never move it. Never raises."""
    envelope = row["payload"].get("native_text_v1") or {}
    route = envelope.get("route")
    if not route or route == live.route or "automation" in envelope or live.superseded or live.history_mount:
        return
    try:
        from gateway.session_envelope import restore_native_source
        source = restore_native_source(row["payload"], authority.runner)
        room = room_for_source(source)
        if room is None or room != room_for_source(live.source):
            return
        entry = authority.runner.session_store.lookup_by_session_key(route)
        if entry is None or authority.logical_owner(entry.session_id) != ref.session_id:
            return
    except Exception:
        logger.warning("Room conversation: could not move %s to %s", ref.session_id, route, exc_info=True)
        return
    live.source, live.route = source, route


def record_turn(room_id, session_id) -> None:
    """Make ``session_id`` the room's current conversation. Never raises (an unknown room keeps none)."""
    from phi_cli import workspace_map as wm
    try:
        wm.set_current_conversation(room_id, session_id)
    except Exception:
        logger.warning("Room conversation: could not record %s for %s", session_id, room_id, exc_info=True)


def follow_reset(source, session_id) -> None:
    """``/new`` or ``/reset`` on a room's lane: the room moves to the fresh conversation with it.
    Never raises."""
    try:
        room = room_for_source(source)
    except Exception:
        logger.warning("Room conversation: could not resolve the room of a reset lane", exc_info=True)
        return
    if room is not None and session_id:
        record_turn(room, session_id)


def quote_line(origin_label, user_name, question) -> str:
    """``[label · user] question``: the question on one line, at most 80 characters (cut with "…")."""
    text = " ".join(str(question or "").split())
    if len(text) > QUOTE_LIMIT:
        text = text[:QUOTE_LIMIT - 1] + "…"
    who = f"{origin_label} · {user_name}" if user_name else str(origin_label)
    return f"[{who}] {text}"


def origin_label(platform: str) -> str:
    """How a quote names a chat tool: its display name without the emoji (``Telegram``, ``Matrix``)."""
    from phi_cli.platforms import PLATFORMS
    info = PLATFORMS.get(platform)
    if info is not None:
        return info.label.split(None, 1)[-1]
    return platform.replace("_", " ").title()


async def mirror_turn(runner, room_id, origin_platform, origin_chat_id, origin_label, user_name, question,
                      response) -> list[tuple[str, str, bool]]:
    """Send ``quote + response`` to every chat linked to the room except the asking chat and email/SMS;
    ``(channel, external_id, ok)`` per chat tried. Never raises."""
    from phi_cli import workspace_map as wm
    try:
        links = await asyncio.to_thread(wm.room_links, room_id)
    except Exception:
        logger.warning("Room conversation: could not read the links of %s", room_id, exc_info=True)
        return []
    text = f"{quote_line(origin_label, user_name, question)}\n\n{response}"
    targets = [(channel, ext) for channel, ext in links if channel not in MIRROR_EXCLUDED_PLATFORMS
               and (channel, ext) != (origin_platform, origin_chat_id)]
    sent = await asyncio.gather(*(_send(runner, channel, ext, text) for channel, ext in targets))
    return [(channel, ext, ok) for (channel, ext), ok in zip(targets, sent)]


async def _send(runner, channel, external_id, text) -> bool:
    from gateway.config import Platform
    try:
        adapter = (getattr(runner, "adapters", None) or {}).get(Platform(channel))
        if adapter is None:
            logger.warning("Room conversation: no running %s adapter for %s", channel, external_id)
            return False
        result = await adapter.send(external_id, text)
    except Exception:
        logger.warning("Room conversation: mirroring to %s %s failed", channel, external_id, exc_info=True)
        return False
    if not getattr(result, "success", False):
        logger.warning("Room conversation: %s refused the mirror to %s: %s", channel, external_id,
                       getattr(result, "error", None))
        return False
    return True


# --- gateway hooks (gateway/session_ingress.py::execute_admission) -----------------------------------


def web_quoted(row, response):
    """A web viewer's prompt answered in a chat: the chat sees the question above the reply."""
    from gateway.session_operator import is_viewer_input
    if not isinstance(response, str) or not response or not is_viewer_input(row):
        return response
    return f"{quote_line(WEB_LABEL, None, row['payload'].get('text'))}\n\n{response}"


def turn_origin(row, event, local_policy) -> Optional[tuple[str, str, Optional[str], str, Optional[str]]]:
    """``(room, origin platform, origin chat, label, user)`` of a turn held in a room, else ``None``."""
    from gateway.session_operator import is_viewer_input
    source = event.source
    room = room_for_source(source)
    if room is not None:
        platform, chat = _platform(source), str(getattr(source, "parent_chat_id", None) or source.chat_id)
        if is_viewer_input(row):
            return room, platform, chat, WEB_LABEL, None
        return room, platform, chat, origin_label(platform), getattr(source, "user_name", None)
    if local_policy is None or local_policy.source in BACKGROUND_SOURCES:
        return None
    from gateway.session_policy import _policy_room_id
    room = _policy_room_id(local_policy)
    return (room, "web", None, WEB_LABEL, None) if room else None


async def after_turn(authority, ref, row, event, local_policy, result, response, started) -> None:
    """A turn ran (``result`` is its TurnRunner result, ``None`` when the handler answered without
    running one): the room moves to its conversation (unless it moved elsewhere after this lane's
    conversation and this turn began), and the other chat tools get the answer off the turn path, as
    a runner background task (shutdown cancels it): a chat tool that never answers does not hold the
    lane. Internal events (API, automation, completions) never touch the room. Never raises."""
    if result is None or event.internal:
        return
    try:
        origin = await asyncio.to_thread(turn_origin, row, event, local_policy)
    except Exception:
        logger.warning("Room conversation: could not resolve the room of %s", ref.session_id, exc_info=True)
        return
    if origin is None:
        return
    room, platform, chat, label, user = origin
    await asyncio.to_thread(_record_unless_moved_on, authority, ref, event, local_policy, room, started)
    answer = response if isinstance(response, str) and response else (result or {}).get("final_response")
    if isinstance(answer, str) and answer.strip():
        runner = authority.runner
        runner._retain_background_task(asyncio.create_task(
            mirror_turn(runner, room, platform, chat, label, user, event.text, answer)))


def _record_unless_moved_on(authority, ref, event, local_policy, room, started) -> None:
    from phi_cli import workspace_map as wm
    try:
        current, since = wm.current_conversation(room), wm.current_conversation_since(room)
        if current not in (None, ref.session_id) and since is not None:
            if min(_lane_started(authority, ref, event, local_policy), started) <= since:
                return  # the room moved on while this conversation was elsewhere: do not take it back
    except Exception:
        logger.warning("Room conversation: could not read the pointer of %s", room, exc_info=True)
        return
    record_turn(room, ref.session_id)


def _lane_started(authority, ref, event, local_policy) -> float:
    """When the lane began its current conversation: its routing entry (``/new``, ``/resume`` and a
    room join renew it), or for a local web/TUI chat the session row's start."""
    if local_policy is not None and room_for_source(event.source) is None:
        row = authority.db.get_session(ref.session_id) or {}
        return float(row.get("started_at") or 0.0)
    store = authority.runner.session_store
    entry = store.lookup_by_session_key(store._generate_session_key(event.source))
    return entry.created_at.timestamp() if entry is not None else 0.0


def join_room_conversation(runner, source) -> Optional[str]:
    """Before a lane reserves its route: join the room's current conversation (not while the lane is
    mid-turn), dropping the lane's agent built for its old conversation the way ``/handoff`` does."""
    store = getattr(runner, "session_store", None)
    if store is None:
        return None
    key = store._generate_session_key(source)
    if key in (getattr(runner, "_running_agents", None) or {}):
        return None
    joined = repoint_route(store, source, key)
    if joined is not None:
        for name in ("_evict_cached_agent", "_release_running_agent_state"):
            release = getattr(runner, name, None)
            if callable(release):
                release(key)
    return joined

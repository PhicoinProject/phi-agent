"""The phone session: all calls with a caller run in ONE session of their own, apart from the chat of the DM room.

That session is a thread in the caller's DM room (Matrix has no other way to give one room two sessions): the
gateway keys a thread message as ``…:dm:<room>:<thread root>``, so the calls, their notices and the agent's spoken
replies live there, and a message the caller types into the thread joins the same session. The root is created on
the first call and kept in ``$PHI_HOME/matrix-call/phone_threads.json`` (room → root event id), so every later
call, also after a restart, comes back to it.

The session runs on a fast model: a session model override (what ``/model`` sets in that thread), persisted in the
session store so it survives a restart. The reasoning level of that model comes from ``agent.reasoning_overrides``
in config.yaml (``gpt-6-luna: none`` turns its reasoning off)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

THREAD_NAME = "📞 电话会话（所有通话都在这里）"
STORE = "phone_threads.json"


def _store_path() -> Path:
    from phi_constants import get_phi_home
    return Path(get_phi_home()) / "matrix-call" / STORE


def _load() -> dict:
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    path = _store_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


async def thread_root(adapter, room: str) -> str | None:
    """The root of the phone thread in ``room``; made (a seed message in the room) the first time."""
    roots = await asyncio.to_thread(_load)
    root = roots.get(room)
    if isinstance(root, str) and root:
        return root
    root = await adapter.create_handoff_thread(room, THREAD_NAME)
    if root:
        roots[room] = root
        await asyncio.to_thread(_save, roots)
        logger.info("matrix-call: phone thread %s made in %s", root, room)
    return root


async def pin_model(runner, source, model: str, provider: str) -> bool:
    """Put the phone session on ``model`` of ``provider``: its persisted session override, applied on its next turn.
    False when there is no session store to hold it (the session keeps the gateway's model)."""
    store = getattr(runner, "session_store", None)
    if not model or store is None or not hasattr(store, "set_model_override"):
        return False
    key = runner._session_key_for_source(source)
    await asyncio.to_thread(store.get_or_create_session, source)  # the override lives on the session's entry
    want = {"model": model, "provider": provider} if provider else {"model": model}
    if store.get_model_override(key) != want:
        await asyncio.to_thread(store.set_model_override, key, want)
        logger.info("matrix-call: phone session %s pinned to %s (%s)", key, model, provider)
    peek = getattr(runner, "_peek_session_state", None)
    conversation = getattr(peek(key) if callable(peek) else None, "conversation", None)
    current = getattr(conversation, "model_override", None)
    if isinstance(current, dict) and current.get("model") != model:
        # An in-memory override of another model would win over the stored one; without it the next turn
        # rehydrates the stored override (_rehydrate_session_model_override).
        conversation.model_override = None
    return True

"""Per-room approval bypass: keep the gateway's session-scoped /yolo on for listed chats.
Hardline floors, approvals.deny and the gateway lifecycle guard still apply (not bypassable).

Settings: ``plugins.entries.room-yolo.settings.rooms`` = list of chat ids (e.g. Matrix room ids)."""
import logging

logger = logging.getLogger(__name__)
_ctx = None


def _rooms():
    rooms = _ctx.get_config("rooms", []) if _ctx is not None else []
    if isinstance(rooms, str):
        rooms = [r.strip() for r in rooms.split(",") if r.strip()]
    return {str(r) for r in rooms or []}


def _enable(key):
    from tools.approval import enable_session_yolo, is_session_yolo_enabled
    if key and not is_session_yolo_enabled(key):
        enable_session_yolo(key)
        logger.info("room-yolo: approvals bypassed for %s", key)


def _on_dispatch(event=None, gateway=None, **_):
    src = getattr(event, "source", None)
    chat = getattr(src, "chat_id", None)
    if not chat or chat not in _rooms():
        return None
    try:
        _enable(gateway._session_key_for_source(src))
    except Exception as exc:  # never block a message because the bypass failed
        logger.warning("room-yolo: could not enable for %s: %r", chat, exc)
    return None


def register(ctx):
    global _ctx
    _ctx = ctx
    ctx.register_hook("pre_gateway_dispatch", _on_dispatch)
    logger.info("room-yolo: registered for %d room(s)", len(_rooms()))

"""What the worker says for an agent reply, and the hook callbacks that route replies of the call's session to it."""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_CHARS = 150  # about 30 s of Chinese speech; the full reply is in the chat anyway
REST = "其余内容见聊天。"
_SENTENCE_END = re.compile(r"[。！？!?；;…]|\.(?=\s|$)")

try:
    from tools.tts_text_normalize import _strip_markdown_for_tts
except Exception:  # outside the gateway; spoken() then only trims
    _strip_markdown_for_tts = None


def spoken(text: str) -> str:
    """Markdown-free text to speak: at most MAX_CHARS, cut at a sentence end when there is one in the second half."""
    t = (_strip_markdown_for_tts(text) if _strip_markdown_for_tts else text).strip()
    if len(t) <= MAX_CHARS:
        return t
    head = t[:MAX_CHARS]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    if ends and ends[-1] >= MAX_CHARS // 2:
        head = head[:ends[-1]]
    return head.rstrip() + " " + REST


class Hooks:
    """Phi hooks run on agent and dispatcher threads; each one only posts to the gateway loop, where the
    controller (call.Calls) decides whether the hook belongs to the active call."""

    def __init__(self, controllers: list):
        self.controllers = controllers  # live list, owned by the plugin

    def _post(self, method: str, *args) -> None:
        for c in list(self.controllers):
            loop = c.loop
            if c.call is not None and loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(getattr(c, method), *args)

    def pre_llm_call(self, session_id=None, turn_id=None, user_message=None, platform=None, task_id=None, **_):
        message = user_message if isinstance(user_message, str) else str(user_message or "")
        self._post("on_turn", session_id, turn_id, message, platform, task_id)

    def post_llm_call(self, session_id=None, turn_id=None, assistant_response=None, platform=None, **_):
        if platform == "matrix" and isinstance(assistant_response, str) and assistant_response.strip():
            self._post("on_reply", session_id, turn_id, assistant_response, "final")

    def on_interim_message(self, session_id=None, turn_id=None, text=None, surface=None, **_):
        # The interim payload names the platform "surface"; there is no platform kwarg.
        if surface == "matrix" and isinstance(text, str) and text.strip() and _interim_shown():
            self._post("on_reply", session_id, turn_id, text, "interim")


def _interim_shown() -> bool:
    """Whether the gateway posts interim assistant text in Matrix rooms (display.interim_assistant_messages, as
    the gateway resolves it per message): the caller hears no more than the chat shows."""
    from gateway.display_config import resolve_display_setting
    from phi_cli.config_effective import load_user_config_effective
    from phi_constants import get_phi_home
    try:
        config = load_user_config_effective(Path(get_phi_home()) / "config.yaml") or {}
    except Exception:
        config = {}  # the gateway's _load_gateway_config falls back the same way
    return bool(resolve_display_setting(config, "matrix", "interim_assistant_messages", True))

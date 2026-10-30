"""A voice note's transcript is echoed to the chat once.

On a busy chat the same note is transcribed and echoed on the busy path, then re-dispatched as a
fresh event (interrupt, busy-router pass) and echoed again, so the chat showed the 🎙️ line twice.
"""
from types import SimpleNamespace

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.run import GatewayRunner
from gateway.session import SessionSource


class _Chat:
    def __init__(self):
        self.sent = []
        self.replies = []

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        self.sent.append((chat_id, content))
        self.replies.append(reply_to)
        return SimpleNamespace(success=True)


def _source(chat="!room-a:example.org"):
    return SessionSource(platform=Platform.MATRIX, chat_id=chat, chat_type="dm", user_id="@ann:example.org")


@pytest.mark.asyncio
async def test_the_same_note_echoed_on_two_paths_shows_once():
    runner, chat = GatewayRunner(GatewayConfig()), _Chat()
    await runner._echo_stt_transcripts(chat, _source(), ["hello there"])
    await runner._echo_stt_transcripts(chat, _source(), ["hello there"])
    assert len(chat.sent) == 1


@pytest.mark.asyncio
async def test_different_notes_and_chats_are_each_echoed():
    runner, chat = GatewayRunner(GatewayConfig()), _Chat()
    await runner._echo_stt_transcripts(chat, _source(), ["first", "second"])
    await runner._echo_stt_transcripts(chat, _source("!room-b:example.org"), ["first"])
    assert len(chat.sent) == 3


@pytest.mark.asyncio
async def test_the_echo_replies_to_the_voice_note_it_transcribes():
    """The transcript sits under the user's voice note, not as a loose bot message."""
    from gateway.platforms.event import MessageEvent, MessageType
    runner, chat = GatewayRunner(GatewayConfig()), _Chat()
    runner._delivery_adapter_for = lambda source: chat
    runner._should_echo_stt_transcripts = lambda: True

    async def transcribe(text, paths, *a, **k):
        return "hello there", ["hello there"]
    runner._enrich_message_with_transcription = transcribe
    event = MessageEvent(text="", message_type=MessageType.VOICE, source=_source(), message_id="$voice-note")
    await runner._enrich_inbound_voice(event, event.source, "", ["/tmp/note.ogg"])
    assert chat.replies == ["$voice-note"]

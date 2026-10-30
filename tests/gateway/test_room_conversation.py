"""One conversation per workspace room across every chat tool linked to it (gateway/room_conversation.py).

A Matrix-like and a Telegram-like chat tool share nothing but the room. A human main-lane message from
either continues the room's current conversation; a lane that ran ``/new`` leads instead of being pulled
back; each turn's answer reaches the room's other chat tools under a one-line quote of the question,
never the asking chat, never email/SMS. Threads and automation keep their own sessions. The end-to-end
cases drive a real GatewayRunner, session authority, SessionStore and SessionDB; only the model turn
is a stand-in.
"""

import asyncio
import logging
import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import BasePlatformAdapter, SendResult
from gateway.session import SessionSource, SessionStore
from phi_cli import workspace_map as wm
from tests.waiting import async_wait_until, wait_until

MATRIX_CHAT, TELEGRAM_CHAT, ANN = "!room-a:example.org", "42", "@ann:example.org"


def _rc():
    import gateway.room_conversation as rc
    return rc


def _matrix(**extra):
    return SessionSource(platform=Platform.MATRIX, chat_id=MATRIX_CHAT, chat_type="group",
                         user_id=ANN, user_name="Ann", **extra)


def _telegram(**extra):
    return SessionSource(platform=Platform.TELEGRAM, chat_id=TELEGRAM_CHAT, chat_type="dm",
                         user_id=TELEGRAM_CHAT, user_name="Ann", **extra)


def _tick():
    """Let the wall clock move, so "before / after the pointer moved" is unambiguous."""
    now = time.time()
    wait_until(lambda: time.time() > now, what="the clock to move")


@pytest.fixture
def room():
    room_id = wm.create_room("Shared")["room_id"]
    wm.link_channel(room_id, "matrix", MATRIX_CHAT)
    wm.link_channel(room_id, "telegram", TELEGRAM_CHAT)
    return room_id


@pytest.fixture
def store(tmp_path):
    return SessionStore(tmp_path / "sessions", GatewayConfig())


def _lane(store, source):
    entry = store.get_or_create_session(source)
    return entry.session_key, entry.session_id


# --- which lanes belong to the room ------------------------------------------------------------------


_NOT_THE_ROOMS = {
    "thread": lambda: _matrix(thread_id="$thread-1", parent_chat_id=MATRIX_CHAT),
    "cron": lambda: replace(_telegram(), user_id="system:cron"),
    "unlinked chat": lambda: replace(_telegram(), chat_id="77", user_id="77"),
    "api server": lambda: SessionSource(platform=Platform.API_SERVER, chat_id="api-1", chat_type="dm", user_id="c-1"),
    "local": lambda: SessionSource(platform=Platform.LOCAL, chat_id="local-1", chat_type="dm"),
}


def test_only_human_main_lanes_of_linked_chats_belong_to_the_room(room):
    wm.link_channel(room, "api_server", "api-1")
    wm.link_channel(room, "local", "local-1")
    rc = _rc()
    assert rc.room_for_source(_matrix()) == room
    assert rc.room_for_source(_telegram()) == room
    assert {kind: rc.room_for_source(make()) for kind, make in _NOT_THE_ROOMS.items()} == dict.fromkeys(_NOT_THE_ROOMS)


def test_a_chat_in_a_profile_without_a_workspace_leaves_no_workspace_map(store):
    rc = _rc()
    key, own = _lane(store, _telegram())
    assert not wm.map_db_path().exists()

    assert rc.room_for_source(_telegram()) is None
    assert rc.repoint_route(store, _telegram(), key) is None
    assert store.peek_session_id(key) == own
    assert not wm.map_db_path().exists()


# --- inbound: lanes follow the room's current conversation -------------------------------------------


def test_a_lane_joins_the_rooms_current_conversation(room, store):
    rc = _rc()
    tg_key, tg_old = _lane(store, _telegram())
    mx_key, shared = _lane(store, _matrix())
    _tick()
    rc.record_turn(room, shared)

    assert rc.repoint_route(store, _telegram(), tg_key) == shared
    assert store.peek_session_id(tg_key) == store.peek_session_id(mx_key) == shared
    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert rc.repoint_route(store, _matrix(), mx_key) is None
    assert tg_old != shared


def test_a_new_chats_first_message_continues_the_room_conversation(room, store):
    rc = _rc()
    _mx_key, shared = _lane(store, _matrix())
    _tick()
    rc.record_turn(room, shared)
    tg_key = store._generate_session_key(_telegram())
    assert store.peek_session_id(tg_key) is None

    assert rc.repoint_route(store, _telegram(), tg_key) == shared
    assert store.peek_session_id(tg_key) == shared


def test_a_lane_that_ran_new_after_the_room_moved_leads_instead_of_being_pulled_back(room, store):
    rc = _rc()
    mx_key, old = _lane(store, _matrix())
    tg_key, _ = _lane(store, _telegram())
    _tick()
    rc.record_turn(room, old)
    _tick()
    fresh = store.reset_session(tg_key).session_id

    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert store.peek_session_id(tg_key) == fresh
    rc.record_turn(room, fresh)
    assert rc.repoint_route(store, _matrix(), mx_key) == fresh
    assert store.peek_session_id(mx_key) == fresh


@pytest.mark.parametrize("surface", ["local", "web", "tui", "api_server", "cron"])
def test_a_chat_lane_does_not_join_a_web_api_or_background_conversation(room, store, surface):
    """The session authority runs a chat's messages only on a chat lane, so a conversation started on
    the web terminal (or by the API, or a background run) is never joined by a chat tool."""
    from phi_state import SessionDB
    rc = _rc()
    tg_key, own = _lane(store, _telegram())
    db = SessionDB()
    try:
        db.create_session("elsewhere-1", source=surface)
    finally:
        db.close()
    _tick()
    rc.record_turn(room, "elsewhere-1")

    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert store.peek_session_id(tg_key) == own


@pytest.mark.parametrize("kind", ["thread", "cron"])
def test_thread_and_automation_lanes_keep_their_own_session(room, store, kind):
    rc = _rc()
    source = _NOT_THE_ROOMS[kind]()
    key, own = _lane(store, source)
    _mx_key, shared = _lane(store, _matrix())
    _tick()
    rc.record_turn(room, shared)

    assert rc.repoint_route(store, source, key) is None
    assert store.peek_session_id(key) == own


def test_a_compressed_conversation_is_joined_at_its_live_tip(room, store):
    from phi_state import SessionDB
    rc = _rc()
    tg_key, _ = _lane(store, _telegram())
    mx_key, root = _lane(store, _matrix())
    db = SessionDB()
    try:
        db.create_session("tip-1", source="matrix", parent_session_id=root)
        db.end_session(root, end_reason="compression")
    finally:
        db.close()
    assert store.advance_compression_session(mx_key, root, "tip-1") is not None
    _tick()
    rc.record_turn(room, root)  # the room names the conversation by its logical id

    assert rc.repoint_route(store, _telegram(), tg_key) == root
    assert store.peek_session_id(tg_key) == "tip-1"
    assert rc.repoint_route(store, _matrix(), mx_key) is None
    assert store.peek_session_id(mx_key) == "tip-1"


def test_a_lane_mid_turn_joins_only_once_its_turn_is_over(room, store):
    rc = _rc()
    tg_key, own = _lane(store, _telegram())
    _mx_key, shared = _lane(store, _matrix())
    _tick()
    rc.record_turn(room, shared)
    released = []
    runner = SimpleNamespace(session_store=store, _running_agents={tg_key: object()},
                             _evict_cached_agent=released.append)

    assert rc.join_room_conversation(runner, _telegram()) is None
    assert store.peek_session_id(tg_key) == own and released == []
    runner._running_agents.clear()
    assert rc.join_room_conversation(runner, _telegram()) == shared
    assert store.peek_session_id(tg_key) == shared and released == [tg_key]


def test_routing_and_recording_never_raise(room, store):
    class _Broken:
        def __getattr__(self, name):
            raise RuntimeError("session store unavailable")

    rc = _rc()
    rc.record_turn("!missing:example.org", "s-1")
    assert wm.current_conversation("!missing:example.org") is None
    tg_key, _ = _lane(store, _telegram())
    rc.record_turn(room, "s-1")
    assert rc.repoint_route(_Broken(), _telegram(), tg_key) is None


# --- outbound: mirroring a turn ----------------------------------------------------------------------


class _Sink:
    """A running chat tool's adapter as the mirror sees it. ``mode``: ok | refuse | raise."""

    def __init__(self, mode="ok"):
        self.mode, self.sent = mode, []

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if self.mode == "raise":
            raise RuntimeError("chat tool is down")
        self.sent.append((chat_id, content))
        return SendResult(success=self.mode == "ok", message_id="m-1")


def _mirror(sinks, room_id, origin, origin_chat, label):
    runner = SimpleNamespace(adapters={Platform(name): sink for name, sink in sinks.items()})
    return asyncio.run(_rc().mirror_turn(runner, room_id, origin, origin_chat, label, "Ann", "Where now?", "Here."))


def test_a_turn_reaches_the_other_chat_tools_with_its_quote_never_the_origin_email_or_sms(room):
    wm.link_channel(room, "email", "ann@example.org")
    wm.link_channel(room, "sms", "+15550100")
    sinks = {name: _Sink() for name in ("matrix", "telegram", "email", "sms")}

    result = _mirror(sinks, room, "matrix", MATRIX_CHAT, "Matrix")

    assert sinks["telegram"].sent == [(TELEGRAM_CHAT, "[Matrix · Ann] Where now?\n\nHere.")]
    assert sinks["matrix"].sent == sinks["email"].sent == sinks["sms"].sent == []
    assert result == [("telegram", TELEGRAM_CHAT, True)]


def test_a_failed_or_missing_chat_tool_is_reported_without_raising(room, caplog):
    wm.link_channel(room, "discord", "9000")
    wm.link_channel(room, "slack", "C0001")  # linked, no adapter running
    sinks = {"matrix": _Sink(), "telegram": _Sink("raise"), "discord": _Sink("refuse")}

    with caplog.at_level(logging.WARNING, logger="gateway.room_conversation"):
        result = _mirror(sinks, room, "web", None, "Web")

    assert sorted(result) == [("discord", "9000", False), ("matrix", MATRIX_CHAT, True),
                              ("slack", "C0001", False), ("telegram", TELEGRAM_CHAT, False)]
    assert sinks["matrix"].sent == [(MATRIX_CHAT, "[Web · Ann] Where now?\n\nHere.")]
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) >= 3


def test_the_quote_is_one_line_of_at_most_80_question_characters():
    rc = _rc()
    assert rc.quote_line("Telegram", "Ann", "first\n  second") == "[Telegram · Ann] first second"
    assert rc.quote_line("Web", None, "hi") == "[Web] hi"
    assert rc.quote_line("Web", None, "q" * 80) == "[Web] " + "q" * 80
    assert rc.quote_line("Web", None, "q" * 81) == "[Web] " + "q" * 79 + "…"


# --- end to end: a real gateway with two chat tools ------------------------------------------------


class _Chat(BasePlatformAdapter):
    """A chat tool that records what the gateway sends it; with ``stuck`` set, a send to it does not
    return until that event is set."""

    def __init__(self, platform):
        super().__init__(PlatformConfig(enabled=True, token="fixture-token"), platform)
        self.sent, self.stuck = [], None

    async def connect(self, *, is_reconnect=False):
        return True

    async def disconnect(self):
        pass

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if self.stuck is not None:
            await self.stuck.wait()
        self.sent.append((chat_id, content))
        return SendResult(success=True, message_id=f"sent-{len(self.sent)}")

    async def edit_message(self, chat_id, message_id, content, *, finalize=False):
        return SendResult(success=True, message_id=message_id)

    async def send_typing(self, chat_id, metadata=None):
        pass

    async def get_chat_info(self, chat_id):
        return {"id": chat_id}


async def _gateway(monkeypatch, gates=None, instance_id="owner"):
    """Real runner + authority; a turn answers ``answer to <text>`` on the session it resolved. A new
    ``instance_id`` is the gateway after a restart: nothing of the earlier one is live in it."""
    from gateway.run import GatewayRunner
    from gateway.session_authority import initialize_session_authority
    from gateway.session_results import execution_result

    monkeypatch.setenv("GATEWAY_ALLOWED_USERS", f"{ANN},{TELEGRAM_CHAT}")
    runner = GatewayRunner(GatewayConfig())
    chats = {"matrix": _Chat(Platform.MATRIX), "telegram": _Chat(Platform.TELEGRAM)}
    runner.adapters = {chat.platform: chat for chat in chats.values()}
    monkeypatch.setattr(runner, "_read_user_config", lambda: {"approvals": {"destructive_slash_confirm": False}})
    authority = await initialize_session_authority(runner, profile_id="default", instance_id=instance_id)
    for chat in chats.values():
        runner._wire_adapter_handlers(chat)
    ran = []

    async def prepare(event, source, session_entry, *args):
        ran.append(session_entry.session_id)
        if gates and event.text in gates:
            await gates[event.text].wait()
        answer = f"answer to {event.text}"
        for role, content in (("user", event.text), ("assistant", answer)):  # the transcript a turn keeps
            authority.db.append_message(session_entry.session_id, role, content)
        execution_result.get()["result"] = {"final_response": answer, "messages": []}
        return answer, None
    monkeypatch.setattr(runner, "_hmwa_prepare_turn", prepare)
    return runner, authority, chats, ran


async def _say(chats, name, text, n):
    from gateway.platforms.event import MessageEvent
    chat = chats[name]
    source = chat.build_source(chat_id=MATRIX_CHAT if name == "matrix" else TELEGRAM_CHAT, chat_type="dm",
                               user_id=ANN if name == "matrix" else TELEGRAM_CHAT, user_name="Ann")
    await chat.handle_message(MessageEvent(text=text, source=source, message_id=f"{name}-{n}"))
    return source


def _texts(chat):
    return [content for _chat_id, content in chat.sent]


@pytest.mark.asyncio
async def test_two_chat_tools_hold_one_room_conversation(monkeypatch, room):
    runner, _authority, chats, ran = await _gateway(monkeypatch)
    store, mx, tg = runner.session_store, chats["matrix"], chats["telegram"]

    tg_source = await _say(chats, "telegram", "first", 1)
    await async_wait_until(lambda: "[Telegram · Ann] first\n\nanswer to first" in _texts(mx), what="the mirror")
    await async_wait_until(lambda: _texts(tg), what="the reply")
    assert _texts(tg) == ["answer to first"]
    shared = store.peek_session_id(store._generate_session_key(tg_source))
    assert wm.current_conversation(room) == shared

    mx_source = await _say(chats, "matrix", "second", 2)  # this chat's first message
    await async_wait_until(lambda: "[Matrix · Ann] second\n\nanswer to second" in _texts(tg), what="the mirror")
    await async_wait_until(lambda: _texts(mx)[-1:] == ["answer to second"], what="the reply")
    assert ran == [shared, shared]

    await _say(chats, "telegram", "/new", 3)
    tg_key = store._generate_session_key(tg_source)
    fresh = await async_wait_until(lambda: (sid := store.peek_session_id(tg_key)) != shared and sid, what="/new")
    await async_wait_until(lambda: wm.current_conversation(room) == fresh, what="the room to follow /new")
    await _say(chats, "matrix", "third", 4)
    await async_wait_until(lambda: "[Matrix · Ann] third\n\nanswer to third" in _texts(tg), what="the mirror")
    await async_wait_until(lambda: _texts(mx)[-1:] == ["answer to third"], what="the reply")
    assert ran[-1] == fresh == store.peek_session_id(store._generate_session_key(mx_source))

    await _say(chats, "telegram", "fourth", 5)  # the lanes take turns on the one conversation
    await async_wait_until(lambda: "[Telegram · Ann] fourth\n\nanswer to fourth" in _texts(mx), what="the mirror")
    await async_wait_until(lambda: _texts(tg)[-1:] == ["answer to fourth"], what="the reply")
    assert ran == [shared, shared, fresh, fresh]
    assert sum("answer to" in text for text in _texts(mx)) == 4  # own replies, never its own turns mirrored back
    assert all(not text.startswith("[Matrix") for text in _texts(mx))


@pytest.mark.asyncio
async def test_a_web_prompt_on_a_chat_conversation_shows_its_question_in_every_chat_tool(monkeypatch, room):
    from gateway.session_contract import Principal, Submission

    runner, authority, chats, _ran = await _gateway(monkeypatch)
    ref = authority.register(_telegram())
    viewer = Principal("authenticated-viewer", "default", frozenset({"session:submit"}), "viewer")
    await authority.submit(viewer, Submission("W", ref, {"text": "from the web"}, "queue"))

    quoted = "[Web] from the web\n\nanswer to from the web"
    await async_wait_until(lambda: _texts(chats["telegram"]) and _texts(chats["matrix"]), what="both chats")
    assert _texts(chats["telegram"]) == [quoted]
    assert _texts(chats["matrix"]) == [quoted]
    assert wm.current_conversation(room) == ref.session_id


@pytest.mark.asyncio
async def test_a_turn_does_not_take_the_room_back_after_it_moved_on(monkeypatch, room):
    from phi_state import SessionDB
    gate = asyncio.Event()
    runner, _authority, chats, ran = await _gateway(monkeypatch, gates={"slow": gate})

    await _say(chats, "telegram", "slow", 1)
    await async_wait_until(lambda: ran, what="the turn to start")
    db = SessionDB()
    try:
        db.create_session("moved-on", source="matrix")  # another lane's /new while this turn runs
    finally:
        db.close()
    _tick()
    _rc().record_turn(room, "moved-on")
    gate.set()

    await async_wait_until(lambda: "[Telegram · Ann] slow\n\nanswer to slow" in _texts(chats["matrix"]),
                           what="the mirror")
    assert wm.current_conversation(room) == "moved-on"


def _dashboard_connection(authority):
    """The web terminal's PTY session on the in-process gateway, as ``/api/ws`` builds it for the
    dashboard's verified operator (legacy session token)."""
    from gateway.session_controls import AuthorityConnection
    identity = {"user_id": "legacy-token-owner", "provider": "session-token", "profile_id": authority.profile_id,
                "instance_id": authority.instance_id, "profile_scope": "host",
                "capabilities": ["session:create", "session:read", "session:submit", "session:control",
                                 "session:approve", "session:respond"]}
    return AuthorityConnection(authority, object(), identity, operator=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("restarted", [False, True], ids=["live", "after-a-restart"])
async def test_the_web_terminal_reopens_the_rooms_chat_conversation_and_prompts_on_its_chat_route(
        monkeypatch, room, restarted):
    """Opening the room in the web terminal resumes the conversation a Matrix chat holds (the room's
    pointer, ``resume_for_room``), the PTY's ``session.resume`` mounts it through the session
    authority, and a prompt typed there runs on the Matrix route: Matrix answers it under the web
    quote and the room's other chat sees it too."""
    from phi_cli.web_routers import chat_workspaces
    from phi_state import SessionDB

    runner, authority, chats, ran = await _gateway(monkeypatch)
    mx_source = await _say(chats, "matrix", "first", 1)
    await async_wait_until(lambda: _texts(chats["matrix"]) and _texts(chats["telegram"]), what="reply + mirror")
    sid = runner.session_store.peek_session_id(runner.session_store._generate_session_key(mx_source))
    db = SessionDB()
    try:
        row = db.get_session(sid)
    finally:
        db.close()
    assert (row["source"], bool(row["session_key"]), bool(row["origin_json"])) == ("matrix", True, True)
    assert wm.current_conversation(room) == sid
    if restarted:
        runner, authority, chats, ran = await _gateway(monkeypatch, instance_id="restarted")
        assert sid not in authority.sessions

    assert await chat_workspaces.resume_for_room({"room_id": room}, None) == sid
    connection = _dashboard_connection(authority)
    try:
        resumed = await connection.dispatch({"id": 1, "method": "session.resume", "params": {"session_id": sid}})
        assert resumed.get("result", {}).get("session_id") == sid, resumed
        submitted = await connection.dispatch({"id": 2, "method": "prompt.submit", "params": {
            "session_id": sid, "input_id": "web-1", "text": "from the web"}})
        assert "result" in submitted, submitted
        quoted = "[Web] from the web\n\nanswer to from the web"
        await async_wait_until(lambda: quoted in _texts(chats["matrix"]) and quoted in _texts(chats["telegram"]),
                               what="the web prompt answered on the chat route")
    finally:
        await connection.close()
    assert ran[-1] == sid and wm.current_conversation(room) == sid


@pytest.mark.asyncio
async def test_a_chat_tool_that_never_takes_the_mirror_does_not_hold_the_asking_lane(monkeypatch, room):
    runner, _authority, chats, ran = await _gateway(monkeypatch)
    stuck = chats["matrix"].stuck = asyncio.Event()

    await _say(chats, "telegram", "first", 1)
    await async_wait_until(lambda: _texts(chats["telegram"]) == ["answer to first"], what="the reply")
    await _say(chats, "telegram", "second", 2)
    await async_wait_until(lambda: _texts(chats["telegram"])[-1:] == ["answer to second"], what="the next turn")
    assert len(ran) == 2 and _texts(chats["matrix"]) == []

    held = [task for task in runner._background_tasks if not task.done()]
    for task in held:  # what the gateway's shutdown does with the runner's background tasks
        task.cancel()
    await asyncio.gather(*held, return_exceptions=True)
    stuck.set()
    await _say(chats, "telegram", "third", 3)
    await async_wait_until(lambda: _texts(chats["matrix"]), what="the next mirror")
    assert _texts(chats["matrix"]) == ["[Telegram · Ann] third\n\nanswer to third"]

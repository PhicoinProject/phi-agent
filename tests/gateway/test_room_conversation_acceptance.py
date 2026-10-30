"""Acceptance: one conversation per workspace room, across every chat tool linked to it.

Black-box contract, written from the design and the fixed interface only, against the real
``SessionStore`` and workspace map in the test's own ``PHI_HOME`` (the hermetic home under
``tmp_path``). A room has one current conversation: a human main-lane message from any linked chat
follows it (``repoint_route``); a lane that ran ``/new`` after the room moved is not pulled back, and
the room follows that lane once its turn is recorded; a turn's answer is mirrored to the room's other
chat tools under a one-line quote of the question. Threads, automation, unlinked chats and
non-messaging surfaces are never touched; email and SMS never get mirrored turns.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import sqlite3
import time
from contextlib import closing
from dataclasses import replace
from types import SimpleNamespace

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.session import SessionSource, SessionStore
from phi_cli import workspace_map as wm
from tests.waiting import wait_until

MATRIX_CHAT = "!room-a:example.org"
TELEGRAM_CHAT = "42"
EMAIL_CHAT = "ann@example.org"
QUESTION = "Where did we leave the release notes?"
ANSWER = "In docs/release.md, second section."


def _rc():
    """The module under test, imported inside each test so every scenario fails on its own until it exists."""
    return importlib.import_module("gateway.room_conversation")


def _matrix(**extra) -> SessionSource:
    return SessionSource(platform=Platform.MATRIX, chat_id=MATRIX_CHAT, chat_type="group",
                         user_id="@ann:example.org", user_name="Ann", **extra)


def _telegram(**extra) -> SessionSource:
    return SessionSource(platform=Platform.TELEGRAM, chat_id=TELEGRAM_CHAT, chat_type="dm",
                         user_id=TELEGRAM_CHAT, user_name="Ann", **extra)


@pytest.fixture
def room() -> str:
    """A room linked to a Matrix room and a Telegram chat."""
    room_id = wm.create_room("Shared")["room_id"]
    wm.link_channel(room_id, "matrix", MATRIX_CHAT)
    wm.link_channel(room_id, "telegram", TELEGRAM_CHAT)
    return room_id


@pytest.fixture
def store(tmp_path) -> SessionStore:
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(exist_ok=True)
    return SessionStore(sessions_dir, GatewayConfig(sessions_dir=sessions_dir, write_sessions_json=False))


def _lane(store: SessionStore, source: SessionSource) -> tuple[str, str]:
    """Open a lane the way an inbound message does; ``(session_key, session_id)``."""
    entry = store.get_or_create_session(source)
    return entry.session_key, entry.session_id


def _after(moment: float) -> None:
    """Hold until the wall clock is past ``moment``, so "created before / after the pointer" is unambiguous."""
    wait_until(lambda: time.time() > moment, what="the clock to pass the previous event")


def _after_lane(store: SessionStore, session_key: str) -> None:
    _after(store.lookup_by_session_key(session_key).created_at.timestamp())


# --- inbound: lanes follow the room's current conversation ----------------------------------------


def test_a_linked_lane_follows_the_room_conversation_and_keeps_its_old_session(room, store):
    from phi_state import SessionDB

    tg_key, tg_old = _lane(store, _telegram())
    mx_key, shared = _lane(store, _matrix())
    _after_lane(store, mx_key)
    rc = _rc()
    rc.record_turn(room, shared)
    assert wm.current_conversation(room) == shared

    assert rc.repoint_route(store, _telegram(), tg_key) == shared
    assert store.peek_session_id(tg_key) == shared
    # Already there: nothing more to do, on either lane.
    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert rc.repoint_route(store, _matrix(), mx_key) is None
    assert store.peek_session_id(mx_key) == shared
    # The Telegram lane's own earlier conversation is left as it was, not deleted.
    db = SessionDB()
    try:
        assert db.get_session(tg_old) is not None
    finally:
        db.close()


def test_a_pointer_to_a_session_that_does_not_exist_moves_no_lane(room, store):
    tg_key, tg_sid = _lane(store, _telegram())
    _after_lane(store, tg_key)
    rc = _rc()
    rc.record_turn(room, "20260101_000000_deadbeef")

    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert store.peek_session_id(tg_key) == tg_sid


def test_a_lane_that_ran_new_is_not_pulled_back_and_the_room_then_follows_it(room, store):
    mx_key, mx_sid = _lane(store, _matrix())
    tg_key, _ = _lane(store, _telegram())
    _after_lane(store, tg_key)
    rc = _rc()
    rc.record_turn(room, mx_sid)
    _after(wm.current_conversation_since(room))
    fresh = store.reset_session(tg_key).session_id  # Telegram's /new, after the room moved

    assert rc.repoint_route(store, _telegram(), tg_key) is None
    assert store.peek_session_id(tg_key) == fresh

    rc.record_turn(room, fresh)  # the /new conversation's first turn
    assert wm.current_conversation(room) == fresh
    assert rc.repoint_route(store, _matrix(), mx_key) == fresh
    assert store.peek_session_id(mx_key) == fresh
    assert rc.repoint_route(store, _telegram(), tg_key) is None


def test_human_main_lanes_of_linked_chats_belong_to_the_room(room):
    rc = _rc()
    assert rc.room_for_source(_matrix()) == room
    assert rc.room_for_source(_telegram()) == room


_UNTOUCHED = {
    "matrix thread": lambda: _matrix(thread_id="$thread-1", parent_chat_id=MATRIX_CHAT),
    "cron user": lambda: replace(_telegram(), user_id="system:cron"),
    "unlinked chat": lambda: replace(_telegram(), chat_id="77", user_id="77"),
    "api server": lambda: SessionSource(platform=Platform.API_SERVER, chat_id="api-chat-1",
                                        chat_type="dm", user_id="client-1"),
    "local": lambda: SessionSource(platform=Platform.LOCAL, chat_id="local-1", chat_type="dm"),
}


@pytest.mark.parametrize("kind", sorted(_UNTOUCHED))
def test_threads_automation_unlinked_and_non_messaging_lanes_are_untouched(room, store, kind):
    # Linked too, so only the surface itself can keep them out of the room.
    wm.link_channel(room, "api_server", "api-chat-1")
    wm.link_channel(room, "local", "local-1")
    source = _UNTOUCHED[kind]()
    key, sid = _lane(store, source)
    mx_key, shared = _lane(store, _matrix())
    _after_lane(store, mx_key)
    rc = _rc()
    rc.record_turn(room, shared)

    assert rc.room_for_source(source) is None
    assert rc.repoint_route(store, source, key) is None
    assert store.peek_session_id(key) == sid
    # Asking about an unlinked chat never links it anywhere.
    assert wm.room_for_channel("telegram", "77") is None


def test_recording_and_routing_never_raise(room, store):
    class _BrokenStore:
        def __getattr__(self, name):
            raise RuntimeError("session store unavailable")

    tg_key, _ = _lane(store, _telegram())
    mx_key, shared = _lane(store, _matrix())
    _after_lane(store, mx_key)
    rc = _rc()
    rc.record_turn(room, shared)

    rc.record_turn("!no-such-room:example.org", shared)
    assert wm.current_conversation("!no-such-room:example.org") is None
    assert wm.current_conversation(room) == shared
    assert rc.repoint_route(_BrokenStore(), _telegram(), tg_key) is None


# --- outbound: a turn's answer reaches the room's other chat tools ---------------------------------


class _Adapter:
    """A chat tool that records what it is asked to send. ``mode``: ok | refuse (success=False) | raise."""

    def __init__(self, mode: str = "ok"):
        self.mode = mode
        self.sent: list[tuple[str, str]] = []

    async def send(self, chat_id, content, reply_to=None, metadata=None):
        if self.mode == "raise":
            raise RuntimeError("chat tool is down")
        self.sent.append((chat_id, content))
        return SimpleNamespace(success=self.mode == "ok")


def _mirror(adapters: dict, room_id: str, origin: str, origin_chat, label: str):
    runner = SimpleNamespace(adapters={Platform(name): a for name, a in adapters.items()})
    return asyncio.run(_rc().mirror_turn(runner, room_id, origin, origin_chat, label, "Ann", QUESTION, ANSWER))


def _expected(label: str) -> str:
    return f"{_rc().quote_line(label, 'Ann', QUESTION)}\n\n{ANSWER}"


@pytest.fixture
def mailed_room(room) -> str:
    """The shared room with an email address linked as well."""
    wm.link_channel(room, "email", EMAIL_CHAT)
    return room


def test_room_links_lists_every_linked_chat_of_that_room_only(mailed_room):
    other = wm.create_room("Other")["room_id"]
    wm.link_channel(other, "telegram", "99")

    assert sorted(wm.room_links(mailed_room)) == sorted(
        [("matrix", MATRIX_CHAT), ("telegram", TELEGRAM_CHAT), ("email", EMAIL_CHAT)])


def test_a_chat_turn_is_mirrored_once_to_the_other_chat_tools_never_back_or_to_email(mailed_room):
    adapters = {"matrix": _Adapter(), "telegram": _Adapter(), "email": _Adapter()}

    result = _mirror(adapters, mailed_room, "matrix", MATRIX_CHAT, "Matrix")

    assert adapters["telegram"].sent == [(TELEGRAM_CHAT, _expected("Matrix"))]
    assert adapters["telegram"].sent[0][1].startswith(_rc().quote_line("Matrix", "Ann", QUESTION))
    assert adapters["matrix"].sent == []
    assert adapters["email"].sent == []
    assert result == [("telegram", TELEGRAM_CHAT, True)]


def test_a_web_turn_is_mirrored_to_every_linked_chat_tool_except_email(mailed_room):
    adapters = {"matrix": _Adapter(), "telegram": _Adapter(), "email": _Adapter()}

    result = _mirror(adapters, mailed_room, "web", None, "Web")

    assert adapters["matrix"].sent == [(MATRIX_CHAT, _expected("Web"))]
    assert adapters["telegram"].sent == [(TELEGRAM_CHAT, _expected("Web"))]
    assert adapters["email"].sent == []
    assert sorted(result) == sorted([("matrix", MATRIX_CHAT, True), ("telegram", TELEGRAM_CHAT, True)])


def test_a_failing_or_missing_chat_tool_is_reported_and_the_others_still_get_the_turn(room, caplog):
    wm.link_channel(room, "discord", "9000")
    wm.link_channel(room, "slack", "C0001")  # linked, but no adapter is running for it
    adapters = {"matrix": _Adapter(), "telegram": _Adapter("raise"), "discord": _Adapter("refuse")}

    with caplog.at_level(logging.WARNING):
        result = _mirror(adapters, room, "web", None, "Web")

    assert adapters["matrix"].sent == [(MATRIX_CHAT, _expected("Web"))]
    assert sorted(result) == sorted([
        ("matrix", MATRIX_CHAT, True), ("telegram", TELEGRAM_CHAT, False),
        ("discord", "9000", False), ("slack", "C0001", False)])
    assert any(record.levelno == logging.WARNING for record in caplog.records)


def test_the_quote_line_is_one_short_line_naming_where_and_who_asked():
    rc = _rc()
    assert rc.quote_line("Telegram", "Ann", "first line\nsecond line") == "[Telegram · Ann] first line second line"
    assert rc.quote_line("Web", None, "hi") == "[Web] hi"
    exact = "q" * 80
    assert rc.quote_line("Matrix", "Ann", exact) == f"[Matrix · Ann] {exact}"

    long_question = "a" * 79 + "bcdef"
    cut = rc.quote_line("Matrix", "Ann", long_question)
    assert cut.startswith("[Matrix · Ann] ") and cut.endswith("…")
    shown = cut[len("[Matrix · Ann] "):-1]
    assert long_question.startswith(shown) and 79 <= len(shown) <= 80


# --- opening the room on the web resumes its current conversation ----------------------------------


@pytest.fixture
def state_db():
    from phi_state import SessionDB

    handle = SessionDB()
    yield handle
    handle.close()


def _talk(db, session_id: str, at: float) -> None:
    db.append_message(session_id, role="user", content="q", timestamp=at)
    db.append_message(session_id, role="assistant", content="a", timestamp=at + 1)


def _dashboard_chat(db, room_id: str) -> str:
    """What opening the room resumed before the pointer existed: a dashboard chat in its directory."""
    db.create_session("local-web-1", source="local", chat_id="local-web-1", cwd=wm.get_room(room_id)["path"])
    _talk(db, "local-web-1", time.time() - 60)
    return "local-web-1"


def test_opening_a_room_resumes_its_current_chat_conversation(room, state_db):
    from phi_cli.web_routers.workspace import latest_room_session

    web = _dashboard_chat(state_db, room)
    assert latest_room_session(room, None) == web
    state_db.create_session("mx-1", source="matrix", chat_id=MATRIX_CHAT, chat_type="group")
    _talk(state_db, "mx-1", time.time() - 600)

    wm.set_current_conversation(room, "mx-1")
    assert latest_room_session(room, None) == "mx-1"


@pytest.mark.parametrize("background", ["oneshot", "cron", "tool", "kanban"])
def test_a_pointer_to_a_background_run_falls_back_to_the_rooms_latest_chat(room, state_db, background):
    from phi_cli.web_routers.workspace import latest_room_session

    web = _dashboard_chat(state_db, room)
    state_db.create_session("bg-1", source=background, cwd=wm.get_room(room)["path"])
    _talk(state_db, "bg-1", time.time() - 10)

    wm.set_current_conversation(room, "bg-1")
    assert latest_room_session(room, None) == web


def test_a_pointer_to_a_deleted_session_falls_back_to_the_rooms_latest_chat(room, state_db):
    from phi_cli.web_routers.workspace import latest_room_session

    web = _dashboard_chat(state_db, room)
    wm.set_current_conversation(room, "20260101_000000_deadbeef")
    assert latest_room_session(room, None) == web


# --- the pointer is stored with its room --------------------------------------------------------


def _stored_pointers(room_id: str) -> list[tuple]:
    with closing(sqlite3.connect(wm.map_db_path())) as conn:
        return conn.execute(
            "SELECT session_id, updated_at FROM room_conversations WHERE room_id = ?", (room_id,)).fetchall()


def test_the_pointer_persists_moves_in_place_and_goes_with_its_room():
    room_id = wm.create_room("Solo")["room_id"]
    assert wm.current_conversation(room_id) is None
    before = time.time()
    wm.set_current_conversation(room_id, "s-1")
    first = wm.current_conversation_since(room_id)
    assert before <= first <= time.time()
    assert [row[0] for row in _stored_pointers(room_id)] == ["s-1"]  # a fresh connection sees it

    _after(first)
    wm.set_current_conversation(room_id, "s-2")
    assert wm.current_conversation(room_id) == "s-2"
    assert wm.current_conversation_since(room_id) > first
    assert [row[0] for row in _stored_pointers(room_id)] == ["s-2"]  # one pointer per room

    with closing(sqlite3.connect(wm.map_db_path())) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM rooms WHERE room_id = ?", (room_id,))
        conn.commit()
    assert wm.current_conversation(room_id) is None
    assert wm.current_conversation_since(room_id) is None
    assert _stored_pointers(room_id) == []


def test_a_map_from_before_the_pointer_gains_it_in_place(tmp_path, monkeypatch):
    home = tmp_path / "old_home"
    home.mkdir()
    with closing(sqlite3.connect(home / "workspace_map.db")) as conn:
        conn.executescript(wm.SCHEMA_SQL)
        conn.execute("DROP TABLE IF EXISTS room_conversations")
        conn.commit()
    monkeypatch.setenv("PHI_HOME", str(home))

    room_id = wm.create_room("Old")["room_id"]
    wm.set_current_conversation(room_id, "s-1")
    assert wm.current_conversation(room_id) == "s-1"

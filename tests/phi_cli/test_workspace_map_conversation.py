"""A workspace room's current conversation: one pointer per room in the workspace map, kept with the
room, and what opening the room on the web resumes while it names a real chat with messages.
"""

import sqlite3
import time
from contextlib import closing

import pytest

from phi_cli import workspace_map as wm
from phi_cli.web_routers.workspace import latest_room_session
from tests.waiting import wait_until


@pytest.fixture
def room():
    return wm.create_room("Shared")["room_id"]


@pytest.fixture
def db():
    from phi_state import SessionDB
    handle = SessionDB()
    yield handle
    handle.close()


def _stored(room_id):
    with closing(sqlite3.connect(wm.map_db_path())) as conn:
        return conn.execute("SELECT session_id FROM room_conversations WHERE room_id = ?", (room_id,)).fetchall()


def _talk(db, sid, at):
    db.append_message(sid, role="user", content="q", timestamp=at)
    db.append_message(sid, role="assistant", content="a", timestamp=at + 1)


def test_the_pointer_is_set_moved_in_place_and_kept_per_room(room):
    other = wm.create_room("Other")["room_id"]
    assert wm.current_conversation(room) is None and wm.current_conversation_since(room) is None

    before = time.time()
    wm.set_current_conversation(room, "s-1")
    since = wm.current_conversation_since(room)
    assert wm.current_conversation(room) == "s-1" and before <= since <= time.time()
    wait_until(lambda: time.time() > since, what="the clock to pass the first pointer")
    wm.set_current_conversation(room, "s-2")

    assert wm.current_conversation(room) == "s-2"
    assert wm.current_conversation_since(room) > since
    assert _stored(room) == [("s-2",)]
    assert wm.current_conversation(other) is None


def test_an_unknown_room_gets_no_pointer():
    with pytest.raises(wm.RoomNotFound):
        wm.set_current_conversation("!missing:example.org", "s-1")
    assert wm.current_conversation("!missing:example.org") is None


def test_the_pointer_goes_with_its_room(room):
    wm.set_current_conversation(room, "s-1")
    with closing(sqlite3.connect(wm.map_db_path())) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM rooms WHERE room_id = ?", (room,))
        conn.commit()
    assert wm.current_conversation(room) is None and _stored(room) == []


def test_a_map_written_before_the_pointer_gains_it_in_place(room, monkeypatch):
    with closing(sqlite3.connect(wm.map_db_path())) as conn:
        conn.execute("DROP TABLE IF EXISTS room_conversations")
        conn.commit()
    monkeypatch.setattr(wm, "_INITIALIZED_PATHS", set())  # a new process opens the old map

    wm.set_current_conversation(room, "s-1")
    assert wm.current_conversation(room) == "s-1"
    assert wm.get_room(room)["room_id"] == room


def test_room_links_are_that_rooms_links_in_link_order(room):
    other = wm.create_room("Other")["room_id"]
    wm.link_channel(room, "telegram", "42")
    wm.link_channel(other, "telegram", "43")
    wm.link_channel(room, "matrix", "!room-a:example.org")

    assert wm.room_links(room) == [("telegram", "42"), ("matrix", "!room-a:example.org")]
    assert wm.room_links(other) == [("telegram", "43")]
    assert wm.room_links("!missing:example.org") == []


# --- opening the room on the web ---------------------------------------------------------------------


def _web_chat(db, room_id):
    """The dashboard chat the room resumed before it had a pointer."""
    db.create_session("local-web-1", source="local", chat_id="local-web-1", cwd=wm.get_room(room_id)["path"])
    _talk(db, "local-web-1", time.time() - 60)
    return "local-web-1"


def test_opening_the_room_resumes_its_current_conversation(room, db):
    web = _web_chat(db, room)
    db.create_session("mx-1", source="matrix", chat_id="!room-a:example.org", chat_type="group")
    _talk(db, "mx-1", time.time() - 600)  # older than the web chat: only the pointer picks it
    assert latest_room_session(room, None) == web

    wm.set_current_conversation(room, "mx-1")
    assert latest_room_session(room, None) == "mx-1"


@pytest.mark.parametrize("kind", ["deleted", "empty", "oneshot", "cron", "tool", "kanban"])
def test_a_pointer_that_is_no_conversation_falls_back_to_the_rooms_latest_chat(room, db, kind):
    web = _web_chat(db, room)
    if kind == "empty":
        db.create_session("p-1", source="telegram", chat_id="42", chat_type="dm")
    elif kind != "deleted":
        db.create_session("p-1", source=kind, cwd=wm.get_room(room)["path"])
        _talk(db, "p-1", time.time() - 10)

    wm.set_current_conversation(room, "p-1")
    assert latest_room_session(room, None) == web

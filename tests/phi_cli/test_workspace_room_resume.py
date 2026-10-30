"""Reopening a workspace room continues its latest conversation (``/api/pty?room_id=`` without ``resume``).

The room's sessions are found the way room activity finds them: the web chat's creation receipt names the
room, else a linked channel, else the room directory as the session's cwd. Empty sessions and subagent
runs are not a conversation to continue; another room's sessions never leak in.
"""

import asyncio
import json
import time

import pytest

from phi_cli import workspace_map as wm
from phi_cli.web_routers import chat_workspaces
from phi_cli.web_routers.workspace import latest_room_session
from phi_state_local import POLICY_PREFIX


def _policy(db, session_id: str, room_id: str) -> None:
    request = json.dumps({"room_id": room_id})
    db.set_meta(POLICY_PREFIX + session_id,
                json.dumps({"session_id": session_id, "policy": {"request_json": request}}))


def _talk(db, sid: str, at: float) -> None:
    db.append_message(sid, role="user", content="q", timestamp=at)
    db.append_message(sid, role="assistant", content="a", timestamp=at + 1)


@pytest.fixture
def rooms():
    return {name: wm.create_room(name) for name in ("Alpha", "Beta", "Linked", "Empty")}


@pytest.fixture
def db():
    from phi_state import SessionDB
    handle = SessionDB()
    yield handle
    handle.close()


def test_latest_session_of_the_room_wins(rooms, db):
    alpha, beta = rooms["Alpha"]["room_id"], rooms["Beta"]["room_id"]
    now = time.time()
    db.create_session("a-old", source="tui", cwd=rooms["Alpha"]["path"])
    _policy(db, "a-old", alpha)
    _talk(db, "a-old", now - 600)
    db.create_session("a-new", source="tui", cwd=rooms["Alpha"]["path"])
    _policy(db, "a-new", alpha)
    _talk(db, "a-new", now - 60)
    # Newer, but another room's: never Alpha's.
    db.create_session("b-1", source="tui", cwd=rooms["Beta"]["path"])
    _policy(db, "b-1", beta)
    _talk(db, "b-1", now - 10)
    # A subagent run inside Alpha and an empty chat opened later in Alpha are not conversations.
    db.create_session("a-child", source="subagent", cwd=rooms["Alpha"]["path"], parent_session_id="a-new")
    _talk(db, "a-child", now - 5)
    db.create_session("a-empty", source="tui", cwd=rooms["Alpha"]["path"])
    _policy(db, "a-empty", alpha)

    assert latest_room_session(alpha, None) == "a-new"
    assert latest_room_session(beta, None) == "b-1"


def test_only_dashboard_chats_are_resumed_and_an_empty_room_has_none(rooms, db):
    """A channel or CLI session in the room is not something the web terminal can reopen (the session
    authority answers ``not_found``), so it never becomes the room's chat; a dashboard chat bound by its
    cwd (``local-`` chat id, no receipt) does."""
    linked = rooms["Linked"]["room_id"]
    wm.link_channel(linked, "telegram", "-1001")
    now = time.time()
    db.create_session("tg", source="telegram", chat_id="-1001", chat_type="group")
    _talk(db, "tg", now - 30)
    db.create_session("cli", source="cli", cwd=rooms["Alpha"]["path"])
    _talk(db, "cli", now - 20)
    db.create_session("web-seed", source="web", cwd=rooms["Beta"]["path"])
    _talk(db, "web-seed", now - 15)
    db.create_session("local-abc", source="local", chat_id="local-abc", cwd=rooms["Beta"]["path"])
    _talk(db, "local-abc", now - 40)

    assert latest_room_session(linked, None) is None
    assert latest_room_session(rooms["Alpha"]["room_id"], None) is None
    assert latest_room_session(rooms["Beta"]["room_id"], None) == "local-abc"
    assert latest_room_session(rooms["Empty"]["room_id"], None) is None
    assert latest_room_session("!missing:example.org", None) is None


def test_the_pty_route_resumes_a_room_without_an_explicit_resume(rooms, db, monkeypatch):
    alpha = rooms["Alpha"]["room_id"]
    db.create_session("a-1", source="tui", cwd=rooms["Alpha"]["path"])
    _policy(db, "a-1", alpha)
    _talk(db, "a-1", time.time() - 30)

    async def run(params):
        return await chat_workspaces.resume_for_room(params, None)

    assert asyncio.run(run({"room_id": alpha})) == "a-1"
    assert asyncio.run(run({"room_id": rooms["Empty"]["room_id"]})) is None
    assert asyncio.run(run({})) is None

"""Archive, room activity and top-level Matrix spaces on ``/api/workspace/*`` (design §五, §七).

Archive hides a room from the tree and keeps its directory and links; a Matrix-linked room is archived in
the map only (the agent never leaves the Matrix room), and its next messaging turn works in the agent
directory. Activity counts running sessions and assistant replies newer than ``seen`` per room, cached
for 5 s. A top-level space is also created in Matrix when the mirror is on and a gateway answers.
"""

import json
import logging
import re
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from agent import room_binding as rb
from gateway import adapter_actions
from phi_cli import web_server
from phi_cli import workspace_map as wm
from phi_cli.web_routers import workspace as workspace_routes
from phi_constants import get_phi_home
from phi_state_local import POLICY_PREFIX

pytest.importorskip("starlette.testclient")
from starlette.testclient import TestClient

MX_ROOM = "!room:example.org"
MX_TOP = "!top:example.org"


@pytest.fixture(autouse=True)
def _multiplex_state_is_per_test():
    from agent import secret_scope
    from tui_gateway import launch_profile_policy

    was_active = secret_scope.is_multiplex_active()
    snapshot = launch_profile_policy._snapshot
    secret_scope.set_multiplex_active(False)
    launch_profile_policy._snapshot = None
    try:
        yield
    finally:
        secret_scope.set_multiplex_active(was_active)
        launch_profile_policy._snapshot = snapshot


@pytest.fixture(autouse=True)
def _fresh_activity_cache(monkeypatch):
    monkeypatch.setattr(workspace_routes, "_ACTIVITY_CACHE", {})
    yield
    rb.set_current_room(None)


@pytest.fixture
def client():
    previous = getattr(web_server.app.state, "auth_required", None)
    web_server.app.state.auth_required = False
    test_client = TestClient(web_server.app)
    test_client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    try:
        yield test_client
    finally:
        if previous is None:
            try:
                delattr(web_server.app.state, "auth_required")
            except AttributeError:
                pass
        else:
            web_server.app.state.auth_required = previous


@pytest.fixture
def gateway(monkeypatch):
    """Records each adapter action asked for; ``answer`` is what the gateway replies (None: no gateway)."""
    calls = []

    class Gateway:
        answer = None

        def __call__(self, platform, action, args, **_kw):
            calls.append((platform, action, dict(args), str(get_phi_home())))
            return self.answer(action, args) if callable(self.answer) else self.answer

    fake = Gateway()
    fake.calls = calls
    monkeypatch.setattr(adapter_actions, "call_adapter_action", fake)
    return fake


def _room_url(room_id: str, action: str = "") -> str:
    return "/api/workspace/rooms/" + quote(room_id, safe="") + (f"/{action}" if action else "")


# --- Archive ---------------------------------------------------------------------------------------


def test_archive_hides_rooms_from_the_tree_and_keeps_their_directories(client):
    loose = client.post("/api/workspace/rooms", json={"name": "Old notes"}).json()["room"]
    space = client.post("/api/workspace/spaces", json={"name": "Projects"}).json()["space"]
    filed = client.post("/api/workspace/rooms", json={"name": "Board", "parent_space": space["room_id"]}).json()["room"]

    for room in (loose, filed):
        resp = client.post(_room_url(room["room_id"], "archive"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["room"]["archived"] is True

    tree = client.get("/api/workspace/tree").json()
    assert loose["room_id"] not in tree["home"]
    assert tree["spaces"][0]["rooms"] == []
    assert loose["room_id"] not in [r["room_id"] for r in client.get("/api/workspace/rooms").json()["rooms"]]
    assert Path(loose["path"]).is_dir() and Path(filed["path"]).is_dir()
    assert wm.get_room(filed["room_id"])["parents"] == [space["room_id"]]

    restored = client.post(_room_url(filed["room_id"], "unarchive"))
    assert restored.status_code == 200, restored.text
    assert restored.json()["room"]["archived"] is False
    assert client.get("/api/workspace/tree").json()["spaces"][0]["rooms"] == [filed["room_id"]]

    for action in ("archive", "unarchive", "seen"):
        assert client.post(_room_url("!local_nope", action)).status_code == 404


def test_archiving_a_linked_room_is_map_only_and_its_turns_work_in_the_agent_dir(client, gateway, caplog):
    room = wm.create_room("General", origin="matrix")
    wm.link_channel(room["room_id"], "matrix", MX_ROOM)

    resp = client.post(_room_url(room["room_id"], "archive"))
    assert resp.status_code == 200, resp.text
    # Never leaves or forgets the Matrix room: no gateway call, the link stays.
    assert gateway.calls == []
    assert wm.channel_links("matrix") == {MX_ROOM: room["room_id"]}
    assert Path(room["path"]).is_dir()

    with caplog.at_level(logging.WARNING, logger="agent.room_binding"):
        binding = rb.bind_for_channel("matrix", MX_ROOM, "group", "General")
    assert binding.source == "agent"
    assert binding.dir == Path(wm.ensure_agent_room()["path"])
    assert any("archived" in r.getMessage() for r in caplog.records
               if r.name == "agent.room_binding" and r.levelno == logging.WARNING)

    assert client.post(_room_url(room["room_id"], "unarchive")).status_code == 200
    again = rb.bind_for_channel("matrix", MX_ROOM, "group", "General")
    assert again.source == "link" and again.room_id == room["room_id"] and again.dir == Path(room["path"])


# --- Activity --------------------------------------------------------------------------------------


def _policy(db, session_id: str, room_id: str) -> None:
    """The local creation receipt a web chat opened in ``room_id`` leaves behind."""
    request = json.dumps({"room_id": room_id})
    db.set_meta(POLICY_PREFIX + session_id,
                json.dumps({"session_id": session_id, "policy": {"request_json": request}}))


def _session_db():
    from phi_state import SessionDB
    return SessionDB()


def _activity(client) -> dict:
    resp = client.get("/api/workspace/activity")
    assert resp.status_code == 200, resp.text
    return resp.json()["rooms"]


def test_activity_counts_running_sessions_and_unread_replies_per_room(client):
    rooms = {name: client.post("/api/workspace/rooms", json={"name": name}).json()["room"]
             for name in ("Web", "Shell", "TG", "Cwd", "Quiet")}
    wm.link_channel(rooms["TG"]["room_id"], "telegram", "-1001")
    now = time.time()
    db = _session_db()
    try:
        # A web chat opened in Web while its cwd is Shell's directory: the room it named wins.
        db.create_session("web1", source="tui", cwd=rooms["Shell"]["path"])
        _policy(db, "web1", rooms["Web"]["room_id"])
        db.append_message("web1", role="user", content="q", timestamp=now - 61)
        db.append_message("web1", role="assistant", content="a1", timestamp=now - 60)
        db.append_message("web1", role="assistant", content="a2", timestamp=now - 59)
        # A linked Telegram group.
        db.create_session("tg1", source="telegram", chat_id="-1001", chat_type="group")
        db.append_message("tg1", role="user", content="hello", timestamp=now - 30)
        db.append_message("tg1", role="assistant", content="hi", timestamp=now - 20)
        # An ended CLI session that worked in Cwd's directory: not running, its reply still unread.
        db.create_session("old1", source="cli", cwd=rooms["Cwd"]["path"])
        db.append_message("old1", role="assistant", content="done", timestamp=now - 7200)
        db.end_session("old1", "user_exit")
    finally:
        db.close()

    activity = _activity(client)
    ids = {name: room["room_id"] for name, room in rooms.items()}
    assert activity[ids["Web"]] == {"running": 1, "unread": 2}
    assert activity[ids["Shell"]] == {"running": 0, "unread": 0}
    assert activity[ids["TG"]] == {"running": 1, "unread": 1}
    assert activity[ids["Cwd"]] == {"running": 0, "unread": 1}
    assert activity[ids["Quiet"]] == {"running": 0, "unread": 0}


def test_activity_without_a_session_store_is_all_zero(client):
    room = client.post("/api/workspace/rooms", json={"name": "Quiet"}).json()["room"]
    assert not (get_phi_home() / "state.db").exists()
    assert _activity(client)[room["room_id"]] == {"running": 0, "unread": 0}


def test_seen_resets_unread_and_activity_is_cached_for_five_seconds(client, monkeypatch):
    assert workspace_routes._ACTIVITY_TTL == 5.0
    room = client.post("/api/workspace/rooms", json={"name": "Web"}).json()["room"]
    db = _session_db()
    try:
        db.create_session("web1", source="tui")
        _policy(db, "web1", room["room_id"])
        db.append_message("web1", role="assistant", content="a1", timestamp=time.time() - 60)
    finally:
        db.close()
    assert _activity(client)[room["room_id"]]["unread"] == 1

    seen = client.post(_room_url(room["room_id"], "seen"))
    assert seen.status_code == 200, seen.text
    assert seen.json()["room"]["last_seen"] is not None
    assert _activity(client)[room["room_id"]]["unread"] == 0  # seen drops the cached answer

    db = _session_db()
    try:
        db.append_message("web1", role="assistant", content="a2", timestamp=time.time() + 1)
    finally:
        db.close()
    assert _activity(client)[room["room_id"]]["unread"] == 0  # still the cached answer
    monkeypatch.setattr(workspace_routes, "_ACTIVITY_TTL", 0.0)
    assert _activity(client)[room["room_id"]]["unread"] == 1


# --- Top-level spaces ------------------------------------------------------------------------------

_CREATE_TOP = ("matrix", "space_mirror.create_space", {"name": "Team", "parent_space": None})


def test_top_level_space_is_created_in_matrix_when_the_mirror_is_on(client, gateway):
    gateway.answer = lambda _action, args: {"space": {"room_id": MX_TOP, "name": args["name"], "type": "space"}}

    resp = client.post("/api/workspace/spaces", json={"name": "Team"})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"space": {"room_id": MX_TOP, "name": "Team", "type": "space"}, "matrix": "created"}
    assert [c[:3] for c in gateway.calls] == [_CREATE_TOP]
    assert gateway.calls[0][3] == str(get_phi_home())
    # The mirror records the space once Matrix has it; the route adds no local row of its own.
    assert client.get("/api/workspace/tree").json()["spaces"] == []


def test_top_level_space_without_a_running_gateway_is_map_only(client, gateway):
    resp = client.post("/api/workspace/spaces", json={"name": "Team"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matrix"] == "skipped: gateway not running"
    assert re.fullmatch(r"[0-9a-f]{16}", body["space"]["room_id"])  # a system id, like any new space
    assert [c[:3] for c in gateway.calls] == [_CREATE_TOP]
    assert [s["room_id"] for s in client.get("/api/workspace/tree").json()["spaces"]] == [body["space"]["room_id"]]


def test_top_level_space_when_matrix_is_not_connected_is_map_only(client, gateway):
    gateway.answer = {"error": "Matrix space mirror is off or not connected.", "status": 503}
    resp = client.post("/api/workspace/spaces", json={"name": "Team"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["matrix"] == "skipped: Matrix space mirror is off or not connected."
    assert len(client.get("/api/workspace/tree").json()["spaces"]) == 1


def test_matrix_refusing_a_top_level_space_is_the_answer_and_the_map_is_unchanged(client, gateway):
    gateway.answer = {"error": "Matrix refused: cannot create rooms", "status": 409}
    resp = client.post("/api/workspace/spaces", json={"name": "Team"})
    assert resp.status_code == 409
    assert resp.json()["detail"] == "Matrix refused: cannot create rooms"
    assert client.get("/api/workspace/tree").json()["spaces"] == []


def test_top_level_space_with_the_mirror_off_does_not_ask(client, gateway):
    (get_phi_home() / "config.yaml").write_text("matrix:\n  space_mirror: false\n", encoding="utf-8")
    resp = client.post("/api/workspace/spaces", json={"name": "Team"})
    assert resp.status_code == 200, resp.text
    assert "matrix" not in resp.json()
    assert gateway.calls == []
    assert len(client.get("/api/workspace/tree").json()["spaces"]) == 1


def test_mark_all_seen_clears_every_room_and_new_replies_count_again(client):
    rooms = {name: client.post("/api/workspace/rooms", json={"name": name}).json()["room"] for name in ("A", "B")}
    now = time.time()
    db = _session_db()
    try:
        for name, room in rooms.items():
            sid = f"s-{name}"
            db.create_session(sid, source="cli", cwd=room["path"])
            db.append_message(sid, role="assistant", content="hi", timestamp=now - 30)
    finally:
        db.close()
    ids = {name: room["room_id"] for name, room in rooms.items()}
    assert {k: _activity(client)[v]["unread"] for k, v in ids.items()} == {"A": 1, "B": 1}

    resp = client.post("/api/workspace/rooms/seen-all")
    assert resp.status_code == 200, resp.text
    assert resp.json()["marked"] >= 2
    assert {k: _activity(client)[v]["unread"] for k, v in ids.items()} == {"A": 0, "B": 0}

    db = _session_db()
    try:
        db.append_message("s-B", role="assistant", content="later", timestamp=time.time() + 5)
    finally:
        db.close()
    workspace_routes._ACTIVITY_CACHE.clear()
    assert {k: _activity(client)[v]["unread"] for k, v in ids.items()} == {"A": 0, "B": 1}

"""``/api/workspace/rooms/{room_id}/ledger``: the room ledger read by the dashboard (design §九).

Read-only and behind the session token. A room that never wrote a ledger answers with no entries and
gets no file; an unknown room is 404. Without ``q`` the ledger reads as a timeline, newest first.
"""

from pathlib import Path
from urllib.parse import quote

import pytest

from agent.room_ledger import Ledger
from phi_cli import web_server
from phi_cli import workspace_map as wm

pytest.importorskip("starlette.testclient")
from starlette.testclient import TestClient


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


def _url(room_id: str, suffix: str = "") -> str:
    return "/api/workspace/rooms/" + quote(room_id, safe="") + "/ledger" + suffix


def _seed(room_dir: Path) -> dict:
    with Ledger(room_dir) as led:
        ids = {
            "decision": led.add("Ship the login fix behind a flag", "decision", keywords=["login", "flag"], ts=100),
            "fact": led.add("Staging uses SQLite", "fact", keywords=["staging", "sqlite"], ts=200),
            "old": led.add("Deploy on Friday", "decision", keywords=["deploy", "friday"], ts=300),
        }
        ids["new"] = led.supersede(ids["old"], "Deploy on Monday", keywords=["deploy", "monday"], ts=400)
        ids["todo"] = led.add("Write the release note", "todo", keywords=["release", "note"], ts=500)
        led.mark_done(ids["todo"])
    return ids


def test_routes_require_the_session_token(client):
    room = wm.create_room("guarded")
    anonymous = TestClient(web_server.app)
    assert anonymous.get(_url(room["room_id"])).status_code == 401
    assert anonymous.get(_url(room["room_id"], "/1")).status_code == 401


def test_unknown_room_is_404_and_a_space_is_400(client):
    assert client.get(_url("!local_nope")).status_code == 404
    assert client.get(_url("!local_nope", "/1")).status_code == 404
    space = wm.create_space("Projects")
    assert client.get(_url(space["room_id"])).status_code == 400


def test_a_room_without_a_ledger_answers_empty_and_gets_no_file(client):
    room = wm.create_room("quiet")
    room_dir = Path(room["path"])
    for params in ({}, {"q": "anything"}, {"kind": "decision", "include_superseded": "true"}):
        resp = client.get(_url(room["room_id"]), params=params)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"entries": []}
    assert client.get(_url(room["room_id"], "/1")).status_code == 404
    assert not (room_dir / ".phi").exists()


def test_timeline_search_and_filters(client):
    room = wm.create_room("busy")
    ids = _seed(Path(room["path"]))

    timeline = client.get(_url(room["room_id"])).json()["entries"]
    assert [e["id"] for e in timeline] == [ids["todo"], ids["new"], ids["fact"], ids["decision"]]
    assert timeline[0]["status"] == "done"

    everything = client.get(_url(room["room_id"]), params={"include_superseded": "true"}).json()["entries"]
    assert [e["id"] for e in everything] == [ids["todo"], ids["new"], ids["old"], ids["fact"], ids["decision"]]
    assert {e["id"]: e["superseded_by"] for e in everything}[ids["old"]] == ids["new"]
    assert set(everything[0]) >= {"id", "ts", "kind", "text", "status", "refs", "superseded_by"}

    decisions = client.get(_url(room["room_id"]), params={"kind": "decision"}).json()["entries"]
    assert [e["id"] for e in decisions] == [ids["new"], ids["decision"]]
    both = client.get(_url(room["room_id"]), params={"kind": "decision,fact", "limit": 2}).json()["entries"]
    assert [e["id"] for e in both] == [ids["new"], ids["fact"]]

    hits = client.get(_url(room["room_id"]), params={"q": "deploy"}).json()["entries"]
    assert [e["id"] for e in hits] == [ids["new"]]
    hits = client.get(_url(room["room_id"]), params={"q": "deploy", "include_superseded": "true"}).json()["entries"]
    assert {e["id"]: e["superseded_by"] for e in hits} == {ids["new"]: None, ids["old"]: ids["new"]}
    assert client.get(_url(room["room_id"]), params={"q": "deploy", "kind": "fact"}).json() == {"entries": []}

    assert client.get(_url(room["room_id"]), params={"kind": "gossip"}).status_code == 400
    assert client.get(_url(room["room_id"]), params={"limit": 0}).status_code in (400, 422)


def test_entry_shows_what_superseded_it(client):
    room = wm.create_room("history")
    ids = _seed(Path(room["path"]))
    old = client.get(_url(room["room_id"], f"/{ids['old']}"))
    assert old.status_code == 200, old.text
    entry = old.json()["entry"]
    assert entry["status"] == "superseded" and entry["superseded_by"] == ids["new"]
    assert entry["text"] == "Deploy on Friday" and entry["keywords"] == "deploy friday"
    new = client.get(_url(room["room_id"], f"/{ids['new']}")).json()["entry"]
    assert new["supersedes"] == ids["old"] and new["superseded_by"] is None
    assert client.get(_url(room["room_id"], "/9999")).status_code == 404

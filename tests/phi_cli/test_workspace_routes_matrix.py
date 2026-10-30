"""``/api/workspace/*`` writes on Matrix-linked rooms go through the gateway's space mirror (design §七).

The dashboard has no Matrix client, so create-space under a linked space, rename and move of a linked
room ask the running gateway (``call_adapter_action``); its refusal is the HTTP answer and the map stays
as it was. A new top-level space asks too (map only when no gateway runs). Unlinked rooms, or
``matrix.space_mirror: false``, edit the map alone without asking.
"""

from urllib.parse import quote

import pytest

from gateway import adapter_actions
from phi_cli import web_server
from phi_cli import workspace_map as wm
from phi_constants import get_phi_home

pytest.importorskip("starlette.testclient")
from starlette.testclient import TestClient

MX_SPACE = "!space:example.org"
MX_ROOM = "!room:example.org"


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


@pytest.fixture
def gateway(monkeypatch):
    """Records each adapter action asked for; ``answer`` is what the gateway replies."""
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


def _room_url(room_id: str) -> str:
    return "/api/workspace/rooms/" + quote(room_id, safe="")


def _linked():
    space = wm.import_space("Team")
    wm.link_channel(space["room_id"], "matrix", MX_SPACE)
    room = wm.create_room("General", origin="matrix")
    wm.link_channel(room["room_id"], "matrix", MX_ROOM)
    return space, room


def test_linked_rename_move_and_create_space_use_the_mirror_answer(client, gateway):
    space, room = _linked()
    local = wm.create_space("Local")

    def answer(action, args):
        if action == "space_mirror.rename":
            return {"room": {**wm.get_room(args["room_id"]), "name": args["name"]}}
        if action == "space_mirror.move":
            return {"room": wm.get_room(args["room_id"])}
        return {"space": {"room_id": "!new:example.org", "name": args["name"], "type": "space"}}

    gateway.answer = answer
    renamed = client.patch(_room_url(room["room_id"]), json={"name": "Lobby"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["room"]["name"] == "Lobby"

    moved = client.post("/api/workspace/move", json={"room_id": local["room_id"], "from": None,
                                                      "to": space["room_id"]})
    assert moved.status_code == 200, moved.text

    created = client.post("/api/workspace/spaces", json={"name": "Sub", "parent_space": space["room_id"]})
    assert created.status_code == 200, created.text
    assert created.json()["space"]["room_id"] == "!new:example.org"

    home = str(get_phi_home())
    assert [c[:3] for c in gateway.calls] == [
        ("matrix", "space_mirror.rename", {"room_id": room["room_id"], "name": "Lobby"}),
        ("matrix", "space_mirror.move", {"room_id": local["room_id"], "from_space": None,
                                         "to_space": space["room_id"]}),
        ("matrix", "space_mirror.create_space", {"name": "Sub", "parent_space": space["room_id"]}),
    ]
    assert all(c[3] == home for c in gateway.calls)
    # The mirror owns the map change: the route did not rename or move on its own.
    assert wm.get_room(room["room_id"])["name"] == "General"
    assert [r["room_id"] for r in wm.list_rooms(space["room_id"])] == []


def test_matrix_refusal_is_the_answer_and_the_map_is_unchanged(client, gateway):
    space, room = _linked()
    wm.move(room["room_id"], None, space["room_id"])
    gateway.answer = {"error": "Matrix refused: needs power level 50 in Team", "status": 409}

    refused = client.patch(_room_url(room["room_id"]), json={"name": "Lobby"})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Matrix refused: needs power level 50 in Team"
    moved = client.post("/api/workspace/move", json={"room_id": room["room_id"], "from": space["room_id"],
                                                      "to": None})
    assert moved.status_code == 409
    assert wm.get_room(room["room_id"])["name"] == "General"
    assert [r["room_id"] for r in wm.list_rooms(space["room_id"])] == [room["room_id"]]


def test_no_running_gateway_is_503_and_the_map_is_unchanged(client, gateway):
    _space, room = _linked()
    gateway.answer = None

    refused = client.patch(_room_url(room["room_id"]), json={"name": "Lobby"})
    assert refused.status_code == 503
    assert "matrix.space_mirror: false" in refused.json()["detail"]
    assert wm.get_room(room["room_id"])["name"] == "General"


def test_unlinked_rooms_edit_the_map_without_asking(client, gateway):
    """Only a new top-level space asks Matrix; with no gateway running it is created in the map alone."""
    _linked()
    (get_phi_home() / "config.yaml").write_text("workspace:\n  max_space_depth: 3\n", encoding="utf-8")
    local = client.post("/api/workspace/rooms", json={"name": "Notes"}).json()["room"]
    top = client.post("/api/workspace/spaces", json={"name": "Projects"})
    assert top.status_code == 200, top.text
    assert top.json()["matrix"] == "skipped: gateway not running"
    projects = top.json()["space"]
    assert [c[:3] for c in gateway.calls] == [
        ("matrix", "space_mirror.create_space", {"name": "Projects", "parent_space": None})]
    gateway.calls.clear()

    assert client.patch(_room_url(local["room_id"]), json={"name": "Diary"}).json()["room"]["name"] == "Diary"
    moved = client.post("/api/workspace/move", json={"room_id": local["room_id"], "from": None,
                                                      "to": projects["room_id"]})
    assert moved.status_code == 200, moved.text
    sub = client.post("/api/workspace/spaces", json={"name": "Sub", "parent_space": projects["room_id"]})
    assert sub.status_code == 200, sub.text
    assert gateway.calls == []


def test_mirror_off_edits_linked_rooms_in_the_map_only(client, gateway):
    _space, room = _linked()
    (get_phi_home() / "config.yaml").write_text("matrix:\n  space_mirror: false\n", encoding="utf-8")

    renamed = client.patch(_room_url(room["room_id"]), json={"name": "Lobby"})
    assert renamed.status_code == 200, renamed.text
    assert wm.get_room(room["room_id"])["name"] == "Lobby"
    assert gateway.calls == []

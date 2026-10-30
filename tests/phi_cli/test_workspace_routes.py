"""``/api/workspace/*``: the dashboard face of the workspace map (design §五, Settings → Workspace).

Every route sits behind the session token, takes the usual ``?profile=`` scope, and maps bad input
to 400 and unknown ids to 404. Disk layout is fixed at creation: rename/move never touch it.
"""

from urllib.parse import quote

import pytest

import phi_yaml as yaml
from phi_cli import web_server
from phi_cli import workspace_map as wm
from phi_cli.workspace_root import workspace_root
from phi_constants import get_phi_home

pytest.importorskip("starlette.testclient")
from starlette.testclient import TestClient


@pytest.fixture(autouse=True)
def _multiplex_state_is_per_test():
    """A ``?profile=`` request flips one-way multi-profile hosting; contain it to one test."""
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


def _room_url(room_id: str) -> str:
    return "/api/workspace/rooms/" + quote(room_id, safe="")


def test_routes_require_the_session_token(client):
    anonymous = TestClient(web_server.app)
    assert anonymous.get("/api/workspace/tree").status_code == 401
    assert anonymous.post("/api/workspace/rooms", json={"name": "x"}).status_code == 401
    assert anonymous.put("/api/workspace/settings", json={"max_space_depth": 3}).status_code == 401
    assert not (get_phi_home() / "workspace_map.db").exists()


def test_create_list_rename_and_move_rooms(client):
    created = client.post("/api/workspace/rooms", json={"name": "Fix login bug"})
    assert created.status_code == 200, created.text
    room = created.json()["room"]
    assert room["rel_path"] == room["room_id"] and room["name"] == "Fix login bug"
    assert room["path"] == str(workspace_root() / room["room_id"])
    assert (workspace_root() / room["room_id"]).is_dir()

    space = client.post("/api/workspace/spaces", json={"name": "Projects"}).json()["space"]
    assert space["type"] == "space" and space["rel_path"] is None

    home = client.get("/api/workspace/rooms").json()["rooms"]
    assert home[0]["rel_path"] == "agent"
    assert room["room_id"] in [r["room_id"] for r in home]

    renamed = client.patch(_room_url(room["room_id"]), json={"name": "Login fix"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["room"]["name"] == "Login fix"
    assert renamed.json()["room"]["rel_path"] == room["room_id"]

    moved = client.post("/api/workspace/move",
                        json={"room_id": room["room_id"], "from": None, "to": space["room_id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["room"]["parents"] == [space["room_id"]]
    listed = client.get("/api/workspace/rooms", params={"space": space["room_id"]}).json()["rooms"]
    assert [r["room_id"] for r in listed] == [room["room_id"]]

    tree = client.get("/api/workspace/tree").json()
    assert tree["spaces"][0]["room_id"] == space["room_id"]
    assert tree["spaces"][0]["rooms"] == [room["room_id"]]
    assert room["room_id"] not in tree["home"]
    assert wm.resolve(room["room_id"]) == workspace_root() / room["room_id"]


def test_bad_input_is_400_and_unknown_ids_are_404(client):
    room = client.post("/api/workspace/rooms", json={"name": "r"}).json()["room"]
    space = client.post("/api/workspace/spaces", json={"name": "S"}).json()["space"]

    assert client.post("/api/workspace/rooms", json={"name": "   "}).status_code == 400
    assert client.post("/api/workspace/spaces", json={"name": ""}).status_code == 400
    assert client.post("/api/workspace/rooms",
                       json={"name": "x", "parent_space": "!local_nope"}).status_code == 404
    assert client.post("/api/workspace/rooms",
                       json={"name": "x", "parent_space": room["room_id"]}).status_code == 400
    # Default nesting limit 3 (space/sub-space/room): a sub-space, but no sub-sub-space.
    sub = client.post("/api/workspace/spaces", json={"name": "Sub", "parent_space": space["room_id"]})
    assert sub.status_code == 200, sub.text
    assert sub.json()["space"]["parents"] == [space["room_id"]]
    nested = client.post("/api/workspace/spaces",
                         json={"name": "Deeper", "parent_space": sub.json()["space"]["room_id"]})
    assert nested.status_code == 400 and "nesting" in nested.json()["detail"].lower()
    assert client.patch(_room_url("!local_nope"), json={"name": "y"}).status_code == 404
    assert client.patch(_room_url(room["room_id"]), json={"name": " "}).status_code == 400
    assert client.get("/api/workspace/rooms", params={"space": "!local_nope"}).status_code == 404
    assert client.post("/api/workspace/move",
                       json={"room_id": room["room_id"], "from": space["room_id"], "to": None}).status_code == 400
    assert client.post("/api/workspace/move",
                       json={"room_id": "!local_nope", "from": None, "to": space["room_id"]}).status_code == 404


def test_move_drags_a_space_between_parents_and_refuses_cycles_and_overflow(client):
    def make(name, parent=None):
        body = {"name": name, "parent_space": parent} if parent else {"name": name}
        resp = client.post("/api/workspace/spaces", json=body)
        assert resp.status_code == 200, resp.text
        return resp.json()["space"]["room_id"]

    def move(rid, src, dst):
        return client.post("/api/workspace/move", json={"room_id": rid, "from": src, "to": dst})

    a, b = make("A"), make("B")
    sub = make("Sub", a)
    resp = move(sub, a, b)
    assert resp.status_code == 200, resp.text
    assert resp.json()["room"]["parents"] == [b]
    tops = {s["room_id"]: s for s in client.get("/api/workspace/tree").json()["spaces"]}
    assert tops[a]["children"] == [] and [c["room_id"] for c in tops[b]["children"]] == [sub]

    assert move(sub, b, None).json()["room"]["parents"] == []
    assert sub in [s["room_id"] for s in client.get("/api/workspace/tree").json()["spaces"]]

    inner = make("Inner", a)
    cycle = move(a, None, inner)
    assert cycle.status_code == 400 and "inside itself" in cycle.json()["detail"]
    # A holds a sub-space, so it cannot go under B.
    deep = move(a, None, b)
    assert deep.status_code == 400 and "nesting" in deep.json()["detail"].lower()


def test_check_reports_issues(client):
    room = client.post("/api/workspace/rooms", json={"name": "vanishing"}).json()["room"]
    (workspace_root() / room["room_id"]).rmdir()
    (workspace_root() / "stray").mkdir()
    report = client.get("/api/workspace/check").json()
    kinds = sorted((i["kind"], i.get("room_id") or i.get("path")) for i in report["issues"])
    assert kinds == [("missing_dir", room["room_id"]), ("unmapped_dir", "stray")]


def test_settings_read_validate_and_store(client):
    got = client.get("/api/workspace/settings").json()
    assert got == {"root": str(workspace_root()), "configured_root": "",
                   "max_space_depth": 3, "default_fence": "approve"}

    for bad in ({"max_space_depth": 1}, {"max_space_depth": 99}, {"default_fence": "loose"},
                {"root": "/somewhere/else"}):
        resp = client.put("/api/workspace/settings", json=bad)
        assert resp.status_code == 400, (bad, resp.text)
    # Re-sending the current root is not a change.
    ok = client.put("/api/workspace/settings",
                    json={"root": str(workspace_root()), "max_space_depth": 4, "default_fence": "strict"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["max_space_depth"] == 4 and ok.json()["default_fence"] == "strict"

    saved = yaml.safe_load((get_phi_home() / "config.yaml").read_text(encoding="utf-8"))
    assert saved["workspace"]["max_space_depth"] == 4
    assert saved["workspace"]["default_fence"] == "strict"
    assert "root" not in saved["workspace"]

    space = client.post("/api/workspace/spaces", json={"name": "Projects"}).json()["space"]
    sub = client.post("/api/workspace/spaces", json={"name": "Hardware", "parent_space": space["room_id"]})
    assert sub.status_code == 200, sub.text
    # Limit 4: one level more than the default.
    deeper = client.post("/api/workspace/spaces",
                         json={"name": "Boards", "parent_space": sub.json()["space"]["room_id"]})
    assert deeper.status_code == 200, deeper.text
    assert client.post("/api/workspace/rooms", json={"name": "x"}).json()["room"]["fence_mode"] == "strict"


def test_profile_query_scopes_the_map_to_that_profile(client, monkeypatch):
    from phi_cli import profiles

    launch_home = get_phi_home()
    profiles_root = launch_home / "profiles"
    beta = profiles_root / "worker_beta"
    beta.mkdir(parents=True)
    (beta / "config.yaml").write_text("model: ''\n", encoding="utf-8")
    (beta / ".env").write_text("BETA=1\n", encoding="utf-8")
    monkeypatch.setattr(profiles, "_get_default_phi_home", lambda: launch_home)
    monkeypatch.setattr(profiles, "_get_profiles_root", lambda: profiles_root)

    resp = client.post("/api/workspace/rooms", params={"profile": "worker_beta"}, json={"name": "beta room"})
    assert resp.status_code == 200, resp.text
    rid = resp.json()["room"]["room_id"]
    assert resp.json()["room"]["path"] == str(beta / "workspace" / rid)
    assert (beta / "workspace_map.db").exists()
    assert not (launch_home / "workspace_map.db").exists()
    assert not (launch_home / "workspace" / rid).exists()

    assert client.get("/api/workspace/tree", params={"profile": "no_such_profile"}).status_code == 404

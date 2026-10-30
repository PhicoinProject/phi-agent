"""Deleting a space (admin 2026-10-26): rooms and sub-spaces move up one level, nothing on disk changes,
and a Matrix-mirrored space is refused (the mirror would re-import it)."""
from urllib.parse import quote

import pytest

from phi_cli import workspace_map as wm
from phi_cli import web_server

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


def _url(space_id: str) -> str:
    return "/api/workspace/spaces/" + quote(space_id, safe="")


def _ids(nodes):
    return [n["room_id"] for n in nodes]


def test_top_level_space_delete_sends_rooms_home_and_sub_spaces_to_the_top():
    top = wm.create_space("Projects")["room_id"]
    sub = wm.create_space("Hardware", parent_space=top)["room_id"]
    room = wm.create_room("Notes", parent_space=top)
    path = wm.resolve(room["room_id"])
    assert path.is_dir()

    out = wm.delete_space(top)

    assert set(out["moved_up"]) == {sub, room["room_id"]} and out["into"] == []
    tree = wm.list_tree()
    assert top not in _ids(tree["spaces"]) and sub in _ids(tree["spaces"])
    assert room["room_id"] in tree["home"]
    assert path.is_dir() and wm.resolve(room["room_id"]) == path
    with pytest.raises(wm.RoomNotFound):
        wm.get_room(top)


def test_nested_space_delete_moves_its_rooms_into_the_parent_space():
    top = wm.create_space("Projects")["room_id"]
    sub = wm.create_space("Hardware", parent_space=top)["room_id"]
    room = wm.create_room("Board", parent_space=sub)["room_id"]

    wm.delete_space(sub)

    assert wm.get_room(room)["parents"] == [top]
    assert room in [r["room_id"] for r in wm.list_rooms(top)]
    assert wm.list_tree()["spaces"][0]["children"] == []


def test_only_spaces_can_be_deleted():
    room = wm.create_room("Notes")["room_id"]
    with pytest.raises(wm.WorkspaceMapError):
        wm.delete_space(room)
    assert wm.get_room(room)["room_id"] == room


def test_route_deletes_a_local_space_and_refuses_a_matrix_mirrored_one(client, monkeypatch):
    local = wm.create_space("Local")["room_id"]
    r = client.delete(_url(local))
    assert r.status_code == 200 and r.json()["deleted"] == local

    mirrored = wm.import_space("From Matrix")["room_id"]
    wm.link_channel(mirrored, "matrix", "!space:example.org")
    monkeypatch.setattr(wm, "matrix_mirror_enabled", lambda: True)
    r = client.delete(_url(mirrored))
    assert r.status_code == 400 and "Matrix" in r.json()["detail"]
    assert wm.get_room(mirrored)["room_id"] == mirrored

    assert client.delete(_url("!missing")).status_code == 404
    assert TestClient(web_server.app).delete(_url(local)).status_code == 401

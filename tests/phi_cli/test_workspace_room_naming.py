"""New chat and room names (design §B / §五), and each room's rules file.

``POST /api/workspace/rooms/new-chat`` hands the web a room to chat in with one click: a fresh
"New chat" room (system id, folder ``<root>/<id>``), or the newest one in that space that nothing has
happened in yet. The chat's first message names the room at once (``derive_room_name``: its first
clause, at most six words, or 16 characters with CJK); the model's session title then replaces that
name. A user rename is final. The room's ``AGENTS.md`` is its rules, edited through
``/api/workspace/rooms/{id}/rules``.
"""

import re
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

from agent import room_binding as rb
from agent.runtime_cwd import clear_session_cwd, set_session_cwd
from agent.title_generator import derive_room_name
from phi_cli import web_server
from phi_cli import workspace_map as wm
from phi_cli.workspace_root import workspace_root
from phi_constants import get_phi_home

pytest.importorskip("starlette.testclient")
from starlette.testclient import TestClient

HEX_ID = re.compile(r"[0-9a-f]{16}")
NEW_CHAT = "/api/workspace/rooms/new-chat"


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


def _rules_url(room_id: str) -> str:
    return "/api/workspace/rooms/" + quote(room_id, safe="") + "/rules"


def _new_chat(client, **body) -> dict:
    resp = client.post(NEW_CHAT, json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["room"]


def _room_dirs() -> set[str]:
    return {p.name for p in workspace_root().iterdir() if p.is_dir() and p.name != "agent"}


def _turn(text: str, callback=None, room_id=None):
    """One turn's naming hook, bound to ``room_id`` like a web session's turn."""
    with rb.room_scope(room_id):
        return rb.name_room_for_turn(text, callback)


def _turn_in_dir(text: str, path, callback=None):
    """A turn with no room bound (a web terminal chat) whose working directory is ``path``."""
    set_session_cwd(str(path))
    try:
        return rb.name_room_for_turn(text, callback)
    finally:
        clear_session_cwd()


@pytest.mark.parametrize("text, expected", [
    ("Why does nginx return 502? It started after the deploy.", "Why does nginx return 502"),
    ("Please help me migrate the billing service to the new cluster tonight", "Please help me migrate the billing"),
    ("Fix the bug in app.py, then rerun the tests", "Fix the bug in app.py"),
    ("  multiple   spaces\nsecond line  ", "multiple spaces"),
    ("帮我修复登录页面的问题，然后部署到测试环境", "帮我修复登录页面的问题"),
    ("请分析一下这个季度所有区域的销售数据并生成一份完整报告", "请分析一下这个季度所有区域的销售"),
    ("用 Python 写一个爬虫抓取新闻网站", "用 Python 写一个爬虫抓取"),
    ("", None),
    ("   \n  ", None),
])
def test_derive_room_name_takes_the_first_clause_in_the_same_language(text, expected):
    assert derive_room_name(text) == expected


def test_new_chat_creates_a_default_room_and_reuses_it_while_untouched(client):
    first = _new_chat(client)
    assert HEX_ID.fullmatch(first["room_id"]) and first["rel_path"] == first["room_id"]
    assert first["name"] == "New chat" and first["name_source"] == "default"
    assert first["origin"] == "web" and first["type"] == "room" and first["parents"] == []
    assert Path(first["path"]) == workspace_root() / first["room_id"] and Path(first["path"]).is_dir()

    assert _new_chat(client)["room_id"] == first["room_id"]
    assert _new_chat(client, parent_space=None)["room_id"] == first["room_id"]
    assert _room_dirs() == {first["room_id"]}


def test_new_chat_is_not_reused_once_anything_happened_in_it(client):
    ran = _new_chat(client)["room_id"]
    (wm.resolve(ran) / "notes.md").write_text("x", encoding="utf-8")  # the chat has run
    named = _new_chat(client)["room_id"]
    assert named != ran
    wm.auto_name(named, "Fix login bug")  # its first message named it
    renamed = _new_chat(client)["room_id"]
    assert renamed not in {ran, named}
    wm.rename(renamed, "New chat")  # the user typed a name, even this one
    archived = _new_chat(client)["room_id"]
    assert archived not in {ran, named, renamed}
    wm.archive(archived)
    fresh = _new_chat(client)["room_id"]
    assert fresh not in {ran, named, renamed, archived}

    # Rooms made any other way are never handed out, even when they look the same.
    client.post("/api/workspace/rooms", json={"name": "New chat"})
    wm.create_room(origin="telegram")
    assert _new_chat(client)["room_id"] == fresh


def test_new_chat_reuses_the_newest_untouched_room(client):
    older = wm.create_room(origin="web")["room_id"]
    newer = wm.create_room(origin="web")["room_id"]
    assert _new_chat(client)["room_id"] == newer
    wm.auto_name(newer, "Taken")
    assert _new_chat(client)["room_id"] == older


def test_new_chat_in_a_space_reuses_only_that_space(client):
    space = client.post("/api/workspace/spaces", json={"name": "Projects"}).json()["space"]["room_id"]
    home = _new_chat(client)["room_id"]
    filed = _new_chat(client, parent_space=space)
    assert filed["room_id"] != home and filed["parents"] == [space]
    assert _new_chat(client, parent_space=space)["room_id"] == filed["room_id"]
    assert _new_chat(client)["room_id"] == home


def test_new_chat_refuses_an_unknown_or_non_space_parent(client):
    room = _new_chat(client)["room_id"]
    assert client.post(NEW_CHAT, json={"parent_space": "!local_nope"}).status_code == 404
    assert client.post(NEW_CHAT, json={"parent_space": room}).status_code == 400
    assert _room_dirs() == {room}
    assert TestClient(web_server.app).post(NEW_CHAT, json={}).status_code == 401
    # The old first-message route is gone.
    assert client.post("/api/workspace/rooms/from-first-message", json={"text": "hi"}).status_code in (404, 405)


def test_first_message_names_the_room_at_once_and_the_model_title_replaces_it():
    rid = wm.create_room(origin="web")["room_id"]
    seen = []

    def on_title(title, source):
        seen.append((title, source, wm.get_room(rid)["name"]))

    callback = _turn("Fix login bug. The session cookie expires too early.", on_title, rid)
    room = wm.get_room(rid)
    assert room["name"] == "Fix login bug" and room["name_source"] == "auto"
    callback("Fix login bug. The session cookie", "derived")  # the session's own instant title
    assert wm.get_room(rid)["name"] == "Fix login bug"
    callback("Login cookie expiry", "llm")
    # The room is renamed before the web hears of the title, so its refresh sees the new name.
    assert seen == [("Fix login bug. The session cookie", "derived", "Fix login bug"),
                    ("Login cookie expiry", "llm", "Login cookie expiry")]
    room = wm.get_room(rid)
    assert room["name_source"] == "auto" and room["rel_path"] == rid
    assert _room_dirs() == {rid}

    # Later chats in the room leave its name alone.
    later = _turn("Write the release notes", None, rid)
    if later is not None:
        later("Release notes draft", "llm")
    assert wm.get_room(rid)["name"] == "Login cookie expiry"


def test_a_user_rename_is_never_overwritten_by_the_model_title():
    rid = wm.create_room(origin="web")["room_id"]
    callback = _turn("Fix login bug", None, rid)
    wm.rename(rid, "My login work")
    callback("Login cookie expiry", "llm")
    room = wm.get_room(rid)
    assert room["name"] == "My login work" and room["name_source"] == "user"
    again = _turn("Fix login bug", None, rid)
    if again is not None:
        again("Login cookie expiry", "llm")
    assert wm.get_room(rid)["name"] == "My login work"


def test_a_web_terminal_chat_is_found_by_its_working_directory():
    room = wm.create_room(origin="web")
    callback = _turn_in_dir("整理会议纪要，发给团队", room["path"])
    assert wm.get_room(room["room_id"])["name"] == "整理会议纪要"
    callback("Meeting notes summary", "llm")
    assert wm.get_room(room["room_id"])["name"] == "Meeting notes summary"


def test_turns_outside_a_new_chat_room_rename_nothing(tmp_path):
    original = lambda title, source: None  # noqa: E731
    # No map yet: nothing is created just to look.
    assert _turn_in_dir("Fix login bug", tmp_path, original) is original
    assert not (get_phi_home() / "workspace_map.db").exists()

    hand = wm.create_room("Hand named")
    agent = wm.ensure_agent_room()
    for room in (hand, agent):
        assert _turn_in_dir("Fix login bug", room["path"], original) is original
        assert _turn("Fix login bug", original, room["room_id"]) is original
    assert _turn_in_dir("Fix login bug", tmp_path, original) is original
    assert wm.get_room(hand["room_id"])["name"] == "Hand named"
    assert wm.get_room(agent["room_id"])["name"] == agent["name"]

    # A machine-authored opener is not the user's first message.
    rid = wm.create_room(origin="web")["room_id"]
    _turn("[System note: the model was switched]", original, rid)
    room = wm.get_room(rid)
    assert room["name"] == "New chat" and room["name_source"] == "default"


def test_a_matrix_linked_room_pushes_its_names_through_the_mirror(monkeypatch):
    from gateway import adapter_actions

    calls, first, second = [], threading.Event(), threading.Event()

    def gateway(platform, action, args, **_kw):
        calls.append((platform, action, dict(args)))
        (second if first.is_set() else first).set()
        return None  # no gateway running: skipped quietly

    monkeypatch.setattr(adapter_actions, "call_adapter_action", gateway)
    plain = wm.create_room(origin="web")["room_id"]
    _turn("Not on Matrix", None, plain)

    rid = wm.create_room(origin="matrix")["room_id"]
    wm.link_channel(rid, "matrix", "!chat:example.org")
    callback = _turn("Fix login bug", None, rid)
    assert first.wait(5)
    callback("Login cookie expiry", "llm")
    assert second.wait(5)

    assert calls == [
        ("matrix", "space_mirror.rename",
         {"room_id": rid, "name": "Fix login bug", "auto": True, "expect": "Fix login bug"}),
        ("matrix", "space_mirror.rename",
         {"room_id": rid, "name": "Login cookie expiry", "auto": True, "expect": "Login cookie expiry"}),
    ]
    # The map is named even though no gateway answered.
    assert wm.get_room(rid)["name"] == "Login cookie expiry"
    assert wm.get_room(plain)["name"] == "Not on Matrix"


def test_matrix_mirror_off_names_the_map_only(monkeypatch):
    from gateway import adapter_actions

    calls = []
    monkeypatch.setattr(adapter_actions, "call_adapter_action", lambda *a, **k: calls.append(a))
    (get_phi_home() / "config.yaml").write_text("matrix:\n  space_mirror: false\n", encoding="utf-8")
    rid = wm.create_room(origin="matrix")["room_id"]
    wm.link_channel(rid, "matrix", "!chat:example.org")
    _turn("Fix login bug", None, rid)
    assert wm.get_room(rid)["name"] == "Fix login bug"
    assert calls == []


def test_room_rules_read_write_and_limit(client):
    room = client.post("/api/workspace/rooms", json={"name": "ruled"}).json()["room"]
    rules = Path(room["path"]) / "AGENTS.md"

    got = client.get(_rules_url(room["room_id"]))
    assert got.status_code == 200, got.text
    assert got.json()["content"] == "" and got.json()["max_chars"] == 8000

    saved = client.put(_rules_url(room["room_id"]), json={"content": "Reply in English.\n"})
    assert saved.status_code == 200, saved.text
    assert rules.read_text(encoding="utf-8") == "Reply in English.\n"
    assert client.get(_rules_url(room["room_id"])).json()["content"] == "Reply in English.\n"

    at_limit = client.put(_rules_url(room["room_id"]), json={"content": "x" * 8000})
    assert at_limit.status_code == 200, at_limit.text
    too_long = client.put(_rules_url(room["room_id"]), json={"content": "x" * 8001})
    assert too_long.status_code == 413
    assert "8000" in too_long.json()["detail"]
    assert rules.read_text(encoding="utf-8") == "x" * 8000
    assert not [p.name for p in rules.parent.iterdir() if p.name != "AGENTS.md"]


def test_room_rules_unknown_room_and_space(client):
    space = client.post("/api/workspace/spaces", json={"name": "S"}).json()["space"]
    assert client.get(_rules_url("!local_nope")).status_code == 404
    assert client.put(_rules_url("!local_nope"), json={"content": "x"}).status_code == 404
    assert client.get(_rules_url(space["room_id"])).status_code == 400
    assert client.put(_rules_url(space["room_id"]), json={"content": "x"}).status_code == 400

"""Matrix space mirror (design §七): the spaces and rooms the agent account joined, their hierarchy
(``m.space.child`` / ``m.space.parent``) and names are mirrored into the workspace map; move, rename and
create-space are written to Matrix first and reach the map only on success. Mirrored rows get a system id
(their directory is ``<root>/<id>``); the Matrix id lives only in the channel link.

Only the shared, agent-visible part is ever touched: no per-user account data (``m.tag``, ``m.direct``,
client settings). mautrix is not installed here, so the homeserver is a small recording fake.
"""

import asyncio
import re
from urllib.parse import quote, unquote

import pytest

from phi_cli import workspace_map as wm
from phi_cli.workspace_root import workspace_root
from phi_constants import get_phi_home
from plugins.platforms.matrix import space_mirror as sm

SERVER = "example.org"
ME = "@phi:example.org"
V3 = "/_matrix/client/v3"

WORK = "!work:example.org"
PROJ = "!projects:example.org"
PHI_SP = "!phi-space:example.org"
REL = "!release:example.org"
NOTES = "!notes:example.org"
DM = "!dm:example.org"
NOT_JOINED = "!elsewhere:example.org"
NAMELESS = "!nameless:example.org"
ALICE = "@alice:example.org"
HEX_ID = re.compile(r"[0-9a-f]{16}")


class FakeMatrixError(Exception):
    """Shaped like mautrix's ``MatrixRequestError``: an HTTP status and an errcode."""

    def __init__(self, status, errcode="M_FORBIDDEN", message="You don't have permission"):
        super().__init__(message)
        self.http_status, self.errcode, self.message = status, errcode, message


def _members():
    return {("m.room.member", ME): {"membership": "join"},
            ("m.room.power_levels", ""): {"users": {ME: 0}, "state_default": 50,
                                          "events": {"m.space.child": 50, "m.room.name": 50}}}


def _space(name, children=(), parents=()):
    state = {("m.room.create", ""): {"type": "m.space"}, ("m.room.name", ""): {"name": name}, **_members()}
    state.update({("m.space.child", c): {"via": [SERVER]} for c in children})
    state.update({("m.space.parent", p): {"via": [SERVER], "canonical": True} for p in parents})
    return state


def _room(name, parents=()):
    state = {("m.room.create", ""): {}, ("m.room.name", ""): {"name": name}, **_members()}
    state.update({("m.space.parent", p): {"via": [SERVER], "canonical": True} for p in parents})
    return state


def _homeserver():
    """Work → Projects → Phi → Release notes (three space levels). Shared notes sits in Work (Work's child
    event) and in Projects (only its own parent claim): two parents. Release notes is in Phi by its parent
    claim alone. The DM and the space child the agent never joined stay out of the map."""
    return {
        WORK: _space("Work", children=[PROJ, NOTES, NOT_JOINED]),
        PROJ: _space("Projects", children=[PHI_SP]),
        PHI_SP: _space("Phi", parents=[PROJ]),
        REL: _room("Release notes", parents=[PHI_SP]),
        NOTES: _room("Shared notes", parents=[PROJ]),
        DM: _room("Chat"),
    }


class FakeAPI:
    """Records every request as (method, decoded path, content) and answers like a tiny homeserver."""

    def __init__(self, rooms):
        self.rooms = rooms
        self.calls = []
        self.fail = {}  # (method, decoded path) -> exception to raise
        self.created = 0

    async def request(self, method, path, content=None, **_kwargs):
        method = getattr(method, "value", method)
        path = unquote(path)
        self.calls.append((method, path, content))
        if (method, path) in self.fail:
            raise self.fail[(method, path)]
        assert path.startswith(V3), path
        rest = path[len(V3):]
        if rest.startswith("/user/"):  # account data / tags: accepted, and caught by the guard below
            return {}
        if method == "GET" and rest == "/joined_rooms":
            return {"joined_rooms": list(self.rooms)}
        if method == "POST" and rest == "/createRoom":
            return self._create(content)
        _, kind, room, *tail = rest.split("/")
        assert kind == "rooms", path
        if method == "GET" and tail == ["state"]:
            return [{"type": t, "state_key": k, "content": c, "sender": ME} for (t, k), c in self.rooms[room].items()]
        if tail[:1] == ["state"]:
            key = (tail[1], tail[2] if len(tail) > 2 else "")
            if method == "PUT":
                self.rooms[room][key] = content
                return {"event_id": "$event"}
            if key not in self.rooms[room]:
                raise FakeMatrixError(404, "M_NOT_FOUND", "Event not found.")
            return self.rooms[room][key]
        if method == "POST" and tail == ["leave"]:
            self.rooms.pop(room, None)
            return {}
        raise AssertionError(f"unexpected request {method} {path}")

    def _create(self, content):
        self.created += 1
        room = f"!new{self.created}:{SERVER}"
        state = {(e["type"], e.get("state_key", "")): e["content"] for e in content.get("initial_state", [])}
        state[("m.room.create", "")] = content.get("creation_content", {})
        state[("m.room.name", "")] = {"name": content.get("name")}
        state.update(_members())
        self.rooms[room] = state
        return {"room_id": room}

    def puts(self, since=0):
        return [(path[len(V3):], content) for method, path, content in self.calls[since:] if method == "PUT"]


class FakeClient:
    def __init__(self, api):
        self.api = api
        self.handlers = {}

    def add_event_handler(self, event_type, handler, wait_sync=False):
        self.handlers.setdefault(str(getattr(event_type, "t", event_type)), []).append(handler)

    def remove_event_handler(self, event_type, handler):
        self.handlers.get(str(getattr(event_type, "t", event_type)), []).remove(handler)


class FakeAdapter:
    def __init__(self):
        self._user_id = ME
        self._dm_rooms = {DM: True}
        self._joined_rooms = set()


class Event:
    def __init__(self, room_id, event_type, state_key, content, sender=ME):
        self.room_id, self.type, self.state_key, self.content, self.sender = (
            room_id, event_type, state_key, content, sender)


def assert_no_account_data(calls):
    """The mirror only touches shared room state: no per-user account data, tags or client settings."""
    for method, path, content in calls:
        text = f"{path} {content!r}"
        for marker in ("/account_data", "/tags", "m.tag", "m.direct", "im.vector", "m.favourite"):
            assert marker not in text, f"per-user data touched: {method} {path}"


def _set_config(text):
    (get_phi_home() / "config.yaml").write_text(text, encoding="utf-8")


def _root_dirs():
    return {p.name for p in workspace_root().iterdir() if p.is_dir()}


def _state_path(room, event_type, key=""):
    return f"{V3}/rooms/{room}/state/{event_type}/{key}"


def _id(mx):
    """The map row of a Matrix room, found by its link."""
    return wm.channel_links("matrix")[mx]


def _row(mx):
    return wm.get_room(_id(mx))


async def _imported(api=None):
    api = api or FakeAPI(_homeserver())
    client, adapter = FakeClient(api), FakeAdapter()
    mirror = sm.SpaceMirror(client, adapter, get_phi_home())
    await mirror.import_all()
    return mirror, api


async def _wired(api=None):
    """The mirror as the adapter's handler factory makes it: handlers registered, first import done."""
    api = api or FakeAPI(_homeserver())
    client, adapter = FakeClient(api), FakeAdapter()
    sm.wire(client, adapter)
    mirror = sm.mirror_for(adapter)
    assert mirror is not None
    await asyncio.wait_for(mirror.imported.wait(), 5)
    return mirror, client, api


async def _fire(client, event_type, event):
    handlers = client.handlers.get(event_type)
    assert handlers, f"no handler registered for {event_type}"
    for handler in handlers:
        await handler(event)


# --- import ------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_mirrors_joined_spaces_rooms_and_edges_at_any_depth():
    mirror, api = await _imported()

    links = wm.channel_links("matrix")
    assert set(links) == {WORK, PROJ, PHI_SP, REL, NOTES}
    assert all(HEX_ID.fullmatch(row) for row in links.values())  # the Matrix id lives only in the link

    tree = wm.list_tree()
    [work] = tree["spaces"]
    assert work["room_id"] == _id(WORK) and work["name"] == "Work"
    [projects] = work["children"]
    assert projects["room_id"] == _id(PROJ)
    [phi] = projects["children"]
    assert phi["room_id"] == _id(PHI_SP) and phi["rooms"] == [_id(REL)]  # three space levels, past the UI limit of 2
    assert work["rooms"] == [_id(NOTES)] and projects["rooms"] == [_id(NOTES)]  # multi-parent
    assert sorted(_row(NOTES)["parents"]) == sorted([_id(WORK), _id(PROJ)])

    release = _row(REL)
    assert release["origin"] == "matrix" and release["rel_path"] == release["room_id"]
    assert release["name"] == "Release notes" and release["name_source"] == "user"
    assert (workspace_root() / release["room_id"]).is_dir()
    assert not (workspace_root() / "Release_notes").exists()  # never named after the display name
    assert _row(PHI_SP)["rel_path"] is None
    assert wm.room_for_channel("matrix", DM) is None  # DMs bind to agent/, not mirrored
    with pytest.raises(LookupError):
        wm.get_room(NOT_JOINED)
    assert_no_account_data(api.calls)

    dirs, before = _root_dirs(), wm.export_map()
    await mirror.import_all()  # periodic re-import: nothing changes, no new directory
    assert _root_dirs() == dirs and wm.export_map() == before
    assert not api.puts()  # importing never writes to Matrix


@pytest.mark.asyncio
async def test_existing_links_and_legacy_rows_keep_their_ids_and_directories():
    old = wm.create_room("Old notes dir")
    wm.link_channel(old["room_id"], "matrix", NOTES)
    (workspace_root() / "Release_notes").mkdir()
    wm.import_room(REL, "Release notes", "Release_notes")  # from before system ids: Matrix id as row id, no link

    await _imported()

    notes = wm.room_for_channel("matrix", NOTES)
    assert notes["room_id"] == old["room_id"] and notes["rel_path"] == old["rel_path"]
    assert notes["name"] == "Shared notes"  # display name follows Matrix, directory stays
    release = wm.room_for_channel("matrix", REL)  # found by its id, then linked
    assert release["room_id"] == REL and release["rel_path"] == "Release_notes"
    assert _root_dirs() == {old["rel_path"], "Release_notes"}


@pytest.mark.asyncio
async def test_resync_archives_rooms_left_and_restores_rejoined_ones():
    mirror, api = await _imported()
    gone = api.rooms.pop(NOTES)
    await mirror.import_all()
    notes = _row(NOTES)
    assert notes["archived"] and (workspace_root() / notes["rel_path"]).is_dir()
    assert wm.room_for_channel("matrix", NOTES)["room_id"] == notes["room_id"]  # link kept; rows are never deleted

    api.rooms[NOTES] = gone
    await mirror.import_all()
    assert not _row(NOTES)["archived"]


@pytest.mark.asyncio
async def test_resync_never_archives_local_rows_linked_to_matrix():
    agent = wm.ensure_agent_room()
    wm.link_channel(agent["room_id"], "matrix", "!old-agent-room:example.org")
    await _imported()
    assert not wm.get_room(agent["room_id"])["archived"]


# --- live updates ------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_change_updates_display_name_only():
    mirror, client, api = await _wired()
    try:
        dirs = _root_dirs()
        await _fire(client, "m.room.name", Event(REL, "m.room.name", "", {"name": "Release plan"}))
        release = _row(REL)
        assert release["name"] == "Release plan" and release["rel_path"] == release["room_id"]
        assert _root_dirs() == dirs
        assert not api.puts()
    finally:
        mirror.stop()


@pytest.mark.asyncio
async def test_our_own_echo_of_an_older_auto_name_is_ignored_and_a_person_renaming_wins():
    rooms = _homeserver()
    rooms[NAMELESS] = _room("")
    mirror, client, api = await _wired(FakeAPI(rooms))
    try:
        rid = _id(NAMELESS)
        wm.auto_name(rid, "Fix login bug")
        wm.auto_name(rid, "Login cookie expiry", expect="Fix login bug")
        # The homeserver echoes the instant name the agent wrote a moment before the model title.
        await _fire(client, "m.room.name", Event(NAMELESS, "m.room.name", "", {"name": "Fix login bug"}))
        room = wm.get_room(rid)
        assert room["name"] == "Login cookie expiry" and room["name_source"] == "auto"

        await _fire(client, "m.room.name", Event(NAMELESS, "m.room.name", "", {"name": "Bug triage"},
                                                 sender=ALICE))
        room = wm.get_room(rid)
        assert room["name"] == "Bug triage" and room["name_source"] == "user"
    finally:
        mirror.stop()


@pytest.mark.asyncio
async def test_leave_archives_and_other_members_leaving_change_nothing():
    mirror, client, api = await _wired()
    try:
        await _fire(client, "m.room.member", Event(REL, "m.room.member", "@someone:example.org",
                                                   {"membership": "leave"}, sender="@someone:example.org"))
        assert not _row(REL)["archived"]
        await _fire(client, "m.room.member", Event(REL, "m.room.member", ME, {"membership": "leave"}))
        release = _row(REL)
        assert release["archived"] and (workspace_root() / release["rel_path"]).is_dir()
        assert release["parents"] == [_id(PHI_SP)]
    finally:
        mirror.stop()


@pytest.mark.asyncio
async def test_space_child_and_parent_events_add_and_remove_edges():
    mirror, client, api = await _wired()
    try:
        await _fire(client, "m.space.child", Event(WORK, "m.space.child", REL, {"via": [SERVER]}))
        assert sorted(_row(REL)["parents"]) == sorted([_id(PHI_SP), _id(WORK)])

        # Work drops the child; Release notes never claimed Work, so the edge goes.
        await _fire(client, "m.space.child", Event(WORK, "m.space.child", REL, {}))
        assert _row(REL)["parents"] == [_id(PHI_SP)]

        # Projects never listed Shared notes; the room withdraws its own claim, so that edge goes too.
        await _fire(client, "m.space.parent", Event(NOTES, "m.space.parent", PROJ, {}))
        assert _row(NOTES)["parents"] == [_id(WORK)]

        # Phi drops a child it never listed, but Release notes still claims Phi: the edge stays.
        await _fire(client, "m.space.child", Event(PHI_SP, "m.space.child", REL, {}))
        assert _row(REL)["parents"] == [_id(PHI_SP)]
        assert not api.puts()
    finally:
        mirror.stop()


# --- write-back --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_move_writes_child_add_then_child_remove_then_parent_and_map_last(monkeypatch):
    mirror, api = await _imported()
    start = len(api.calls)
    seen_at_map_write = []
    real_move = wm.move

    def recording_move(*args):
        seen_at_map_write.append(list(api.puts(start)))
        return real_move(*args)

    monkeypatch.setattr(wm, "move", recording_move)
    result = await mirror.move(_id(NOTES), _id(WORK), _id(PHI_SP))

    assert "error" not in result, result
    via = {"via": [SERVER]}
    expected = [
        (f"/rooms/{PHI_SP}/state/m.space.child/{NOTES}", via),
        (f"/rooms/{WORK}/state/m.space.child/{NOTES}", {}),
        (f"/rooms/{NOTES}/state/m.space.parent/{PHI_SP}", {**via, "canonical": True}),
    ]
    puts = api.puts(start)
    assert puts[:3] == expected
    assert puts[3:] == [(f"/rooms/{NOTES}/state/m.space.parent/{WORK}", {})]
    assert seen_at_map_write == [puts]  # the map moved once, after every Matrix write
    assert result["room"]["room_id"] == _id(NOTES)
    assert sorted(_row(NOTES)["parents"]) == sorted([_id(PROJ), _id(PHI_SP)])
    assert_no_account_data(api.calls)


@pytest.mark.asyncio
async def test_refused_move_leaves_map_untouched_and_names_the_power_level():
    mirror, api = await _imported()
    api.fail[("PUT", _state_path(WORK, "m.space.child", NOTES))] = FakeMatrixError(403)
    before = wm.export_map()

    result = await mirror.move(_id(NOTES), _id(WORK), _id(PHI_SP))

    assert result["error"] == "Matrix refused: needs power level 50 in Work"
    assert result["status"] == 409
    assert wm.export_map() == before
    # The child already added to Phi is taken back out.
    assert api.puts()[-1] == (f"/rooms/{PHI_SP}/state/m.space.child/{NOTES}", {})
    assert api.rooms[PHI_SP][("m.space.child", NOTES)] == {}


@pytest.mark.asyncio
async def test_unreachable_homeserver_leaves_map_untouched():
    mirror, api = await _imported()
    api.fail[("PUT", _state_path(PHI_SP, "m.space.child", NOTES))] = OSError("Connection reset by peer")
    before = wm.export_map()

    result = await mirror.move(_id(NOTES), _id(WORK), _id(PHI_SP))

    assert result["error"].startswith("Matrix unreachable") and result["status"] == 502
    assert wm.export_map() == before


@pytest.mark.asyncio
async def test_move_the_map_refuses_writes_nothing_to_matrix():
    mirror, api = await _imported()
    start = len(api.calls)
    result = await mirror.move(_id(REL), _id(WORK), _id(PROJ))  # Release notes is not in Work
    assert result["status"] == 400 and "not in" in result["error"]
    assert api.puts(start) == []


@pytest.mark.asyncio
async def test_rename_writes_matrix_first_and_a_refusal_keeps_the_name():
    mirror, api = await _imported()
    result = await mirror.rename(_id(REL), "Release plan")
    assert result["room"]["name"] == "Release plan"
    assert api.puts()[-1] == (f"/rooms/{REL}/state/m.room.name/", {"name": "Release plan"})
    assert _row(REL)["rel_path"] == _id(REL)

    api.fail[("PUT", _state_path(REL, "m.room.name"))] = FakeMatrixError(403)
    result = await mirror.rename(_id(REL), "Something else")
    assert result["error"] == "Matrix refused: needs power level 50 in Release plan"
    assert _row(REL)["name"] == "Release plan"


@pytest.mark.asyncio
async def test_a_nameless_room_is_a_new_chat_and_only_its_current_auto_name_reaches_matrix():
    rooms = _homeserver()
    rooms[NAMELESS] = _room("")
    mirror, api = await _imported(FakeAPI(rooms))
    rid = _id(NAMELESS)
    room = wm.get_room(rid)
    assert room["name"] == "New chat" and room["name_source"] == "default" and room["rel_path"] == rid

    # The first message named it in the map; the naming hook pushes that name.
    wm.auto_name(rid, "Fix login bug")
    start = len(api.calls)
    result = await mirror.rename(rid, "Fix login bug", auto=True, expect="Fix login bug")
    assert result["room"]["name"] == "Fix login bug" and result["room"]["name_source"] == "auto"
    assert api.puts(start) == [(f"/rooms/{NAMELESS}/state/m.room.name/", {"name": "Fix login bug"})]

    # A push that arrives after the model title replaced it writes nothing.
    wm.auto_name(rid, "Login cookie expiry", expect="Fix login bug")
    start = len(api.calls)
    stale = await mirror.rename(rid, "Fix login bug", auto=True, expect="Fix login bug")
    assert stale["room"]["name"] == "Login cookie expiry" and api.puts(start) == []

    # Nor does one after a person renamed the room.
    wm.rename(rid, "My login work")
    start = len(api.calls)
    late = await mirror.rename(rid, "Login cookie expiry", auto=True, expect="Login cookie expiry")
    assert late["room"]["name"] == "My login work" and late["room"]["name_source"] == "user"
    assert api.puts(start) == []


@pytest.mark.asyncio
async def test_create_space_sends_encryption_and_invited_history_then_links_it():
    mirror, api = await _imported()
    _set_config("workspace:\n  max_space_depth: 4\n")
    start = len(api.calls)

    result = await mirror.create_space("Research", _id(PROJ))

    assert "error" not in result, result
    [(method, path, body)] = [c for c in api.calls[start:] if c[0] == "POST"]
    assert path == f"{V3}/createRoom"
    assert body["name"] == "Research" and body["creation_content"] == {"type": "m.space"}
    state = {e["type"]: e for e in body["initial_state"]}
    assert state["m.room.encryption"]["content"]["algorithm"] == "m.megolm.v1.aes-sha2"
    assert state["m.room.history_visibility"]["content"] == {"history_visibility": "invited"}
    new, new_mx = result["space"]["room_id"], f"!new1:{SERVER}"
    assert HEX_ID.fullmatch(new)
    assert api.puts(start) == [
        (f"/rooms/{PROJ}/state/m.space.child/{new_mx}", {"via": [SERVER]}),
        (f"/rooms/{new_mx}/state/m.space.parent/{PROJ}", {"via": [SERVER], "canonical": True}),
    ]
    space = wm.get_room(new)
    assert space["type"] == "space" and space["parents"] == [_id(PROJ)] and space["name"] == "Research"
    assert wm.channel_links("matrix")[new_mx] == new
    assert_no_account_data(api.calls)


@pytest.mark.asyncio
async def test_create_space_past_the_nesting_limit_never_reaches_matrix():
    mirror, api = await _imported()  # default limit 3: Phi is already a level-3 space
    start = len(api.calls)
    result = await mirror.create_space("Too deep", _id(PHI_SP))
    assert result["status"] == 400 and "nesting limit" in result["error"]
    assert api.calls[start:] == []


@pytest.mark.asyncio
async def test_create_space_whose_link_is_refused_leaves_the_new_space():
    mirror, api = await _imported()
    _set_config("workspace:\n  max_space_depth: 4\n")
    api.fail[("PUT", _state_path(PROJ, "m.space.child", f"!new1:{SERVER}"))] = FakeMatrixError(403)
    before = wm.export_map()

    result = await mirror.create_space("Research", _id(PROJ))

    assert result["error"] == "Matrix refused: needs power level 50 in Projects"
    assert ("POST", f"{V3}/rooms/!new1:{SERVER}/leave", {}) in api.calls
    assert wm.export_map() == before


@pytest.mark.asyncio
async def test_create_top_level_space_creates_it_in_matrix_without_a_parent_link():
    mirror, api = await _imported()
    start = len(api.calls)

    result = await mirror.create_space("Team", None)

    assert "error" not in result, result
    [(method, path, body)] = [c for c in api.calls[start:] if c[0] == "POST"]
    assert path == f"{V3}/createRoom"
    assert body["name"] == "Team" and body["creation_content"] == {"type": "m.space"}
    state = {e["type"]: e for e in body["initial_state"]}
    assert state["m.room.encryption"]["content"]["algorithm"] == "m.megolm.v1.aes-sha2"
    assert state["m.room.history_visibility"]["content"] == {"history_visibility": "invited"}
    assert "m.room.join_rules" not in state  # no parent space to restrict joining to
    assert api.puts(start) == []
    new = result["space"]["room_id"]
    assert HEX_ID.fullmatch(new)
    space = wm.get_room(new)
    assert space["type"] == "space" and space["parents"] == [] and space["name"] == "Team"
    assert wm.channel_links("matrix")[f"!new1:{SERVER}"] == new
    assert new in [s["room_id"] for s in wm.list_tree()["spaces"]]
    assert_no_account_data(api.calls)


@pytest.mark.asyncio
async def test_create_top_level_space_refused_by_matrix_leaves_the_map_unchanged():
    mirror, api = await _imported()
    api.fail[("POST", f"{V3}/createRoom")] = FakeMatrixError(403, message="You cannot create rooms")
    before = wm.export_map()

    result = await mirror.create_space("Team", None)

    assert result == {"error": "Matrix refused: You cannot create rooms", "status": 409}
    assert wm.export_map() == before


@pytest.mark.asyncio
async def test_create_space_in_an_unlinked_local_space_stays_map_only():
    mirror, api = await _imported()
    _set_config("workspace:\n  max_space_depth: 3\n")
    local = wm.create_space("Local")
    start = len(api.calls)

    result = await mirror.create_space("Sub", local["room_id"])

    assert result["space"]["parents"] == [local["room_id"]]
    assert HEX_ID.fullmatch(result["space"]["room_id"])
    assert [c for c in api.calls[start:] if c[0] in ("POST", "PUT")] == []


# --- account data guard (with its negative control) --------------------------------------------------


class _TaggingMirror(sm.SpaceMirror):
    """Deliberately wrong: also files the moved room under a per-user tag."""

    async def move(self, room_id, from_space, to_space):
        result = await super().move(room_id, from_space, to_space)
        await self.api.request("PUT", f"{V3}/user/{quote(ME)}/rooms/{quote(room_id)}/tags/m.favourite", {})
        return result


class _DirectMirror(sm.SpaceMirror):
    """Deliberately wrong: also rewrites the agent's ``m.direct`` account data."""

    async def move(self, room_id, from_space, to_space):
        result = await super().move(room_id, from_space, to_space)
        await self.api.request("PUT", f"{V3}/user/{quote(ME)}/account_data/m.direct", {ME: [room_id]})
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize("variant", [_TaggingMirror, _DirectMirror])
async def test_negative_control_a_mirror_writing_account_data_is_caught(variant):
    api = FakeAPI(_homeserver())
    mirror = variant(FakeClient(api), FakeAdapter(), get_phi_home())
    await mirror.import_all()
    await mirror.move(_id(NOTES), _id(WORK), _id(PHI_SP))
    with pytest.raises(AssertionError, match="per-user data touched"):
        assert_no_account_data(api.calls)


# --- config, wiring, actions -------------------------------------------------------------------------


def test_space_mirror_defaults_on_and_config_turns_it_off():
    from phi_cli.config_defaults import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["matrix"]["space_mirror"] is True
    assert wm.matrix_mirror_enabled() is True
    _set_config("matrix:\n  space_mirror: false\n")
    assert wm.matrix_mirror_enabled() is False


@pytest.mark.asyncio
async def test_mirror_off_imports_and_writes_nothing():
    _set_config("matrix:\n  space_mirror: false\n")
    api = FakeAPI(_homeserver())
    client, adapter = FakeClient(api), FakeAdapter()
    sm.wire(client, adapter)
    await asyncio.sleep(0.05)
    assert sm.mirror_for(adapter) is None and client.handlers == {} and api.calls == []
    answer = await sm.action_move(adapter, {"room_id": NOTES, "from_space": WORK, "to_space": PHI_SP})
    assert answer["status"] == 503 and "off" in answer["error"]
    assert not (get_phi_home() / "workspace_map.db").exists() or wm.channel_links("matrix") == {}


@pytest.mark.asyncio
async def test_turning_the_mirror_off_while_running_freezes_the_map():
    mirror, client, api = await _wired()
    try:
        _set_config("matrix:\n  space_mirror: false\n")
        since = len(api.calls)
        api.rooms.pop(NOTES)
        api.rooms[REL][("m.room.name", "")] = {"name": "Release plan"}
        await mirror.import_all()
        await _fire(client, "m.room.name", Event(REL, "m.room.name", "", {"name": "Release plan"}))
        await _fire(client, "m.room.member", Event(WORK, "m.room.member", ME, {"membership": "leave"}))
        assert api.calls[since:] == []
        assert not _row(NOTES)["archived"] and not _row(WORK)["archived"]
        assert _row(REL)["name"] == "Release notes"
    finally:
        mirror.stop()


@pytest.mark.asyncio
async def test_actions_reach_the_wired_mirror_and_rewiring_replaces_it():
    mirror, client, api = await _wired()
    adapter = next(a for a in sm._MIRRORS if sm._MIRRORS[a] is mirror)
    try:
        answer = await sm.action_rename(adapter, {"room_id": _id(REL), "name": "Release plan"})
        assert answer["room"]["name"] == "Release plan"
        answer = await sm.action_move(adapter, {"room_id": _id(NOTES), "from_space": _id(WORK),
                                                "to_space": _id(PHI_SP)})
        assert sorted(answer["room"]["parents"]) == sorted([_id(PROJ), _id(PHI_SP)])

        sm.wire(client, adapter)  # the same client again: nothing new
        assert sm.mirror_for(adapter) is mirror and len(client.handlers["m.space.child"]) == 1

        fresh = FakeClient(api)
        sm.wire(fresh, adapter)  # a reconnect hands a new client: the old handlers go
        assert sm.mirror_for(adapter) is not mirror and client.handlers["m.space.child"] == []
        assert len(fresh.handlers["m.space.child"]) == 1
    finally:
        sm.mirror_for(adapter).stop()
        mirror.stop()


def test_register_adds_the_handler_factory_and_the_actions():
    from gateway import adapter_actions

    class Ctx:
        def __init__(self):
            self.factories, self.unload = [], []

        def register_platform_handler(self, platform, factory):
            self.factories.append((platform, factory))

        def on_unload(self, fn):
            self.unload.append(fn)

    ctx = Ctx()
    sm.register(ctx)
    assert ctx.factories == [("matrix", sm.wire)]
    for name in ("space_mirror.move", "space_mirror.rename", "space_mirror.create_space"):
        assert adapter_actions.get_adapter_action("matrix", name) is not None


# --- map helpers the mirror relies on ----------------------------------------------------------------


def test_map_helpers_unarchive_links_import_parent_and_prechecks():
    top = wm.import_space("A")
    mid = wm.import_space("B", parent_space=top["room_id"])
    low = wm.import_space("C")
    wm.import_parent(low["room_id"], mid["room_id"])  # an imported edge ignores the UI nesting limit
    assert wm.get_room(low["room_id"])["parents"] == [mid["room_id"]]
    with pytest.raises(wm.DepthLimitError):
        wm.check_space_nesting(low["room_id"])
    wm.check_space_nesting(None)

    room = wm.create_room("Notes", parent_space=top["room_id"])
    wm.link_channel(room["room_id"], "matrix", "!n:example.org")
    assert wm.channel_links("matrix") == {"!n:example.org": room["room_id"]}
    wm.archive(room["room_id"])
    assert wm.channel_links("matrix") == {"!n:example.org": room["room_id"]}  # archived rows included
    assert not wm.unarchive(room["room_id"])["archived"]

    loose = wm.import_space("E")
    before = wm.export_map()
    with pytest.raises(wm.WorkspaceMapError, match="not in"):
        wm.check_move(room["room_id"], mid["room_id"], low["room_id"])
    with pytest.raises(wm.DepthLimitError):  # default limit 3: under level-2 B its rooms would be level 4
        wm.check_move(loose["room_id"], None, mid["room_id"])
    assert wm.check_move(loose["room_id"], None, top["room_id"])["room_id"] == loose["room_id"]
    with pytest.raises(wm.WorkspaceMapError, match="inside itself"):
        wm.check_move(top["room_id"], None, low["room_id"])
    assert wm.check_move(room["room_id"], top["room_id"], mid["room_id"])["room_id"] == room["room_id"]
    assert wm.export_map() == before  # checks never write

"""Workspace map store (design §五/§八): one flat directory per room under the workspace root,
spaces and channel links only in ``$PHI_HOME/workspace_map.db``.

The invariant every test leans on: a room's ``rel_path`` is fixed at creation — rename, move,
add/remove parent and archive change the map, never the disk. New rooms and spaces get a system id
(16 lowercase hex characters); a new room's directory is ``<root>/<id>``, never its display name.
"""

import re
import sqlite3
import threading

import pytest

from phi_cli import workspace_map as wm
from phi_cli.workspace_root import agent_dir, workspace_root
from phi_constants import get_phi_home

HEX_ID = re.compile(r"[0-9a-f]{16}")


def _set_config(text: str) -> None:
    (get_phi_home() / "config.yaml").write_text(text, encoding="utf-8")


def _root_dirs() -> set[str]:
    return {p.name for p in workspace_root().iterdir() if p.is_dir()}


def test_workspace_root_defaults_under_phi_home_and_honours_config(tmp_path, monkeypatch):
    root = workspace_root()
    assert root == get_phi_home() / "workspace"
    assert root.is_dir()
    assert agent_dir() == root / "agent" and agent_dir().is_dir()

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _set_config("workspace:\n  root: ~/rooms\n")
    assert workspace_root() == tmp_path / "home" / "rooms"
    assert (tmp_path / "home" / "rooms").is_dir()


def test_create_room_gets_a_system_id_that_is_also_its_directory():
    room = wm.create_room("Fix login bug")
    assert HEX_ID.fullmatch(room["room_id"])
    assert room["rel_path"] == room["room_id"]
    assert room["name"] == "Fix login bug" and room["name_source"] == "user"
    assert room["type"] == "room" and room["origin"] == "local"
    assert room["fence_mode"] == "approve" and room["extra_write_paths"] == []
    assert wm.resolve(room["room_id"]) == workspace_root() / room["room_id"]
    assert (workspace_root() / room["room_id"]).is_dir()
    # The display name never names a directory.
    assert not (workspace_root() / "Fix_login_bug").exists()
    assert _root_dirs() == {room["room_id"]}

    again = wm.create_room("Fix login bug")
    assert again["room_id"] != room["room_id"]
    assert again["rel_path"] == again["room_id"] and wm.resolve(again["room_id"]).is_dir()


def test_create_room_without_a_name_is_a_default_new_chat():
    room = wm.create_room()
    assert room["name"] == "New chat" and room["name_source"] == "default"
    assert HEX_ID.fullmatch(room["room_id"]) and room["rel_path"] == room["room_id"]
    with pytest.raises(wm.WorkspaceMapError):
        wm.create_room("   ")


def test_new_room_id_skips_ids_taken_by_a_row_or_a_directory(monkeypatch):
    existing = wm.create_room("first")["room_id"]
    (workspace_root() / "0123456789abcdef").mkdir()
    picks = iter([existing, "0123456789abcdef", "fedcba9876543210"])
    monkeypatch.setattr(wm.secrets, "token_hex", lambda n: next(picks))
    room = wm.create_room("second")
    assert room["room_id"] == room["rel_path"] == "fedcba9876543210"

    monkeypatch.setattr(wm.secrets, "token_hex", lambda n: existing)
    with pytest.raises(wm.WorkspaceMapError):
        wm.create_room("never")
    assert len([r for r in wm.list_rooms(None) if r["type"] == "room"]) == 2


def test_spaces_get_a_system_id_and_no_directory():
    space = wm.create_space("Projects")
    assert HEX_ID.fullmatch(space["room_id"]) and space["rel_path"] is None
    imported = wm.import_space("Team")
    assert HEX_ID.fullmatch(imported["room_id"]) and imported["origin"] == "matrix"
    assert _root_dirs() == set()


def test_legacy_rows_keep_their_ids_and_directories():
    """``!local_`` ids, Matrix ids as row ids and underscore folders from before stay as they are."""
    root = workspace_root()
    (root / "Old_notes").mkdir()
    (root / "Team_chat").mkdir()
    old = wm.import_room("!local_abcDEF123456", "Old notes", "Old_notes", origin="local")
    mx = wm.import_room("!legacy:example.org", "Team chat", "Team_chat")
    wm.link_channel(mx["room_id"], "matrix", "!legacy:example.org")
    assert wm.resolve("!local_abcDEF123456") == root / "Old_notes"
    assert wm.room_for_channel("matrix", "!legacy:example.org")["room_id"] == "!legacy:example.org"
    assert old["name_source"] == "user" and mx["name_source"] == "user"
    renamed = wm.rename("!legacy:example.org", "Team")
    assert renamed["rel_path"] == "Team_chat" and renamed["room_id"] == "!legacy:example.org"
    assert wm.ensure_agent_room()["room_id"] == "!local_agent"
    assert _root_dirs() == {"Old_notes", "Team_chat", "agent"}


def test_name_source_column_is_added_to_an_old_map_and_old_rows_count_as_user_named():
    path = get_phi_home() / "workspace_map.db"
    conn = sqlite3.connect(path)
    conn.executescript(wm.SCHEMA_SQL)  # the column is added in place, as last_seen was
    assert "name_source" not in {r[1] for r in conn.execute("PRAGMA table_info(rooms)")}
    conn.execute("INSERT INTO rooms (room_id, type, name, rel_path, created_at, updated_at) "
                 "VALUES ('!local_old', 'room', 'New chat', 'Old', 1, 1)")
    conn.commit()
    conn.close()
    (workspace_root() / "Old").mkdir()
    wm._INITIALIZED_PATHS.clear()

    old = wm.get_room("!local_old")
    assert old["name_source"] == "user"
    # A row that merely reads "New chat" from before is never auto-renamed.
    assert wm.auto_name("!local_old", "Something else") is None
    assert wm.get_room("!local_old")["name"] == "New chat"


def test_auto_name_replaces_only_default_or_its_own_instant_name():
    room = wm.create_room()["room_id"]
    named = wm.auto_name(room, "Fix login bug")
    assert named["name"] == "Fix login bug" and named["name_source"] == "auto"
    # The model title replaces the instant name it was derived alongside ...
    assert wm.auto_name(room, "Login cookie expiry", expect="Fix login bug")["name"] == "Login cookie expiry"
    # ... but not a different auto name (another turn got there first).
    assert wm.auto_name(room, "Stale title", expect="Fix login bug") is None
    assert wm.auto_name(room, "No expectation") is None
    assert wm.get_room(room)["name"] == "Login cookie expiry"


def test_auto_name_never_overwrites_a_user_rename():
    room = wm.create_room()["room_id"]
    wm.auto_name(room, "Fix login bug")
    renamed = wm.rename(room, "My login work")
    assert renamed["name_source"] == "user"
    assert wm.auto_name(room, "Login cookie expiry", expect="Fix login bug") is None
    assert wm.auto_name(room, "Fix login bug", expect="Fix login bug") is None
    assert wm.get_room(room)["name"] == "My login work"
    assert wm.auto_name(wm.create_room("Named by hand")["room_id"], "Other") is None
    assert wm.auto_name(wm.create_space("S")["room_id"], "Other") is None


def test_new_rooms_take_the_configured_default_fence():
    _set_config("workspace:\n  default_fence: strict\n")
    assert wm.create_room("locked")["fence_mode"] == "strict"


def test_rel_path_is_immutable_across_rename_move_and_parent_changes():
    a = wm.create_space("Projects")
    b = wm.create_space("LBNL")
    room = wm.create_room("esp32 buddy", parent_space=a["room_id"])
    rid, before = room["room_id"], room["rel_path"]
    dirs_before = _root_dirs()

    renamed = wm.rename(rid, "ESP32 companion board")
    assert renamed["name"] == "ESP32 companion board"
    assert renamed["rel_path"] == before

    moved = wm.move(rid, a["room_id"], b["room_id"])
    assert moved["parents"] == [b["room_id"]]
    wm.add_parent(rid, a["room_id"])
    wm.remove_parent(rid, b["room_id"])
    wm.archive(rid)

    assert wm.get_room(rid)["rel_path"] == before
    assert wm.resolve(rid) == workspace_root() / before
    assert _root_dirs() == dirs_before
    # Not even a raw UPDATE can re-point a registered room.
    conn = sqlite3.connect(get_phi_home() / "workspace_map.db")
    try:
        with pytest.raises(sqlite3.DatabaseError):
            conn.execute("UPDATE rooms SET rel_path = 'elsewhere' WHERE room_id = ?", (rid,))
    finally:
        conn.close()


def test_rename_rejects_an_empty_name_and_unknown_room():
    room = wm.create_room("x")
    with pytest.raises(wm.WorkspaceMapError):
        wm.rename(room["room_id"], "   ")
    with pytest.raises(wm.RoomNotFound):
        wm.rename("!local_missing", "y")


def test_a_room_can_live_in_several_spaces():
    a = wm.create_space("Projects")["room_id"]
    b = wm.create_space("Hardware lab")["room_id"]
    rid = wm.create_room("board", parent_space=a)["room_id"]
    wm.add_parent(rid, b)

    def ids(space):
        return [r["room_id"] for r in wm.list_rooms(space)]

    assert ids(a) == [rid] and ids(b) == [rid]
    assert sorted(wm.get_room(rid)["parents"]) == sorted([a, b])
    tree = {s["room_id"]: s for s in wm.list_tree()["spaces"]}
    assert tree[a]["rooms"] == [rid] and tree[b]["rooms"] == [rid]
    assert rid not in ids(None)

    wm.remove_parent(rid, a)
    assert ids(a) == [] and ids(b) == [rid]
    wm.remove_parent(rid, b)
    assert rid in ids(None)


def test_move_validates_endpoints():
    a = wm.create_space("A")["room_id"]
    b = wm.create_space("B")["room_id"]
    rid = wm.create_room("r")["room_id"]
    other = wm.create_room("other")["room_id"]

    assert wm.move(rid, None, a)["parents"] == [a]          # Home -> A
    with pytest.raises(wm.WorkspaceMapError):
        wm.move(rid, b, a)                                   # not in B
    with pytest.raises(wm.WorkspaceMapError):
        wm.move(rid, a, other)                               # a room is not a space
    with pytest.raises(wm.RoomNotFound):
        wm.move(rid, a, "!local_nope")
    assert wm.move(rid, a, None)["parents"] == []            # back to Home
    assert rid in [r["room_id"] for r in wm.list_rooms(None)]


def test_space_depth_limit_default_configured_and_matrix_import_bypass():
    # Default limit 3 counts the room: space (1) / sub-space (2) / room (3).
    assert wm.DEFAULT_MAX_SPACE_DEPTH == 3 and wm.max_space_depth() == 3
    projects = wm.create_space("Projects")["room_id"]
    hardware = wm.create_space("Hardware", parent_space=projects)["room_id"]
    assert wm.get_room(hardware)["parents"] == [projects]
    with pytest.raises(wm.DepthLimitError):
        wm.create_space("Deeper", parent_space=hardware)
    # A space holding a sub-space cannot itself be nested to the same limit.
    other = wm.create_space("Other")["room_id"]
    with pytest.raises(wm.DepthLimitError):
        wm.move(projects, None, other)
    with pytest.raises(wm.DepthLimitError):
        wm.add_parent(projects, other)

    # A config that explicitly says 2 keeps space/room only.
    _set_config("workspace:\n  max_space_depth: 2\n")
    assert wm.max_space_depth() == 2
    with pytest.raises(wm.DepthLimitError):
        wm.create_space("Sub", parent_space=other)
    loose = wm.create_space("Loose")["room_id"]
    with pytest.raises(wm.DepthLimitError):
        wm.move(loose, None, other)

    # Matrix import shows deeper hierarchies as they are.
    outer = wm.import_space("Outer")["room_id"]
    inner = wm.import_space("Inner", parent_space=outer)["room_id"]
    deepest = wm.import_space("Deepest", parent_space=inner)["room_id"]
    tree = {s["room_id"]: s for s in wm.list_tree()["spaces"]}
    assert tree[outer]["children"][0]["children"][0]["room_id"] == deepest
    # Rooms are leaves and never depth-checked.
    rid = wm.create_room("leaf", parent_space=deepest)["room_id"]
    assert [r["room_id"] for r in wm.list_rooms(deepest)] == [rid]


def test_space_cycles_are_refused():
    _set_config("workspace:\n  max_space_depth: 6\n")
    a = wm.create_space("A")["room_id"]
    b = wm.create_space("B", parent_space=a)["room_id"]
    with pytest.raises(wm.WorkspaceMapError):
        wm.move(a, None, b)
    with pytest.raises(wm.WorkspaceMapError):
        wm.add_parent(a, a)


def _tree_ids() -> dict:
    """space id -> (sub-space ids, room ids), plus the top-level space ids under None."""
    out: dict = {}

    def walk(nodes):
        for n in nodes:
            out[n["room_id"]] = ([c["room_id"] for c in n["children"]], n["rooms"])
            walk(n["children"])

    spaces = wm.list_tree()["spaces"]
    walk(spaces)
    out[None] = [s["room_id"] for s in spaces]
    return out


def test_sub_space_moves_between_parents_and_to_the_top_with_its_rooms():
    a = wm.create_space("A")["room_id"]
    b = wm.create_space("B")["room_id"]
    sub = wm.create_space("Sub", parent_space=a)["room_id"]
    rid = wm.create_room("r", parent_space=sub)["room_id"]

    assert wm.move(sub, a, b)["parents"] == [b]
    tree = _tree_ids()
    assert tree[a][0] == [] and tree[b][0] == [sub] and tree[sub][1] == [rid]
    assert tree[None] == [a, b]

    assert wm.move(sub, b, None)["parents"] == []
    tree = _tree_ids()
    assert tree[b][0] == [] and set(tree[None]) == {a, b, sub} and tree[sub][1] == [rid]
    # A top-level space without sub-spaces drops into another space.
    assert wm.move(sub, None, a)["parents"] == [a]


def test_space_move_refuses_cycles_and_overflow_and_leaves_the_map_unchanged():
    top = wm.create_space("Top")["room_id"]
    sub = wm.create_space("Sub", parent_space=top)["room_id"]
    other = wm.create_space("Other")["room_id"]

    with pytest.raises(wm.WorkspaceMapError, match="inside itself"):
        wm.move(top, None, sub)
    with pytest.raises(wm.WorkspaceMapError, match="inside itself"):
        wm.move(sub, top, sub)
    # Top already has a sub-space: under Other its room level would be 4 > 3.
    with pytest.raises(wm.DepthLimitError, match="limit is 3"):
        wm.move(top, None, other)
    # A sub-space cannot go under another sub-space either.
    other_sub = wm.create_space("Other sub", parent_space=other)["room_id"]
    with pytest.raises(wm.DepthLimitError):
        wm.move(sub, top, other_sub)
    # The failed move did not drop the old link.
    assert wm.get_room(sub)["parents"] == [top]
    assert wm.get_room(top)["parents"] == []


def test_home_lists_unparented_rooms_and_the_agent_dm_first():
    agent = wm.ensure_agent_room()
    assert wm.ensure_agent_room()["room_id"] == agent["room_id"]
    assert agent["type"] == "dm" and agent["rel_path"] == "agent"
    assert wm.resolve(agent["room_id"]) == agent_dir()

    space = wm.create_space("Projects")["room_id"]
    loose = wm.create_room("loose")["room_id"]
    filed = wm.create_room("filed", parent_space=space)["room_id"]
    gone = wm.create_room("gone")["room_id"]
    wm.archive(gone)

    home = [r["room_id"] for r in wm.list_rooms(None)]
    assert home[0] == agent["room_id"]
    assert loose in home
    assert filed not in home and gone not in home and space not in home
    assert wm.list_tree()["home"] == home
    # Archiving keeps the directory and the binding.
    assert wm.resolve(gone).is_dir()


def test_list_rooms_of_unknown_or_non_space_is_an_error():
    rid = wm.create_room("r")["room_id"]
    with pytest.raises(wm.RoomNotFound):
        wm.list_rooms("!local_nope")
    with pytest.raises(wm.WorkspaceMapError):
        wm.list_rooms(rid)


def test_spaces_have_no_directory():
    space = wm.create_space("Projects")
    assert space["rel_path"] is None
    with pytest.raises(wm.WorkspaceMapError):
        wm.resolve(space["room_id"])
    with pytest.raises(wm.RoomNotFound):
        wm.resolve("!local_unknown")


def test_channel_links_find_the_room_and_stay_unique():
    rid = wm.create_room("ops")["room_id"]
    other = wm.create_room("other")["room_id"]
    wm.link_channel(rid, "telegram", "-100123")
    assert wm.room_for_channel("telegram", "-100123")["room_id"] == rid
    assert wm.room_for_channel("telegram", "-100999") is None
    assert wm.room_for_channel("matrix", "-100123") is None
    with pytest.raises(wm.WorkspaceMapError):
        wm.link_channel(other, "telegram", "-100123")


def test_check_reports_missing_and_unmapped_dirs_only():
    wm.ensure_agent_room()
    missing = wm.create_room("vanished")
    wm.resolve(missing["room_id"]).rmdir()
    root = workspace_root()
    (root / "stray").mkdir()
    (root / ".hidden").mkdir()
    (root / "Projects" / "legacy_app").mkdir(parents=True)
    wm.import_room("!legacy:example.org", "Legacy app", "Projects/legacy_app")
    wm.create_room("fine")

    report = wm.check()
    assert report["rooms"] == 4
    assert sorted((i["kind"], i.get("room_id") or i.get("path")) for i in report["issues"]) == [
        ("missing_dir", missing["room_id"]), ("unmapped_dir", "stray")]


def test_eight_concurrent_creates_get_eight_distinct_dirs():
    barrier = threading.Barrier(8)
    results, errors = [], []

    def worker():
        try:
            barrier.wait()
            results.append(wm.create_room("Same name"))
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len({r["room_id"] for r in results}) == 8
    assert all(r["rel_path"] == r["room_id"] for r in results)
    assert all(wm.resolve(r["room_id"]).is_dir() for r in results)
    assert _root_dirs() == {r["room_id"] for r in results}


def test_import_draft_dry_run_writes_nothing_and_apply_only_inserts(tmp_path):
    root = workspace_root()
    legacy = tmp_path / "legacy_outside"
    legacy.mkdir()
    (root / "Projects" / "legacy_app").mkdir(parents=True)
    draft = {
        "spaces": [
            {"room_id": "!projects:example.org", "name": "Projects"},
            {"room_id": "!hw:example.org", "name": "Hardware", "parents": ["!projects:example.org"]},
            {"room_id": "!deep:example.org", "name": "Deep", "parents": ["!hw:example.org"]},
        ],
        "rooms": [
            {"room_id": "!phi:example.org", "name": "Phi Agent", "path": str(root / "Projects" / "legacy_app"),
             "parents": ["!projects:example.org", "!deep:example.org"],
             "channels": [{"channel": "matrix", "external_id": "!phi:example.org"}]},
            {"room_id": "!old:example.org", "name": "Old", "path": str(legacy)},
            {"room_id": "!later:example.org", "name": "Not yet", "path": "Not_yet"},
        ],
    }
    report = wm.import_draft(draft)
    assert report["applied"] is False
    assert report["summary"] == {"register": 6, "exists": 0, "conflict": 0, "error": 0}
    by_id = {e["room_id"]: e for e in report["entries"]}
    assert by_id["!phi:example.org"]["rel_path"] == "Projects/legacy_app"
    assert by_id["!old:example.org"]["rel_path"] == str(legacy)
    assert by_id["!later:example.org"]["dir_exists"] is False
    # Dry run: nothing registered, nothing created.
    assert wm.room_for_channel("matrix", "!phi:example.org") is None
    assert wm.list_tree()["spaces"] == []
    assert not (root / "Not_yet").exists()

    applied = wm.import_draft(draft, apply=True)
    assert applied["applied"] is True
    assert wm.room_for_channel("matrix", "!phi:example.org")["room_id"] == "!phi:example.org"
    assert wm.resolve("!phi:example.org") == root / "Projects" / "legacy_app"
    assert wm.resolve("!old:example.org") == legacy
    assert not (root / "Not_yet").exists()
    assert sorted(wm.get_room("!phi:example.org")["parents"]) == ["!deep:example.org", "!projects:example.org"]

    again = wm.import_draft(draft)
    assert again["summary"] == {"register": 0, "exists": 6, "conflict": 0, "error": 0}

    exported = wm.export_map()
    assert {s["room_id"] for s in exported["spaces"]} == {s["room_id"] for s in draft["spaces"]}
    assert {r["room_id"]: r["path"] for r in exported["rooms"]}["!phi:example.org"] == "Projects/legacy_app"


def test_import_draft_apply_is_all_or_nothing():
    draft = {
        "spaces": [{"room_id": "!s:example.org", "name": "S"}],
        "rooms": [
            {"room_id": "!a:example.org", "name": "A", "path": "A", "parents": ["!s:example.org"]},
            {"room_id": "!b:example.org", "name": "B", "path": "B", "parents": ["!unknown:example.org"]},
            {"room_id": "!c:example.org", "name": "C", "type": "space?", "path": "C"},
        ],
    }
    report = wm.import_draft(draft)
    assert report["summary"]["error"] == 2
    with pytest.raises(wm.WorkspaceMapError):
        wm.import_draft(draft, apply=True)
    assert wm.list_tree()["spaces"] == []

    taken = wm.create_room("taken")
    conflicting = {"rooms": [{"room_id": taken["room_id"], "name": "x", "path": "other"}]}
    assert wm.import_draft(conflicting)["summary"]["conflict"] == 1
    with pytest.raises(wm.WorkspaceMapError):
        wm.import_draft(conflicting, apply=True)
    assert wm.get_room(taken["room_id"])["rel_path"] == taken["room_id"]

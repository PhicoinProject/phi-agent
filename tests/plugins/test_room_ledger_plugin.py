"""room-ledger (plugins/room-ledger): the bound room's ledger fills itself from tool results, the
``ledger`` tool adds, finds and corrects entries, and each turn sees the room's decisions and open
items (design §九). Without a bound room nothing is written anywhere.
"""

import importlib.util
import json
import re
import sqlite3
from pathlib import Path

import pytest

from agent import room_binding as rb
from agent.room_ledger import Ledger, ledger_ref

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "room-ledger"
# Shaped like a real provider key; never a live one.
SECRET = "sk-proj-" + "redactme" * 4  # key-shaped fixture, built at runtime so no key literal ships
FIXED_LINE = "Room ledger: search it (ledger search) before answering questions about earlier work here."


class _Ctx:
    def __init__(self):
        self.hooks, self.tools = {}, {}

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_tool(self, name, toolset, schema, handler, **kw):
        self.tools[name] = {"toolset": toolset, "schema": schema, "handler": handler, **kw}


@pytest.fixture
def plugin():
    spec = importlib.util.spec_from_file_location("phi_room_ledger_plugin", PLUGIN / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ctx = _Ctx()
    mod.register(ctx)
    return ctx


@pytest.fixture
def room(tmp_path):
    room_dir = tmp_path / "room"
    room_dir.mkdir()
    rb.set_current_room(rb.RoomBinding(room_id="!room:test", name="room", dir=room_dir, fence_mode="off"))
    yield room_dir
    rb.set_current_room(None)


def _db(room_dir: Path) -> Path:
    return room_dir / ".phi" / "ledger.db"


def _rows(room_dir: Path) -> list[dict]:
    if not _db(room_dir).exists():
        return []
    con = sqlite3.connect(_db(room_dir))
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM entries ORDER BY id")]
    finally:
        con.close()


def _tool(plugin, name, args, result, session_id="s1"):
    plugin.hooks["post_tool_call"](tool_name=name, args=args, result=result, session_id=session_id,
                                   task_id="t1", tool_call_id="c1", turn_id="u1", status="ok")


def _term(plugin, command, exit_code, output="", session_id="s1"):
    _tool(plugin, "terminal", {"command": command},
          json.dumps({"output": output, "exit_code": exit_code, "error": None}), session_id)


def _todos(plugin, *items, session_id="s1"):
    todos = [{"id": i, "content": c, "status": s} for i, c, s in items]
    _tool(plugin, "todo_list", {"todos": todos}, json.dumps({"todos": todos, "revision": 1, "summary": {}}),
          session_id)


def _ledger(plugin, **args):
    return json.loads(plugin.tools["ledger"]["handler"](args, session_id="s1"))


def _inject(plugin):
    out = plugin.hooks["pre_llm_call"](session_id="s1", task_id="t1", turn_id="u1", user_message="hi",
                                       conversation_history=[], is_first_turn=False, model="m", platform="cli")
    if isinstance(out, dict):
        return out.get("context")
    return out


def test_without_a_bound_room_nothing_is_written(plugin, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert rb.current_room() is None
    plugin.hooks["on_session_start"](session_id="s1", model="m", platform="cli")
    _term(plugin, "false", 1)
    _term(plugin, "pytest", 0, "===== 3 passed in 0.10s =====")
    _todos(plugin, ("1", "Ship it", "in_progress"))
    _tool(plugin, "write_file", {"path": "a.txt"}, json.dumps({"files_modified": [str(tmp_path / "a.txt")]}))
    plugin.hooks["on_session_finalize"](session_id="s1", platform="cli")
    assert _inject(plugin) is None
    assert "error" in _ledger(plugin, action="add", text="x", kind="note", keywords=["a", "b"])
    assert list(tmp_path.rglob("ledger.db")) == []


def test_reading_a_room_without_a_ledger_creates_no_file(plugin, room):
    assert _inject(plugin) is None
    assert _ledger(plugin, action="search", q="anything") == {"entries": []}
    assert "error" in _ledger(plugin, action="done", id=1)
    assert "error" in _ledger(plugin, action="supersede", id=1, text="x")
    _term(plugin, "ls", 0, "a b c")
    assert not _db(room).exists()


def test_failed_command_is_recorded_with_exit_code_and_a_passing_one_is_not(plugin, room):
    _term(plugin, "make build", 0, "ok")
    _term(plugin, "sleep 60 &", None, "")  # background: no exit code yet
    _term(plugin, "pytest -x tests/test_login.py\necho second line", 2, "boom")
    _term(plugin, "make " + "x" * 500, 1, "")
    rows = _rows(room)
    assert [r["kind"] for r in rows] == ["step", "step"]
    assert "exit 2" in rows[0]["text"] and "pytest -x tests/test_login.py" in rows[0]["text"]
    assert "second line" not in rows[0]["text"]
    assert "exit 1" in rows[1]["text"] and "x" * 150 in rows[1]["text"] and "x" * 200 not in rows[1]["text"]
    assert not any("make build" in r["text"] or "sleep 60" in r["text"] for r in rows)


def test_test_summaries_are_recorded_as_results(plugin, room):
    _term(plugin, "pytest tests/", 0, "collected 13 items\n\n...\n===== 12 passed, 1 skipped in 3.21s =====\n")
    _term(plugin, "npx vitest run", 0, " Test Files  2 passed (2)\n      Tests  8 passed (8)\n   Duration  1.2s\n")
    _term(plugin, "scripts/run_tests.sh", 0,
          "=== Summary: 3 files, 40 tests passed, 0 failed (100% complete) in 9.1s (4 workers) ===\n")
    _term(plugin, "pytest tests/test_a.py", 1, "===== 1 failed, 3 passed in 0.52s =====")
    results = [r["text"] for r in _rows(room) if r["kind"] == "result"]
    assert any("12 passed, 1 skipped" in t for t in results)
    assert any(re.search(r"Tests\s+8 passed", t) for t in results)
    assert any("Summary: 3 files, 40 tests passed, 0 failed" in t for t in results)
    assert any("1 failed, 3 passed" in t for t in results)
    assert len(results) == 4
    assert not any("collected 13 items" in r["text"] or "Duration" in r["text"] for r in _rows(room))


def test_git_commit_sha_is_captured(plugin, room):
    _term(plugin, "git commit -m 'Fix login'", 0,
          "[feat/login 1a2b3c4] Fix login redirect\n 1 file changed, 2 insertions(+)\n")
    (row,) = _rows(room)
    assert row["kind"] == "step" and "1a2b3c4" in row["text"] and "feat/login" in row["text"]
    assert "1a2b3c4" in json.loads(row["refs"])


def test_written_and_patched_paths_are_recorded(plugin, room):
    target = room / "src" / "app.py"
    _tool(plugin, "write_file", {"path": "src/app.py", "content": "x"},
          json.dumps({"bytes_written": 1, "files_modified": [str(target)], "resolved_path": str(target)}))
    _tool(plugin, "patch", {"path": "README.md"},
          json.dumps({"success": True, "files_modified": [str(room / "README.md")]}))
    _tool(plugin, "write_file", {"path": "bad"}, json.dumps({"error": "denied"}))
    rows = _rows(room)
    assert [r["kind"] for r in rows] == ["step", "step"]
    assert "src/app.py" in rows[0]["text"] and json.loads(rows[0]["refs"]) == ["src/app.py"]
    assert "README.md" in rows[1]["text"]


def test_plan_transitions_are_recorded_once_each(plugin, room):
    _todos(plugin, ("1", "Write tests", "pending"), ("2", "Ship", "pending"))
    assert _rows(room) == []
    _todos(plugin, ("1", "Write tests", "in_progress"), ("2", "Ship", "pending"))
    _todos(plugin, ("1", "Write tests", "in_progress"), ("2", "Ship", "pending"))
    _todos(plugin, ("1", "Write tests", "completed"), ("2", "Ship", "cancelled"))
    _todos(plugin, ("1", "Write tests", "completed"), ("2", "Ship", "cancelled"))
    texts = [r["text"] for r in _rows(room)]
    assert len(texts) == 3
    assert "in_progress" in texts[0] and "Write tests" in texts[0]
    assert "completed" in texts[1] and "cancelled" in texts[2] and "Ship" in texts[2]


def test_session_start_end_and_identical_consecutive_entries_collapse(plugin, room):
    plugin.hooks["on_session_start"](session_id="s1", model="m", platform="cli")
    plugin.hooks["on_session_start"](session_id="s1", model="m", platform="cli")
    _term(plugin, "make test", 2)
    _term(plugin, "make test", 2)
    _term(plugin, "make lint", 1)
    _term(plugin, "make test", 2)
    # on_session_end fires after every turn, so the end is on_session_finalize, which runs unbound.
    rb.set_current_room(None)
    plugin.hooks["on_session_finalize"](session_id="s1", platform="cli")
    plugin.hooks["on_session_finalize"](session_id="s1", platform="cli")
    plugin.hooks["on_session_finalize"](session_id="other", platform="cli")
    texts = [r["text"] for r in _rows(room)]
    assert len(texts) == 5
    assert "started" in texts[0].lower() and "ended" in texts[-1].lower()
    assert sum("make test" in t for t in texts) == 2


def test_secrets_are_redacted_before_storing(plugin, room):
    _term(plugin, f"curl -H 'Authorization: Bearer {SECRET}' https://api.example.invalid/v1", 22, "")
    _term(plugin, "env", 0, f"OPENAI_API_KEY={SECRET}\n===== 2 passed in 0.1s ===== {SECRET}")
    added = _ledger(plugin, action="add", text=f"The key is {SECRET}", kind="fact",
                    keywords=["key", SECRET], refs=[SECRET])
    assert "id" in added
    assert len(_rows(room)) == 3
    for path in _db(room).parent.iterdir():
        assert SECRET.encode() not in path.read_bytes(), path.name


def _seed(room_dir: Path) -> dict:
    led = Ledger(room_dir)
    ids = {"decisions": [], "blockers": [], "todos": []}
    for i in range(15):
        ids["decisions"].append(led.add(f"Decision {i}: " + "use the boring option " * 20, "decision",
                                        keywords=["choice", f"d{i}"], ts=1000 + i))
    for i in range(3):
        ids["blockers"].append(led.add(f"Blocker {i}: waiting on access", "blocker", keywords=["access", "wait"],
                                       ts=900 + i))
    for i in range(2):
        ids["todos"].append(led.add(f"Todo {i}: tidy docs", "todo", keywords=["docs", "tidy"], ts=950 + i))
    for kind in ("fact", "step", "result", "note"):
        led.add(f"A {kind} that must not be injected", kind, keywords=["noise", kind], ts=2000)
    ids["old"] = led.add("Old decision to drop", "decision", keywords=["old", "drop"], ts=1500)
    ids["new"] = led.supersede(ids["old"], "New decision replacing the old one", ts=1501)
    ids["closed"] = led.add("Closed blocker", "blocker", keywords=["closed", "x"], ts=1600)
    led.mark_done(ids["closed"])
    led.close()
    return ids


def test_injection_is_bounded_and_carries_decisions_and_open_items_only(plugin, room):
    ids = _seed(room)
    block = _inject(plugin)
    assert block and len(block) <= 1500
    assert FIXED_LINE in block
    entries = [line for line in block.splitlines() if line.startswith("#")]
    assert 0 < len(entries) <= 10
    for line in entries:
        assert re.match(r"^#\d+ (decision|blocker|todo) \S", line), line
    shown = {int(line.split()[0][1:]) for line in entries}
    assert set(ids["blockers"]) <= shown
    assert ids["new"] in shown
    assert ids["old"] not in shown and ids["closed"] not in shown
    assert "must not be injected" not in block
    assert all(line.startswith(ledger_ref(int(line.split()[0][1:])) + " ") for line in entries)


def test_injection_is_empty_when_nothing_qualifies(plugin, room):
    led = Ledger(room)
    led.add("Only a fact", "fact", keywords=["only", "fact"])
    entry = led.add("A finished todo", "todo", keywords=["done", "todo"])
    led.mark_done(entry)
    led.close()
    assert _inject(plugin) is None


def test_ledger_tool_round_trip(plugin, room):
    spec = plugin.tools["ledger"]
    assert spec["toolset"] == "todo"
    desc = spec["schema"]["description"].lower()
    assert "decision" in desc and "blocker" in desc and "search" in desc

    added = _ledger(plugin, action="add", text="Use SQLite WAL for the ledger", kind="decision",
                    keywords=["sqlite", "wal", "ledger"], refs=["design.md"])
    assert added["ref"] == ledger_ref(added["id"]) == f"#{added['id']}"
    hits = _ledger(plugin, action="search", q="sqlite wal")["entries"]
    assert [h["id"] for h in hits] == [added["id"]]

    new = _ledger(plugin, action="supersede", id=added["id"], text="Use SQLite WAL with a busy timeout",
                  keywords=["sqlite", "timeout"])
    assert new["id"] != added["id"]
    assert [h["id"] for h in _ledger(plugin, action="search", q="sqlite")["entries"]] == [new["id"]]
    both = _ledger(plugin, action="search", q="sqlite", include_superseded=True)["entries"]
    assert {h["id"] for h in both} == {added["id"], new["id"]}
    assert "error" in _ledger(plugin, action="supersede", id=added["id"], text="again")

    todo = _ledger(plugin, action="add", text="Write the migration note", kind="todo", keywords=["migration", "note"])
    assert _ledger(plugin, action="done", id=todo["id"])["status"] == "done"
    assert "error" in _ledger(plugin, action="done", id=todo["id"])

    assert "error" in _ledger(plugin, action="add", text="x", kind="step", keywords=["a", "b"])
    assert "error" in _ledger(plugin, action="add", text="x", kind="note", keywords=["only-one"])
    assert "error" in _ledger(plugin, action="add", text="x", kind="note", keywords=list("abcdef"))
    assert "error" in _ledger(plugin, action="explode")

    rows = {r["id"]: r for r in _rows(room)}
    assert rows[added["id"]]["status"] == "superseded" and rows[new["id"]]["supersedes"] == added["id"]


def test_bundled_plugin_loads_by_default_and_rides_the_todo_toolset():
    from phi_cli.plugins import discover_plugins, get_plugin_manager, get_plugin_toolsets
    from phi_cli.plugins_discovery import gate_manifest
    from phi_cli.plugins_manifest import PluginManifest
    from phi_cli.tools_config import _get_platform_tools
    from toolsets import resolve_toolset

    manifest = PluginManifest(name="room-ledger", source="bundled", path=str(PLUGIN), key="room-ledger")
    assert gate_manifest(manifest, disabled=set(), enabled=None).action == "load"
    assert gate_manifest(manifest, disabled={"room-ledger"}, enabled=None).action == "placeholder"

    discover_plugins()
    loaded = get_plugin_manager()._plugins["room-ledger"]
    assert loaded.enabled and "ledger" in loaded.tools_registered
    assert "ledger" in resolve_toolset("todo")
    # A tool added to a built-in toolset follows that toolset's switch: it is not a plugin toolset.
    assert "todo" not in {key for key, _, _ in get_plugin_toolsets()}
    assert "todo" in _get_platform_tools({}, "cli")
    assert "todo" not in _get_platform_tools({"platform_toolsets": {"cli": ["terminal", "file"]}}, "cli")

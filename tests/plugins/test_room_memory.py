"""Room memory (design v2): the room's ``.phi/memory.md`` is rebuilt from its ledger after a turn that
changed the ledger, and shown only in that room's system prompt; a web chat opened in a room's directory
is bound to the room."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import room_binding as rb
from agent.room_ledger import open_ledger

ROOT = Path(__file__).resolve().parents[2]
MEMORY = ROOT / "plugins" / "room-ledger" / "room_memory.py"


@pytest.fixture
def mem():
    spec = importlib.util.spec_from_file_location("phi_room_memory_test", MEMORY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def room(tmp_path):
    room_dir = tmp_path / "room"
    room_dir.mkdir()
    return room_dir


def _binding(room_dir, name="room"):
    return rb.RoomBinding(room_id=f"!{name}:test", name=name, dir=room_dir, fence_mode="off")


def test_rebuild_reads_live_ledger_entries_only(mem, room, monkeypatch):
    ledger = open_ledger(room)
    ledger.add("Session started (cli)", "step", keywords=("session", "start"))
    old = ledger.add("Deploy with ./deploy_v1.sh", "decision", keywords=("deploy", "script"))
    ledger.supersede(old, "Deploy with ./deploy_v2.sh --canary")
    ledger.add("CI flaky on test_io", "blocker", keywords=("ci", "flaky"))
    seen = {}

    def fake(ledger_text):
        seen["ledger"] = ledger_text
        return "- Deploy: `./deploy_v2.sh --canary` (#3, 2026-10-27)\n- CI blocked by test_io (#4, 2026-10-27)"

    monkeypatch.setattr(mem, "_call_model", fake)
    text = mem.rebuild(room)
    assert "deploy_v1" not in seen["ledger"] and "Session started" not in seen["ledger"]
    assert "deploy_v2.sh --canary" in seen["ledger"]
    assert mem.strip_stamp((room / ".phi" / "memory.md").read_text()).strip() == text


def test_rebuild_happens_exactly_when_the_ledger_changed(mem, room, monkeypatch):
    calls = []
    monkeypatch.setattr(mem, "_call_model", lambda t: calls.append(t) or "- noted (#1)")
    ledger = open_ledger(room)
    ledger.add("Session started (cli)", "step", keywords=("session", "start"))
    assert mem.stale(room) is False  # nothing but session boundaries
    first = ledger.add("Ship from ./dist", "decision", keywords=("ship", "dist"))
    assert mem.stale(room) is True
    mem.rebuild(room)
    assert mem.stale(room) is False  # built from exactly these entries
    ledger.add("Session started (cli)", "step", keywords=("session", "again"))
    assert mem.stale(room) is False  # a session boundary is no change
    ledger.supersede(first, "Ship from ./build")
    assert mem.stale(room) is True  # a replaced decision is a change
    mem.rebuild(room)
    entry = ledger.add("CI blocked", "blocker", keywords=("ci", "blocked"))
    mem.rebuild(room)
    ledger.mark_done(entry)
    assert mem.stale(room) is True  # a closed blocker is a change
    assert len(calls) == 3


def test_a_draft_without_citations_or_none_keeps_the_old_memory(mem, room, monkeypatch):
    open_ledger(room).add("Use port 18080", "decision", keywords=("port", "server"))
    mem.write(room, "- old line (#1, 2026-10-01)", "0" * 16)
    for reply in ("NONE", "- something with no source"):
        monkeypatch.setattr(mem, "_call_model", lambda *_a, r=reply: r)
        assert mem.rebuild(room) is None
        assert "old line" in (room / ".phi" / "memory.md").read_text()


def test_clean_keeps_bullets_within_the_cap(mem):
    raw = "```markdown\nHere you go:\n" + "\n".join(f"- line {i} (#{i})" for i in range(2000)) + "\n```"
    out = mem.clean(raw)
    assert out.startswith("- line 0") and "Here you go" not in out
    assert len(out) <= mem.MAX_CHARS


def test_room_memory_is_in_its_own_room_prompt_only(mem, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(), b.mkdir()
    mem.write(a, "- Room A builds with make dist (#4, 2026-10-27)", "f" * 16)
    rb.set_current_room(_binding(a, "a"))
    try:
        lines = "\n".join(rb.active_room_lines())
        assert "Room A builds with make dist" in lines and "not the truth" in lines
        assert "<!-- ledger:" not in lines
        rb.set_current_room(_binding(b, "b"))
        assert "Room A builds" not in "\n".join(rb.active_room_lines())
    finally:
        rb.set_current_room(None)


def test_room_memory_off_hides_it_and_stops_rebuilds(mem, tmp_path, monkeypatch):
    a = tmp_path / "a"
    a.mkdir()
    mem.write(a, "- secret plan (#1)", "f" * 16)
    open_ledger(a).add("New plan", "decision", keywords=("new", "plan"))
    monkeypatch.setattr(rb, "room_memory_enabled", lambda: False)
    rb.set_current_room(_binding(a, "a"))
    try:
        assert "secret plan" not in "\n".join(rb.active_room_lines())
    finally:
        rb.set_current_room(None)
    assert mem.refresh(a) is None


def test_every_turn_end_refreshes_the_bound_room(room):
    spec = importlib.util.spec_from_file_location("phi_room_ledger_plugin_mem",
                                                  ROOT / "plugins" / "room-ledger" / "__init__.py")
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    hooks = {}
    plugin.register(SimpleNamespace(register_hook=lambda n, f: hooks.__setitem__(n, f),
                                    register_tool=lambda **kw: None))
    calls = []
    plugin._room_memory().refresh = lambda room_dir: calls.append(room_dir)
    hooks["on_session_end"](session_id="s1")  # no bound room: nothing
    rb.set_current_room(_binding(room))
    try:
        hooks["on_session_end"](session_id="s1")
    finally:
        rb.set_current_room(None)
    assert calls == [room.resolve()]


def test_a_web_chat_in_a_room_directory_is_bound_to_that_room():
    from gateway.session_policy import build_policy, policy_scope
    from phi_cli import workspace_map as wm

    room = wm.create_room("Pty room")
    # The dashboard chat sends only the room's directory as cwd (no room_id).
    policy = build_policy({'cwd': room['path'], 'model': 'm'}, {}, profile_terminal=False)
    assert 'room_id' not in json.loads(policy.request_json)
    with policy_scope(policy):
        assert rb.current_room() is not None and rb.current_room().room_id == room['room_id']
    assert rb.current_room() is None

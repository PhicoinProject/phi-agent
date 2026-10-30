"""Per-room ledger (design §九): append-only storage, supersede, open items, export, concurrency."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from agent.room_ledger import KINDS, Ledger
from phi_cli.sqlite_util import open_db

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(tmp_path / "room")
    yield led
    led.close()


def test_db_lives_under_room_phi_dir_with_shared_wal_policy(tmp_path):
    room = tmp_path / "room"
    with Ledger(room) as led:
        led.add("first entry", kind="note")
        assert led.path == room / ".phi" / "ledger.db"
    assert (room / ".phi" / "ledger.db").is_file()
    # WAL unless the shared policy refuses it (WAL-reset-bug SQLite builds, configured DELETE).
    probe = open_db(tmp_path / "probe.db", db_label="probe")
    try:
        probe.execute("CREATE TABLE t(x)")
        expected = probe.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        probe.close()
    conn = sqlite3.connect(room / ".phi" / "ledger.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == expected
    finally:
        conn.close()


def test_seven_kinds_and_validation(ledger):
    assert KINDS == ("decision", "fact", "result", "blocker", "todo", "note", "step")
    for kind in KINDS:
        ledger.add(f"a {kind} entry", kind=kind)
    with pytest.raises(ValueError):
        ledger.add("bogus kind", kind="opinion")
    with pytest.raises(ValueError):
        ledger.add("   ", kind="note")
    conn = sqlite3.connect(ledger.path)
    try:  # the CHECK constraint guards writers that bypass the API too
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO entries(ts, actor, kind, text) VALUES (0, 'agent', 'opinion', 'x')")
    finally:
        conn.close()


def test_add_stores_fields_and_refs(ledger):
    entry_id = ledger.add("ported the router fix", kind="result", keywords=["router", "修复"],
                          refs=["agent/router.py", "abc1234"], actor="subagent-2", session_id="s-1", task_id="t9")
    row = ledger.get(entry_id)
    assert row["text"] == "ported the router fix"
    assert row["keywords"] == "router 修复"
    assert row["refs"] == ["agent/router.py", "abc1234"]
    assert (row["actor"], row["session_id"], row["task_id"], row["status"]) == ("subagent-2", "s-1", "t9", "active")
    assert ledger.search("修复")[0]["id"] == entry_id  # keywords are searchable


def test_supersede_hides_old_row(ledger):
    old = ledger.add("gateway port is 8642", kind="fact", keywords="port")
    new = ledger.supersede(old, "gateway port is 8650")
    assert [h["id"] for h in ledger.search("gateway port")] == [new]
    both = {h["id"]: h for h in ledger.search("gateway port", include_superseded=True)}
    assert set(both) == {old, new}
    assert both[old]["status"] == "superseded"
    assert ledger.get(old)["superseded_by"] == new
    new_row = ledger.get(new)
    assert (new_row["supersedes"], new_row["kind"], new_row["keywords"]) == (old, "fact", "port")
    with pytest.raises(ValueError):
        ledger.supersede(old, "superseding a superseded row")
    with pytest.raises(KeyError):
        ledger.supersede(99999, "no such row")


def test_failed_supersede_leaves_old_row_active(ledger):
    old = ledger.add("proxy is on", kind="fact")
    with pytest.raises(ValueError):
        ledger.supersede(old, "  ")
    assert ledger.get(old)["status"] == "active"
    conn = sqlite3.connect(ledger.path)
    try:
        assert conn.execute("SELECT count(*) FROM entries").fetchone()[0] == 1
    finally:
        conn.close()


def test_mark_done_open_items_and_recent(ledger):
    now = time.time()
    blocker = ledger.add("disk full on build host", kind="blocker", ts=now - 30)
    todo_a = ledger.add("rotate the api key", kind="todo", ts=now - 20)
    todo_b = ledger.add("write the release note", kind="todo", ts=now - 10)
    ledger.add("a note", kind="note", ts=now)
    d1 = ledger.add("use sqlite for the ledger", kind="decision", ts=now - 50)
    d2 = ledger.add("keep the old port", kind="decision", ts=now - 5)
    assert ledger.mark_done(todo_a) is True
    assert ledger.mark_done(todo_a) is False  # already done
    assert ledger.get(todo_a)["status"] == "done"
    assert [r["id"] for r in ledger.open_items()] == [blocker, todo_b]
    assert [r["id"] for r in ledger.open_items(limit=1)] == [blocker]
    assert [r["id"] for r in ledger.recent()] == [d2, d1]
    assert [r["id"] for r in ledger.recent(kinds=("decision", "blocker"), limit=2)] == [d2, blocker]
    # done items stay searchable facts
    assert ledger.search("rotate api key")[0]["id"] == todo_a


def test_search_kind_filter(ledger):
    note = ledger.add("cache warmup slow", kind="note")
    fact = ledger.add("cache warmup takes 40 s", kind="fact")
    assert [h["id"] for h in ledger.search("cache warmup", kinds=("note",))] == [note]
    assert fact in [h["id"] for h in ledger.search("cache warmup")]


def test_export_markdown_newest_first_grouped_by_day(ledger):
    day1 = datetime(2026, 10, 1, 12, 0).timestamp()
    day2 = datetime(2026, 10, 2, 12, 0).timestamp()
    a = ledger.add("alpha decided", kind="decision", ts=day1)
    b = ledger.add("beta fact", kind="fact", ts=day2)
    c = ledger.add("gamma todo\nsecond line", kind="todo", ts=day2 + 60)
    ledger.mark_done(c)
    d = ledger.supersede(b, "beta fact corrected")
    md = ledger.export_markdown()
    assert md.startswith("# Ledger")
    assert md.index("## 2026-10-02") < md.index("## 2026-10-01")
    lines = md.splitlines()
    pos = {i: next(n for n, line in enumerate(lines) if f"#{i} " in line) for i in (a, b, c, d)}
    assert pos[d] < pos[c] < pos[b] < pos[a]  # newest first (d was written now)
    assert "superseded by #%d" % d in lines[pos[b]]
    assert "(done)" in lines[pos[c]]
    assert "  second line" in md


_WORKER = """
import sys
from agent.room_ledger import Ledger
room, worker = sys.argv[1], int(sys.argv[2])
led = Ledger(room)
for i in range(100):
    led.add(f"worker {worker} entry {i}", kind="step", actor=f"subagent-{worker}")
led.close()
"""


def test_eight_processes_append_800_rows_without_duplicate_ids(tmp_path):
    room = tmp_path / "room"
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(filter(None, [str(REPO_ROOT), os.environ.get("PYTHONPATH")])))
    procs = [subprocess.Popen([sys.executable, "-c", _WORKER, str(room), str(w)], cwd=REPO_ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for w in range(8)]
    for proc in procs:
        _out, err = proc.communicate(timeout=180)
        assert proc.returncode == 0, err
    conn = sqlite3.connect(room / ".phi" / "ledger.db")
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM entries")]
        texts = {r[0] for r in conn.execute("SELECT text FROM entries")}
        assert len(ids) == 800 and len(set(ids)) == 800
        assert texts == {f"worker {w} entry {i}" for w in range(8) for i in range(100)}
        assert conn.execute("SELECT count(*) FROM entries_words").fetchone()[0] == 800
        assert conn.execute("SELECT count(*) FROM entries_tri").fetchone()[0] == 800
    finally:
        conn.close()
    with Ledger(room) as led:
        assert {h["text"] for h in led.search("entry 42", k=8)} == {f"worker {w} entry 42" for w in range(8)}

"""Move workspace (design §二 H): every room directory follows ``workspace.root`` to a new place.

Same filesystem: one ``os.rename``. Across filesystems: copy (symlinks stay symlinks, modes and mtimes
kept, sockets/fifos skipped), verify (file list, sizes, sha256 up to 64 MB), and only then switch
``workspace.root``. A failed copy or verify leaves the config as it was and marks the target with
``.phi_move_failed``; the old root is never deleted. While ``$PHI_HOME/workspace_move.lock`` names a live
process, new turns run unbound (fail open) instead of binding a room that is moving.
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

import phi_yaml as yaml
from agent import room_binding as rb
from gateway.config import Platform
from gateway.session import SessionSource
from phi_cli import workspace_map as wm
from phi_cli import workspace_root as wr
from phi_constants import get_phi_home

MTIME = 1_600_000_000


@pytest.fixture(autouse=True)
def _unbound_after():
    yield
    rb.set_current_room(None)


@pytest.fixture
def cross_fs(monkeypatch):
    """Force the copy path: the target counts as another filesystem."""
    monkeypatch.setattr(wr, "_same_fs", lambda _a, _b: False)


def _saved_root():
    path = get_phi_home() / "config.yaml"
    if not path.exists():
        return None
    saved = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return (saved.get("workspace") or {}).get("root")


def _notes() -> str:
    """The Notes room's directory name: its system id, not its display name."""
    return next(r["rel_path"] for r in wm.list_rooms(None) if r["name"] == "Notes")


def _populate():
    """A room with a file (mode 0640, old mtime), a subdir file, a symlink and a fifo."""
    room = wm.create_room("Notes")
    base = wr.workspace_root() / _notes()
    (base / "a.txt").write_text("alpha", encoding="utf-8")
    os.chmod(base / "a.txt", 0o640)
    os.utime(base / "a.txt", (MTIME, MTIME))
    (base / "sub").mkdir()
    (base / "sub" / "b.bin").write_bytes(b"\0" * 1000)
    os.symlink("a.txt", base / "link")
    os.mkfifo(base / "pipe")
    return room


def _states():
    seen = []

    def progress(state, done_bytes, total_bytes):
        seen.append((state, done_bytes, total_bytes))

    return seen, progress


def _assert_failed_move_is_contained(old, target):
    """A failed move: config untouched, rooms still resolve under the old root, target marked, no lock."""
    assert _saved_root() is None
    assert wr.workspace_root() == old
    assert (old / _notes() / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (target / wr.FAILED_MARKER).is_file()
    assert not wr.move_lock_path().exists()


def test_same_filesystem_move_renames_the_root_and_switches_the_config():
    room = _populate()
    old = wr.workspace_root()
    target = get_phi_home() / "moved"
    plan = wr.plan_move(str(target))
    assert plan["same_fs"] is True
    assert plan["files"] == 3  # a.txt, sub/b.bin, link; the fifo is not counted
    assert plan["bytes"] == len("alpha") + 1000

    seen, progress = _states()
    result = wr.move_root(str(target), progress=progress)

    assert result["same_fs"] is True
    assert not old.exists()
    assert _saved_root() == str(target)
    assert wr.workspace_root() == target
    assert wm.resolve(room["room_id"]) == target / _notes()
    assert os.readlink(target / _notes() / "link") == "a.txt"
    assert seen[-1][0] == "done"
    assert not wr.move_lock_path().exists()


def test_cross_filesystem_move_copies_verifies_then_switches_and_keeps_the_old_root(cross_fs):
    room = _populate()
    legacy_dir = get_phi_home() / "legacy_notes"
    legacy_dir.mkdir()
    legacy = wm.import_room("!legacy:example.org", "Legacy", str(legacy_dir))
    assert legacy["rel_path"] == str(legacy_dir)
    old = wr.workspace_root()
    target = get_phi_home() / "elsewhere" / "workspace"
    config_during = {}

    def progress(state, _done, _total):
        config_during.setdefault(state, _saved_root())

    result = wr.move_root(str(target), progress=progress)

    assert result["same_fs"] is False
    assert list(config_during) == ["copying", "verifying", "switching", "done"]
    # Nothing points at the new root until the copy is verified.
    assert config_during["copying"] is None and config_during["verifying"] is None
    assert _saved_root() == str(target)
    assert wm.resolve(room["room_id"]) == target / _notes()
    copied = target / _notes()
    assert (copied / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert (copied / "a.txt").stat().st_mode & 0o777 == 0o640
    assert int((copied / "a.txt").stat().st_mtime) == MTIME
    assert (copied / "sub" / "b.bin").read_bytes() == b"\0" * 1000
    assert (copied / "link").is_symlink() and os.readlink(copied / "link") == "a.txt"
    assert not os.path.lexists(copied / "pipe")
    # The old root stays where it was; a legacy room outside the root is not moved.
    assert (old / _notes() / "a.txt").read_text(encoding="utf-8") == "alpha"
    assert wm.resolve("!legacy:example.org") == legacy_dir
    assert not (target / wr.FAILED_MARKER).exists()
    assert not wr.move_lock_path().exists()


def _corrupting_copy(real_copy):
    def copy(src, dst, report):
        real_copy(src, dst, report)
        (dst / _notes() / "a.txt").write_text("alphX", encoding="utf-8")  # same size, other bytes

    return copy


def test_verify_failure_leaves_the_config_unchanged_and_marks_the_target(cross_fs, monkeypatch):
    _populate()
    old = wr.workspace_root()
    target = get_phi_home() / "elsewhere"
    monkeypatch.setattr(wr, "_copy_root", _corrupting_copy(wr._copy_root))

    with pytest.raises(wr.MoveError, match="verify"):
        wr.move_root(str(target))

    _assert_failed_move_is_contained(old, target)


def test_negative_control_switching_before_verification_is_caught(cross_fs, monkeypatch):
    """Deliberately wrong: the config is switched as soon as the copy lands, before verifying."""
    _populate()
    old = wr.workspace_root()
    target = get_phi_home() / "elsewhere"
    corrupting = _corrupting_copy(wr._copy_root)

    def switch_early(src, dst, report):
        corrupting(src, dst, report)
        wr._switch_config(dst)

    monkeypatch.setattr(wr, "_copy_root", switch_early)
    with pytest.raises(wr.MoveError):
        wr.move_root(str(target))

    with pytest.raises(AssertionError):
        _assert_failed_move_is_contained(old, target)


def test_preflight_refuses_bad_targets():
    _populate()
    old = wr.workspace_root()
    (get_phi_home() / "busy").mkdir()
    (get_phi_home() / "busy" / "x").write_text("x", encoding="utf-8")
    (get_phi_home() / "a_file").write_text("x", encoding="utf-8")
    refusals = {
        "moved": "absolute",
        str(old): "already",
        str(old / "inner"): "inside",
        str(get_phi_home()): "inside",
        str(get_phi_home() / "busy"): "empty",
        str(get_phi_home() / "a_file"): "not a directory",
    }
    for path, reason in refusals.items():
        with pytest.raises(wr.MoveError, match=reason):
            wr.plan_move(path)
    assert wr.plan_move(str(get_phi_home() / "fresh"))["files"] == 3
    assert _saved_root() is None and old.is_dir()


def test_preflight_refuses_a_target_that_is_not_writable(monkeypatch):
    _populate()
    parent = get_phi_home() / "locked"
    parent.mkdir()
    os.chmod(parent, 0o555)
    if os.geteuid() == 0:  # root ignores mode bits
        real_access = os.access
        monkeypatch.setattr(wr.os, "access",
                            lambda p, mode, **kw: False if str(p) == str(parent) else real_access(p, mode, **kw))
    try:
        with pytest.raises(wr.MoveError, match="not writable"):
            wr.plan_move(str(parent / "workspace"))
    finally:
        os.chmod(parent, 0o755)


def test_preflight_refuses_when_free_space_is_short(monkeypatch):
    _populate()
    needed = len("alpha") + 1000
    monkeypatch.setattr(wr.shutil, "disk_usage",
                        lambda _p: SimpleNamespace(total=10 ** 9, used=0, free=int(needed * 1.05)))
    with pytest.raises(wr.MoveError, match="space"):
        wr.plan_move(str(get_phi_home() / "moved"))
    monkeypatch.setattr(wr.shutil, "disk_usage",
                        lambda _p: SimpleNamespace(total=10 ** 9, used=0, free=needed * 2))
    assert wr.plan_move(str(get_phi_home() / "moved"))["bytes"] == needed


def _group_source():
    return SessionSource(platform=Platform.TELEGRAM, chat_id="-1001", chat_type="group", chat_name="Group")


def test_the_move_lock_blocks_new_bindings_and_turns_run_unbound(caplog):
    room = wm.create_room("ops")
    wm.link_channel(room["room_id"], "telegram", "-1001")
    wr.move_lock_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        assert wr.move_in_progress() is True
        with caplog.at_level(logging.WARNING, logger="agent.room_binding"):
            assert rb.session_room_vars(_group_source()) == {}
            with rb.room_scope(room["room_id"]) as bound:
                assert bound is None
                assert rb.current_room() is None
        warnings = [r.getMessage() for r in caplog.records
                    if r.name == "agent.room_binding" and r.levelno == logging.WARNING]
        assert len(warnings) == 2 and all("moving" in w for w in warnings)
    finally:
        wr.move_lock_path().unlink()

    assert rb.session_room_vars(_group_source())["room"].room_id == room["room_id"]
    with rb.room_scope(room["room_id"]) as bound:
        assert bound is not None and bound.room_id == room["room_id"]


def test_a_stale_lock_from_a_dead_process_does_not_block():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    wr.move_lock_path().write_text(str(proc.pid), encoding="utf-8")
    try:
        assert wr.move_in_progress() is False
        room = wm.create_room("ops")
        with rb.room_scope(room["room_id"]) as bound:
            assert bound is not None
        # A stale lock is replaced by the next move.
        _populate()
        wr.move_root(str(get_phi_home() / "moved"))
        assert _saved_root() == str(get_phi_home() / "moved")
    finally:
        if wr.move_lock_path().exists():
            wr.move_lock_path().unlink()
    assert not wr.move_lock_path().exists()


def test_a_running_move_refuses_a_second_one():
    _populate()
    wr.move_lock_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        with pytest.raises(wr.MoveError, match="already"):
            wr.move_root(str(get_phi_home() / "moved"))
    finally:
        wr.move_lock_path().unlink()
    assert _saved_root() is None and (wr.workspace_root() / _notes()).is_dir()


def test_failed_copy_marks_the_target(cross_fs, monkeypatch):
    _populate()
    old = wr.workspace_root()
    target = get_phi_home() / "elsewhere"

    def broken(src, dst, report):
        dst.mkdir(parents=True, exist_ok=True)
        raise shutil.Error([(str(src), str(dst), "disk full")])

    monkeypatch.setattr(wr, "_copy_root", broken)
    with pytest.raises(wr.MoveError, match="copy"):
        wr.move_root(str(target))
    _assert_failed_move_is_contained(old, target)


# --- /api/workspace/root -------------------------------------------------------------------------------


@pytest.fixture
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
def client(_multiplex_state_is_per_test):
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient

    from phi_cli import web_server

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


def _wait_for_move(client, timeout=10.0):
    deadline = time.monotonic() + timeout
    while True:
        status = client.get("/api/workspace/root/move").json()
        if status["state"] in ("done", "failed") or time.monotonic() > deadline:
            return status
        time.sleep(0.05)


def test_root_routes_plan_move_and_report_progress(client):
    room = _populate()
    target = get_phi_home() / "moved"
    assert client.get("/api/workspace/root/move").json()["state"] == "idle"

    plan = client.post("/api/workspace/root/plan", json={"path": str(target)})
    assert plan.status_code == 200, plan.text
    assert plan.json()["same_fs"] is True and plan.json()["files"] == 3
    assert client.post("/api/workspace/root/plan", json={"path": "moved"}).status_code == 400
    assert client.post("/api/workspace/root/move", json={"path": "moved"}).status_code == 400

    started = client.post("/api/workspace/root/move", json={"path": str(target)})
    assert started.status_code == 200, started.text
    status = _wait_for_move(client)
    assert status["state"] == "done", status
    assert status["error"] is None and status["done_bytes"] == status["total_bytes"] == plan.json()["bytes"]
    assert client.get("/api/workspace/settings").json()["root"] == str(target)
    assert wm.resolve(room["room_id"]) == target / _notes()


def test_root_move_route_refuses_while_another_move_holds_the_lock(client):
    _populate()
    wr.move_lock_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        resp = client.post("/api/workspace/root/move", json={"path": str(get_phi_home() / "moved")})
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"]
    finally:
        wr.move_lock_path().unlink()
    assert _saved_root() is None

"""Per-session write roots (room fence, tool layer) in agent/file_safety.py.

A session bound to a room sets its write roots through a contextvar; they take
precedence over the process-wide ``PHI_WRITE_SAFE_ROOT`` for that session only.
Fence modes: ``strict`` denies outside (``safe_root``), ``approve`` classifies
outside writes as ``needs_approval`` (the file tools prompt), ``off`` applies
no session root. With nothing set, behaviour is exactly the upstream one.
"""

import contextvars
import json
import os
import threading

import pytest

from agent.file_safety import (
    _classify_write_denial,
    approve_session_write_path,
    get_safe_write_roots,
    get_session_fence,
    get_write_denied_error,
    is_fence_approval_required,
    is_write_denied,
    reset_session_write_roots,
    set_session_write_roots,
)


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.delenv("PHI_WRITE_SAFE_ROOT", raising=False)
    room = tmp_path / "workspace" / "my_room"
    room.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    return room, outside


@pytest.fixture
def fence():
    """Set a session fence for one test and always reset it."""
    tokens = []

    def _set(roots, mode):
        tokens.append(set_session_write_roots([str(r) for r in roots], mode=mode))

    yield _set
    for token in reversed(tokens):
        reset_session_write_roots(token)


class TestNothingSet:
    def test_no_fence_by_default(self, room):
        assert get_session_fence() == ("off", [])
        assert get_safe_write_roots() == set()

    def test_env_root_still_applies_without_session(self, room, monkeypatch):
        room_dir, outside = room
        monkeypatch.setenv("PHI_WRITE_SAFE_ROOT", str(room_dir))
        assert _classify_write_denial(str(outside / "x.txt")) == "safe_root"
        assert _classify_write_denial(str(room_dir / "x.txt")) is None
        err = get_write_denied_error(str(outside / "x.txt"))
        assert "PHI_WRITE_SAFE_ROOT" in err

    def test_no_approval_needed_without_session(self, room):
        _, outside = room
        assert is_fence_approval_required(str(outside / "x.txt")) is False
        assert is_write_denied(str(outside / "x.txt")) is False


class TestSessionRootsOverrideEnv:
    def test_session_roots_win_over_env(self, room, fence, monkeypatch):
        room_dir, outside = room
        monkeypatch.setenv("PHI_WRITE_SAFE_ROOT", str(outside))
        fence([room_dir], "strict")
        assert get_safe_write_roots() == {os.path.realpath(room_dir)}
        assert _classify_write_denial(str(outside / "x.txt")) == "safe_root"
        assert _classify_write_denial(str(room_dir / "sub" / "x.txt")) is None

    def test_reset_restores_env_roots(self, room, monkeypatch):
        room_dir, outside = room
        monkeypatch.setenv("PHI_WRITE_SAFE_ROOT", str(outside))
        token = set_session_write_roots([str(room_dir)], mode="strict")
        assert get_safe_write_roots() == {os.path.realpath(room_dir)}
        reset_session_write_roots(token)
        assert get_safe_write_roots() == {os.path.realpath(outside)}
        assert get_session_fence() == ("off", [])

    def test_nested_set_and_reset(self, room):
        room_dir, outside = room
        outer = set_session_write_roots([str(room_dir)], mode="strict")
        inner = set_session_write_roots([str(outside)], mode="approve")
        assert get_session_fence() == ("approve", [os.path.realpath(outside)])
        reset_session_write_roots(inner)
        assert get_session_fence() == ("strict", [os.path.realpath(room_dir)])
        reset_session_write_roots(outer)
        assert get_session_fence() == ("off", [])

    def test_roots_are_resolved_and_symlink_escape_is_outside(self, room, fence, tmp_path):
        room_dir, outside = room
        link = room_dir / "escape"
        link.symlink_to(outside, target_is_directory=True)
        fence([room_dir], "strict")
        # The link sits inside the room but lands outside: realpath decides.
        assert _classify_write_denial(str(link / "x.txt")) == "safe_root"

    def test_copied_context_sees_fence_fresh_thread_does_not(self, room, fence):
        room_dir, _ = room
        fence([room_dir], "strict")
        assert contextvars.copy_context().run(get_session_fence)[0] == "strict"
        seen = []
        t = threading.Thread(target=lambda: seen.append(get_session_fence()))
        t.start()
        t.join()
        assert seen == [("off", [])]

    def test_invalid_mode_rejected(self, room):
        room_dir, _ = room
        with pytest.raises(ValueError):
            set_session_write_roots([str(room_dir)], mode="permissive")


class TestStrict:
    def test_outside_denied_with_room_message(self, room, fence):
        room_dir, outside = room
        fence([room_dir], "strict")
        target = str(outside / "x.txt")
        assert is_write_denied(target) is True
        err = get_write_denied_error(target)
        assert err and "room" in err and os.path.realpath(room_dir) in err
        assert "PHI_WRITE_SAFE_ROOT" not in err
        assert is_fence_approval_required(target) is False

    def test_approved_path_does_not_open_strict(self, room, fence):
        room_dir, outside = room
        fence([room_dir], "strict")
        assert approve_session_write_path(str(outside)) is False
        assert _classify_write_denial(str(outside / "x.txt")) == "safe_root"

    def test_ssh_config_gate_does_not_reopen_strict(self, room, fence, tmp_path, monkeypatch):
        room_dir, _ = room
        monkeypatch.setenv("HOME", str(tmp_path))
        fence([room_dir], "strict")
        assert _classify_write_denial(str(tmp_path / ".ssh" / "config")) == "safe_root"


class TestApprove:
    def test_outside_needs_approval(self, room, fence):
        room_dir, outside = room
        fence([room_dir], "approve")
        target = str(outside / "x.txt")
        assert _classify_write_denial(target) == "needs_approval"
        assert is_fence_approval_required(target) is True
        assert is_fence_approval_required(str(room_dir / "x.txt")) is False
        # Callers that cannot prompt fail closed with a plain reason.
        err = get_write_denied_error(target)
        assert err and "approv" in err and os.path.realpath(room_dir) in err

    def test_approval_opens_path_for_this_session_only(self, room, fence):
        room_dir, outside = room
        fence([room_dir], "approve")
        target = str(outside / "x.txt")
        assert approve_session_write_path(target) is True
        assert _classify_write_denial(target) is None
        assert get_write_denied_error(target) is None
        assert _classify_write_denial(str(outside / "other.txt")) == "needs_approval"
        mode, roots = get_session_fence()
        assert mode == "approve" and os.path.realpath(target) in roots
        # A new session fence starts without the earlier approval.
        token = set_session_write_roots([str(room_dir)], mode="approve")
        try:
            assert _classify_write_denial(target) == "needs_approval"
        finally:
            reset_session_write_roots(token)

    def test_credentials_stay_hard_denied(self, room, fence, tmp_path, monkeypatch):
        room_dir, _ = room
        monkeypatch.setenv("HOME", str(tmp_path))
        fence([room_dir], "approve")
        key = str(tmp_path / ".ssh" / "authorized_keys")
        assert _classify_write_denial(key) == "credential"
        assert is_fence_approval_required(key) is False


class TestOff:
    def test_off_applies_no_session_root(self, room, fence, monkeypatch):
        room_dir, outside = room
        fence([room_dir], "off")
        assert get_session_fence() == ("off", [])
        assert get_safe_write_roots() == set()
        assert _classify_write_denial(str(outside / "x.txt")) is None

    def test_off_keeps_env_root(self, room, fence, monkeypatch):
        room_dir, outside = room
        monkeypatch.setenv("PHI_WRITE_SAFE_ROOT", str(outside))
        fence([room_dir], "off")
        assert get_safe_write_roots() == {os.path.realpath(outside)}


class TestFileToolGate:
    """approve mode routes outside writes to the approval gate (mirrors ~/.ssh/config)."""

    def test_no_human_blocks_and_writes_nothing(self, room, fence):
        from tools.file_tools import write_file_tool

        room_dir, outside = room
        fence([room_dir], "approve")
        target = outside / "x.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-none"))
        assert "BLOCKED" in result["error"]
        assert not target.exists()

    def test_braces_in_path_do_not_break_the_message(self, room, fence):
        from tools.file_tools import write_file_tool

        room_dir, outside = room
        fence([room_dir], "approve")
        target = outside / "{why}{0}.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-braces"))
        assert "BLOCKED" in result["error"] and os.path.realpath(target) in result["error"]
        assert not target.exists()

    def test_approved_write_lands_and_is_remembered(self, room, fence, monkeypatch):
        import tools.approval as approval
        from tools.file_tools import write_file_tool

        calls = []

        def _gate(**kw):
            calls.append(kw)
            return {"approved": True, "message": None}

        monkeypatch.setattr(approval, "_run_approval_gate", _gate)
        room_dir, outside = room
        fence([room_dir], "approve")
        target = outside / "x.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-ok"))
        assert "error" not in result or not result["error"], result
        assert target.read_text() == "hello\n"
        assert len(calls) == 1 and os.path.realpath(target) in calls[0]["description"]
        # Approved for the session: the next write does not prompt again.
        write_file_tool(str(target), "again\n", task_id="fence-gate-ok")
        assert len(calls) == 1

    def test_denied_write_reports_and_writes_nothing(self, room, fence, monkeypatch):
        import tools.approval as approval
        from tools.file_tools import write_file_tool

        monkeypatch.setattr(approval, "_run_approval_gate",
                            lambda **kw: {"approved": False, "message": "denied by user"})
        room_dir, outside = room
        fence([room_dir], "approve")
        target = outside / "x.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-deny"))
        assert "denied by user" in result["error"]
        assert not target.exists()
        assert _classify_write_denial(str(target)) == "needs_approval"

    def test_inside_room_never_prompts(self, room, fence, monkeypatch):
        import tools.approval as approval
        from tools.file_tools import write_file_tool

        def _boom(**kw):
            raise AssertionError("no prompt expected inside the room")

        monkeypatch.setattr(approval, "_run_approval_gate", _boom)
        room_dir, _ = room
        fence([room_dir], "approve")
        target = room_dir / "x.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-in"))
        assert not result.get("error"), result
        assert target.read_text() == "hello\n"

    def test_strict_write_outside_denied_without_prompt(self, room, fence, monkeypatch):
        import tools.approval as approval
        from tools.file_tools import write_file_tool

        def _boom(**kw):
            raise AssertionError("strict mode never prompts")

        monkeypatch.setattr(approval, "_run_approval_gate", _boom)
        room_dir, outside = room
        fence([room_dir], "strict")
        target = outside / "x.txt"
        result = json.loads(write_file_tool(str(target), "hello\n", task_id="fence-gate-strict"))
        assert "denied" in result["error"].lower()
        assert not target.exists()

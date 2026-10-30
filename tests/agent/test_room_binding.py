"""Session → room binding (design §B): every turn works inside one room directory.

Resolution order: a channel linked in the workspace map wins; an unlinked DM works in the agent's
own directory (``<root>/agent``) and is never registered; an unlinked group gets a room created and
linked on its first message: a system id names its directory (``<root>/<id>``), the chat's name is
only its display name. Threads work in their parent channel's room.
"""

import logging
import sqlite3

import pytest

from agent import room_binding as rb
from agent.runtime_cwd import clear_session_cwd, scoped_session_cwd
from gateway.config import Platform
from gateway.run import GatewayRunner
from gateway.session import SessionContext, SessionSource
from gateway.session_context import _UNSET, _VAR_MAP
from phi_cli import workspace_map as wm
from phi_cli.workspace_root import agent_dir, workspace_root
from phi_constants import get_phi_home


def _set_config(text: str) -> None:
    (get_phi_home() / "config.yaml").write_text(text, encoding="utf-8")


def _root_dirs() -> set[str]:
    return {p.name for p in workspace_root().iterdir() if p.is_dir()}


@pytest.fixture(autouse=True)
def _clean_session_context():
    yield
    for var in _VAR_MAP.values():
        var.set(_UNSET)
    clear_session_cwd()
    rb.set_current_room(None)


def _turn(platform, chat_id, chat_type, chat_name="", **extra):
    runner = object.__new__(GatewayRunner)
    source = SessionSource(platform=platform, chat_id=chat_id, chat_type=chat_type, chat_name=chat_name, **extra)
    return runner, SessionContext(source=source, connected_platforms=[], home_channels={})


def test_a_linked_channel_wins_over_the_dm_and_group_rules():
    room = wm.create_room("ops")
    wm.link_channel(room["room_id"], "telegram", "42")
    for chat_type in ("dm", "group"):
        bound = rb.bind_for_channel("telegram", "42", chat_type, "Alice")
        assert bound.room_id == room["room_id"]
        assert bound.dir == workspace_root() / room["room_id"]
        assert bound.source == "link"


@pytest.mark.parametrize("chat_type", ["dm", "direct", "private"])
def test_unknown_dm_binds_agent_dir_without_link(chat_type):
    bound = rb.bind_for_channel("telegram", "777", chat_type, "Alice")
    assert bound.dir == agent_dir()
    assert bound.room_id == wm.ensure_agent_room()["room_id"]
    assert bound.source == "agent"
    # A DM is never registered or given its own directory.
    assert wm.room_for_channel("telegram", "777") is None
    assert _root_dirs() == {"agent"}


def test_unknown_group_creates_and_links_a_room_once():
    bound = rb.bind_for_channel("discord", "555", "group", "Build Chat")
    assert bound.source == "created"
    assert bound.name == "Build Chat"
    assert bound.dir == workspace_root() / bound.room_id and bound.dir.is_dir()
    assert wm.get_room(bound.room_id)["name_source"] == "user"
    assert wm.room_for_channel("discord", "555")["room_id"] == bound.room_id
    assert wm.get_room(bound.room_id)["origin"] == "discord"

    again = rb.bind_for_channel("discord", "555", "group", "Renamed upstream")
    assert (again.room_id, again.source, again.dir) == (bound.room_id, "link", bound.dir)
    assert _root_dirs() == {bound.room_id}

    unnamed = rb.bind_for_channel("discord", "556", "channel", "")
    assert unnamed.dir == workspace_root() / unnamed.room_id
    assert wm.get_room(unnamed.room_id)["name"] == "New chat"
    assert wm.get_room(unnamed.room_id)["name_source"] == "default"
    assert _root_dirs() == {bound.room_id, unnamed.room_id}


def test_threads_bind_to_their_parent_room():
    parent = rb.bind_for_channel("telegram", "-100", "group", "Team")
    topic = rb.bind_for_channel("telegram", "-100", "group", "Team", thread_id="17")
    assert topic.room_id == parent.room_id

    channel = rb.bind_for_channel("discord", "900", "group", "general")
    thread = rb.bind_for_channel("discord", "901", "thread", "a thread", thread_id="901", parent_chat_id="900")
    assert thread.room_id == channel.room_id and thread.dir == channel.dir
    assert wm.room_for_channel("discord", "901") is None


def test_bind_room_id_resolves_rooms_and_refuses_spaces():
    room = wm.create_room("web room")
    bound = rb.bind_room_id(room["room_id"])
    assert (bound.room_id, bound.dir, bound.source) == (room["room_id"], workspace_root() / room["room_id"], "web")
    space = wm.create_space("Projects")
    with pytest.raises(wm.WorkspaceMapError):
        rb.bind_room_id(space["room_id"])
    with pytest.raises(wm.RoomNotFound):
        rb.bind_room_id("!local_nope")


def test_room_context_block_names_space_path_dir_and_fence():
    space = wm.create_space("Projects")
    filed = wm.create_room("esp32", parent_space=space["room_id"])
    assert rb.room_context_block(rb.bind_room_id(filed["room_id"])) == (
        f"Workspace: bound to Projects/esp32 -> {filed['path']} (writes outside need approval).")

    _set_config("workspace:\n  default_fence: strict\n")
    strict = wm.create_room("locked")
    assert rb.room_context_block(rb.bind_room_id(strict["room_id"])) == (
        f"Workspace: bound to Home/locked -> {strict['path']} (writes outside are blocked).")

    _set_config("workspace:\n  default_fence: 'off'\n")
    loose = wm.create_room("loose")
    assert rb.room_context_block(rb.bind_room_id(loose["room_id"])).endswith("(writes outside are not fenced).")


def test_gateway_turn_binds_cwd_and_room_and_clear_resets_them():
    runner, context = _turn(Platform.TELEGRAM, "-1001", "group", "Group")
    tokens = runner._set_session_env(context)
    room = wm.room_for_channel("telegram", "-1001")
    assert room is not None
    assert scoped_session_cwd() == room["path"]
    assert rb.current_room().room_id == room["room_id"]

    runner._clear_session_env(tokens)
    assert rb.current_room() is None
    assert scoped_session_cwd() == ""


def test_gateway_dm_turn_works_in_the_agent_dir():
    runner, context = _turn(Platform.TELEGRAM, "123", "dm", "Alice")
    tokens = runner._set_session_env(context)
    try:
        assert scoped_session_cwd() == str(agent_dir())
        assert rb.current_room().source == "agent"
    finally:
        runner._clear_session_env(tokens)


def test_bind_sessions_off_changes_nothing():
    _set_config("workspace:\n  bind_sessions: false\n")
    runner, context = _turn(Platform.TELEGRAM, "-1001", "group", "Group")
    tokens = runner._set_session_env(context)
    try:
        assert scoped_session_cwd() == ""
        assert rb.current_room() is None
        assert not (get_phi_home() / "workspace_map.db").exists()
    finally:
        runner._clear_session_env(tokens)


@pytest.mark.parametrize("platform", [Platform.LOCAL, Platform.API_SERVER, Platform.WEBHOOK])
def test_non_messaging_surfaces_are_not_bound(platform):
    runner, context = _turn(platform, "x1", "group", "Group")
    tokens = runner._set_session_env(context)
    try:
        assert scoped_session_cwd() == ""
        assert rb.current_room() is None
    finally:
        runner._clear_session_env(tokens)


def test_a_failing_map_never_binds_and_logs_a_warning(monkeypatch, caplog):
    def broken(*_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(wm, "room_for_channel", broken)
    runner, context = _turn(Platform.TELEGRAM, "-1001", "group", "Group")
    with caplog.at_level(logging.WARNING, logger="agent.room_binding"):
        tokens = runner._set_session_env(context)
    try:
        assert scoped_session_cwd() == ""
        assert rb.current_room() is None
        assert any(r.levelno == logging.WARNING for r in caplog.records)
    finally:
        runner._clear_session_env(tokens)


def test_environment_hints_carry_the_room_line(monkeypatch):
    import agent.prompt_builder as pb

    monkeypatch.setattr(pb, "is_wsl", lambda: False)
    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    bound = rb.bind_room_id(wm.create_room("hinted")["room_id"])
    assert "Workspace: bound" not in pb.build_environment_hints()
    token = rb.set_current_room(bound)
    try:
        hints = pb.build_environment_hints()
    finally:
        rb.reset_current_room(token)
    assert rb.room_context_block(bound) in hints
    assert hints.index("Current working directory:") < hints.index("Workspace: bound")


def test_room_agents_md_loads_for_a_non_git_room_dir_and_is_capped(tmp_path):
    from agent.prompt_builder import build_context_files_prompt, drain_truncation_warnings

    room_dir = wm.resolve(wm.create_room("rules room")["room_id"])
    (room_dir / "AGENTS.md").write_text("Answer in haiku.\n", encoding="utf-8")
    assert "Answer in haiku." in build_context_files_prompt(cwd=str(room_dir), skip_soul=True)

    drain_truncation_warnings()
    body = "# Rules\n" + "x" * 9000 + "\nTAIL-MARK"
    (room_dir / "AGENTS.md").write_text(body, encoding="utf-8")
    prompt = build_context_files_prompt(cwd=str(room_dir), skip_soul=True)
    assert "x" * 8000 not in prompt and "TAIL-MARK" in prompt
    warnings = drain_truncation_warnings()
    assert any("8000" in w and "shorten" in w.lower() for w in warnings), warnings

    # The 8000-char cap is for room rules only; any other project keeps the usual budget.
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text(body, encoding="utf-8")
    assert "x" * 9000 in build_context_files_prompt(cwd=str(project), skip_soul=True)


def test_a_bound_turn_fences_writes_to_the_room_and_keeps_approvals_for_the_session():
    from pathlib import Path
    from agent.file_safety import approve_session_write_path, get_session_fence, get_write_denied_error

    outside = Path("/opt/phi_fence_probe/x.txt")  # outside the room AND the temp dir (tests run under it)
    runner, context = _turn(Platform.TELEGRAM, "-1001", "group", "Group")
    context.session_key = "agent:main:telegram:group:-1001"
    tokens = runner._set_session_env(context)
    try:
        mode, roots = get_session_fence()
        room_dir = wm.room_for_channel("telegram", "-1001")["path"]
        assert mode == "approve" and room_dir in roots
        assert get_write_denied_error(room_dir + "/ok.txt") is None
        assert "room's write fence" in (get_write_denied_error(str(outside)) or "")
        assert approve_session_write_path(str(outside.parent))
    finally:
        runner._clear_session_env(tokens)
    assert get_session_fence() == ("off", [])

    tokens = runner._set_session_env(context)  # next turn, same session: the approval holds
    try:
        assert get_write_denied_error(str(outside)) is None
    finally:
        runner._clear_session_env(tokens)


def test_bind_turn_room_points_the_terminal_at_the_room_on_the_local_backend(monkeypatch):
    from tools import terminal_tool as tt

    monkeypatch.delenv("TERMINAL_ENV", raising=False)
    runner, context = _turn(Platform.TELEGRAM, "123", "dm", "Alice")
    tokens = runner._set_session_env(context)
    try:
        rb.bind_turn_room("sess-room-1")
        assert tt.resolve_task_overrides("sess-room-1")["cwd"] == str(agent_dir())
        assert tt.get_session_cwd("sess-room-1") == str(agent_dir())
        tt.record_session_cwd("sess-room-1", "/tmp")  # the agent cd's elsewhere ...
        rb.bind_turn_room("sess-room-1")  # ... a later turn in the same room keeps it
        assert tt.get_session_cwd("sess-room-1") == "/tmp"
    finally:
        runner._clear_session_env(tokens)
        tt._task_env_overrides.pop(tt._qualify_task_key("sess-room-1"), None)
        tt.clear_session_cwd("sess-room-1")


def test_bind_turn_room_leaves_remote_backends_alone(monkeypatch):
    from tools import terminal_tool as tt

    monkeypatch.setenv("TERMINAL_ENV", "ssh")
    runner, context = _turn(Platform.TELEGRAM, "124", "dm", "Bob")
    tokens = runner._set_session_env(context)
    try:
        rb.bind_turn_room("sess-room-2")
        assert "cwd" not in tt.resolve_task_overrides("sess-room-2")
    finally:
        runner._clear_session_env(tokens)

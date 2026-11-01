"""PHI guard: long-lived apps Phi starts go into their own systemd scope, not the service cgroup."""

from unittest.mock import patch

import pytest

import tools.app_scope as app_scope
import tools.process_registry as pr


def _fake_scope(argv, name, env=None):
    return ["SCOPE", *argv], {**(env or {}), "S": "1"}


@pytest.fixture
def under_unit(monkeypatch):
    """A systemd service with a usable user bus."""
    monkeypatch.setenv("INVOCATION_ID", "abc")
    monkeypatch.setattr(app_scope.shutil, "which", lambda name: "/usr/bin/systemd-run")
    monkeypatch.setattr(pr, "_systemd_run_user_scope_available", lambda: True)
    monkeypatch.setattr(pr, "systemd_user_bus_env",
                        lambda env=None: {**(env or {}), "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus"})


@pytest.mark.platforms("linux")
def test_wraps_in_own_scope_without_memory_limit(under_unit):
    argv, env = app_scope.scoped_app_argv(["/usr/bin/chrome", "--x"], "chrome debug", {"A": "1"})
    assert argv[:4] == ["/usr/bin/systemd-run", "--user", "--scope", "--quiet"]
    assert argv[argv.index("--") + 1:] == ["/usr/bin/chrome", "--x"]
    unit = argv[argv.index("--unit") + 1]
    assert unit.startswith("phi-app-chrome-debug-")
    assert "--collect" in argv and "MemoryAccounting=yes" in argv
    assert not any(a.startswith("MemoryMax=") for a in argv)  # the app keeps the memory it had
    assert env is not None and env["A"] == "1" and "DBUS_SESSION_BUS_ADDRESS" in env


@pytest.mark.platforms("linux")
@pytest.mark.parametrize("case", ["no_unit", "no_bus", "no_binary"])
def test_unchanged_launch_when_no_scope_is_possible(under_unit, monkeypatch, case):
    if case == "no_unit":
        monkeypatch.delenv("INVOCATION_ID")
    elif case == "no_bus":
        monkeypatch.setattr(pr, "_systemd_run_user_scope_available", lambda: False)
    else:
        monkeypatch.setattr(app_scope.shutil, "which", lambda name: None)
    env = {"A": "1"}
    assert app_scope.scoped_app_argv(["chrome"], "x", env) == (["chrome"], env)


def test_browser_connect_launches_chrome_through_the_scope(tmp_path, monkeypatch):
    from phi_cli import browser_connect

    seen = {}

    class _Proc:
        pid = 4242

        def poll(self):
            return 0

    def _popen(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env")
        return _Proc()

    monkeypatch.setattr(browser_connect, "chrome_debug_data_dir", lambda: str(tmp_path))
    with patch("tools.app_scope.scoped_app_argv", side_effect=_fake_scope), \
         patch.object(browser_connect, "get_chrome_debug_candidates", return_value=["/usr/bin/chrome"]), \
         patch.object(browser_connect, "is_browser_debug_ready", return_value=False), \
         patch("subprocess.Popen", side_effect=_popen):
        browser_connect.launch_chrome_debug(9222, "Linux")
    assert seen["argv"][:2] == ["SCOPE", "/usr/bin/chrome"]
    assert seen["env"] == {"S": "1"}


@pytest.mark.platforms("posix")
def test_lightpanda_serve_launches_through_the_scope(monkeypatch):
    import tools.browser_lightpanda as lp

    seen = {}

    class _Proc:
        pid = 4343

        def poll(self):
            return 1

    def _popen(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env")
        return _Proc()

    monkeypatch.setattr(lp, "find_lightpanda_binary", lambda: "/opt/lightpanda")
    monkeypatch.setattr(lp, "_pick_free_loopback_port", lambda: 43111)
    monkeypatch.setattr(lp, "_cdp_ready", lambda url: False)
    monkeypatch.setattr(lp, "_browser_env", lambda: {"PATH": "/usr/bin"})
    monkeypatch.setattr(lp.subprocess, "Popen", _popen)
    with patch("tools.app_scope.scoped_app_argv", side_effect=_fake_scope):
        lp.launch_lightpanda("lp_scope")
    assert seen["argv"][:3] == ["SCOPE", "/opt/lightpanda", "serve"]
    assert seen["env"] == {"PATH": "/usr/bin", "S": "1"}


@pytest.mark.platforms("posix")
def test_agent_browser_cli_launches_through_the_scope(tmp_path, monkeypatch):
    from tools import browser_tool_session as session

    seen = {}
    monkeypatch.setattr(session.subprocess, "Popen",
                        lambda argv, **kw: seen.update(argv=argv, env=kw.get("env")) or object())
    with patch("tools.app_scope.scoped_app_argv", side_effect=_fake_scope):
        session._popen_agent_browser(["agent-browser", "open", "x"], {"A": "1"}, str(tmp_path), "t")
    assert seen["argv"] == ["SCOPE", "agent-browser", "open", "x"]
    assert seen["env"] == {"A": "1", "S": "1"}


@pytest.mark.platforms("posix")
def test_browser_harness_cli_launches_through_the_scope(monkeypatch):
    from tools import browser_use_cli as bu

    seen = {}

    class _Proc:
        pid, returncode = 4444, 0

        def communicate(self, input=None, timeout=None):
            return "", ""

    monkeypatch.setattr(bu.subprocess, "Popen", lambda argv, **kw: seen.update(argv=argv, env=kw.get("env")) or _Proc())
    with patch("tools.app_scope.scoped_app_argv", side_effect=_fake_scope):
        bu._run_cli_killing_process_group(["browser-harness"], "print(1)", {"A": "1"}, 5)
    assert seen["argv"] == ["SCOPE", "browser-harness"]
    assert seen["env"] == {"A": "1", "S": "1"}


def test_terminal_prompt_says_how_to_start_long_lived_programs():
    from tools.terminal_tool import TERMINAL_TOOL_DESCRIPTION

    assert "systemd-run --user --scope" in TERMINAL_TOOL_DESCRIPTION
    assert "background=true" in TERMINAL_TOOL_DESCRIPTION


class TestWorkerMemoryLimit:
    GIB = 1024 ** 3

    @pytest.fixture
    def host_60g(self, monkeypatch):
        monkeypatch.setattr(pr.Path, "read_text", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no cgroup")))
        monkeypatch.setattr(pr.os, "sysconf", lambda name: {"SC_PHYS_PAGES": 60 * 262144, "SC_PAGE_SIZE": 4096}[name])
        monkeypatch.delenv("TERMINAL_LOCAL_MEMORY_MAX_MB", raising=False)

    def test_default_is_16_gib(self, host_60g):
        assert pr._worker_memory_max_bytes() == 16 * self.GIB

    def test_zero_means_default(self, host_60g, monkeypatch):
        monkeypatch.setenv("TERMINAL_LOCAL_MEMORY_MAX_MB", "0")
        assert pr._worker_memory_max_bytes() == 16 * self.GIB

    def test_config_may_raise_up_to_half_of_ram(self, host_60g, monkeypatch):
        monkeypatch.setenv("TERMINAL_LOCAL_MEMORY_MAX_MB", str(24 * 1024))
        assert pr._worker_memory_max_bytes() == 24 * self.GIB
        monkeypatch.setenv("TERMINAL_LOCAL_MEMORY_MAX_MB", "999999")
        assert pr._worker_memory_max_bytes() == 30 * self.GIB

    def test_config_key_is_bridged(self):
        from phi_cli.config import TERMINAL_CONFIG_ENV_MAP
        from phi_cli.config_defaults import DEFAULT_CONFIG

        assert DEFAULT_CONFIG["terminal"]["local_memory_max_mb"] == 0
        assert TERMINAL_CONFIG_ENV_MAP["local_memory_max_mb"] == "TERMINAL_LOCAL_MEMORY_MAX_MB"

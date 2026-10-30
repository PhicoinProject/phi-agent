"""v52: gateway turns bind to a room directory (``workspace.bind_sessions``, default on).

An install that already pins its messaging turns to a directory (an explicit ``terminal.cwd``)
keeps today's behaviour: the migration writes ``bind_sessions: false`` for it, once.
"""

import pytest

import phi_yaml as yaml


def _migrate(tmp_path, monkeypatch, config: dict) -> dict:
    from phi_cli.config_migrations import run_migrations

    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump({"_config_version": 51, **config}), encoding="utf-8")
    monkeypatch.setenv("PHI_HOME", str(tmp_path))
    run_migrations(51, {"env_added": [], "config_added": [], "warnings": []}, quiet=True)
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def test_new_installs_bind_sessions_by_default():
    from phi_cli.config import DEFAULT_CONFIG
    from phi_cli.config_migrations import MIGRATIONS

    assert DEFAULT_CONFIG["workspace"]["bind_sessions"] is True
    assert MIGRATIONS[-1][0] == 52 == DEFAULT_CONFIG["_config_version"]


def test_explicit_terminal_cwd_keeps_todays_behaviour(tmp_path, monkeypatch):
    raw = _migrate(tmp_path, monkeypatch, {"terminal": {"cwd": "/srv/project"}, "workspace": {"default_fence": "strict"}})
    assert raw["workspace"] == {"default_fence": "strict", "bind_sessions": False}
    assert raw["terminal"]["cwd"] == "/srv/project"

    # Idempotent: a second pass changes nothing.
    again = _migrate(tmp_path, monkeypatch, raw)
    assert again["workspace"] == raw["workspace"]


def test_missing_workspace_section_is_created_for_an_explicit_cwd(tmp_path, monkeypatch):
    raw = _migrate(tmp_path, monkeypatch, {"terminal": {"cwd": "~/work"}})
    assert raw["workspace"] == {"bind_sessions": False}


@pytest.mark.parametrize("terminal", [{}, {"cwd": "."}, {"cwd": "auto"}, {"cwd": "cwd"}, {"cwd": ""}, {"backend": "local"}])
def test_placeholder_or_absent_cwd_is_left_on_the_default(tmp_path, monkeypatch, terminal):
    raw = _migrate(tmp_path, monkeypatch, {"terminal": terminal} if terminal else {})
    assert "bind_sessions" not in (raw.get("workspace") or {})


def test_an_explicit_bind_sessions_choice_is_kept(tmp_path, monkeypatch):
    raw = _migrate(tmp_path, monkeypatch, {"terminal": {"cwd": "/srv/project"}, "workspace": {"bind_sessions": True}})
    assert raw["workspace"]["bind_sessions"] is True

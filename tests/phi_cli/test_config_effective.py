"""Invariants for ``phi_cli.config_effective.load_user_config_effective`` — the one loader every
defaults-free config reader (gateway runtime, TUI gateway, cron, ``phi send`` bridge, doctor,
bootstrap modules) goes through."""
import textwrap

import pytest

import phi_yaml as yaml
from phi_cli import config, config_effective, managed_scope


@pytest.fixture
def homes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    managed = tmp_path / "managed"
    managed.mkdir()
    monkeypatch.setenv("PHI_HOME", str(home))
    monkeypatch.setenv("PHI_MANAGED_DIR", str(managed))
    monkeypatch.setenv("FIXTURE_USER_KEY", "user-secret")
    monkeypatch.setenv("FIXTURE_MANAGED_URL", "https://managed.example")
    _reset_caches()
    return home, managed


def _reset_caches():
    import phi_cli.config as cfg
    from phi_cli import config_effective, managed_scope

    cfg._LOAD_CONFIG_CACHE.clear()
    cfg._RAW_CONFIG_CACHE.clear()
    config_effective._EFFECTIVE_CACHE.clear()
    config_effective._LAST_GOOD_USER_RAW.clear()
    managed_scope.invalidate_managed_cache()


def _write(path, body):
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    _reset_caches()


USER_YAML = """
    model:
      name: user/model
      api_key: ${FIXTURE_USER_KEY}
    provider: custom
    display:
      skin: user-skin
    """
MANAGED_YAML = """
    model:
      base_url: ${FIXTURE_MANAGED_URL}
    display:
      skin: managed-skin
    """


def test_effective_is_user_plus_managed_plus_env_with_no_defaults(homes):
    """Contract as a fixture: given user config.yaml X, managed overlay Y and env Z, the effective
    dict is exactly this literal — ``${VAR}`` expanded on both layers, managed keys winning,
    root ``provider`` migrated under ``model``, and no DEFAULT_CONFIG key introduced (a missing
    key stays missing). Per-message gateway reads (and the system prompt built from them) are
    pinned by this shape, not by re-running the implementation's primitives."""
    from phi_cli.config_effective import load_user_config_effective

    home, managed = homes
    _write(home / "config.yaml", USER_YAML)
    _write(managed / "config.yaml", MANAGED_YAML)

    effective = load_user_config_effective(home / "config.yaml")

    assert effective == {
        "model": {
            "default": "user/model",
            "provider": "custom",
            "api_key": "user-secret",
            "base_url": "https://managed.example",
        },
        "display": {"skin": "managed-skin"},
    }


def test_broken_yaml_serves_last_good_and_fail_closed_raises(homes):
    """A torn mid-edit write must not silently drop user overrides: the fail-open path serves the last
    successfully parsed user file through the same pipeline; ``fail_closed`` surfaces the error to
    callers that keep their own last-good state."""
    from phi_cli.config_effective import load_user_config_effective

    home, _ = homes
    _write(home / "config.yaml", USER_YAML)
    good = load_user_config_effective(home / "config.yaml")

    (home / "config.yaml").write_text("model: [unterminated", encoding="utf-8")
    _reset_caches_keep_last_good()

    assert load_user_config_effective(home / "config.yaml") == good
    with pytest.raises(yaml.YAMLError):  # the type _refresh_fallback_model's own last-good path keys on
        load_user_config_effective(home / "config.yaml", fail_closed=True)


def test_good_backup_is_written_only_for_the_active_home(homes, tmp_path):
    """Reading ANOTHER profile's config (doctor, TUI cwd lookup) is a read: it must not create
    ``backups/config/`` inside that profile. The active home keeps the last-good copy."""
    from phi_cli.config_effective import load_user_config_effective

    home, _ = homes
    other = tmp_path / "other-profile"
    other.mkdir()
    _write(home / "config.yaml", USER_YAML)
    _write(other / "config.yaml", USER_YAML)

    load_user_config_effective(other / "config.yaml")
    load_user_config_effective(home / "config.yaml")

    assert not (other / "backups").exists()
    assert list((home / "backups" / "config").glob("config.yaml.good.*"))


def _reset_caches_keep_last_good():
    import phi_cli.config as cfg
    from phi_cli import config_effective

    cfg._RAW_CONFIG_CACHE.clear()
    config_effective._EFFECTIVE_CACHE.clear()


# --- PHI guard tests (kept across stable syncs) ---

def test_no_defaults_and_managed_layer_still_applies(homes):
    home, managed = homes
    assert config_effective.load_user_config_effective() == {}
    (managed / "config.yaml").write_text("model:\n  default: managed-model\n")
    assert config_effective.load_user_config_effective() == {"model": {"default": "managed-model"}}
    assert not (home / "config.yaml").exists()


def test_env_change_invalidates_cache_and_return_is_independent(homes, monkeypatch):
    home, managed = homes
    monkeypatch.setenv("TEST_MODEL", "first")
    (home / "config.yaml").write_text("model:\n  default: ${TEST_MODEL}\n")
    result = config_effective.load_user_config_effective()
    assert result["model"]["default"] == "first"
    result["model"]["default"] = "mutated"
    assert config_effective.load_user_config_effective()["model"]["default"] == "first"
    monkeypatch.setenv("TEST_MODEL", "second")
    assert config_effective.load_user_config_effective()["model"]["default"] == "second"


def test_bad_yaml_recovers_but_fail_closed_still_raises(homes):
    home, managed = homes
    path = home / "config.yaml"
    path.write_text("model:\n  default: kept-model\n")
    assert config_effective.load_user_config_effective()["model"]["default"] == "kept-model"
    path.write_text("model: [broken")
    assert config_effective.load_user_config_effective()["model"]["default"] == "kept-model"
    with pytest.raises(yaml.YAMLError):
        config_effective.load_user_config_effective(fail_closed=True)


def test_other_profile_read_does_not_create_backup(homes):
    home, managed = homes
    other = home.parent / "other"
    other.mkdir()
    path = other / "config.yaml"
    path.write_text("model: other-model\n")
    config_effective.load_user_config_effective(path)
    assert not (other / "backups").exists()


def test_gateway_and_tui_consume_same_effective_values_without_writing(homes, monkeypatch):
    from gateway import run
    from tui_gateway import server

    home, managed = homes
    monkeypatch.setattr(run, "_phi_home", home)
    monkeypatch.setattr(server, "_phi_home", home)
    monkeypatch.setenv("TEST_MODEL", "user-model")
    path = home / "config.yaml"
    original = "model:\n  name: ${TEST_MODEL}\ndisplay:\n  show_reasoning: false\n"
    path.write_text(original)
    (managed / "config.yaml").write_text("display:\n  show_reasoning: true\n")
    expected = config_effective.load_user_config_effective(path)
    assert expected["model"]["default"] == "user-model"
    assert expected["display"]["show_reasoning"] is True
    assert run._load_gateway_config(path) == expected
    assert run._load_gateway_runtime_config() == expected
    assert server._load_cfg() == expected
    assert "agent" not in expected
    assert path.read_text() == original


def test_managed_environment_is_not_reexpanded_through_profile_scope(homes, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope

    home, managed = homes
    monkeypatch.setenv("TEST_SHARED_VALUE", "process-value")
    (home / "config.yaml").write_text("user_value: ${TEST_SHARED_VALUE}\n")
    (managed / "config.yaml").write_text("managed_value: ${TEST_SHARED_VALUE}\n")
    token = set_secret_scope({"TEST_SHARED_VALUE": "profile-value"})
    try:
        result = config_effective.load_user_config_effective()
        assert result["user_value"] == "profile-value"
        assert result["managed_value"] == "process-value"
        complete = config.load_config()
        assert complete["user_value"] == "profile-value"
        assert complete["managed_value"] == "process-value"
        monkeypatch.setenv("TEST_SHARED_VALUE", "rotated-process-value")
        refreshed = config_effective.load_user_config_effective()
        assert refreshed["managed_value"] == "rotated-process-value"
        assert refreshed["user_value"] == "profile-value"
        complete = config.load_config()
        assert complete["user_value"] == "profile-value"
        assert complete["managed_value"] == "rotated-process-value"
    finally:
        reset_secret_scope(token)

"""Code execution children inherit the active profile home, not the server default."""

import sys

import pytest

from phi_constants import (
    get_phi_home_override,
    reset_phi_home_override,
    set_phi_home_override,
)
from tools.code_execution_env import _build_child_env


@pytest.fixture
def home_override():
    tokens = []

    def set_home(path):
        tokens.append(set_phi_home_override(path))
        return str(path)

    yield set_home
    for token in reversed(tokens):
        reset_phi_home_override(token)


def child_env():
    return _build_child_env(
        rpc_endpoint="sock",
        rpc_token="test-token",
        tmpdir="/tmp/phi-test",
        child_python=sys.executable,
    )


def test_override_rewrites_stale_default_each_turn(monkeypatch, home_override, tmp_path):
    monkeypatch.setenv("PHI_HOME", "/machine/default/.phi")
    alpha = home_override(tmp_path / "profiles" / "alpha")
    assert child_env()["PHI_HOME"] == alpha
    beta = home_override(tmp_path / "profiles" / "beta with spaces")
    assert child_env()["PHI_HOME"] == beta


def test_no_override_preserves_inherited_home(monkeypatch):
    assert get_phi_home_override() is None
    monkeypatch.setenv("PHI_HOME", "/machine/default/.phi")
    assert child_env()["PHI_HOME"] == "/machine/default/.phi"
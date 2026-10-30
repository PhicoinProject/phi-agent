"""Orphan launcher discovery follows the declared console script names."""

from __future__ import annotations

import textwrap

import pytest
from phi_cli import main_install_repair

pytestmark = pytest.mark.platforms("windows")


@pytest.fixture
def temp_pyproject(tmp_path, monkeypatch):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        textwrap.dedent(
            """\
        [project]
        name = "fake"
        version = "0.0.0"

        [project.scripts]
        phi = "phi_cli.main:main"
        phi-agent = "run_agent:main"
        phi-acp = "acp_adapter.entry:main"
    """
        )
    )
    import phi_cli.main as main_mod

    monkeypatch.setattr(main_mod, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def fake_scripts_dir(tmp_path):
    scripts = tmp_path / "venv" / "Scripts"
    scripts.mkdir(parents=True)
    return scripts


class TestPhiExeShims:
    """The orphan sweep includes declared scripts and the legacy gateway shim."""

    def test_shims_include_declared_console_scripts(
        self, temp_pyproject, fake_scripts_dir
    ):
        names = {path.name for path in main_install_repair._phi_exe_shims(fake_scripts_dir)}

        assert {"phi.exe", "phi-agent.exe", "phi-acp.exe"} <= names
        assert "phi-gateway.exe" in names

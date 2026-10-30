"""Tests for get_phi_home() profile-mode fallback warning.

Regression test for https://github.com/PhicoinProject/phi-agent/issues/18594.

When PHI_HOME is unset but an active_profile file indicates a non-default
profile is active, get_phi_home() should:
  1. STILL return ~/.phi (raising would brick 30+ module-level callers)
  2. Emit a loud one-shot warning to stderr so operators can diagnose
     cross-profile data contamination after the fact.

The warning goes to stderr directly (not through logging) because this
function is called at module-import time from 30+ sites, often before the
logging subsystem has been configured.
"""

from pathlib import Path

import pytest


@pytest.fixture
def fresh_constants(monkeypatch, tmp_path):
    """Import phi_constants fresh and reset the one-shot warn flag."""
    import importlib
    import phi_constants
    importlib.reload(phi_constants)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.delenv("PHI_HOME", raising=False)
    return phi_constants


class TestGetPhiHomeProfileWarning:
    @pytest.mark.platforms("linux")
    def test_classic_mode_no_active_profile_no_warning(
        self, fresh_constants, tmp_path, capsys
    ):
        """Classic mode: no active_profile file → silent, returns ~/.phi."""
        result = fresh_constants.get_phi_home()
        assert result == tmp_path / ".phi"
        assert "PHI_HOME fallback" not in capsys.readouterr().err


    @pytest.mark.platforms("linux")
    def test_named_profile_unset_home_warns_once(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile=coder + PHI_HOME unset → warn loudly, still return fallback."""
        phi_dir = tmp_path / ".phi"
        phi_dir.mkdir()
        (phi_dir / "active_profile").write_text("coder\n")

        result = fresh_constants.get_phi_home()

        # 1. Still returns the fallback — no import-time crash
        assert result == tmp_path / ".phi"
        # 2. Stderr got the warning exactly once
        err = capsys.readouterr().err
        assert err.count("PHI_HOME fallback") == 1
        assert "'coder'" in err

        # 3. One-shot: second and third calls don't re-warn
        fresh_constants.get_phi_home()
        fresh_constants.get_phi_home()
        err2 = capsys.readouterr().err
        assert "PHI_HOME fallback" not in err2

    def test_phi_home_set_suppresses_warning(
        self, fresh_constants, tmp_path, capsys, monkeypatch
    ):
        """Even if active_profile is 'coder', setting PHI_HOME suppresses warning."""
        profile_dir = tmp_path / ".phi" / "profiles" / "coder"
        profile_dir.mkdir(parents=True)
        (tmp_path / ".phi" / "active_profile").write_text("coder\n")
        monkeypatch.setenv("PHI_HOME", str(profile_dir))

        result = fresh_constants.get_phi_home()

        assert result == profile_dir
        assert "PHI_HOME fallback" not in capsys.readouterr().err

    @pytest.mark.platforms("linux")
    def test_unreadable_active_profile_no_crash(
        self, fresh_constants, tmp_path, capsys
    ):
        """active_profile that can't be decoded → fall through silently."""
        phi_dir = tmp_path / ".phi"
        phi_dir.mkdir()
        # Write bytes that aren't valid utf-8
        (phi_dir / "active_profile").write_bytes(b"\xff\xfe\x00\x00")

        result = fresh_constants.get_phi_home()

        assert result == tmp_path / ".phi"
        # Shouldn't crash; shouldn't warn either (can't tell what profile was intended)
        assert "PHI_HOME fallback" not in capsys.readouterr().err


class TestBootReadersBeforeProfileOverride:
    """Readers that run before the CLI applies the sticky ``active_profile`` must not warn.

    ``phi_bootstrap`` points ``TMPDIR`` at the scratch dir of the *process* home during
    import, and ``main._apply_profile_override`` re-homes the process a few lines later. A
    caller that already resolved its home must not send the policy back through
    ``get_phi_home()``: for a sticky-profile user with ``PHI_HOME`` unset in a plain
    shell that lookup falls back to the default profile and warns, on every ``phi``
    command, while nothing lands in the wrong place. Same fix the parser's ``_cfg_path()``
    carries for the ``--no-config`` help string.
    """

    def test_scratch_export_uses_the_process_home_silently(
        self, fresh_constants, tmp_path, capsys
    ):
        """Boot scratch setup: silent, and pointed at the home the bootstrap resolved."""
        phi_dir = tmp_path / ".phi"
        (phi_dir / "profiles" / "coder").mkdir(parents=True)
        (phi_dir / "active_profile").write_text("coder\n")
        capsys.readouterr()  # drop anything the setup above printed

        env = {"PATH": "/usr/bin:/bin"}
        assert fresh_constants.apply_scratch_tmp_env(env) is True

        assert env["TMPDIR"] == str(phi_dir / "cache" / "scratch")
        assert "PHI_HOME fallback" not in capsys.readouterr().err

    def test_explicit_home_scratch_dir_never_reads_the_effective_home(
        self, fresh_constants, tmp_path, capsys
    ):
        """A caller that passes a home (`phi doctor` for another profile) stays silent."""
        phi_dir = tmp_path / ".phi"
        profile_dir = phi_dir / "profiles" / "coder"
        profile_dir.mkdir(parents=True)
        (phi_dir / "active_profile").write_text("coder\n")
        capsys.readouterr()  # drop anything the setup above printed

        scratch = fresh_constants.get_scratch_dir(profile_dir)

        assert scratch == profile_dir / "cache" / "scratch"
        assert scratch.is_dir()
        assert "PHI_HOME fallback" not in capsys.readouterr().err


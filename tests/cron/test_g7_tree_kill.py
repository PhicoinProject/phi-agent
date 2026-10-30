"""G7 — a cron script timeout/cancel must leave ZERO living descendants (PHI port).

Upstream provenance (frozen target 4baf4269ffb1385e2317f4e872b3b8d3128a6199):
  - 2f0f01192df71834c8f6df6cff1f30371fd6b53a
    fix(cron): tree-kill script timeout descendants via agent.deadline.kill_process_tree

PHI gap (read out of PHI source, not inferred from the title):
``cron/scheduler.py::_terminate_cron_script_process`` only signals the
script's own POSIX process GROUP. A grandchild that called ``setsid``
(backgrounded shell jobs, watchdogs) has its own group and survives, so the
job reports failure while an orphan keeps running. Both production call
sites in ``_run_job_script`` — the ownership-lost/cancel path and the script
deadline path — use that group-only helper.

The fix routes both through a new ``_terminate_cron_script_tree`` which
prefers ``agent.deadline.kill_process_tree`` (psutil snapshots the descendant
set BEFORE signalling, so own-session grandchildren are reached) and falls
back to the existing group helper on invalid pid / import error / no signal /
exception.

Prerequisites verified present in PHI before porting: ``agent/deadline.py``
exposes ``kill_process_tree`` and ``pyproject.toml`` already pins psutil.

Deliberate PHI adaptations guarded below:
  PHI-G7-DEV-1  the env var is PHI_CRON_SCRIPT_TIMEOUT (not HERMES_*).
  PHI-G7-DEV-2  an already-exited proc must not be signalled AND must not
                emit a spurious "no signal" warning — mirrors PHI's existing
                ``_terminate_cron_script_process`` early return.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest


@pytest.fixture
def cron_env(tmp_path, monkeypatch):
    """Isolated cron environment with a temp PHI_HOME.

    Mirrors the fixture in tests/cron/test_cron_script.py (it is module-local
    there, not in conftest).
    """
    phi_home = tmp_path / ".phi"
    phi_home.mkdir()
    (phi_home / "cron").mkdir()
    (phi_home / "cron" / "output").mkdir()
    (phi_home / "scripts").mkdir()
    monkeypatch.setenv("PHI_HOME", str(phi_home))

    import cron.jobs as jobs_mod

    monkeypatch.setattr(jobs_mod, "PHI_DIR", phi_home)
    monkeypatch.setattr(jobs_mod, "CRON_DIR", phi_home / "cron")
    monkeypatch.setattr(jobs_mod, "JOBS_FILE", phi_home / "cron" / "jobs.json")
    monkeypatch.setattr(jobs_mod, "OUTPUT_DIR", phi_home / "cron" / "output")

    return phi_home


def _tree_killer(sched):
    """Resolve the tree-kill helper, xfail-free.

    On an unfixed baseline the symbol is absent; the helper-shape tests then
    report that as a plain failure instead of an ImportError-style error, but
    the BEHAVIOURAL proof of this package is
    ``test_timeout_leaves_no_setsid_grandchild``, which fails on the real
    symptom (a surviving own-session grandchild) with no reference to the new
    name at all.
    """
    return getattr(sched, "_terminate_cron_script_tree", None)


class TestScriptTimeoutTreeKill:
    def test_unified_tree_kill_failure_falls_back(self, monkeypatch, caplog):
        """kill_process_tree reporting 'no signal sent' must fall back to the
        group helper rather than silently leaving the tree alive."""
        from agent import deadline
        from cron import scheduler_script as sched

        proc = SimpleNamespace(pid=12345, poll=lambda: None)
        fallback_calls = []
        monkeypatch.setattr(deadline, "kill_process_tree", lambda _pid: False)
        monkeypatch.setattr(
            sched,
            "_terminate_cron_script_process",
            lambda candidate: fallback_calls.append(candidate),
        )

        with caplog.at_level("WARNING", logger=sched.__name__):
            sched._terminate_cron_script_tree(cast("subprocess.Popen", proc))

        assert fallback_calls == [proc]
        assert "falling back to process-group termination" in caplog.text

    def test_tree_kill_exception_falls_back(self, monkeypatch, caplog):
        """A raising kill_process_tree must not propagate out of the
        terminate path — the script still has to be reaped."""
        from agent import deadline
        from cron import scheduler_script as sched

        def _boom(_pid):
            raise RuntimeError("psutil exploded")

        proc = SimpleNamespace(pid=12345, poll=lambda: None)
        fallback_calls = []
        monkeypatch.setattr(deadline, "kill_process_tree", _boom)
        monkeypatch.setattr(
            sched,
            "_terminate_cron_script_process",
            lambda candidate: fallback_calls.append(candidate),
        )

        with caplog.at_level("WARNING", logger=sched.__name__):
            sched._terminate_cron_script_tree(cast("subprocess.Popen", proc))

        assert fallback_calls == [proc]

    def test_invalid_pid_never_reaches_unified_tree_kill(self, monkeypatch, caplog):
        """pid 0 is 'every process in my group' to kill(2) — it must never be
        handed to the tree killer."""
        from agent import deadline
        from cron import scheduler_script as sched

        proc = SimpleNamespace(pid=0, poll=lambda: None)
        tree_kill_calls = []
        fallback_calls = []
        monkeypatch.setattr(
            deadline, "kill_process_tree", lambda pid: tree_kill_calls.append(pid)
        )
        monkeypatch.setattr(
            sched,
            "_terminate_cron_script_process",
            lambda candidate: fallback_calls.append(candidate),
        )

        with caplog.at_level("WARNING", logger=sched.__name__):
            sched._terminate_cron_script_tree(cast("subprocess.Popen", proc))

        assert tree_kill_calls == []
        assert fallback_calls == [proc]
        assert "invalid pid 0" in caplog.text

    def test_already_exited_proc_is_left_alone(self, monkeypatch, caplog):
        """PHI-G7-DEV-2: a script that finished right at the deadline needs no
        signalling, and must not produce a spurious warning."""
        from agent import deadline
        from cron import scheduler_script as sched

        proc = SimpleNamespace(pid=12345, poll=lambda: 0)
        tree_kill_calls = []
        fallback_calls = []
        monkeypatch.setattr(
            deadline,
            "kill_process_tree",
            lambda pid: tree_kill_calls.append(pid) or True,
        )
        monkeypatch.setattr(
            sched,
            "_terminate_cron_script_process",
            lambda candidate: fallback_calls.append(candidate),
        )

        with caplog.at_level("WARNING", logger=sched.__name__):
            sched._terminate_cron_script_tree(cast("subprocess.Popen", proc))

        assert tree_kill_calls == []
        assert fallback_calls == []
        assert caplog.text.strip() == ""

    def test_successful_tree_kill_does_not_also_run_group_kill(self, monkeypatch):
        """Not-too-wide: on success the fallback must NOT also fire, or every
        timeout would double-signal."""
        from agent import deadline
        from cron import scheduler_script as sched

        proc = SimpleNamespace(pid=12345, poll=lambda: None)
        fallback_calls = []
        monkeypatch.setattr(deadline, "kill_process_tree", lambda _pid: True)
        monkeypatch.setattr(
            sched,
            "_terminate_cron_script_process",
            lambda candidate: fallback_calls.append(candidate),
        )

        sched._terminate_cron_script_tree(cast("subprocess.Popen", proc))

        assert fallback_calls == []

    def test_timeout_path_routes_through_tree_kill(self, monkeypatch, cron_env):
        """The script-deadline site must use the tree killer."""
        from cron import scheduler_script as sched

        tree_calls = []

        def _record_and_kill(proc):
            tree_calls.append(proc.pid)
            proc.kill()

        monkeypatch.setattr(
            sched, "_terminate_cron_script_tree", _record_and_kill, raising=False
        )
        monkeypatch.setenv("PHI_CRON_SCRIPT_TIMEOUT", "1")
        monkeypatch.setattr(sched._sched, "_SCRIPT_TIMEOUT", sched._sched._DEFAULT_SCRIPT_TIMEOUT)

        scripts_dir = cron_env / "scripts"
        (scripts_dir / "long_timeout.py").write_text(
            "import time; time.sleep(30)\n", encoding="utf-8"
        )
        ok, out = sched._run_job_script(
            str(scripts_dir / "long_timeout.py"), workdir=str(cron_env)
        )
        assert not ok
        assert "timed out" in out
        assert len(tree_calls) == 1

    def test_cancel_path_also_tree_kills(self, monkeypatch, cron_env):
        """The ownership-lost/cancel site is the timeout site's sibling and
        must go through the same tree kill."""
        from cron import scheduler_script as sched

        tree_calls = []

        def _record_and_kill(proc):
            tree_calls.append(proc.pid)
            proc.kill()

        monkeypatch.setattr(
            sched, "_terminate_cron_script_tree", _record_and_kill, raising=False
        )

        class _Cancelled:
            def is_set(self):
                return True

            def set(self):
                pass

        scripts_dir = cron_env / "scripts"
        (scripts_dir / "long_cancel.py").write_text(
            "import time; time.sleep(30)\n", encoding="utf-8"
        )
        ok, out = sched._run_job_script(
            str(scripts_dir / "long_cancel.py"),
            workdir=str(cron_env),
            cancel_event=_Cancelled(),
        )
        assert not ok
        assert "ownership was lost" in out
        assert len(tree_calls) == 1

    @pytest.mark.live_system_guard_bypass
    def test_timeout_leaves_no_setsid_grandchild(self, cron_env, monkeypatch):
        """Real-process acceptance: the script spawns a grandchild in its OWN
        session. killpg cannot reach it; kill_process_tree must. This is the
        actual symptom the package claims to fix, so it runs for real rather
        than through a mock."""
        psutil = pytest.importorskip(
            "psutil",
            reason="kill_process_tree needs psutil to reach own-session descendants",
        )

        from cron import scheduler_script as sched

        def is_live(pid):
            try:
                process = psutil.Process(pid)
                return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            except (psutil.NoSuchProcess, psutil.ZombieProcess):
                return False

        scripts_dir = cron_env / "scripts"
        pid_file = cron_env / "grandchild.pid"
        (scripts_dir / "spawner.py").write_text(
            "import subprocess, sys, time\n"
            "p = subprocess.Popen(\n"
            "    [sys.executable, '-c', 'import time; time.sleep(30)'],\n"
            "    start_new_session=True,\n"
            "    stdin=subprocess.DEVNULL,\n"
            "    stdout=subprocess.DEVNULL,\n"
            "    stderr=subprocess.DEVNULL,\n"
            ")\n"
            f"open({str(pid_file)!r}, 'w').write(str(p.pid))\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        # PHI-G7-DEV-1: PHI_CRON_SCRIPT_TIMEOUT, not HERMES_*.
        monkeypatch.setenv("PHI_CRON_SCRIPT_TIMEOUT", "2")
        monkeypatch.setattr(sched._sched, "_SCRIPT_TIMEOUT", sched._sched._DEFAULT_SCRIPT_TIMEOUT)

        ok, out = sched._run_job_script(
            str(scripts_dir / "spawner.py"), workdir=str(cron_env)
        )
        assert not ok, f"script should have timed out, got {out!r}"

        deadline = time.monotonic() + 5
        gpid = None
        while time.monotonic() < deadline and gpid is None:
            try:
                gpid = int(pid_file.read_text().strip())
            except (FileNotFoundError, ValueError):
                time.sleep(0.05)
        assert gpid is not None, "spawner never wrote the grandchild pid"

        try:
            deadline = time.monotonic() + 5
            while is_live(gpid) and time.monotonic() < deadline:
                time.sleep(0.05)
            assert not is_live(gpid), (
                f"grandchild pid {gpid} survived the script timeout — the "
                "timeout path orphaned an own-session descendant"
            )
        finally:
            if is_live(gpid):
                try:
                    psutil.Process(gpid).kill()
                except psutil.NoSuchProcess:
                    pass

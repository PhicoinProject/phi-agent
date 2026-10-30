"""One launch's hook consent and Kanban/terminal pins never reach the auto-started shared daemon."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

# Every launch-scoped value a client process may hold when it auto-starts the shared daemon
# (SWEEP_daemon-launch-env.md): consent, Kanban worker pins, the launching turn's session identity,
# human-presence and one-shot markers, a bot-to-bot turn author, a terminal's systemd markers.
LEAKS = {'PHI_ACCEPT_HOOKS': '1', 'PHI_KANBAN_TASK': 't_1', 'PHI_KANBAN_BOARD': 'other',
         'PHI_KANBAN_DB': '/x/kanban.db', 'PHI_SESSION_SOURCE': 'kanban', 'TERMINAL_CWD': '/x',
         'PHI_TENANT': 'acme', 'PHI_SESSION_SOURCE_EXPLICIT': '1', 'PHI_TURN_AUTHOR': '{"handle":"x"}',
         'PHI_INTERACTIVE': '1', 'PHI_GATEWAY_SESSION': '1', 'PHI_SINGLE_QUERY_SESSION': '1',
         'PHI_SESSION_ID': 'launching-turn', 'PHI_SESSION_KEY': 'agent:main:tui:x',
         'PHI_SESSION_PLATFORM': 'tui', 'PHI_SESSION_CHAT_ID': 'c1', 'PHI_CRON_SESSION': '1',
         # A terminal running under a systemd service: not the daemon's own supervisor.
         'INVOCATION_ID': 'terminal-scope', 'JOURNAL_STREAM': '8:1'}


@pytest.mark.platforms("linux")
@pytest.mark.spawns_gateway_lookalike  # stub interpreter records env then exits; reaped below
def test_daemon_does_not_inherit_hook_consent_or_worker_pins(tmp_path, monkeypatch):
    from phi_cli import gateway_runtime_start as start
    home = tmp_path / 'home'
    home.mkdir(mode=0o700)
    witness = home / 'env.json'
    executable = tmp_path / 'owned-interpreter'
    executable.write_text(
        '#!' + sys.executable + '\nimport json, os\n'
        + f'open({str(witness)!r}, "w").write(json.dumps('
        + '{k: os.environ.get(k) for k in ' + repr([*LEAKS, 'PHI_INFERENCE_MODEL']) + '}))\n',
        encoding='utf-8')
    executable.chmod(0o700)
    monkeypatch.setattr(sys, 'executable', str(executable))
    for key, value in {**LEAKS, 'PHI_INFERENCE_MODEL': 'fallback'}.items():
        monkeypatch.setenv(key, value)
    child = start.spawn_unmanaged_gateway(home, deadline=time.monotonic() + 5)
    try:
        assert child.wait(timeout=10) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    seen = json.loads(Path(witness).read_text())
    assert seen == {**dict.fromkeys(LEAKS), 'PHI_INFERENCE_MODEL': 'fallback'}
    assert os.environ['PHI_ACCEPT_HOOKS'] == '1'  # the launching process keeps its own policy

"""Start long-lived apps (browsers, display servers, helper daemons) outside the Phi service's cgroup.

PHI. Under a systemd unit (the gateway or the dashboard service) every child shares the unit's
cgroup: its memory is charged to Phi, and a restart of the unit kills it (``KillMode=mixed``).
Wrapping the launch in ``systemd-run --user --scope`` gives the app its own transient scope, with
memory accounting and no extra limit. ``systemd-run --scope`` execs the app in place, so the Popen
pid IS the app's pid: every pid / process-group based wait, poll and kill keeps working unchanged.

Anywhere else (not Linux, not under a systemd unit, no ``systemd-run`` or no reachable user bus) the
argv and env come back unchanged, i.e. exactly the previous launch.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import uuid
from typing import Optional, Sequence


def scoped_app_argv(argv: Sequence[str], name: str,
                    env: Optional[dict] = None) -> tuple[list[str], Optional[dict]]:
    """``(argv, env)`` that launch *argv* in its own ``phi-app-<name>-<id>.scope`` when possible.

    The returned env carries the user-bus variables ``systemd-run`` needs (a copy of ``env``, or of
    ``os.environ`` when ``env`` is None). Callers keep their own Popen kwargs (``start_new_session``
    included: a scope is a cgroup, not a session).
    """
    argv = list(argv)
    if not sys.platform.startswith("linux") or not os.environ.get("INVOCATION_ID"):
        return argv, env
    binary = shutil.which("systemd-run")
    if not binary:
        return argv, env
    from tools import process_registry as pr

    if not pr._systemd_run_user_scope_available():
        return argv, env
    label = re.sub(r"[^A-Za-z0-9_.-]", "-", name).strip("-")[:40] or "app"
    unit = f"phi-app-{label}-{uuid.uuid4().hex[:8]}"
    no_expand = ["--expand-environment=no"] if pr._SYSTEMD_RUN_NO_EXPAND else []
    scoped = [binary, "--user", "--scope", "--quiet", *no_expand, "--unit", unit, "--collect",
              "--property", "MemoryAccounting=yes", "--", *argv]
    return scoped, pr.systemd_user_bus_env(env)

"""Resolve PHI_HOME for standalone skill scripts.

Skill scripts may run outside the Phi process (e.g. system Python,
nix env, CI) where ``phi_constants`` is not importable.  This module
provides the same ``get_phi_home()`` and ``display_phi_home()``
contracts as ``phi_constants`` without requiring it on ``sys.path``.

When ``phi_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``phi_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``PHI_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from phi_constants import display_phi_home
    from phi_constants import get_phi_home
except (ModuleNotFoundError, ImportError):

    def get_phi_home() -> Path:
        """Return the Phi home directory (default: ~/.phi).

        Mirrors ``phi_constants.get_phi_home()``."""
        val = os.environ.get("PHI_HOME", "").strip()
        return Path(val) if val else Path.home() / ".phi"

    def display_phi_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``phi_constants.display_phi_home()``."""
        home = get_phi_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)

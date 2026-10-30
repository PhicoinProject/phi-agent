"""Resolve PHI_HOME for standalone skill scripts.

Skill scripts may run outside the Phi process (system Python, nix env,
CI) where ``phi_constants`` is not importable.  This module provides the
same ``get_phi_home()`` contract without requiring it on ``sys.path``.

When ``phi_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from phi_constants import get_phi_home
except (ModuleNotFoundError, ImportError):

    def get_phi_home() -> Path:
        """Return the Phi home directory (default: ``~/.phi``)."""
        val = os.environ.get("PHI_HOME", "").strip()
        return Path(val) if val else Path.home() / ".phi"

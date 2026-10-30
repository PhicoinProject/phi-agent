"""Where room directories live: ``workspace.root`` (default ``$PHI_HOME/workspace``).

Every room gets one flat directory under the root, named once at creation (a new room's directory
is its system id) and never renamed. The main agent's own directory is ``<root>/agent``.

Moving the root (design §二 H, :func:`move_root`) renames it on the same filesystem, or copies,
verifies and only then switches ``workspace.root``; the old root is never deleted.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import stat
import time
from pathlib import Path
from typing import Callable, Optional

from phi_constants import get_phi_home

# Directory names a room can never take: the agent's own dir and Phi's per-dir state dir.
RESERVED_DIR_NAMES = frozenset({"agent", ".phi"})


def workspace_config() -> dict:
    """The ``workspace`` config section (defaults merged), never mutated."""
    from phi_cli.config import cfg_get, load_config_readonly
    section = cfg_get(load_config_readonly(), "workspace", default={})
    return section if isinstance(section, dict) else {}


def configured_root() -> str:
    """The raw ``workspace.root`` value; empty means the default under ``$PHI_HOME``."""
    value = workspace_config().get("root")
    return value.strip() if isinstance(value, str) else ""


def root_for(raw: str) -> Path:
    """Where a ``workspace.root`` value points (``~`` expanded, relative under ``$PHI_HOME``,
    empty = ``$PHI_HOME/workspace``), without creating anything."""
    raw = (raw or "").strip()
    root = Path(os.path.expanduser(raw)) if raw else get_phi_home() / "workspace"
    return root if root.is_absolute() else get_phi_home() / root


def workspace_root() -> Path:
    """The workspace root (see :func:`root_for`), created on first use."""
    root = root_for(configured_root())
    root.mkdir(parents=True, exist_ok=True)
    return root


def agent_dir() -> Path:
    """The main agent's directory, ``<root>/agent`` (created)."""
    path = workspace_root() / "agent"
    path.mkdir(exist_ok=True)
    return path


# --- Move workspace (design §二 H) ----------------------------------------------------------------------

MOVE_LOCK_NAME = "workspace_move.lock"
FAILED_MARKER = ".phi_move_failed"
SPACE_MARGIN = 1.1  # free space needed at the target, relative to the workspace size
HASH_LIMIT = 64 * 1024 * 1024  # files up to this size are compared by sha256, larger ones by size
_UNREADABLE_LOCK_GRACE_S = 60  # a lock without a pid is a move still writing it, for this long


class MoveError(ValueError):
    """A workspace move that was refused or failed; ``workspace.root`` is unchanged."""


Progress = Callable[[str, int, int], None]


def move_lock_path() -> Path:
    """``$PHI_HOME/workspace_move.lock``: holds the pid of the process moving the root."""
    return get_phi_home() / MOVE_LOCK_NAME


def move_in_progress() -> bool:
    """True while the move lock names a live process; a stale lock (dead pid) does not count."""
    path = move_lock_path()
    try:
        text = path.read_text(encoding="utf-8").strip()
        age = time.time() - path.stat().st_mtime
    except FileNotFoundError:
        return False
    except OSError:
        return True
    try:
        pid = int(text)
    except ValueError:
        return age < _UNREADABLE_LOCK_GRACE_S
    from phi_cli._subprocess_compat import pid_exists_stdlib
    return pid > 0 and pid_exists_stdlib(pid)


def _raise(exc: OSError) -> None:
    raise exc


def _manifest(root: Path) -> dict[str, tuple]:
    """Relative path → ``("d",)``, ``("f", size)`` or ``("l", link text)``; sockets, fifos and devices
    are skipped (a move does not carry them). Symlinks are never followed."""
    entries: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root, onerror=_raise):
        for name in dirnames + filenames:
            path = os.path.join(dirpath, name)
            mode = os.lstat(path)
            rel = os.path.relpath(path, root)
            if stat.S_ISLNK(mode.st_mode):
                entries[rel] = ("l", os.readlink(path))
            elif stat.S_ISDIR(mode.st_mode):
                entries[rel] = ("d",)
            elif stat.S_ISREG(mode.st_mode):
                entries[rel] = ("f", mode.st_size)
    return entries


def _existing_ancestor(path: Path) -> Path:
    while not os.path.lexists(path) and path.parent != path:
        path = path.parent
    return path


def _same_fs(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


def _size_text(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def plan_move(new_root: str) -> dict:
    """Check a move to ``new_root`` without changing anything: ``{same_fs, bytes, files, from, to}``.

    Refused (:class:`MoveError`): a relative path, the current root, a place inside the current root
    or containing it, an existing file or non-empty directory, an unwritable place, a managed
    install, or less free space than the workspace size × :data:`SPACE_MARGIN`.
    """
    raw = os.path.expanduser(str(new_root or "").strip())
    if not raw or not os.path.isabs(raw):
        raise MoveError("The new workspace root must be an absolute path.")
    target = Path(os.path.normpath(raw))
    old = workspace_root()
    real_old, real_target = old.resolve(), target.resolve()
    if real_target == real_old:
        raise MoveError("That is already the workspace root.")
    if real_target.is_relative_to(real_old) or real_old.is_relative_to(real_target):
        raise MoveError("The new workspace root cannot be inside the current one, or contain it.")
    if os.path.lexists(target):
        if target.is_symlink() or not target.is_dir():
            raise MoveError(f"{target} exists and is not a directory.")
        if any(target.iterdir()):
            raise MoveError(f"{target} is not empty; pick a new or empty directory.")
    anchor = _existing_ancestor(target)
    if not os.access(anchor, os.W_OK | os.X_OK):
        raise MoveError(f"{anchor} is not writable.")
    from phi_cli.config import format_managed_message, is_managed
    if is_managed():
        raise MoveError(format_managed_message("move the workspace"))
    try:
        entries = _manifest(old)
    except OSError as exc:
        raise MoveError(f"Cannot read the current workspace ({exc}).") from exc
    size = sum(e[1] for e in entries.values() if e[0] == "f")
    free = shutil.disk_usage(anchor).free
    if free < size * SPACE_MARGIN:
        raise MoveError(f"Not enough free space at {anchor}: the workspace needs about "
                        f"{_size_text(size * SPACE_MARGIN)}, {_size_text(free)} is free.")
    return {"same_fs": _same_fs(old, anchor), "bytes": size,
            "files": sum(1 for e in entries.values() if e[0] in ("f", "l")),
            "from": str(old), "to": str(target)}


def _take_lock() -> Path:
    path = move_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    for _attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            if move_in_progress():
                break
            with contextlib.suppress(FileNotFoundError):
                path.unlink()  # stale: its process is gone
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(str(os.getpid()))
        return path
    raise MoveError("A workspace move is already running.")


def _release_lock(path: Path) -> None:
    with contextlib.suppress(OSError):
        if path.read_text(encoding="utf-8").strip() == str(os.getpid()):
            path.unlink()


def _copy_root(src: Path, dst: Path, report: Callable[[int], None]) -> None:
    """Copy ``src`` into ``dst``: symlinks as symlinks, modes and mtimes kept, sockets/fifos skipped;
    ``report(n)`` after each file of ``n`` bytes. Directory modes and mtimes are set last, deepest first."""
    dirs = []
    for dirpath, dirnames, filenames in os.walk(src, onerror=_raise):
        target = dst / os.path.relpath(dirpath, src)
        target.mkdir(parents=True, exist_ok=True)
        dirs.append((dirpath, target))
        for name in dirnames + filenames:
            source = os.path.join(dirpath, name)
            st = os.lstat(source)
            if stat.S_ISLNK(st.st_mode):  # os.walk does not descend symlinked directories
                os.symlink(os.readlink(source), target / name)
                with contextlib.suppress(NotImplementedError, OSError):
                    os.utime(target / name, ns=(st.st_atime_ns, st.st_mtime_ns), follow_symlinks=False)
            elif stat.S_ISREG(st.st_mode):
                shutil.copy2(source, target / name)
                report(st.st_size)
    for source, target in reversed(dirs):
        shutil.copystat(source, target)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_copy(src: Path, dst: Path) -> Optional[str]:
    """None when ``dst`` holds what ``src`` holds (file list, sizes, link texts, sha256 up to
    :data:`HASH_LIMIT`), else what differs."""
    want, got = _manifest(src), _manifest(dst)
    got.pop(FAILED_MARKER, None)
    if want != got:
        missing = sorted(set(want) - set(got))
        extra = sorted(set(got) - set(want))
        changed = sorted(rel for rel in set(want) & set(got) if want[rel] != got[rel])
        first = (missing or extra or changed)[0]
        kind = "missing" if missing else "unexpected" if extra else "differs"
        return f"{first} {kind}"
    for rel, entry in want.items():
        if entry[0] == "f" and entry[1] <= HASH_LIMIT and _sha256(src / rel) != _sha256(dst / rel):
            return f"{rel} content differs"
    return None


def _switch_config(new_root: Path) -> None:
    """Point ``workspace.root`` at ``new_root`` through the config writer; other settings stay."""
    from phi_cli import config as config_mod
    with config_mod._CONFIG_LOCK:
        path = config_mod.get_config_path()
        raw = config_mod.read_user_config_raw(path)
        config_mod._ensure_dict(raw, "workspace")["root"] = str(new_root)
        config_mod.atomic_config_write(path, raw)


def _fail(target: Path, message: str) -> MoveError:
    """Mark ``target`` as a failed move (never used as a root) and return the error to raise."""
    with contextlib.suppress(OSError):
        target.mkdir(parents=True, exist_ok=True)
        (target / FAILED_MARKER).write_text(message + "\n", encoding="utf-8")
    return MoveError(message)


def move_root(new_root: str, progress: Optional[Progress] = None, *, config_lock=None) -> dict:
    """Move the workspace root to ``new_root`` and switch ``workspace.root``; returns the plan.

    ``progress(state, done_bytes, total_bytes)`` sees ``copying``, ``verifying``, ``switching`` and
    ``done``. Same filesystem: one rename. Otherwise copy, verify, then switch — a failure before the
    switch leaves the config alone and marks the target with :data:`FAILED_MARKER`. Rooms stored with
    an absolute path are not moved, and the old root is kept. While this runs the move lock tells
    room binding to leave new turns unbound. ``config_lock`` is held around the config switch.
    """
    report = progress or (lambda *_args: None)
    guard = config_lock if config_lock is not None else contextlib.nullcontext()
    lock = _take_lock()
    try:
        plan = plan_move(new_root)
        old, target, total = Path(plan["from"]), Path(plan["to"]), plan["bytes"]
        if plan["same_fs"]:
            report("switching", 0, total)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(old, target)
            except OSError as exc:
                if exc.errno != errno.EXDEV:
                    raise MoveError(f"Could not move the workspace to {target} ({exc.strerror or exc}).") from exc
                plan["same_fs"] = False  # e.g. a bind mount: copy instead
            else:
                try:
                    with guard:
                        _switch_config(target)
                except Exception as exc:
                    try:
                        os.rename(target, old)
                    except OSError:
                        raise MoveError(f"The workspace was moved to {target}, but the config could not be "
                                        f"switched ({exc}); set workspace.root to {target}.") from exc
                    raise MoveError(f"The config could not be switched ({exc}); "
                                    f"the workspace stayed at {old}.") from exc
        if not plan["same_fs"]:
            done = [0]

            def copied(n: int) -> None:
                done[0] += n
                report("copying", done[0], total)

            report("copying", 0, total)
            try:
                _copy_root(old, target, copied)
            except OSError as exc:
                raise _fail(target, f"The workspace copy failed ({str(exc)[:300]}); "
                                    "the workspace root was not changed.") from exc
            report("verifying", done[0], total)
            try:
                problem = _verify_copy(old, target)
            except OSError as exc:
                problem = str(exc)[:300]
            if problem:
                raise _fail(target, f"The copy did not verify ({problem}); the workspace root was not changed.")
            report("switching", total, total)
            try:
                with guard:
                    _switch_config(target)
            except Exception as exc:
                raise _fail(target, f"The copy is complete but the config could not be switched ({exc}); "
                                    "the workspace root was not changed.") from exc
        report("done", total, total)
        return plan
    finally:
        _release_lock(lock)

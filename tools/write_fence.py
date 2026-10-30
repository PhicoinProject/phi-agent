"""Kernel write fence for child processes (Linux Landlock), design §六 kernel layer.

A fenced process may write only beneath the allowed directories plus
``/dev/null``, ``/dev/tty`` and ``/dev/pts``; reads, exec and network are left
alone. The ruleset is inherited across fork/exec, so every grandchild stays
inside the fence, and it cannot be lifted by the process itself.

Launch mechanism: a re-exec helper, not ``preexec_fn``. The gateway runs many
threads, and CPython documents ``preexec_fn`` as unsafe once threads exist (the
child may deadlock on a lock another thread held at fork time); it also forces
``fork()`` instead of ``vfork``/``posix_spawn``. :func:`fence_argv` instead
prefixes the command with ``python -I -S -W ignore <this file> --allow DIR ... -- cmd``:
the helper is a fresh single-threaded process that applies the ruleset to
itself and ``execvp``s the command (same pid, so process-group bookkeeping is
unchanged). It works for any argv, which lets later callers fence their own
spawns. On any failure the helper exits 126 without running the command: a
fenced launch never silently degrades to an unfenced one. The module is
stdlib-only because ``-I`` keeps the project off ``sys.path``.

:func:`make_preexec` returns the in-process "apply" callable the helper uses;
it can also serve as a ``preexec_fn`` for single-threaded callers.
"""

import argparse
import ctypes
import errno
import functools
import os
import platform
import re
import stat
import sys
from typing import Callable, Iterable

# landlock_create_ruleset / landlock_add_rule / landlock_restrict_self come from
# the asm-generic table, identical on every 64-bit arch below; arches missing
# here (32-bit, mips, ...) report the fence as unavailable.
_SYSCALLS = {arch: (444, 445, 446) for arch in (
    "x86_64", "amd64", "aarch64", "arm64", "riscv64", "ppc64le", "s390x", "loongarch64")}

ACCESS_FS = {
    "execute": 1 << 0, "write_file": 1 << 1, "read_file": 1 << 2, "read_dir": 1 << 3,
    "remove_dir": 1 << 4, "remove_file": 1 << 5, "make_char": 1 << 6, "make_dir": 1 << 7,
    "make_reg": 1 << 8, "make_sock": 1 << 9, "make_fifo": 1 << 10, "make_block": 1 << 11,
    "make_sym": 1 << 12, "refer": 1 << 13, "truncate": 1 << 14, "ioctl_dev": 1 << 15,
}
_WRITE_V1 = ("write_file", "remove_dir", "remove_file", "make_char", "make_dir", "make_reg",
             "make_sock", "make_fifo", "make_block", "make_sym")
# Rights the kernel accepts on a rule whose fd is not a directory.
_FILE_RIGHTS = ACCESS_FS["write_file"] | ACCESS_FS["truncate"]
_DEV_FILES = ("/dev/null", "/dev/tty")
_DEV_DIRS = ("/dev/pts",)

_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38
_HELPER_FAILED = 126


class _PathBeneathAttr(ctypes.Structure):
    _layout_ = "ms"  # packed u64+s32; 3.14 warns on a bare _pack_, older versions ignore this
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def handled_write_access(abi: int) -> int:
    """Every filesystem write right the given Landlock ABI can handle (never read/exec/ioctl)."""
    if abi <= 0:
        return 0
    mask = 0
    for name in _WRITE_V1:
        mask |= ACCESS_FS[name]
    if abi >= 2:
        mask |= ACCESS_FS["refer"]
    if abi >= 3:
        mask |= ACCESS_FS["truncate"]
    return mask


def _libc():
    return ctypes.CDLL(None, use_errno=True)


def _syscall(libc, number: int, *args) -> int:
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(number), *(ctypes.c_long(a) if isinstance(a, int) else a for a in args))
    if result < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return result


@functools.cache
def _probe() -> tuple[int, str]:
    """(abi, reason). Never raises."""
    if not sys.platform.startswith("linux"):
        return 0, f"Landlock is Linux-only (platform {sys.platform})"
    machine = platform.machine().lower()
    numbers = _SYSCALLS.get(machine)
    if numbers is None:
        return 0, f"no Landlock syscall numbers for arch {machine}"
    try:
        abi = _syscall(_libc(), numbers[0], None, 0, _CREATE_RULESET_VERSION)
    except OSError as exc:
        reason = {
            errno.ENOSYS: "kernel built without Landlock",
            errno.EOPNOTSUPP: "Landlock disabled at boot (add landlock to lsm=)",
            errno.EPERM: "Landlock syscalls blocked (seccomp/container profile)",
        }.get(exc.errno, f"Landlock probe failed: {exc}")
        return 0, reason
    except Exception as exc:  # ctypes/libc trouble: report, never raise
        return 0, f"Landlock probe failed: {exc}"
    return int(abi), f"Landlock ABI {int(abi)} available"


def landlock_abi() -> int:
    """Running kernel's Landlock ABI version; 0 when unsupported. Never raises."""
    return _probe()[0]


def fence_status() -> dict:
    """``{"kernel": bool, "abi": int, "reason": str}`` for the UI."""
    abi, reason = _probe()
    return {"kernel": abi > 0, "abi": abi, "reason": reason}


def make_preexec(allowed_write_dirs: list[str], *, handled_access: int | None = None) -> Callable[[], None] | None:
    """Return a callable that fences the *calling* process, or None when the ABI is 0.

    Directories get every handled right beneath them; a regular file or device in
    the list gets write/truncate on itself. Paths that do not exist are skipped.
    ``/dev/null``, ``/dev/tty`` and ``/dev/pts`` are always added. ``handled_access``
    narrows the handled rights (default: all write rights of the running ABI).
    The callable raises ``OSError`` if the ruleset cannot be applied.
    """
    abi = landlock_abi()
    if abi <= 0:
        return None
    create, add_rule, restrict = _SYSCALLS[platform.machine().lower()]
    handled = handled_write_access(abi) if handled_access is None else handled_access
    paths = [*allowed_write_dirs, *_DEV_FILES, *_DEV_DIRS]

    def apply() -> None:
        libc = _libc()
        attr = ctypes.c_uint64(handled)  # struct landlock_ruleset_attr, handled_access_fs only
        ruleset = _syscall(libc, create, ctypes.byref(attr), ctypes.sizeof(attr), 0)
        try:
            for path in paths:
                try:
                    fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
                except OSError:
                    continue
                try:
                    full = stat.S_ISDIR(os.fstat(fd).st_mode) and path not in _DEV_DIRS
                    rights = handled if full else handled & _FILE_RIGHTS
                    if rights:
                        rule = _PathBeneathAttr(rights, fd)
                        _syscall(libc, add_rule, ruleset, _RULE_PATH_BENEATH, ctypes.byref(rule), 0)
                finally:
                    os.close(fd)
            if libc.prctl(*(ctypes.c_ulong(a) for a in (_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))) != 0:
                err = ctypes.get_errno()
                raise OSError(err, os.strerror(err))
            _syscall(libc, restrict, ruleset, 0)
        finally:
            os.close(ruleset)

    return apply


def fence_argv(argv: list[str], allowed_write_dirs: list[str]) -> list[str] | None:
    """``argv`` wrapped in the fence helper, or None when the kernel cannot fence."""
    if landlock_abi() <= 0 or not sys.executable:
        return None
    allow = [part for d in allowed_write_dirs for part in ("--allow", d)]
    # -W ignore: the helper's stderr is the command's stderr; it must add nothing to it.
    return [sys.executable, "-I", "-S", "-W", "ignore", os.path.abspath(__file__), *allow, "--", *argv]


def default_package_cache_dirs(env: dict) -> list[str]:
    """Package-manager caches a fenced command may write (pip/uv/go under the XDG cache, npm)."""
    home = env.get("HOME") or os.path.expanduser("~")
    xdg = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
    return [xdg, os.path.join(home, ".npm")]


# Denial lines from coreutils/bash/python: the path is quoted ('..', "..", ‘..’) or,
# for bash redirections, the field before the message (``bash: PATH: Permission denied``).
_DENIAL_RE = re.compile(r"Permission denied|Read-only file system|EACCES|EROFS")
_QUOTED_RE = re.compile(r"""'([^'\n]+)'|"([^"\n]+)"|‘([^’\n]+)’""")
_FIELD_RE = re.compile(r"(?:^|:\s)([^:\s'\"][^:\n]*?):\s*(?:Permission denied|Read-only file system)")
_BARE_PATH_RE = re.compile(r"(/[^\s:'\"]+)")


def _is_under(path: str, roots: Iterable[str]) -> bool:
    return any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots)


def describe_fence_denials(output: str, *, allowed: list[str], room_dirs: list[str], cwd: str, mode: str) -> str | None:
    """A plain note when ``output`` shows a write denied outside the fence, else None."""
    if not output or not _DENIAL_RE.search(output):
        return None
    allowed_real = [os.path.realpath(a) for a in allowed if a]
    blocked: list[str] = []
    for line in output.splitlines():
        if not _DENIAL_RE.search(line):
            continue
        candidates = [next(filter(None, m.groups())) for m in _QUOTED_RE.finditer(line)]
        if not candidates:  # a field with spaces is prose ("cannot create /x"), not a path
            candidates = [c for c in (m.group(1).strip() for m in _FIELD_RE.finditer(line))
                          if c.startswith("/") or " " not in c]
        if not candidates:
            candidates = _BARE_PATH_RE.findall(line)
        for cand in candidates:
            path = os.path.realpath(os.path.join(cwd or "/", os.path.expanduser(cand)))
            if not _is_under(path, allowed_real) and path not in blocked:
                blocked.append(path)
    if not blocked:
        return None
    room = ", ".join(room_dirs)
    shown = ", ".join(blocked[:5]) + (" ..." if len(blocked) > 5 else "")
    if mode == "approve":
        return (f"[room fence] Blocked a write outside {room}: {shown}. "
                "The user can approve this path for the session; until then commands may only write "
                f"inside {room}, the session temp dir and package caches.")
    return (f"[room fence: strict] Blocked a write outside {room}: {shown}. "
            f"This room only allows writes inside {room}, the session temp dir and package caches.")


def main(argv: list[str] | None = None) -> int:
    """Helper entry point: ``--allow DIR ... -- cmd ...``; exec ``cmd`` fenced or exit 126."""
    parser = argparse.ArgumentParser(prog="write_fence", description="Run a command inside the write fence.")
    parser.add_argument("--allow", action="append", default=[], metavar="DIR")
    parser.add_argument("cmd", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("missing command after --")
    try:
        apply = make_preexec(args.allow)
        if apply is None:
            raise OSError(errno.ENOSYS, fence_status()["reason"])
        apply()
    except Exception as exc:
        sys.stderr.write(f"phi write fence: cannot apply ({exc}); command not run\n")
        return _HELPER_FAILED
    try:
        os.execvp(cmd[0], cmd)
    except OSError as exc:
        sys.stderr.write(f"phi write fence: {cmd[0]}: {exc.strerror}\n")
        return 127 if exc.errno == errno.ENOENT else _HELPER_FAILED
    return _HELPER_FAILED  # execvp only returns when patched out


if __name__ == "__main__":
    sys.exit(main())

"""Kernel write fence (tools/write_fence.py) on a real Landlock kernel.

The fence lets a child process write only beneath the allowed dirs (plus
/dev/null, /dev/tty, /dev/pts); reads stay unrestricted. Every denial case is
checked on the filesystem, not just by exit status. The parametrized negative
control proves the checks can tell a complete ruleset from one that leaves
``make_reg`` unhandled.
"""

import os
import shlex
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools import write_fence
from tools.write_fence import describe_fence_denials, fence_argv, fence_status, landlock_abi, make_preexec

REPO = Path(__file__).resolve().parents[2]
_STATUS = fence_status()
needs_landlock = pytest.mark.skipif(not _STATUS["kernel"], reason=f"Landlock unavailable: {_STATUS['reason']}")


@pytest.fixture
def dirs(tmp_path):
    room = tmp_path / "room"
    room.mkdir()
    (room / "seed.txt").write_text("seed\n")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "existing.txt").write_text("keep\n")
    return room, outside


def run_fenced(argv, allow, cwd=None):
    full = fence_argv([str(a) for a in argv], [str(a) for a in allow])
    assert full is not None
    return subprocess.run(full, cwd=cwd, capture_output=True, text=True, timeout=60)


def run_variant(argv, allow, omit=()):
    """Apply a ruleset with ``omit`` rights left unhandled, then exec ``argv`` (fresh process)."""
    code = textwrap.dedent("""
        import os, sys
        from tools import write_fence as wf
        mask = wf.handled_write_access(wf.landlock_abi())
        for name in filter(None, sys.argv[1].split(",")):
            mask &= ~wf.ACCESS_FS[name]
        wf.make_preexec([sys.argv[2]], handled_access=mask)()
        os.execvp(sys.argv[3], sys.argv[3:])
    """)
    return subprocess.run([sys.executable, "-c", code, ",".join(omit), str(allow), *map(str, argv)],
                          cwd=REPO, capture_output=True, text=True, timeout=60)


# --- probing never raises ---------------------------------------------------

def test_status_shape():
    status = fence_status()
    assert set(status) == {"kernel", "abi", "reason"}
    assert isinstance(status["kernel"], bool) and isinstance(status["abi"], int)
    assert status["kernel"] is (status["abi"] > 0) and status["abi"] == landlock_abi()
    assert status["reason"]


def test_syscall_numbers_per_arch():
    for arch in ("x86_64", "aarch64"):
        assert write_fence._SYSCALLS[arch] == (444, 445, 446)
    assert write_fence._SYSCALLS.get("i686") is None


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="arch table is consulted on Linux only")
def test_unsupported_arch_reports_zero(monkeypatch):
    monkeypatch.setattr(write_fence.platform, "machine", lambda: "mips")
    abi, reason = write_fence._probe.__wrapped__()
    assert abi == 0 and "mips" in reason


def test_abi_zero_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(write_fence, "_probe", lambda: (0, "disabled for test"))
    assert landlock_abi() == 0
    assert make_preexec([str(tmp_path)]) is None
    assert fence_argv(["true"], [str(tmp_path)]) is None
    assert fence_status() == {"kernel": False, "abi": 0, "reason": "disabled for test"}


def test_handled_rights_follow_abi():
    f = write_fence.ACCESS_FS
    base = write_fence.handled_write_access(1)
    for name in ("write_file", "remove_dir", "remove_file", "make_char", "make_dir", "make_reg",
                 "make_sock", "make_fifo", "make_block", "make_sym"):
        assert base & f[name], name
    assert not base & (f["refer"] | f["truncate"])
    assert write_fence.handled_write_access(2) & f["refer"]
    assert write_fence.handled_write_access(3) & f["truncate"]
    full = write_fence.handled_write_access(8)
    assert not full & (f["read_file"] | f["read_dir"] | f["execute"] | f["ioctl_dev"])


def test_helper_fails_closed_without_running(monkeypatch, capsys, tmp_path):
    ran = []
    monkeypatch.setattr(write_fence.os, "execvp", lambda *a: ran.append(a))

    def broken(dirs, **kw):
        def apply():
            raise OSError(1, "Operation not permitted")
        return apply

    monkeypatch.setattr(write_fence, "make_preexec", broken)
    assert write_fence.main(["--allow", str(tmp_path), "--", "true"]) == 126
    monkeypatch.setattr(write_fence, "make_preexec", lambda dirs, **kw: None)
    assert write_fence.main(["--allow", str(tmp_path), "--", "true"]) == 126
    assert ran == []
    assert "not run" in capsys.readouterr().err


# --- denial note for the terminal result (pure text) --------------------------

class TestDescribeDenials:
    ROOM = "/work/room"

    def note(self, output, cwd=ROOM, mode="approve", allowed=(ROOM, "/work/tmp")):
        return describe_fence_denials(output, allowed=list(allowed), room_dirs=[self.ROOM], cwd=cwd, mode=mode)

    @pytest.mark.parametrize("output, path", [
        ("bash: /srv/x.txt: Permission denied", "/srv/x.txt"),
        ("touch: cannot touch '/srv/new': Permission denied", "/srv/new"),
        ("mkdir: cannot create directory ‘/srv/d’: Permission denied", "/srv/d"),
        ("PermissionError: [Errno 13] Permission denied: '/srv/p.txt'", "/srv/p.txt"),
        ("ln: failed to create symbolic link '/srv/l': Read-only file system", "/srv/l"),
        ("open /srv/y: EACCES", "/srv/y"),
        ("sh: 1: cannot create /srv/z: Permission denied", "/srv/z"),
        ("bash: line 3: /srv/w: Permission denied", "/srv/w"),
    ])
    def test_outside_denial_named(self, output, path):
        note = self.note(output)
        assert note and "room fence" in note and self.ROOM in note and path in note
        assert "approve" in note

    def test_strict_wording_has_no_approval_offer(self):
        note = self.note("bash: /srv/x.txt: Permission denied", mode="strict")
        assert note and "room fence" in note and self.ROOM in note and "approve" not in note

    def test_relative_path_resolved_against_cwd(self):
        assert self.note("bash: x.txt: Permission denied", cwd="/srv")
        assert self.note("bash: x.txt: Permission denied", cwd=self.ROOM) is None

    @pytest.mark.parametrize("output", [
        "all good",
        "bash: /work/room/locked: Permission denied",
        "cp: cannot create regular file '/work/tmp/a': Permission denied",
        "Permission denied (publickey).",
    ])
    def test_no_note_when_not_the_fence(self, output):
        assert self.note(output) is None


# --- real kernel ------------------------------------------------------------

def _no(path):
    return not os.path.lexists(path)


OUTSIDE_WRITES = {
    "sh_redirect": (lambda r, o: ["sh", "-c", f"echo x > {o}/new.txt"], lambda r, o: _no(o / "new.txt")),
    "sh_append": (lambda r, o: ["sh", "-c", f"echo x >> {o}/existing.txt"],
                  lambda r, o: (o / "existing.txt").read_text() == "keep\n"),
    "python_open": (lambda r, o: [sys.executable, "-c", f"open({str(o / 'new.txt')!r}, 'w').write('x')"],
                    lambda r, o: _no(o / "new.txt")),
    "mkdir": (lambda r, o: ["mkdir", f"{o}/newdir"], lambda r, o: _no(o / "newdir")),
    "mv_out": (lambda r, o: ["mv", f"{r}/seed.txt", f"{o}/seed.txt"],
               lambda r, o: _no(o / "seed.txt") and (r / "seed.txt").exists()),
    # ABI 1 answers EXDEV and mv falls back to copy+unlink: the copy into the room is
    # allowed, the unlink outside is not, so only the outside file is checked.
    "mv_in": (lambda r, o: ["mv", f"{o}/existing.txt", f"{r}/taken.txt"],
              lambda r, o: (o / "existing.txt").exists()),
    "ln_s": (lambda r, o: ["ln", "-s", "/etc/hostname", f"{o}/link"], lambda r, o: _no(o / "link")),
    "truncate": (lambda r, o: ["truncate", "-s", "0", f"{o}/existing.txt"],
                 lambda r, o: (o / "existing.txt").read_text() == "keep\n"),
    "touch": (lambda r, o: ["touch", f"{o}/new"], lambda r, o: _no(o / "new")),
    "rm": (lambda r, o: ["rm", "-f", f"{o}/existing.txt"], lambda r, o: (o / "existing.txt").exists()),
    "child_of_child": (lambda r, o: ["sh", "-c", f"sh -c 'touch {o}/deep'"], lambda r, o: _no(o / "deep")),
}


@needs_landlock
@pytest.mark.parametrize("case", sorted(OUTSIDE_WRITES))
def test_outside_write_denied(dirs, case):
    room, outside = dirs
    build, untouched = OUTSIDE_WRITES[case]
    proc = run_fenced(build(room, outside), [room])
    assert proc.returncode != 0, proc
    assert untouched(room, outside), proc


@needs_landlock
def test_unfenced_control_writes(dirs):
    """The same command without the fence does write: the denial checks are not vacuous."""
    room, outside = dirs
    subprocess.run(["sh", "-c", f"echo x > {outside}/new.txt"], check=True, timeout=30)
    assert (outside / "new.txt").exists()


@needs_landlock
def test_writes_inside_room_work(dirs, tmp_path):
    room, _ = dirs
    script = ("set -e; echo x > a; mkdir d; mv a d/b; ln -s b d/l; truncate -s 0 seed.txt; "
              f"rm d/l; mkfifo d/f; {shlex.quote(sys.executable)} -c \"open('d/p','w').write('y')\"")
    proc = run_fenced(["sh", "-c", script], [room, tmp_path / "missing"], cwd=room)
    assert proc.returncode == 0, proc
    assert (room / "d" / "b").read_text() == "x\n"
    assert (room / "seed.txt").read_text() == ""
    assert (room / "d" / "p").read_text() == "y"


@needs_landlock
def test_reads_outside_and_dev_null_work(dirs):
    room, outside = dirs
    proc = run_fenced(["sh", "-c", f"cat {outside}/existing.txt; ls {outside} >/dev/null; "
                                   "echo gone > /dev/null; echo err > /dev/stderr; echo ok"], [room])
    assert proc.returncode == 0, proc
    assert proc.stdout == "keep\nok\n"
    assert proc.stderr == "err\n"


@needs_landlock
def test_preexec_fn_form(dirs):
    room, outside = dirs
    proc = subprocess.run(["sh", "-c", f"echo x > {room}/in; echo x > {outside}/out"],
                          preexec_fn=make_preexec([str(room)]), capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0 and "Permission denied" in proc.stderr
    assert (room / "in").exists() and _no(outside / "out")


@needs_landlock
@pytest.mark.parametrize("omit, blocked", [((), True), (("make_reg",), False)],
                         ids=["full-ruleset", "wrong-variant-omits-make_reg"])
def test_negative_control_detects_missing_make_reg(dirs, omit, blocked):
    """A ruleset leaving make_reg unhandled lets ``touch outside/new`` through; the check sees it."""
    room, outside = dirs
    proc = run_variant(["touch", f"{outside}/new"], room, omit=omit)
    assert proc.returncode == (1 if blocked else 0), proc
    assert _no(outside / "new") is blocked


# --- LocalEnvironment: terminal commands under the session fence -------------

@needs_landlock
class TestLocalEnvironmentFence:
    @pytest.fixture
    def env(self, dirs, tmp_path, monkeypatch):
        from tools.environments.local import LocalEnvironment

        term_tmp = tmp_path / "term_tmp"
        term_tmp.mkdir()
        # The fence allows the terminal temp dir and TMPDIR; keep both away from tmp_path.
        monkeypatch.setenv("TERMINAL_TEMP_DIR", str(term_tmp))
        monkeypatch.setenv("TMPDIR", str(term_tmp))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
        monkeypatch.delenv("PHI_WRITE_SAFE_ROOT", raising=False)
        room, _ = dirs
        env = LocalEnvironment(cwd=str(room), timeout=30)
        yield env
        env.cleanup()

    @pytest.fixture
    def session(self):
        from agent.file_safety import reset_session_write_roots, set_session_write_roots

        tokens = []
        yield lambda roots, mode: tokens.append(set_session_write_roots([str(r) for r in roots], mode=mode))
        for token in reversed(tokens):
            reset_session_write_roots(token)

    @pytest.mark.parametrize("mode", ["strict", "approve"])
    def test_outside_blocked_with_plain_note(self, env, dirs, session, mode):
        room, outside = dirs
        session([room], mode)
        result = env.execute(f"echo x > {outside}/new.txt", bounded_capture=True)
        assert result["returncode"] != 0
        assert _no(outside / "new.txt")
        assert "room fence" in result["output"] and str(room) in result["output"]
        assert ("approve" in result["output"]) is (mode == "approve")

    def test_note_only_on_terminal_tool_path(self, env, dirs, session):
        room, outside = dirs
        session([room], "approve")
        result = env.execute(f"echo x > {outside}/new.txt")
        assert _no(outside / "new.txt") and "room fence" not in result["output"]

    def test_room_temp_and_session_state_keep_working(self, env, dirs, session, tmp_path):
        room, _ = dirs
        session([room], "strict")
        result = env.execute("mkdir sub && cd sub && echo hi > f && export PHI_FENCE_T=1 && mktemp", bounded_capture=True)
        assert result["returncode"] == 0, result
        assert (room / "sub" / "f").read_text() == "hi\n"
        assert result["output"].strip().startswith(str(tmp_path / "term_tmp"))
        again = env.execute("pwd -P; echo ${PHI_FENCE_T:-unset}", bounded_capture=True)
        assert again["output"].split() == [str((room / "sub").resolve()), "1"]

    def test_approved_path_becomes_writable(self, env, dirs, session):
        from agent.file_safety import approve_session_write_path

        room, outside = dirs
        session([room], "approve")
        assert approve_session_write_path(str(outside))
        result = env.execute(f"echo x > {outside}/new.txt", bounded_capture=True)
        assert result["returncode"] == 0, result
        assert (outside / "new.txt").exists()

    @pytest.mark.parametrize("mode", ["off", None])
    def test_off_or_unset_is_unfenced(self, env, dirs, session, mode):
        room, outside = dirs
        if mode:
            session([room], mode)
        result = env.execute(f"echo x > {outside}/new.txt", bounded_capture=True)
        assert result["returncode"] == 0, result
        assert (outside / "new.txt").exists()

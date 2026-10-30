"""Tests for utils.atomic_json_write — crash-safe JSON file writes."""

import json
import os
from unittest.mock import patch

import pytest

from utils import atomic_json_write


class TestAtomicJsonWrite:
    """Core atomic write behavior."""

    @pytest.mark.skipif(os.name != "posix", reason="POSIX creation permissions")
    @pytest.mark.parametrize("kind", ["credential", "vault", "pairing", "mcp"])
    def test_private_consumers_create_exclusive_temps_and_keep_old_data(self, tmp_path, monkeypatch, kind):
        import stat
        import utils
        from agent.anthropic_credentials import _atomic_write_private_json
        from agent.vault_store import VaultStore

        home = tmp_path / "private"
        if kind == "credential":
            target = home / "credentials.json"
            write = lambda value: _atomic_write_private_json(target, {"value": value})
            read = lambda: json.loads(target.read_text())["value"]
        elif kind in ("pairing", "mcp"):
            from gateway.pairing import _save_json_file
            from tools.mcp_oauth import _write_json

            target = home / "state.json"
            writer = _save_json_file if kind == "pairing" else _write_json
            write = lambda value: writer(target, {"value": value})
            read = lambda: json.loads(target.read_text())["value"]
        else:
            pytest.importorskip("cryptography")
            store = VaultStore(home)
            target = store._vault_path
            write = lambda value: store._write_all([{"value": value}])
            read = lambda: store._read_all()[0]["value"]

        created = []
        real_open = os.open

        def observe_open(path, flags, mode=0o777, *args, **kwargs):
            if flags & os.O_CREAT:
                created.append((flags, mode))
            return real_open(path, flags, mode, *args, **kwargs)

        monkeypatch.setattr(utils.tempfile._os, "open", observe_open)
        write("old")
        assert created
        assert all(flags & os.O_EXCL and mode == 0o600 for flags, mode in created)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        before = set(target.parent.iterdir())
        old_bytes = target.read_bytes()

        def reject_replace(*args):
            raise OSError("simulated disk full")

        monkeypatch.setattr(utils, "atomic_replace", reject_replace)
        with pytest.raises(OSError):
            write("new")
        assert target.read_bytes() == old_bytes
        assert read() == "old"
        assert set(target.parent.iterdir()) == before

    @pytest.mark.parametrize("consumer", ["sessions", "suggestions", "allowlist"])
    def test_consumers_preserve_data_on_replace_failure(self, tmp_path, monkeypatch, consumer):
        import stat
        from agent import shell_hooks
        from cron import suggestions
        from gateway.session_persistence import SessionPersistenceMixin

        home = tmp_path / "records"
        monkeypatch.setenv("PHI_HOME", str(home))
        if consumer == "sessions":
            store = SessionPersistenceMixin()
            store.sessions_dir = home / "sessions"
            target = store.sessions_dir / "sessions.json"
            write = lambda: store._save_sessions_json({"key": "a\udcffb"})
        elif consumer == "suggestions":
            target = home / "cron" / "suggestions.json"
            monkeypatch.setattr(suggestions, "SUGGESTIONS_FILE", target)
            write = lambda: suggestions._save_raw([{"id": "a\udcffb"}])
        else:
            target = home / "hooks" / "allowlist.json"
            monkeypatch.setattr(shell_hooks, "allowlist_path", lambda: target)
            write = lambda: shell_hooks.save_allowlist({"approvals": ["a\udcffb"]})

        write()
        original = target.read_bytes()
        loaded = json.loads(original)
        stored = loaded["key"] if consumer == "sessions" else (
            loaded["suggestions"][0]["id"] if consumer == "suggestions" else loaded["approvals"][0]
        )
        assert stored == "a\udcffb"
        if os.name == "posix":
            assert stat.S_IMODE(target.stat().st_mode) == 0o600

        def reject_replace(*args):
            raise OSError("simulated disk full")

        monkeypatch.setattr("utils.atomic_replace", reject_replace)
        if consumer == "allowlist":
            write()
        else:
            with pytest.raises(OSError, match="simulated disk full"):
                write()
        assert target.read_bytes() == original
        assert list(target.parent.iterdir()) == [target]

    def test_surrogate_escaped_paths_round_trip(self, tmp_path):
        target = tmp_path / "records" / "paths.json"
        payload = {"cwd": "a\udcffb", "plain": "caf\u00e9"}

        atomic_json_write(target, payload)

        assert json.loads(target.read_text(encoding="utf-8")) == payload
        assert list(target.parent.iterdir()) == [target]


    def test_cleans_up_temp_file_on_baseexception(self, tmp_path):
        class SimulatedAbort(BaseException):
            pass

        target = tmp_path / "data.json"
        original = {"preserved": True}
        target.write_text(json.dumps(original), encoding="utf-8")

        with patch("utils.json.dumps", side_effect=SimulatedAbort):
            with pytest.raises(SimulatedAbort):
                atomic_json_write(target, {"new": True})

        tmp_files = [f for f in tmp_path.iterdir() if ".tmp" in f.name]
        assert len(tmp_files) == 0
        assert json.loads(target.read_text(encoding="utf-8")) == original


    def test_concurrent_writes_dont_corrupt(self, tmp_path):
        """Multiple rapid writes should each produce valid JSON."""
        import threading

        target = tmp_path / "concurrent.json"
        errors = []

        def writer(n):
            try:
                atomic_json_write(target, {"writer": n, "data": list(range(100))})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # File should contain valid JSON from one of the writers
        result = json.loads(target.read_text())
        assert "writer" in result
        assert len(result["data"]) == 100

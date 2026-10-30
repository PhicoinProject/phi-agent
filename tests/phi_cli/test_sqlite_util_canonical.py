"""Shared short-lived SQLite connection and transaction contracts."""

import sqlite3
from contextlib import closing

import pytest

from phi_cli.sqlite_util import open_db, transaction


@pytest.mark.parametrize("module_name, attribute", [
    ("agent.verification_evidence", "_connect"),
    ("cron.executions", "_connect"),
    ("cron.incidents", "_connect"),
    ("cron.notepad", "_connect"),
    ("cron.delivery_queue", "_connect"),
    ("gateway.delivery_ledger", "_connect"),
    ("tools.async_delegation", "_connect"),
    ("phi_cli.projects_db", "connect"),
    ("gateway.hosted_rooms_common", "open_sqlite"),
])
def test_store_uses_canonical_connection(tmp_path, monkeypatch, module_name, attribute):
    import importlib
    from phi_cli import sqlite_util

    monkeypatch.setenv("PHI_HOME", str(tmp_path))
    module = importlib.import_module(module_name)
    for name in ("EXECUTIONS_FILE", "NOTEPAD_FILE", "DELIVERY_DB"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, tmp_path / f"{name.lower()}.db")
    if module_name == "cron.incidents":
        monkeypatch.setattr(module._executions, "EXECUTIONS_FILE", tmp_path / "executions.db")
    if module_name in ("agent.verification_evidence", "gateway.delivery_ledger", "tools.async_delegation"):
        monkeypatch.setattr(module, "_db_path", lambda: tmp_path / "state.db")
    calls = []

    def observed_open(path, **kwargs):
        calls.append(kwargs)
        return open_db(path, **kwargs)

    monkeypatch.setattr(sqlite_util, "open_db", observed_open)
    if getattr(module, "open_db", None) is open_db:
        monkeypatch.setattr(module, "open_db", observed_open)
    arguments = (tmp_path / "opened.db",) if module_name in (
        "phi_cli.projects_db", "gateway.hosted_rooms_common",
    ) else ()
    with closing(getattr(module, attribute)(*arguments)) as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] > 0
    assert len(calls) == 1 and calls[0]["db_label"]


def test_commit_rollback_and_close(tmp_path):
    path = tmp_path / "store.db"
    connection = open_db(path, db_label="test", foreign_keys=True, busy_timeout_ms=1234)
    with transaction(connection, immediate=True):
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('committed')")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="rollback"):
        with transaction(open_db(path, db_label="test")) as connection:
            connection.execute("INSERT INTO records VALUES ('rolled back')")
            raise RuntimeError("rollback")
    with closing(sqlite3.connect(path)) as reader:
        assert reader.execute("SELECT value FROM records").fetchall() == [("committed",)]
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_initialization_failure_closes_connection(tmp_path):
    seen = []

    def initialize(connection):
        seen.append(connection)
        raise RuntimeError("initialization failed")

    with pytest.raises(RuntimeError, match="initialization failed"):
        open_db(tmp_path / "failed.db", db_label="test", initialize=initialize)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        seen[0].execute("SELECT 1")


def test_plugin_database_uses_shared_wal_policy(tmp_path, monkeypatch):
    from plugins.plugin_storage import plugin_db
    import phi_state_wal

    monkeypatch.setenv("PHI_HOME", str(tmp_path))
    monkeypatch.setattr(phi_state_wal, "is_sqlite_wal_reset_vulnerable", lambda: False)
    monkeypatch.setattr(phi_state_wal, "resolve_journal_mode", lambda: "wal")
    monkeypatch.setattr(phi_state_wal, "_path_on_cross_vm_fs", lambda path: True)
    with closing(plugin_db("test-plugin")) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
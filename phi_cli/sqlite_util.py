"""Shared SQLite primitives for the small per-profile / board stores."""

from __future__ import annotations

import contextlib
import sqlite3
import time
from pathlib import Path
from typing import Callable, Iterator


def open_db(
    path: Path | str, *, db_label: str, busy_timeout_ms: int = 5000,
    wal: bool = True, foreign_keys: bool = False, synchronous_full: bool = False,
    row_factory=sqlite3.Row, check_same_thread: bool = True, wal_lock_retries: int = 1,
    initialize: Callable[[sqlite3.Connection], None] | None = None,
) -> sqlite3.Connection:
    """Open with shared WAL policy and close on any initialization failure."""
    from phi_state_wal import apply_wal_with_fallback

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=busy_timeout_ms / 1000, check_same_thread=check_same_thread)
    try:
        connection.row_factory = row_factory
        connection.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
        if wal:
            for attempt in range(wal_lock_retries):
                try:
                    apply_wal_with_fallback(connection, db_label=db_label)
                    break
                except sqlite3.OperationalError as error:
                    if str(error).lower() != "database is locked" or attempt + 1 == wal_lock_retries:
                        raise
                    time.sleep(0.01 * (2 ** attempt))
        if foreign_keys:
            connection.execute("PRAGMA foreign_keys=ON")
        if synchronous_full:
            connection.execute("PRAGMA synchronous=FULL")
        if initialize is not None:
            initialize(connection)
    except BaseException:
        connection.close()
        raise
    return connection


@contextlib.contextmanager
def transaction(connection: sqlite3.Connection, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
    """Commit or roll back and always close the short-lived connection."""
    try:
        if immediate:
            connection.execute("BEGIN IMMEDIATE")
        with connection:
            yield connection
    finally:
        connection.close()


def add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE <table> ADD COLUMN <ddl>``, idempotent across races: True when this call added
    it, False on the ``duplicate column name`` a concurrent migrator caused.

    ``column`` is the human-readable name for the call site; ``ddl`` carries the actual definition. See
    #21708.
    """
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
        return True
    except sqlite3.OperationalError as exc:
        if "duplicate column name" in str(exc).lower():
            return False
        raise


@contextlib.contextmanager
def write_txn(conn: sqlite3.Connection):
    """An IMMEDIATE write transaction. The explicit ROLLBACK is guarded so a SQLite auto-rollback
    (no transaction left under EIO / contention / corruption) cannot shadow the original error."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass
        raise
    else:
        conn.execute("COMMIT")

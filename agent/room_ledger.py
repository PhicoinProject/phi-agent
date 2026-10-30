"""Per-room ledger (design §九): an append-only log of decisions, facts, results, blockers, todos, notes and
steps at ``<room_dir>/.phi/ledger.db``, searchable with :mod:`agent.fact_search`.

Rows are never edited in place: a correction is a new row that supersedes the old one, and ``mark_done`` only
closes a todo or blocker. Several processes (the room session and its subagents) may append at once.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path

from agent import fact_search

KINDS = ("decision", "fact", "result", "blocker", "todo", "note", "step")
STATUSES = ("active", "superseded", "done")

_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        session_id TEXT,
        actor TEXT NOT NULL DEFAULT 'agent',
        kind TEXT NOT NULL CHECK (kind IN ({', '.join(repr(k) for k in KINDS)})),
        text TEXT NOT NULL,
        keywords TEXT NOT NULL DEFAULT '',
        refs TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ({', '.join(repr(s) for s in STATUSES)})),
        supersedes INTEGER,
        task_id TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS entries_status_kind_ts ON entries(status, kind, ts)",
    "CREATE INDEX IF NOT EXISTS entries_supersedes ON entries(supersedes)",
)


def _keywords(value: str | Iterable[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(v).strip() for v in value if str(v).strip())


def _row(row: Mapping) -> dict:
    out = dict(row)
    if isinstance(out.get("refs"), str):
        try:
            out["refs"] = json.loads(out["refs"])
        except ValueError:
            out["refs"] = []
    return out


class Ledger(fact_search.FactStore):
    """The ledger of one room directory."""

    DB_LABEL = "ledger.db"
    SCHEMA = _SCHEMA

    def __init__(self, room_dir: Path | str, *, half_life_days: float = fact_search.DEFAULT_HALF_LIFE_DAYS):
        self.room_dir = Path(room_dir)
        self.half_life_days = half_life_days
        super().__init__(self.room_dir / ".phi" / "ledger.db")

    @staticmethod
    def _prepare(text: str, kind: str, keywords, refs, actor: str, session_id, task_id, ts) -> tuple:
        if kind not in KINDS:
            raise ValueError(f"ledger kind must be one of {', '.join(KINDS)}, not {kind!r}")
        text = (text or "").strip()
        if not text:
            raise ValueError("ledger entry text must not be empty")
        return (time.time() if ts is None else float(ts), session_id, actor or "agent", kind, text,
                _keywords(keywords), json.dumps(list(refs or ()), ensure_ascii=False), task_id)

    def _insert(self, conn, values: tuple, supersedes: int | None = None) -> int:
        cur = conn.execute(
            "INSERT INTO entries(ts, session_id, actor, kind, text, keywords, refs, task_id, supersedes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*values, supersedes))
        entry_id = cur.lastrowid
        fact_search.index_row(conn, "entries", entry_id, values[4], values[5])
        return entry_id

    def add(self, text: str, kind: str = "note", *, keywords: str | Iterable[str] = (), refs: Iterable[str] = (),
            actor: str = "agent", session_id: str | None = None, task_id: str | None = None,
            ts: float | None = None) -> int:
        """Append one entry and return its id."""
        values = self._prepare(text, kind, keywords, refs, actor, session_id, task_id, ts)
        with self._writing() as conn:
            return self._insert(conn, values)

    def add_many(self, entries: Iterable[Mapping]) -> list[int]:
        """Append several entries (mappings of :meth:`add`'s arguments) in one transaction."""
        prepared = [self._prepare(e["text"], e.get("kind", "note"), e.get("keywords"), e.get("refs"),
                                  e.get("actor", "agent"), e.get("session_id"), e.get("task_id"), e.get("ts"))
                    for e in entries]
        with self._writing() as conn:
            return [self._insert(conn, values) for values in prepared]

    def supersede(self, old_id: int, text: str, *, kind: str | None = None,
                  keywords: str | Iterable[str] | None = None, refs: Iterable[str] = (), actor: str = "agent",
                  session_id: str | None = None, task_id: str | None = None, ts: float | None = None) -> int:
        """Record ``text`` as the correction of ``old_id``; kind, keywords and task default to the old row's."""
        with self._writing() as conn:
            old = conn.execute("SELECT * FROM entries WHERE id = ?", (old_id,)).fetchone()
            if old is None:
                raise KeyError(f"no ledger entry #{old_id}")
            if old["status"] == "superseded":
                raise ValueError(f"ledger entry #{old_id} is already superseded")
            values = self._prepare(text, kind or old["kind"], old["keywords"] if keywords is None else keywords,
                                   refs, actor, session_id, old["task_id"] if task_id is None else task_id, ts)
            new_id = self._insert(conn, values, supersedes=old_id)
            conn.execute("UPDATE entries SET status = 'superseded' WHERE id = ?", (old_id,))
            return new_id

    def mark_done(self, entry_id: int) -> bool:
        """Close an active entry; False when it is missing or not active."""
        with self._writing() as conn:
            cur = conn.execute("UPDATE entries SET status = 'done' WHERE id = ? AND status = 'active'", (entry_id,))
            return cur.rowcount == 1

    def get(self, entry_id: int) -> dict | None:
        with self._reading() as conn:
            row = conn.execute(
                "SELECT e.*, (SELECT n.id FROM entries n WHERE n.supersedes = e.id ORDER BY n.id DESC LIMIT 1) "
                "AS superseded_by FROM entries e WHERE e.id = ?", (entry_id,)).fetchone()
        return None if row is None else _row(row)

    def search(self, q: str, k: int = 8, include_superseded: bool = False, *, kinds: Iterable[str] | None = None,
               rerank: bool = True) -> list[dict]:
        """Best entries for ``q``; done entries stay findable, superseded ones only when asked."""
        statuses = STATUSES if include_superseded else ("active", "done")
        where = f"e.status IN ({','.join('?' * len(statuses))})"
        params: list = list(statuses)
        if kinds is not None:
            kinds = tuple(kinds)
            if not kinds:
                return []
            where += f" AND e.kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        with self._reading() as conn:
            hits = fact_search.search(conn, q, where=where, params=params, ts_key="ts", k=k,
                                      half_life_days=self.half_life_days, rerank=rerank)
        return [_row(h) for h in hits]

    def recent(self, kinds: Iterable[str] = ("decision",), limit: int = 10) -> list[dict]:
        """Newest active entries of ``kinds``."""
        kinds = tuple(kinds)
        if not kinds or limit <= 0:
            return []
        with self._reading() as conn:
            rows = conn.execute(
                f"SELECT * FROM entries WHERE status = 'active' AND kind IN ({','.join('?' * len(kinds))}) "
                "ORDER BY ts DESC, id DESC LIMIT ?", (*kinds, limit)).fetchall()
        return [_row(r) for r in rows]

    def open_items(self, limit: int = 10) -> list[dict]:
        """Active blockers, then active todos, newest first within each."""
        if limit <= 0:
            return []
        with self._reading() as conn:
            rows = conn.execute(
                "SELECT * FROM entries WHERE status = 'active' AND kind IN ('blocker', 'todo') "
                "ORDER BY kind = 'todo', ts DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [_row(r) for r in rows]

    def timeline(self, kinds: Iterable[str] | None = None, include_superseded: bool = False,
                 limit: int = 50) -> list[dict]:
        """Newest entries first, each with ``superseded_by``; superseded ones only when asked."""
        statuses = STATUSES if include_superseded else ("active", "done")
        where = f"e.status IN ({','.join('?' * len(statuses))})"
        params: list = list(statuses)
        if kinds is not None:
            kinds = tuple(kinds)
            if not kinds:
                return []
            where += f" AND e.kind IN ({','.join('?' * len(kinds))})"
            params += kinds
        if limit <= 0:
            return []
        with self._reading() as conn:
            rows = conn.execute(
                "SELECT e.*, (SELECT n.id FROM entries n WHERE n.supersedes = e.id ORDER BY n.id DESC LIMIT 1) "
                f"AS superseded_by FROM entries e WHERE {where} ORDER BY e.ts DESC, e.id DESC LIMIT ?",
                (*params, limit)).fetchall()
        return [_row(r) for r in rows]

    def export_markdown(self) -> str:
        """The whole ledger as Markdown, newest first, grouped by local day."""
        with self._reading() as conn:
            rows = [_row(r) for r in conn.execute(
                "SELECT e.*, (SELECT n.id FROM entries n WHERE n.supersedes = e.id ORDER BY n.id DESC LIMIT 1) "
                "AS superseded_by FROM entries e ORDER BY e.ts DESC, e.id DESC")]
        lines = [f"# Ledger — {self.room_dir.name}"]
        day = None
        for row in rows:
            when = datetime.fromtimestamp(row["ts"])
            if when.strftime("%Y-%m-%d") != day:
                day = when.strftime("%Y-%m-%d")
                lines += ["", f"## {day}", ""]
            marks = []
            if row["status"] == "superseded":
                marks.append(f"(superseded by #{row['superseded_by']})" if row["superseded_by"] else "(superseded)")
            elif row["status"] == "done":
                marks.append("(done)")
            if row["supersedes"]:
                marks.append(f"(replaces #{row['supersedes']})")
            first, *rest = row["text"].splitlines() or [""]
            head = " ".join([f"- #{row['id']} {when:%H:%M} {row['kind']}", *marks])
            lines.append(f"{head} — {first}")
            lines += [f"  {line}" for line in rest]
            extras = []
            if row["keywords"]:
                extras.append(f"keywords: {row['keywords']}")
            if row["refs"]:
                extras.append("refs: " + ", ".join(str(r) for r in row["refs"]))
            if extras:
                lines.append("  " + " · ".join(extras))
        return "\n".join(lines) + "\n"


def ledger_ref(entry_id: int) -> str:
    """How summaries and injected context cite an entry: ``#<id>``."""
    return f"#{int(entry_id)}"


_OPEN: dict[Path, Ledger] = {}
_OPEN_LOCK = threading.Lock()


def open_ledger(room_dir: Path | str, *, create: bool = True) -> Ledger | None:
    """The process-wide Ledger of ``room_dir``; with ``create=False`` None while the room has no ledger file."""
    key = Path(room_dir).resolve()
    if not create and not (key / ".phi" / "ledger.db").is_file():
        return None
    with _OPEN_LOCK:
        ledger = _OPEN.get(key)
        if ledger is not None and ledger._conn is not None and not ledger.path.is_file():
            ledger.close()  # the file was removed under an open handle: start a new one
            ledger = None
        if ledger is None:
            ledger = _OPEN[key] = Ledger(key)
        return ledger

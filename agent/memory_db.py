"""Global memory store (design §十) at ``<PHI_HOME>/memory.db``.

``hard`` entries are always in the prompt and share a per-target character budget (entries joined by
``ENTRY_DELIMITER`` count against it, like the MEMORY.md/USER.md files they replace). ``soft`` entries are
unbounded and recalled per message by relevance under a character budget. Edits never rewrite a row: a
replacement supersedes it, a removal archives it.
"""

from __future__ import annotations

import difflib
import time
from collections.abc import Callable, Iterable
from pathlib import Path

from agent import fact_search
from phi_constants import get_phi_home

TARGETS = ("memory", "user")
TIERS = ("hard", "soft")
STATUSES = ("active", "superseded", "archived")
KINDS = ("rule", "skill", "identity", "fact", "preference", "note")
ENTRY_DELIMITER = "\n§\n"
HARD_LIMIT_CHARS = 4000
SOFT_BUDGET_CHARS = 4000
SOFT_MAX_CHARS = 8000
SOFT_MIN_COVERAGE = 0.34
SOFT_RECALL_CANDIDATES = 64

_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        target TEXT NOT NULL CHECK (target IN ({', '.join(repr(t) for t in TARGETS)})),
        tier TEXT NOT NULL CHECK (tier IN ({', '.join(repr(t) for t in TIERS)})),
        kind TEXT NOT NULL DEFAULT 'note',
        text TEXT NOT NULL,
        keywords TEXT NOT NULL DEFAULT '',
        priority INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ({', '.join(repr(s) for s in STATUSES)})),
        supersedes INTEGER,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        last_used_at REAL,
        use_count INTEGER NOT NULL DEFAULT 0,
        source_session TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS entries_target_tier_status ON entries(target, tier, status)",
    "CREATE INDEX IF NOT EXISTS entries_supersedes ON entries(supersedes)",
)
_HARD_ORDER = "ORDER BY priority DESC, created_at, id"


class MemoryFullError(ValueError):
    """A hard entry would push its target's always-on block past the limit."""


def _keywords(value: str | Iterable[str] | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    return " ".join(str(v).strip() for v in value if str(v).strip())


def _check(target: str | None = None, tier: str | None = None, kind: str | None = None) -> None:
    if target is not None and target not in TARGETS:
        raise ValueError(f"memory target must be one of {', '.join(TARGETS)}, not {target!r}")
    if tier is not None and tier not in TIERS:
        raise ValueError(f"memory tier must be one of {', '.join(TIERS)}, not {tier!r}")
    if kind is not None and kind not in KINDS:
        raise ValueError(f"memory kind must be one of {', '.join(KINDS)}, not {kind!r}")


def _text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise ValueError("memory entry text must not be empty")
    return text


def _split(raw: str | None) -> list[str]:
    """MEMORY.md / USER.md text as stripped, non-empty entries."""
    parts = (p.strip() for p in (raw or "").replace("\r\n", "\n").split(ENTRY_DELIMITER))
    return [p for p in parts if p]


class MemoryDB(fact_search.FactStore):
    """The global hard/soft memory of one Phi home."""

    DB_LABEL = "memory.db"
    SCHEMA = _SCHEMA

    def __init__(self, path: Path | str | None = None, *, hard_limit_chars: int = HARD_LIMIT_CHARS,
                 half_life_days: float = fact_search.DEFAULT_HALF_LIFE_DAYS, limits: dict[str, int] | None = None):
        super().__init__(get_phi_home() / "memory.db" if path is None else path)
        self.hard_limit_chars = hard_limit_chars
        self.half_life_days = half_life_days
        self.limits = dict(limits or {})  # per-target hard limits (memory_char_limit / user_char_limit)

    def limit_for(self, target: str) -> int:
        return int(self.limits.get(target, self.hard_limit_chars))

    # ── hard block ───────────────────────────────────────────────────────────────

    @staticmethod
    def _hard_texts(conn, target: str, exclude_id: int | None = None) -> list[str]:
        rows = conn.execute(f"SELECT id, text FROM entries WHERE target = ? AND tier = 'hard' AND status = 'active' "
                            f"{_HARD_ORDER}", (target,)).fetchall()
        return [r["text"] for r in rows if r["id"] != exclude_id]

    def _ensure_fits(self, conn, target: str, text: str, exclude_id: int | None = None) -> None:
        total = len(ENTRY_DELIMITER.join([*self._hard_texts(conn, target, exclude_id), text]))
        limit = self.limit_for(target)
        if total > limit:
            raise MemoryFullError(
                f"the always-on {target} block would use {total}/{limit} chars; merge or demote "
                "entries first (replace one with a merged text, or demote one to soft recall)")

    def hard_block(self, target: str, limit_chars: int | None = None) -> str:
        """Active hard entries, highest priority then oldest first, joined by the delimiter; entries that would
        push the block past ``limit_chars`` are left out whole."""
        _check(target)
        limit = self.limit_for(target) if limit_chars is None else limit_chars
        with self._reading() as conn:
            texts = self._hard_texts(conn, target)
        block = ""
        for text in texts:
            candidate = f"{block}{ENTRY_DELIMITER}{text}" if block else text
            if len(candidate) <= limit:
                block = candidate
        return block

    def hard_usage(self, target: str) -> tuple[int, int]:
        """(chars used by the hard block, limit)."""
        _check(target)
        with self._reading() as conn:
            return len(ENTRY_DELIMITER.join(self._hard_texts(conn, target))), self.limit_for(target)

    # ── writes ───────────────────────────────────────────────────────────────────

    def _insert(self, conn, *, target: str, tier: str, kind: str, text: str, keywords: str, priority: int,
                supersedes: int | None = None, created_at: float | None = None, last_used_at: float | None = None,
                use_count: int = 0, source_session: str | None = None) -> int:
        now = time.time()
        cur = conn.execute(
            "INSERT INTO entries(target, tier, kind, text, keywords, priority, supersedes, created_at, updated_at, "
            "last_used_at, use_count, source_session) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (target, tier, kind, text, keywords, int(priority), supersedes, now if created_at is None else created_at,
             now, last_used_at, use_count, source_session))
        fact_search.index_row(conn, "entries", cur.lastrowid, text, keywords)
        return cur.lastrowid

    @staticmethod
    def _active_text(conn, target: str, text: str):
        return conn.execute("SELECT id FROM entries WHERE target = ? AND status = 'active' AND text = ? LIMIT 1",
                            (target, text)).fetchone()

    def add(self, target: str, tier: str, text: str, kind: str = "note", keywords: str | Iterable[str] = (),
            priority: int = 0, *, source_session: str | None = None) -> int:
        """Store an entry and return its id (the existing id when the same text is already active)."""
        _check(target, tier, kind)
        text = _text(text)
        with self._writing() as conn:
            existing = self._active_text(conn, target, text)
            if existing is not None:
                return existing["id"]
            if tier == "hard":
                self._ensure_fits(conn, target, text)
            return self._insert(conn, target=target, tier=tier, kind=kind, text=text, keywords=_keywords(keywords),
                                priority=priority, source_session=source_session)

    @staticmethod
    def _resolve(conn, entry: int | str, target: str | None):
        """The active row named by id, exact text, or a unique substring of its text."""
        if isinstance(entry, bool) or not isinstance(entry, (int, str)):
            raise TypeError("memory entry must be an id or a text fragment")
        scope, params = ("status = 'active'", []) if target is None else ("status = 'active' AND target = ?", [target])
        if isinstance(entry, int):
            row = conn.execute(f"SELECT * FROM entries WHERE id = ? AND {scope}", (entry, *params)).fetchone()
            if row is None:
                raise LookupError(f"no active memory entry #{entry}")
            return row
        needle = entry.strip()
        if not needle:
            raise ValueError("memory entry text fragment must not be empty")
        rows = conn.execute(f"SELECT * FROM entries WHERE text = ? AND {scope}", (needle, *params)).fetchall()
        if not rows:
            rows = conn.execute(f"SELECT * FROM entries WHERE instr(text, ?) > 0 AND {scope}",
                                (needle, *params)).fetchall()
        if not rows:
            raise LookupError(f"no active memory entry matches {needle[:60]!r}")
        if len(rows) > 1:
            raise ValueError(f"{len(rows)} active memory entries match {needle[:60]!r}; use a longer fragment or an id")
        return rows[0]

    def _supersede(self, conn, old, new_text: str, *, keywords: str | None = None, kind: str | None = None,
                   priority: int | None = None, source_session: str | None = None) -> int:
        new_id = self._insert(
            conn, target=old["target"], tier=old["tier"], kind=kind or old["kind"], text=new_text,
            keywords=old["keywords"] if keywords is None else keywords,
            priority=old["priority"] if priority is None else priority, supersedes=old["id"],
            created_at=old["created_at"], last_used_at=old["last_used_at"], use_count=old["use_count"],
            source_session=source_session)
        conn.execute("UPDATE entries SET status = 'superseded', updated_at = ? WHERE id = ?", (time.time(), old["id"]))
        return new_id

    def replace(self, entry: int | str, new_text: str, *, target: str | None = None,
                keywords: str | Iterable[str] | None = None, kind: str | None = None, priority: int | None = None,
                source_session: str | None = None) -> int:
        """Supersede ``entry`` with ``new_text`` (same tier and place in the block); returns the new id."""
        _check(target, kind=kind)
        new_text = _text(new_text)
        with self._writing() as conn:
            old = self._resolve(conn, entry, target)
            if old["tier"] == "hard":
                self._ensure_fits(conn, old["target"], new_text, exclude_id=old["id"])
            return self._supersede(conn, old, new_text, keywords=None if keywords is None else _keywords(keywords),
                                   kind=kind, priority=priority, source_session=source_session)

    def remove(self, entry: int | str, *, target: str | None = None) -> int:
        """Archive ``entry``; returns its id."""
        with self._writing() as conn:
            row = self._resolve(conn, entry, target)
            conn.execute("UPDATE entries SET status = 'archived', updated_at = ? WHERE id = ?", (time.time(), row["id"]))
            return row["id"]

    def promote(self, entry: int | str, *, target: str | None = None) -> int:
        """Move a soft entry into the hard block (subject to the limit); returns its id."""
        with self._writing() as conn:
            row = self._resolve(conn, entry, target)
            if row["tier"] != "hard":
                self._ensure_fits(conn, row["target"], row["text"])
                conn.execute("UPDATE entries SET tier = 'hard', updated_at = ? WHERE id = ?", (time.time(), row["id"]))
            return row["id"]

    def demote(self, entry: int | str, *, target: str | None = None) -> int:
        """Move a hard entry to soft recall; returns its id."""
        with self._writing() as conn:
            row = self._resolve(conn, entry, target)
            conn.execute("UPDATE entries SET tier = 'soft', updated_at = ? WHERE id = ?", (time.time(), row["id"]))
            return row["id"]

    def set_priority(self, entry: int | str, priority: int, *, target: str | None = None) -> int:
        """Pin (priority > 0: first in the block) or unpin an entry in place; returns its id."""
        with self._writing() as conn:
            row = self._resolve(conn, entry, target)
            conn.execute("UPDATE entries SET priority = ?, updated_at = ? WHERE id = ?",
                         (int(priority), time.time(), row["id"]))
            return row["id"]

    def archive_all(self, target: str | None = None) -> int:
        """Archive every active entry (of ``target``); returns how many."""
        _check(target)
        scope, params = ("", ()) if target is None else (" AND target = ?", (target,))
        with self._writing() as conn:
            return conn.execute(f"UPDATE entries SET status = 'archived', updated_at = ? WHERE status = 'active'{scope}",
                                (time.time(), *params)).rowcount

    @staticmethod
    def _tier_rows(conn, target: str, tier: str) -> list:
        return conn.execute(f"SELECT * FROM entries WHERE target = ? AND tier = ? AND status = 'active' {_HARD_ORDER}",
                            (target, tier)).fetchall()

    def _place(self, conn, target: str, tier: str, text: str) -> None:
        """Make ``text`` an active ``tier`` entry: an active copy in the other tier moves over, else a new row."""
        existing = self._active_text(conn, target, text)
        if existing is not None:
            conn.execute("UPDATE entries SET tier = ?, updated_at = ? WHERE id = ?", (tier, time.time(), existing["id"]))
        else:
            self._insert(conn, target=target, tier=tier, kind="fact" if target == "memory" else "preference",
                         text=text, keywords="", priority=0)

    def rewrite(self, target: str, tier: str, fn: Callable[[list[str]], list[str] | None]) -> list[str] | None:
        """Read-modify-write one target/tier list in one write transaction. ``fn`` gets the active texts in block
        order and returns the new list, or None to leave the store alone; it must not use this store. Kept texts
        keep their rows, a changed text supersedes the row at its place, dropped texts are archived, and a new
        text active in the other tier moves over. No budget check here: callers apply their own."""
        _check(target, tier)
        with self._writing() as conn:
            rows = self._tier_rows(conn, target, tier)
            new = fn([r["text"] for r in rows])
            if new is None:
                return None
            new = list(dict.fromkeys(_text(t) for t in new))
            added = []
            matcher = difflib.SequenceMatcher(None, [r["text"] for r in rows], new, autojunk=False)
            for op, i1, i2, j1, j2 in matcher.get_opcodes():
                pairs = min(i2 - i1, j2 - j1) if op == "replace" else 0
                for row, text in zip(rows[i1:i1 + pairs], new[j1:j1 + pairs]):
                    self._supersede(conn, row, text)
                if op != "equal":
                    for row in rows[i1 + pairs:i2]:
                        conn.execute("UPDATE entries SET status = 'archived', updated_at = ? WHERE id = ?",
                                     (time.time(), row["id"]))
                    added += new[j1 + pairs:j2]
            for text in added:  # after the archives, so a text that moved within the list is not revived twice
                self._place(conn, target, tier, text)
            return new

    def active_texts(self, target: str, tier: str = "hard") -> list[str]:
        """Active texts of one target/tier in block order."""
        _check(target, tier)
        with self._reading() as conn:
            return [r["text"] for r in self._tier_rows(conn, target, tier)]

    def is_empty(self) -> bool:
        """True when the store has never held an entry (of any status)."""
        with self._reading() as conn:
            return conn.execute("SELECT 1 FROM entries LIMIT 1").fetchone() is None

    # ── reads ────────────────────────────────────────────────────────────────────

    def entries(self, target: str | None = None, tier: str | None = None, *,
                include_inactive: bool = False) -> list[dict]:
        clauses, params = [], []
        if target is not None:
            _check(target)
            clauses.append("target = ?")
            params.append(target)
        if tier is not None:
            _check(tier=tier)
            clauses.append("tier = ?")
            params.append(tier)
        if not include_inactive:
            clauses.append("status = 'active'")
        where = " AND ".join(clauses) or "1"
        with self._reading() as conn:
            rows = conn.execute(f"SELECT * FROM entries WHERE {where} ORDER BY target, tier, priority DESC, "
                                "created_at, id", params).fetchall()
        return [dict(r) for r in rows]

    def get(self, entry_id: int) -> dict | None:
        """The row with ``entry_id`` in any status, or None."""
        with self._reading() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id = ?", (int(entry_id),)).fetchone()
        return None if row is None else dict(row)

    def search(self, query: str, k: int = 8, *, target: str | None = None, tier: str | None = None,
               include_inactive: bool = False, min_coverage: float = 0.0) -> list[dict]:
        """Ranked entries for ``query``; does not count as use."""
        clauses, params = ["1"], []
        if target is not None:
            _check(target)
            clauses.append("e.target = ?")
            params.append(target)
        if tier is not None:
            _check(tier=tier)
            clauses.append("e.tier = ?")
            params.append(tier)
        if not include_inactive:
            clauses.append("e.status = 'active'")
        with self._reading() as conn:
            return fact_search.search(conn, query, where=" AND ".join(clauses), params=params, ts_key="updated_at",
                                      uses_key="use_count", k=k, half_life_days=self.half_life_days,
                                      min_coverage=min_coverage)

    def soft_recall(self, query: str, budget_chars: int = SOFT_BUDGET_CHARS, max_chars: int = SOFT_MAX_CHARS, *,
                    target: str | None = None, min_coverage: float = SOFT_MIN_COVERAGE) -> list[dict]:
        """Relevant soft entries in score order within ``budget_chars``; an entry that does not fit the budget
        may still use the room up to ``max_chars`` when it scores at least half the top score. Empty when
        nothing covers ``min_coverage`` of the query. Recalled entries count as used."""
        hits = self.search(query, k=SOFT_RECALL_CANDIDATES, target=target, tier="soft", min_coverage=min_coverage)
        if not hits:
            return []
        top = hits[0]["score"]
        chosen, used = [], 0
        for hit in hits:
            size = len(hit["text"])
            if used + size <= budget_chars or (hit["score"] >= 0.5 * top and used + size <= max_chars):
                chosen.append(hit)
                used += size
        if chosen:
            now = time.time()
            ids = [h["id"] for h in chosen]
            with self._writing() as conn:
                conn.execute(f"UPDATE entries SET use_count = use_count + 1, last_used_at = ? "
                             f"WHERE id IN ({','.join('?' * len(ids))})", (now, *ids))
            for hit in chosen:
                hit["use_count"] = int(hit.get("use_count") or 0) + 1
                hit["last_used_at"] = now
        return chosen

    # ── markdown bridge ──────────────────────────────────────────────────────────

    def import_markdown(self, memory_md_text: str = "", user_md_text: str = "") -> dict[str, dict[str, int]]:
        """Import MEMORY.md / USER.md style text (entries split on the delimiter) as hard entries; whatever no
        longer fits the hard limit lands in soft. Entries already active are skipped, so re-importing is safe."""
        report = {}
        for target, raw in (("memory", memory_md_text), ("user", user_md_text)):
            counts = {"imported": 0, "skipped": 0, "soft": 0}
            kind = "fact" if target == "memory" else "preference"
            with self._writing() as conn:
                for text in dict.fromkeys(_split(raw)):
                    if self._active_text(conn, target, text) is not None:
                        counts["skipped"] += 1
                        continue
                    tier = "hard"
                    try:
                        self._ensure_fits(conn, target, text)
                    except MemoryFullError:
                        tier = "soft"
                        counts["soft"] += 1
                    self._insert(conn, target=target, tier=tier, kind=kind, text=text, keywords="", priority=0)
                    counts["imported"] += 1
            report[target] = counts
        return report

    def import_markdown_once(self, memory_md_text: str = "", user_md_text: str = "") -> dict[str, int] | None:
        """First-run migration: every MEMORY.md / USER.md entry becomes a hard entry in file order, even past the
        limit (``hard_block`` leaves out what does not fit, nothing is dropped). Returns the per-target counts, or
        None when the store already holds rows, so a second run never imports again."""
        with self._writing() as conn:
            if conn.execute("SELECT 1 FROM entries LIMIT 1").fetchone() is not None:
                return None
            counts = {}
            for target, raw in (("memory", memory_md_text), ("user", user_md_text)):
                texts = list(dict.fromkeys(_split(raw)))
                for text in texts:
                    self._insert(conn, target=target, tier="hard", kind="fact" if target == "memory" else "preference",
                                 text=text, keywords="", priority=0)
                counts[target] = len(texts)
            return counts

    def export_markdown(self, target: str, *, include_soft: bool = False) -> str:
        """The active entries as MEMORY.md / USER.md text (hard block order; soft entries after, if asked)."""
        _check(target)
        with self._reading() as conn:
            texts = self._hard_texts(conn, target)
            if include_soft:
                texts += [r["text"] for r in conn.execute(
                    f"SELECT text FROM entries WHERE target = ? AND tier = 'soft' AND status = 'active' {_HARD_ORDER}",
                    (target,))]
        return ENTRY_DELIMITER.join(texts)

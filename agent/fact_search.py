"""Lexical fact search shared by the room ledger and the global memory store (design §九).

Two FTS5 indexes per store: a word index (``porter unicode61``) over the text with CJK runs expanded into
overlapping bigrams plus single characters, and a ``trigram`` index over the raw text that rescues typos.
Query terms with an exact hit go to the word index; terms with none go to the trigram index as an OR of their
3-grams. The two bm25 lists are fused with RRF (k=60) and reranked by term coverage, recency, kind and usage.

User text never reaches ``MATCH`` raw: every term is a quoted phrase, so FTS5 operators are plain words.
"""

from __future__ import annotations

import contextlib
import math
import os
import re
import sqlite3
import threading
import time
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from phi_cli.sqlite_util import open_db, write_txn

RRF_K = 60
DEFAULT_HALF_LIFE_DAYS = 14.0
DEFAULT_CANDIDATES = 400
MAX_QUERY_TERMS = 64
KIND_WEIGHTS = {
    # room ledger
    "decision": 1.3, "fact": 1.25, "result": 1.2, "blocker": 1.1, "todo": 1.0, "note": 0.8, "step": 0.7,
    # global memory
    "rule": 1.3, "identity": 1.3, "skill": 1.2, "preference": 1.2,
}

_CJK = ("\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff"
        "\ua960-\ua97f\uac00-\ud7af\ud7b0-\ud7ff\uf900-\ufaff\uff66-\uff9f\U00020000-\U0002fa1f")
_CJK_RUN = re.compile(f"[{_CJK}]+")
_TERM = re.compile(f"[{_CJK}]+|[^\\W_{_CJK}]+")
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _cjk_grams(run: str) -> list[str]:
    if len(run) == 1:
        return [run]
    return [run[i:i + 2] for i in range(len(run) - 1)]


def cjk_expand(text: str) -> str:
    """Replace every CJK run with its overlapping bigrams followed by its single characters."""
    def expand(match: re.Match) -> str:
        run = match.group(0)
        grams = _cjk_grams(run) + (list(run) if len(run) > 1 else [])
        return " " + " ".join(grams) + " "

    return " ".join(_CJK_RUN.sub(expand, text).split())


def query_terms(query: str, max_terms: int = MAX_QUERY_TERMS) -> list[str]:
    """Lowercased latin/digit words of 2+ chars plus CJK bigrams (the char itself for a 1-char run), deduped."""
    terms: list[str] = []
    for match in _TERM.finditer(query or ""):
        token = match.group(0)
        if _CJK_RUN.fullmatch(token):
            grams = _cjk_grams(token)
        elif len(token) >= 2:
            grams = [token.lower()]
        else:
            continue
        for gram in grams:
            if gram not in terms:
                terms.append(gram)
    return terms[:max_terms]


def fts_phrase(term: str) -> str:
    """An FTS5 string literal: quoted, inner quotes doubled, so operators and syntax stay plain text."""
    return '"' + term.replace('"', '""') + '"'


def _trigrams(term: str) -> list[str]:
    term = term.lower()
    return [term[i:i + 3] for i in range(len(term) - 2)]


def rrf_fuse(ranked_lists: Iterable[Sequence[int]], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal rank fusion: sum of 1/(k + rank) with 1-based ranks."""
    fused: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, rowid in enumerate(ranked, start=1):
            fused[rowid] = fused.get(rowid, 0.0) + 1.0 / (k + rank)
    return fused


def _ident(name: str) -> str:
    if not _IDENT.fullmatch(name):
        raise ValueError(f"invalid table name: {name!r}")
    return name


def create_index(conn: sqlite3.Connection, table: str = "entries") -> None:
    table = _ident(table)
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {table}_words USING fts5(body, tokenize='porter unicode61')")
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS {table}_tri USING fts5(body, tokenize='trigram')")


def index_row(conn: sqlite3.Connection, table: str, rowid: int, text: str, keywords: str = "") -> None:
    """Index one row in both FTS tables under the row's id (call inside the writing transaction)."""
    table = _ident(table)
    body = f"{text} {keywords}".strip()
    conn.execute(f"INSERT INTO {table}_words(rowid, body) VALUES (?, ?)", (rowid, cjk_expand(body)))
    conn.execute(f"INSERT INTO {table}_tri(rowid, body) VALUES (?, ?)", (rowid, body))


def _ranked(conn, fts: str, table: str, match: str, where: str, params: Sequence, limit: int) -> list[int]:
    # CROSS JOIN keeps the FTS table as the outer loop; ties go to the newer row.
    sql = (f"SELECT {fts}.rowid FROM {fts} CROSS JOIN {table} AS e ON e.id = {fts}.rowid "
           f"WHERE {fts} MATCH ? AND ({where}) ORDER BY bm25({fts}), {fts}.rowid DESC LIMIT ?")
    return [r[0] for r in conn.execute(sql, (match, *params, limit))]


def _hits(conn, fts: str, table: str, match: str, where: str, params: Sequence) -> set[int]:
    sql = (f"SELECT {fts}.rowid FROM {fts} CROSS JOIN {table} AS e ON e.id = {fts}.rowid "
           f"WHERE {fts} MATCH ? AND ({where})")
    return {r[0] for r in conn.execute(sql, (match, *params))}


def search(conn: sqlite3.Connection, query: str, *, table: str = "entries", where: str = "1",
           params: Sequence = (), ts_key: str = "ts", uses_key: str | None = None, k: int = 8,
           kind_weights: Mapping[str, float] | None = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
           min_coverage: float = 0.0, candidates: int = DEFAULT_CANDIDATES, rerank: bool = True,
           now: float | None = None) -> list[dict]:
    """Rank rows of ``table`` for ``query``.

    ``where``/``params`` filter rows through alias ``e`` and must come from store code, never from users.
    Each result is the row as a dict plus ``score``, ``rrf`` and ``coverage`` (share of query terms present:
    exact terms literally, missing terms through any of their 3-grams). ``rerank=False`` ranks by plain RRF.
    """
    table = _ident(table)
    terms = query_terms(query)
    if not terms or k <= 0:
        return []
    words, tri = f"{table}_words", f"{table}_tri"
    hits = {t: _hits(conn, words, table, fts_phrase(t), where, params) for t in terms}
    exact = [t for t in terms if hits[t]]
    missing = [t for t in terms if not hits[t]]
    lists = []
    if exact:
        lists.append(_ranked(conn, words, table, " OR ".join(fts_phrase(t) for t in exact), where, params,
                             candidates))
    grams = list(dict.fromkeys(g for t in missing for g in _trigrams(t)))
    if grams:
        lists.append(_ranked(conn, tri, table, " OR ".join(fts_phrase(g) for g in grams), where, params,
                             candidates))
    fused = rrf_fuse(lists)
    if not fused:
        return []
    ids = list(fused)
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM {table} WHERE id IN ({','.join('?' * len(ids))})", ids)}
    weights = KIND_WEIGHTS if kind_weights is None else kind_weights
    now = time.time() if now is None else now
    missing_grams = {t: _trigrams(t) for t in missing}
    results = []
    for rowid, rrf in fused.items():
        row = rows.get(rowid)
        if row is None:
            continue
        haystack = f"{row.get('text') or ''} {row.get('keywords') or ''}".lower()
        covered = sum(1 for t in exact if rowid in hits[t])
        covered += sum(1 for t in missing if any(g in haystack for g in missing_grams[t]))
        coverage = covered / len(terms)
        score = rrf
        if rerank:
            if coverage < min_coverage:
                continue
            age_days = max(0.0, now - float(row.get(ts_key) or now)) / 86400.0
            recency = 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 1.0
            score = rrf * coverage ** 2 * (0.6 + 0.4 * recency) * weights.get(row.get("kind"), 1.0)
            if uses_key:
                score *= 1.0 + 0.1 * math.log1p(max(0, int(row.get(uses_key) or 0)))
        row.update(score=score, rrf=rrf, coverage=coverage)
        results.append(row)
    results.sort(key=lambda r: (-r["score"], -r["id"]))
    return results[:k]


class FactStore:
    """One SQLite file with an ``entries`` table and its two FTS indexes; subclasses supply the schema.

    The connection opens lazily, is shared by threads under a lock and reopened after a fork.
    """

    DB_LABEL = "facts.db"
    SCHEMA: tuple[str, ...] = ()

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None
        self._pid = 0

    def _initialize(self, conn: sqlite3.Connection) -> None:
        conn.isolation_level = None
        with write_txn(conn):
            for statement in self.SCHEMA:
                conn.execute(statement)
            create_index(conn, "entries")

    def _connection(self) -> sqlite3.Connection:
        if self._conn is not None and self._pid != os.getpid():
            self._conn = None  # inherited across fork: never touch the parent's handle
        if self._conn is None:
            # 30 s busy wait: where WAL is unavailable (SQLite with the WAL-reset bug → DELETE journal),
            # several sessions appending at once queue on the file lock; the 5 s default starves under load.
            self._conn = open_db(self.path, db_label=self.DB_LABEL, check_same_thread=False, wal_lock_retries=5,
                                 busy_timeout_ms=30000, initialize=self._initialize)
            self._pid = os.getpid()
        return self._conn

    @contextlib.contextmanager
    def _reading(self):
        """A read transaction, so the several statements of one search see one snapshot."""
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN")
            try:
                yield conn
            finally:
                with contextlib.suppress(sqlite3.OperationalError):
                    conn.execute("COMMIT")

    @contextlib.contextmanager
    def _writing(self):
        with self._lock:
            conn = self._connection()
            with write_txn(conn):
                yield conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None and self._pid == os.getpid():
                self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        self.close()

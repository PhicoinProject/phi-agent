"""Global memory store (design §十): hard block + limit, soft recall budget, supersede/archive, markdown import."""

from __future__ import annotations

import sqlite3

import pytest

from agent.memory_db import ENTRY_DELIMITER, HARD_LIMIT_CHARS, MemoryDB, MemoryFullError


@pytest.fixture
def db(tmp_path):
    store = MemoryDB(tmp_path / "memory.db")
    yield store
    store.close()


def _rows(db_path, sql, params=()):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_default_path_is_phi_home_memory_db(tmp_path, monkeypatch):
    from phi_constants import get_phi_home

    monkeypatch.setenv("PHI_HOME", str(tmp_path / "home"))
    with MemoryDB() as store:
        store.add("memory", "hard", "a fact")
        assert store.path == get_phi_home() / "memory.db"
    assert (get_phi_home() / "memory.db").is_file()


def test_add_validates_target_tier_and_text(db):
    with pytest.raises(ValueError):
        db.add("notes", "hard", "x")
    with pytest.raises(ValueError):
        db.add("memory", "medium", "x")
    with pytest.raises(ValueError):
        db.add("memory", "hard", "  ")
    db.add("memory", "hard", "a valid entry creates the schema")
    with pytest.raises(sqlite3.IntegrityError):  # CHECK constraints guard writers that bypass the API
        conn = sqlite3.connect(db.path)
        try:
            conn.execute("INSERT INTO entries(target, tier, kind, text, status, created_at, updated_at) "
                         "VALUES ('notes', 'hard', 'note', 'x', 'active', 0, 0)")
        finally:
            conn.close()


def test_hard_block_orders_by_priority_then_age_and_joins_with_delimiter(db):
    a = db.add("memory", "hard", "alpha rule", kind="rule")
    b = db.add("memory", "hard", "beta rule", kind="rule", priority=5)
    db.add("memory", "hard", "gamma rule", kind="rule")
    db.add("memory", "soft", "soft only")
    db.add("user", "hard", "user pref", kind="preference")
    assert db.hard_block("memory") == ENTRY_DELIMITER.join(["beta rule", "alpha rule", "gamma rule"])
    assert db.hard_block("user") == "user pref"
    assert db.hard_usage("memory") == (len("beta rule\n§\nalpha rule\n§\ngamma rule"), HARD_LIMIT_CHARS)
    # A smaller render budget drops what does not fit instead of cutting an entry in half.
    assert db.hard_block("memory", limit_chars=len("beta rule\n§\nalpha rule")) == "beta rule\n§\nalpha rule"
    db.remove(a)
    db.demote(b)
    assert db.hard_block("memory") == "gamma rule"


def test_add_returns_existing_id_for_identical_active_text(db):
    first = db.add("memory", "hard", "same text")
    assert db.add("memory", "hard", "same text") == first
    assert db.add("user", "hard", "same text") != first  # targets are independent


def test_hard_limit_boundary_counts_delimiters(db):
    """Exactly 4000 chars (entries + delimiters) fits; 4001 is refused and nothing changes."""
    db.add("memory", "hard", "a" * 2000)
    last = db.add("memory", "hard", "b" * (HARD_LIMIT_CHARS - 2000 - len(ENTRY_DELIMITER)))
    assert db.hard_usage("memory") == (HARD_LIMIT_CHARS, HARD_LIMIT_CHARS)
    db.demote(last)
    with pytest.raises(MemoryFullError) as excinfo:
        db.add("memory", "hard", "c" * (HARD_LIMIT_CHARS - 2000 - len(ENTRY_DELIMITER) + 1))
    message = str(excinfo.value).lower()
    assert "merge" in message and "demote" in message and "4001" in message
    assert db.hard_usage("memory") == (2000, HARD_LIMIT_CHARS)
    assert _rows(db.path, "SELECT count(*) FROM entries")[0][0] == 2
    # A single oversized entry is refused even when the block is empty.
    with pytest.raises(MemoryFullError):
        db.add("user", "hard", "u" * (HARD_LIMIT_CHARS + 1))
    db.add("user", "hard", "u" * HARD_LIMIT_CHARS)  # user target has its own budget
    db.add("memory", "soft", "s" * 10 * HARD_LIMIT_CHARS)  # soft has none


def test_replace_supersedes_by_id_or_unique_substring(db):
    old = db.add("memory", "hard", "proxy listens on port 7890", kind="fact", keywords="proxy", priority=3)
    new = db.replace(old, "proxy listens on port 7891")
    rows = {r["id"]: r for r in db.entries(include_inactive=True)}
    assert rows[old]["status"] == "superseded"
    assert (rows[new]["supersedes"], rows[new]["kind"], rows[new]["keywords"], rows[new]["priority"],
            rows[new]["tier"]) == (old, "fact", "proxy", 3, "hard")
    assert db.hard_block("memory") == "proxy listens on port 7891"
    newer = db.replace("port 7891", "proxy listens on port 7892")
    assert db.hard_block("memory") == "proxy listens on port 7892"
    assert [h["id"] for h in db.search("proxy port")] == [newer]
    db.add("memory", "hard", "proxy has no auth")
    with pytest.raises(ValueError):
        db.replace("proxy", "ambiguous")
    with pytest.raises(LookupError):
        db.replace("no such text", "x")
    with pytest.raises(LookupError):
        db.replace(old, "superseded rows cannot be replaced again")


def test_replace_respects_hard_limit_excluding_the_replaced_row(db):
    big = db.add("memory", "hard", "x" * HARD_LIMIT_CHARS)
    same = db.replace(big, "y" * HARD_LIMIT_CHARS)  # swapping in an equal-size text fits
    with pytest.raises(MemoryFullError):
        db.replace(same, "z" * (HARD_LIMIT_CHARS + 1))
    assert db.hard_block("memory") == "y" * HARD_LIMIT_CHARS


def test_remove_archives_and_promote_checks_limit(db):
    gone = db.add("memory", "soft", "temporary scratch fact about mirrors")
    db.remove(gone)
    assert db.search("scratch mirrors") == []
    assert [h["status"] for h in db.search("scratch mirrors", include_inactive=True)] == ["archived"]
    soft = db.add("memory", "soft", "s" * 100)
    db.add("memory", "hard", "h" * (HARD_LIMIT_CHARS - 50))
    with pytest.raises(MemoryFullError):
        db.promote(soft)
    db.demote(db.entries(target="memory", tier="hard")[0]["id"])
    db.promote(soft)
    assert db.hard_block("memory") == "s" * 100


def _pad(text: str, size: int) -> str:
    out = text
    i = 0
    while len(out) < size:
        out += f" lorem{i}"
        i += 1
    return out[:size]


@pytest.fixture
def recall_db(db):
    high = [db.add("memory", "soft", _pad(f"vector cache tuning finding {i}:", 1500), kind="fact") for i in range(3)]
    low = [db.add("memory", "soft", _pad(f"vector math aside {i}:", 300), kind="note") for i in range(3)]
    return db, high, low


def test_soft_recall_fills_budget_and_extends_only_for_strong_hits(recall_db):
    db, high, low = recall_db
    hits = db.soft_recall("vector cache", budget_chars=4000, max_chars=8000)
    # high[2] crosses the 4000 budget but scores >= 0.5*top, so it may use the extension; the weak
    # one-word matches may not.
    assert {h["id"] for h in hits} == set(high)
    assert sum(len(h["text"]) for h in hits) == 4500


def test_soft_recall_budget_and_max_bounds(recall_db):
    db, high, low = recall_db
    assert {h["id"] for h in db.soft_recall("vector cache", budget_chars=8000, max_chars=8000)} == set(high + low)
    capped = db.soft_recall("vector cache", budget_chars=4000, max_chars=4000)
    assert sum(len(h["text"]) for h in capped) <= 4000
    assert len([h for h in capped if h["id"] in high]) == 2
    assert {h["id"] for h in capped if h["id"] in low} == set(low)  # smaller relevant hits fill what is left


def test_soft_recall_returns_nothing_below_min_coverage(db):
    db.add("memory", "soft", "kafka broker restarted")
    assert db.soft_recall("kafka quorum fsync") == []  # 1 of 3 terms (0.33) is not relevant
    assert [h["text"] for h in db.soft_recall("kafka broker fsync")] == ["kafka broker restarted"]
    assert db.soft_recall("") == []
    assert db.soft_recall("zebra yoghurt umbrella") == []


def test_soft_recall_bumps_usage_and_ignores_hard_rows(db):
    soft = db.add("memory", "soft", "pnpm store lives on the data disk")
    db.add("memory", "hard", "pnpm store must not be pruned")
    first = db.soft_recall("pnpm store")
    assert [h["id"] for h in first] == [soft]
    assert first[0]["use_count"] == 1 and first[0]["last_used_at"] is not None
    db.soft_recall("pnpm store")
    row = next(r for r in db.entries() if r["id"] == soft)
    assert row["use_count"] == 2
    db.search("pnpm store")  # plain search does not count as use
    assert next(r for r in db.entries() if r["id"] == soft)["use_count"] == 2


def test_usage_boost_lifts_frequently_recalled_entries(db):
    used = db.add("memory", "soft", "mirror sync uses rsync over ssh (a)")
    fresh = db.add("memory", "soft", "mirror sync uses rsync over ssh (b)")
    assert [h["id"] for h in db.search("mirror rsync")][0] == fresh  # newer wins a plain tie
    conn = sqlite3.connect(db.path)
    try:
        conn.execute("UPDATE entries SET use_count = 50 WHERE id = ?", (used,))
        conn.commit()
    finally:
        conn.close()
    assert [h["id"] for h in db.search("mirror rsync")][0] == used


def test_import_markdown_is_idempotent_and_round_trips(db):
    memory_md = "Project uses uv.\n§\nTests run in containers.\n§\n\n"
    user_md = "Prefers short answers.\r\n§\r\nReplies in Chinese."
    first = db.import_markdown(memory_md, user_md)
    assert first == {"memory": {"imported": 2, "skipped": 0, "soft": 0},
                     "user": {"imported": 2, "skipped": 0, "soft": 0}}
    again = db.import_markdown(memory_md, user_md)
    assert again == {"memory": {"imported": 0, "skipped": 2, "soft": 0},
                     "user": {"imported": 0, "skipped": 2, "soft": 0}}
    assert _rows(db.path, "SELECT count(*) FROM entries")[0][0] == 4
    assert {r["tier"] for r in db.entries()} == {"hard"}
    assert db.export_markdown("memory") == "Project uses uv.\n§\nTests run in containers."
    assert db.export_markdown("user") == "Prefers short answers.\n§\nReplies in Chinese."
    assert db.hard_block("user") == db.export_markdown("user")


def test_import_markdown_overflow_goes_soft_instead_of_failing(db):
    entries = ["a" * 3000, "b" * 1500, "c" * 500]
    counts = db.import_markdown(ENTRY_DELIMITER.join(entries), "")
    assert counts["memory"] == {"imported": 3, "skipped": 0, "soft": 1}
    assert db.hard_block("memory") == "a" * 3000 + ENTRY_DELIMITER + "c" * 500
    assert [r["text"] for r in db.entries(tier="soft")] == ["b" * 1500]
    assert db.import_markdown(ENTRY_DELIMITER.join(entries), "")["memory"]["skipped"] == 3

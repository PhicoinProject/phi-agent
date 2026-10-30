"""memory.db as the memory tool's store (design §十): the one-time MEMORY.md / USER.md import, the hard
and soft tiers, the 4000-char hard budget and the read-only MEMORY.md / USER.md views."""

import json

import pytest

from agent.memory_db import MemoryDB
from tools.memory_tool import MEMORY_SCHEMA, MemoryStore, apply_memory_pending, memory_tool
from tools.memory_tool_db import IMPORT_MARKER, VIEW_HEADER, memory_db_path
from tools.memory_tool_store import memory_tier

DELIM = "\n§\n"


@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    d = tmp_path / "memories"
    d.mkdir()
    monkeypatch.setattr("tools.memory_tool.get_memory_dir", lambda: d)
    return d


def _store(**limits) -> MemoryStore:
    s = MemoryStore(**limits)
    s.load_from_disk()
    return s


def _db() -> MemoryDB:
    return MemoryDB(memory_db_path())


def _words(n_chars: int, seed: int = 0) -> str:
    """Plain distinct words, about ``n_chars`` long."""
    out, i = [], 0
    while len(" ".join(out)) < n_chars:
        out.append(f"item{seed}x{i}")
        i += 1
    return " ".join(out)


class TestMigration:
    def test_imports_once_as_hard_and_leaves_files_untouched(self, mem_dir):
        memory_md = DELIM.join(["Project uses pytest", "Deploys run on Fridays", "Project uses pytest"]).encode()
        user_md = "Prefers short answers".encode()
        (mem_dir / "MEMORY.md").write_bytes(memory_md)
        (mem_dir / "USER.md").write_bytes(user_md)

        store = _store()

        assert memory_db_path() == mem_dir.parent / "memory.db"
        with _db() as db:
            assert [e["text"] for e in db.entries("memory")] == ["Project uses pytest", "Deploys run on Fridays"]
            assert [e["text"] for e in db.entries("user")] == ["Prefers short answers"]
            assert {e["tier"] for e in db.entries()} == {"hard"}
        assert store.memory_entries == ["Project uses pytest", "Deploys run on Fridays"]
        assert store.user_entries == ["Prefers short answers"]
        marker = json.loads((mem_dir / IMPORT_MARKER).read_text())
        assert marker["tier"] == "hard"
        assert marker["entries"] == {"MEMORY.md": 2, "USER.md": 1}
        assert (mem_dir / "MEMORY.md").read_bytes() == memory_md
        assert (mem_dir / "USER.md").read_bytes() == user_md

    def test_over_limit_file_is_imported_whole(self, mem_dir):
        entries = [_words(1500, i) for i in range(4)]  # ~6000 chars against a 4000 limit
        (mem_dir / "MEMORY.md").write_text(DELIM.join(entries))
        store = _store()
        with _db() as db:
            assert db.active_texts("memory") == entries
        assert store.memory_entries == entries
        assert json.loads((mem_dir / IMPORT_MARKER).read_text())["entries"]["MEMORY.md"] == 4

    def test_never_imports_again(self, mem_dir):
        (mem_dir / "MEMORY.md").write_text("first fact")
        _store()
        (mem_dir / "MEMORY.md").write_text(DELIM.join(["first fact", "hand-added later"]))
        (mem_dir / IMPORT_MARKER).unlink()  # the database itself decides, not the marker
        store = _store()
        assert store.memory_entries == ["first fact"]
        with _db() as db:
            assert [e["text"] for e in db.entries(include_inactive=True)] == ["first fact"]


class TestHardBudget:
    def test_defaults_are_4000(self):
        from phi_cli.config_defaults import DEFAULT_CONFIG

        store = MemoryStore()
        assert (store.memory_char_limit, store.user_char_limit) == (4000, 4000)
        assert DEFAULT_CONFIG["memory"]["memory_char_limit"] == 4000
        assert DEFAULT_CONFIG["memory"]["user_char_limit"] == 4000

    def test_hard_add_over_limit_is_refused_with_hint_and_drops_nothing(self, mem_dir):
        store = _store()
        first = _words(2500, 1)
        assert json.loads(memory_tool(action="add", target="memory", content=first, store=store))["success"]
        view = (mem_dir / "MEMORY.md").read_text()

        out = json.loads(memory_tool(action="add", target="memory", content=_words(1600, 2), store=store))

        assert out["success"] is False
        for hint in ("Memory full", "Nothing was dropped", "Merge related entries", "tier='soft'"):
            assert hint in out["error"]
        assert out["current_entries"] == [first]
        assert store.memory_entries == [first]
        with _db() as db:
            assert db.active_texts("memory") == [first]
            assert db.active_texts("memory", "soft") == []
        assert (mem_dir / "MEMORY.md").read_text() == view

    def test_soft_has_no_fixed_limit(self, mem_dir):
        store = _store()
        texts = [f"soft note {i}: {_words(1300, i)}" for i in range(10)]  # ~13000 chars
        for text in texts:
            out = json.loads(memory_tool(action="add", target="memory", content=text, tier="soft", store=store))
            assert out["success"] is True and out["tier"] == "soft"
        with _db() as db:
            assert db.active_texts("memory", "soft") == texts
            assert db.hard_usage("memory") == (0, 4000)
        assert store.memory_entries == []

    def test_unknown_tier_is_rejected(self, mem_dir):
        store = _store()
        out = json.loads(memory_tool(action="add", target="memory", content="A fact", tier="warm", store=store))
        assert out["success"] is False and "Unknown tier" in out["error"]
        with _db() as db:
            assert db.entries() == []

    def test_schema_offers_optional_tier(self):
        params = MEMORY_SCHEMA["parameters"]
        assert params["properties"]["tier"]["enum"] == ["hard", "soft"]
        assert "tier" not in params.get("required", [])

    def test_staged_soft_write_replays_into_soft(self, mem_dir):
        store = _store()
        result = apply_memory_pending({"action": "add", "target": "memory", "tier": "soft",
                                       "content": "Staging build is slow on Mondays"}, store)
        assert result["success"] is True
        with _db() as db:
            assert db.active_texts("memory", "soft") == ["Staging build is slow on Mondays"]
            assert db.active_texts("memory") == []

    def test_an_entry_lives_in_one_tier(self, mem_dir):
        store = _store()
        store.add("memory", "Prefers tabs")
        with memory_tier("soft"):
            assert store.add("memory", "Prefers tabs")["success"]
        assert store.memory_entries == []
        assert store._soft_entries["memory"] == ["Prefers tabs"]
        with _db() as db:
            assert [(e["tier"], e["text"]) for e in db.entries("memory")] == [("soft", "Prefers tabs")]


class TestViews:
    def test_views_regenerate_from_hard_entries_only(self, mem_dir):
        store = _store()
        store.add("memory", "Fact one")
        store.add("memory", "Fact two")
        with memory_tier("soft"):
            store.add("memory", "Soft only detail")
        assert (mem_dir / "MEMORY.md").read_text() == f"{VIEW_HEADER}\nFact one{DELIM}Fact two"

        store.remove("memory", "Fact one")
        assert (mem_dir / "MEMORY.md").read_text() == f"{VIEW_HEADER}\nFact two"
        store.add("user", "Name is Sam")
        assert (mem_dir / "USER.md").read_text() == f"{VIEW_HEADER}\nName is Sam"
        assert not list(mem_dir.glob("*.bak.*"))

    def test_hand_edited_view_is_backed_up_and_never_read_back(self, mem_dir):
        store = _store()
        store.add("memory", "Fact one")
        (mem_dir / "MEMORY.md").write_text(f"{VIEW_HEADER}\nFact one{DELIM}Typed by hand")

        store.add("memory", "Fact two")

        assert (mem_dir / "MEMORY.md").read_text() == f"{VIEW_HEADER}\nFact one{DELIM}Fact two"
        backups = list(mem_dir.glob("MEMORY.md.bak.*"))
        assert len(backups) == 1 and "Typed by hand" in backups[0].read_text()
        assert _store().memory_entries == ["Fact one", "Fact two"]

    def test_reloaded_snapshot_holds_hard_entries_only(self, mem_dir):
        store = _store()
        store.add("memory", "Uses Postgres 16")
        with memory_tier("soft"):
            store.add("memory", "Postgres vacuum runs nightly")
        snapshot = _store().format_for_system_prompt("memory")
        assert "Uses Postgres 16" in snapshot
        assert "vacuum" not in snapshot

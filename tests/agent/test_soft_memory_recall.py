"""Soft global memory recall (design §十): recalled per turn into the user message, only when relevant to
the message and its last two turns; the system prompt carries only the frozen hard block."""

import pytest

from agent.memory_db import MemoryDB
from agent.system_prompt import _memory_parts, build_system_prompt_parts
from agent.turn_context import _memory_turn_start_and_prefetch, compose_user_api_content
from tests.agent.test_system_prompt import _make_agent
from tools.memory_tool import MemoryStore
from tools.memory_tool_db import memory_db_path
from tools.memory_tool_store import SOFT_RECALL_HEADER, memory_tier

DELIM = "\n§\n"
SEP = "═" * 46
HARD = "Deploy target is the blue cluster"
SOFT = "Kubernetes upgrades are scheduled on the first Tuesday of each quarter"
QUESTION = "When are Kubernetes upgrades scheduled?"


@pytest.fixture()
def mem_dir(tmp_path, monkeypatch):
    d = tmp_path / "memories"
    d.mkdir()
    monkeypatch.setattr("tools.memory_tool.get_memory_dir", lambda: d)
    return d


def _store() -> MemoryStore:
    s = MemoryStore()
    s.load_from_disk()
    return s


def _db() -> MemoryDB:
    return MemoryDB(memory_db_path())


def _seeded_session() -> MemoryStore:
    """A store holding HARD and SOFT, reloaded as a new session would load it."""
    seed = _store()
    seed.add("memory", HARD)
    with memory_tier("soft"):
        seed.add("memory", SOFT)
    return _store()


def _agent(store):
    return _make_agent(_memory_store=store, _memory_enabled=True, _user_profile_enabled=True,
                       _user_turn_count=1)


def _block_body(rendered: str) -> str:
    """The entries of a rendered system-prompt memory block, below its header."""
    return rendered.split(f"{SEP}\n")[-1]


def _soft_recall_only_reaches_the_user_message(store):
    """One turn: SOFT is recalled into this turn's user message and never into the system prompt,
    whose memory block stays the hard block frozen at load."""
    with _db() as db:
        frozen = db.hard_block("memory")
    agent = _agent(store)

    recall = _memory_turn_start_and_prefetch(agent, QUESTION, history=[])
    user_content = compose_user_api_content(QUESTION, recall, "")
    system = "\n\n".join(build_system_prompt_parts(agent).values())

    assert SOFT in recall and recall.startswith(SOFT_RECALL_HEADER)
    assert "<memory-context>" in user_content and SOFT in user_content
    assert HARD in system
    assert SOFT not in system and SOFT_RECALL_HEADER not in system
    assert [_block_body(p) for p in _memory_parts(agent)] == [frozen]


class TestSystemPromptBlock:
    def test_block_is_hard_block_and_stays_frozen(self, mem_dir):
        seed = _store()
        for fact in ("Fact A", "Fact B"):
            seed.add("memory", fact)
        seed.add("user", "Prefers metric units")
        with memory_tier("soft"):
            seed.add("memory", "Soft fact C")
        store = _store()
        agent = _agent(store)
        with _db() as db:
            frozen = [db.hard_block("memory"), db.hard_block("user")]
        before = _memory_parts(agent)
        assert [_block_body(p) for p in before] == frozen == [f"Fact A{DELIM}Fact B", "Prefers metric units"]

        store.add("memory", "Fact D added mid-session")
        store.remove("memory", "Fact A")
        with memory_tier("soft"):
            store.add("memory", "Soft fact E")

        assert _memory_parts(agent) == before
        assert store.memory_entries == ["Fact B", "Fact D added mid-session"]

    def test_over_limit_import_shows_what_hard_block_fits(self, mem_dir):
        entries = [f"note {i} " + "word " * 290 for i in range(4)]  # 4 x ~1460 chars, 4000 limit
        (mem_dir / "MEMORY.md").write_text(DELIM.join(e.strip() for e in entries))
        store = _store()
        with _db() as db:
            block = db.hard_block("memory")
        assert len(store.memory_entries) == 4
        assert _block_body(store.format_for_system_prompt("memory")) == block
        assert block.count(DELIM) == 1  # two entries fit, nothing was dropped from the database


class TestSoftRecall:
    def test_relevant_soft_memory_rides_the_user_message_only(self, mem_dir):
        _soft_recall_only_reaches_the_user_message(_seeded_session())

    def test_soft_recall_into_the_system_prompt_is_caught(self, mem_dir, monkeypatch):
        """Negative control: a store that also renders soft recall into its system-prompt block must fail
        the check above."""
        original = MemoryStore.format_for_system_prompt

        def leaky(self, target):
            return "\n".join(filter(None, [original(self, target), self.soft_recall_block(QUESTION)])) or None

        monkeypatch.setattr(MemoryStore, "format_for_system_prompt", leaky)
        with pytest.raises(AssertionError):
            _soft_recall_only_reaches_the_user_message(_seeded_session())

    def test_soft_recall_is_fenced_apart_from_authoritative_provider_recall(self, mem_dir):
        """Soft memory is secondary: it rides its own block, never under the provider block's
        "authoritative" note, and an external prefetch beside it keeps that note."""
        recall = _memory_turn_start_and_prefetch(_agent(_seeded_session()), QUESTION, history=[])
        external = "Provider fact: the release train leaves on Fridays"
        user_content = compose_user_api_content(QUESTION, f"{external}\n\n{recall}", "")
        blocks = user_content.split("<memory-context>")[1:]
        assert len(blocks) == 2
        provider, soft = blocks
        assert external in provider and "authoritative" in provider and SOFT not in provider
        assert SOFT in soft and "authoritative" not in soft and "secondary" in soft

    def test_irrelevant_or_trivial_prompt_injects_nothing(self, mem_dir):
        agent = _agent(_seeded_session())
        for prompt in ("Pick a jazz album", "thanks", "/help", ""):
            assert _memory_turn_start_and_prefetch(agent, prompt, history=[]) == ""
        with _db() as db:
            assert [e["use_count"] for e in db.entries(tier="soft")] == [0]

    def test_recall_counts_use(self, mem_dir):
        agent = _agent(_seeded_session())
        for _ in range(2):
            assert SOFT in _memory_turn_start_and_prefetch(agent, QUESTION, history=[])
        with _db() as db:
            (row,) = db.entries(tier="soft")
            assert row["use_count"] == 2 and row["last_used_at"]
            assert [e["use_count"] for e in db.entries(tier="hard")] == [0]

    def test_query_adds_the_last_two_user_assistant_texts(self, mem_dir):
        agent = _agent(_seeded_session())
        follow_up = "Which month is it?"
        about = [{"role": "user", "content": "Tell me about the Kubernetes upgrades"},
                 {"role": "assistant", "content": "They are scheduled quarterly."}]
        tool = [{"role": "tool", "content": "jazz album list"}]
        elsewhere = [{"role": "user", "content": "Pick a jazz album"},
                     {"role": "assistant", "content": "Try Blue Train."}]

        assert _memory_turn_start_and_prefetch(agent, follow_up, history=[]) == ""
        assert SOFT in _memory_turn_start_and_prefetch(agent, follow_up, history=about + tool)
        assert _memory_turn_start_and_prefetch(agent, follow_up, history=about + elsewhere + tool) == ""

    def test_disabled_target_is_not_recalled(self, mem_dir):
        store = _seeded_session()
        store.memory_enabled = False
        assert _memory_turn_start_and_prefetch(_agent(store), QUESTION, history=[]) == ""

"""plan_run: dispatches ready ``assignee: agent`` plan items through the delegate entry,
wave by wave, within the parallel cap and the spawn-depth limit."""

import json
from types import SimpleNamespace

import pytest

import tools.delegate_tool as delegate_tool
import tools.plan_dispatch as plan_dispatch
from tools.registry import registry
from tools.todo_tool import TodoStore


def _agent_item(i, depends_on=(), writes=(), content=None):
    item = {"id": i, "content": content or f"implement part {i} of the feature",
            "status": "pending", "assignee": "agent"}
    if depends_on:
        item["depends_on"] = list(depends_on)
    if writes:
        item["writes"] = list(writes)
    return item


class FakeDelegate:
    """Stands in for ``delegate_task``; records each batch and the store state at dispatch."""

    def __init__(self, store, fail=None, error=None):
        self.store, self.fail, self.error = store, fail or {}, error
        self.calls = []

    def __call__(self, goal=None, context=None, tasks=None, background=None, parent_agent=None, **kw):
        status = {t["id"]: t["status"] for t in self.store.read()}
        by_goal = {t["content"]: t["id"] for t in self.store.read()}
        ids = [by_goal[t["goal"]] for t in tasks]
        self.calls.append({"ids": ids, "tasks": tasks, "background": background,
                           "status": [status[i] for i in ids], "parent": parent_agent})
        if self.error:
            return json.dumps({"error": self.error})
        results = []
        for n, item_id in enumerate(ids):
            if item_id in self.fail:
                results.append({"task_index": n, "status": "failed", "summary": None, "error": self.fail[item_id]})
            else:
                results.append({"task_index": n, "status": "completed", "summary": f"{item_id} done"})
        return json.dumps({"results": results, "total_duration_seconds": 0.1})


@pytest.fixture
def cfg(monkeypatch):
    delegation = {"max_concurrent_children": 10, "max_spawn_depth": 1}
    agents = {}
    monkeypatch.setattr(delegate_tool, "_load_config", lambda: delegation)
    monkeypatch.setattr(plan_dispatch, "_agents_config", lambda: agents)
    return SimpleNamespace(delegation=delegation, agents=agents)


def _setup(monkeypatch, items, title=None, depth=0, **fake_kw):
    store = TodoStore()
    store.write(items)
    if title is not None:
        store.set_title(title)
    events = []
    agent = SimpleNamespace(_delegate_depth=depth, valid_tool_names={"todo_list", "plan_run", "delegate_task"},
                            tool_progress_callback=lambda *a, **kw: events.append((a, kw)))
    fake = FakeDelegate(store, **fake_kw)
    monkeypatch.setattr(delegate_tool, "delegate_task", fake)
    return store, agent, fake, events


def _run(store, agent, **args):
    return json.loads(registry.dispatch("plan_run", args, store=store, parent_agent=agent))


def _by_id(store):
    return {t["id"]: t for t in store.read()}


class TestBatches:
    def test_waves_dispatched_in_order(self, monkeypatch, cfg):
        items = [_agent_item("a"), _agent_item("b"), _agent_item("c", depends_on=["a", "b"]),
                 {"id": "d", "content": "review everything", "status": "pending", "assignee": "self"}]
        store, agent, fake, _ = _setup(monkeypatch, items)
        out = _run(store, agent)
        assert [c["ids"] for c in fake.calls] == [["a", "b"], ["c"]]
        assert out["dispatched"] == [["a", "b"], ["c"]]
        # Marked in_progress before the delegate ran; joined synchronously.
        assert all(s == "in_progress" for c in fake.calls for s in c["status"])
        assert all(c["background"] is False and c["parent"] is agent for c in fake.calls)
        items = _by_id(store)
        assert [items[i]["status"] for i in "abc"] == ["completed"] * 3
        assert items["c"]["result"] == "c done"
        assert items["d"]["status"] == "pending"  # self items are left to the caller
        assert out["plan"]["ready"] == ["d"]
        assert out["todos"] == store.read()

    def test_goal_is_item_content(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a", content="write the parser module")])
        _run(store, agent)
        assert fake.calls[0]["tasks"][0]["goal"] == "write the parser module"

    def test_overlapping_writes_never_share_a_batch(self, monkeypatch, cfg):
        items = [_agent_item("a", writes=["src/*.py"]), _agent_item("b", writes=["src/app.py"]),
                 _agent_item("c", writes=["docs/x.md"])]
        store, agent, fake, _ = _setup(monkeypatch, items)
        _run(store, agent)
        assert [c["ids"] for c in fake.calls] == [["a", "c"], ["b"]]

    def test_nothing_ready_for_agents(self, monkeypatch, cfg):
        items = [{"id": "a", "content": "do it myself", "status": "pending"}]
        store, agent, fake, _ = _setup(monkeypatch, items)
        out = _run(store, agent)
        assert fake.calls == []
        assert out["dispatched"] == []
        assert out["plan"]["ready"] == ["a"]

    def test_progress_events_carry_plan(self, monkeypatch, cfg):
        store, agent, _, events = _setup(monkeypatch, [_agent_item("a")])
        _run(store, agent)
        plan_events = [kw for a, kw in events if a[0] == "plan.updated"]
        assert len(plan_events) == 2  # after marking in_progress, after applying results
        first, last = plan_events[0]["state"], plan_events[-1]["state"]
        assert first["todos"][0]["status"] == "in_progress"
        assert last["todos"][0]["status"] == "completed"
        assert last["revision"] > first["revision"]
        assert set(last["plan"]) >= {"ready", "waves", "critical_path", "blocked", "serialized"}


class TestCap:
    def _five(self):
        return [_agent_item(c) for c in "abcde"]

    def test_default_cap_is_agents_max_parallel_4(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, self._five())
        _run(store, agent)
        assert [len(c["ids"]) for c in fake.calls] == [4, 1]

    def test_requested_max_parallel(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, self._five())
        _run(store, agent, max_parallel=2)
        assert [len(c["ids"]) for c in fake.calls] == [2, 2, 1]

    def test_delegation_children_limit_applies(self, monkeypatch, cfg):
        cfg.delegation["max_concurrent_children"] = 3
        store, agent, fake, _ = _setup(monkeypatch, self._five())
        _run(store, agent, max_parallel=8)
        assert [len(c["ids"]) for c in fake.calls] == [3, 2]

    def test_agents_max_parallel_caps_children_limit(self, monkeypatch, cfg):
        cfg.agents["max_parallel"] = 1
        store, agent, fake, _ = _setup(monkeypatch, self._five())
        _run(store, agent)
        assert [len(c["ids"]) for c in fake.calls] == [1] * 5


class TestDepth:
    def test_refused_at_max_spawn_depth(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a")], depth=1)
        before = store.snapshot()
        out = _run(store, agent)
        assert "error" in out
        assert "max_spawn_depth" in out["error"] and "depth 1" in out["error"]
        assert fake.calls == []
        assert store.snapshot() == before

    def test_allowed_below_max_spawn_depth(self, monkeypatch, cfg):
        cfg.delegation["max_spawn_depth"] = 2
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a")], depth=1)
        _run(store, agent)
        assert [c["ids"] for c in fake.calls] == [["a"]]

    def test_requires_delegate_tool(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a")])
        agent.valid_tool_names = {"todo_list", "plan_run"}
        assert "error" in _run(store, agent)
        assert fake.calls == []


class TestContext:
    def test_results_feed_dependants(self, monkeypatch, cfg):
        items = [_agent_item("a"), _agent_item("b"), _agent_item("c", depends_on=["a", "b"])]
        store, agent, fake, _ = _setup(monkeypatch, items, title="Ship the parser")
        _run(store, agent)
        first_ctx = fake.calls[0]["tasks"][0]["context"]
        assert "Ship the parser" in first_ctx
        assert "done" not in first_ctx
        ctx = fake.calls[1]["tasks"][0]["context"]
        assert "Ship the parser" in ctx
        assert "a done" in ctx and "b done" in ctx

    def test_no_title_no_deps_no_context(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a")])
        _run(store, agent)
        assert not fake.calls[0]["tasks"][0].get("context")


class TestFailures:
    def test_failed_child_goes_back_to_pending(self, monkeypatch, cfg):
        items = [_agent_item("a"), _agent_item("b"), _agent_item("c", depends_on=["b"])]
        store, agent, fake, _ = _setup(monkeypatch, items, fail={"b": "boom"})
        out = _run(store, agent)
        assert [c["ids"] for c in fake.calls] == [["a", "b"]]  # no retry, c never unblocked
        items = _by_id(store)
        assert items["a"]["status"] == "completed"
        assert items["b"]["status"] == "pending"
        assert "boom" in items["b"]["result"]
        assert out["plan"]["blocked"] == ["c"]

    def test_whole_call_error_releases_batch(self, monkeypatch, cfg):
        store, agent, fake, _ = _setup(monkeypatch, [_agent_item("a"), _agent_item("b")], error="spawning is paused")
        out = _run(store, agent)
        assert len(fake.calls) == 1
        assert [t["status"] for t in store.read()] == ["pending", "pending"]
        assert all("spawning is paused" in t["result"] for t in store.read())
        assert out["plan"]["ready"] == ["a", "b"]

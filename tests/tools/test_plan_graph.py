"""Plan graph on top of the todo list: depends_on / writes / assignee / result plus the
computed ``plan`` block (ready, waves, critical_path, blocked, serialized)."""

import json

import pytest

import tools.todo_tool as todo_mod
from tools.registry import registry
from tools.todo_tool import TodoStore, compute_plan, todo_tool


def _item(i, status="pending", **extra):
    return {"id": i, "content": f"task {i}", "status": status, **extra}


def _call(store, todos=None, merge=False, title=None):
    args = {"merge": merge}
    if todos is not None:
        args["todos"] = todos
    if title is not None:
        args["title"] = title
    return json.loads(registry.dispatch("todo_list", args, store=store))


class TestBackwardCompat:
    def test_old_items_round_trip_unchanged(self):
        store = TodoStore()
        old = [_item("1"), _item("2", "in_progress"), _item("3", "completed")]
        out = _call(store, old)
        assert [{"id": "2", "content": "task 2", "status": "in_progress"},
                {"id": "1", "content": "task 1", "status": "pending"},
                {"id": "3", "content": "task 3", "status": "completed"}] == out["todos"]
        assert out["revision"] == 1
        assert out["summary"] == {"total": 3, "pending": 1, "in_progress": 1, "completed": 1, "cancelled": 0}

    def test_old_list_plan_is_flat(self):
        out = _call(TodoStore(), [_item("a"), _item("b"), _item("c", "completed")])
        plan = out["plan"]
        assert plan["ready"] == ["a", "b"]
        assert plan["blocked"] == []
        assert plan["waves"] == [["a", "b", "c"]]
        assert plan["serialized"] == []
        assert len(plan["critical_path"]) == 1

    def test_read_without_args_includes_plan(self):
        store = TodoStore()
        _call(store, [_item("a"), _item("b", depends_on=["a"])])
        out = _call(store)
        assert out["plan"]["ready"] == ["a"]
        assert out["plan"]["blocked"] == ["b"]

    def test_noop_write_keeps_revision(self):
        store = TodoStore()
        items = [_item("a", writes=["src/x.py"], assignee="agent")]
        assert _call(store, items)["revision"] == 1
        assert _call(store, items)["revision"] == 1


class TestFields:
    def test_optional_fields_kept_and_normalized(self):
        store = TodoStore()
        items = store.write([
            _item("a", assignee="agent", writes=["./src/", "src", ""], result="  done  "),
            _item("b", depends_on="a", assignee="robot"),
        ])
        a, b = items
        assert a["assignee"] == "agent"
        assert a["writes"] == ["src"]
        assert a["result"] == "done"
        assert b["depends_on"] == ["a"]
        assert "assignee" not in b  # unknown assignee dropped

    def test_merge_updates_and_clears_fields(self):
        store = TodoStore()
        store.write([_item("a"), _item("b", depends_on=["a"], writes=["x"])])
        items = store.write([{"id": "b", "depends_on": [], "result": "ok", "assignee": "self"}], merge=True)
        b = items[1]
        assert "depends_on" not in b
        assert b["writes"] == ["x"]
        assert b["result"] == "ok"
        assert b["assignee"] == "self"
        assert b["content"] == "task b"

    def test_title_kept_until_replaced(self):
        store = TodoStore()
        assert _call(store, [_item("a")], title="Ship it")["plan"]["title"] == "Ship it"
        assert _call(store, [_item("a", "completed")], merge=True)["plan"]["title"] == "Ship it"
        assert _call(store, title="")["plan"]["title"] == ""


class TestValidation:
    def test_unknown_dependency_named(self):
        store = TodoStore()
        store.write([_item("a")])
        out = _call(store, [_item("a"), _item("b", depends_on=["ghost", "a", "zz"])])
        assert "error" in out
        assert "ghost" in out["error"] and "zz" in out["error"]
        assert store.read() == [_item("a")]  # rejected write leaves the list alone
        assert store.snapshot()["revision"] == 1

    def test_self_dependency_rejected(self):
        out = _call(TodoStore(), [_item("a", depends_on=["a"])])
        assert "error" in out and "'a'" in out["error"] and "itself" in out["error"]

    def test_cycle_named(self):
        out = _call(TodoStore(), [_item("a", depends_on=["c"]), _item("b", depends_on=["a"]),
                                  _item("c", depends_on=["b"])])
        assert "error" in out
        assert "a -> c -> b -> a" in out["error"]

    def test_merge_creating_cycle_rejected(self):
        store = TodoStore()
        store.write([_item("a"), _item("b", depends_on=["a"])])
        before = store.read()
        out = _call(store, [{"id": "a", "depends_on": ["b"]}], merge=True)
        assert "Dependency cycle" in out["error"]
        assert store.read() == before

    def test_restore_drops_bad_dependencies(self):
        store = TodoStore()
        items = store.restore([_item("a", depends_on=["a", "ghost"]), _item("b", depends_on=["a"])],
                              revision=3)
        assert "depends_on" not in items[0]
        assert items[1]["depends_on"] == ["a"]


class TestGraph:
    def _diamond(self, **status):
        return [_item("a", status.get("a", "pending")),
                _item("b", status.get("b", "pending"), depends_on=["a"]),
                _item("c", status.get("c", "pending"), depends_on=["a"]),
                _item("d", status.get("d", "pending"), depends_on=["b", "c"])]

    def test_ready_and_blocked(self):
        plan = compute_plan(self._diamond())
        assert plan["ready"] == ["a"]
        assert plan["blocked"] == ["b", "c", "d"]
        plan = compute_plan(self._diamond(a="completed"))
        assert plan["ready"] == ["b", "c"]
        assert plan["blocked"] == ["d"]
        plan = compute_plan(self._diamond(a="completed", b="completed", c="in_progress"))
        assert plan["ready"] == []
        assert plan["blocked"] == ["d"]

    def test_waves(self):
        assert compute_plan(self._diamond())["waves"] == [["a"], ["b", "c"], ["d"]]

    def test_cancelled_items_not_in_waves(self):
        items = self._diamond(c="cancelled")
        plan = compute_plan(items)
        assert plan["waves"] == [["a"], ["b"], ["d"]]
        assert "c" not in plan["critical_path"]

    def test_critical_path_longest_chain(self):
        items = [_item("a"), _item("b", depends_on=["a"]), _item("x"),
                 _item("c", depends_on=["b"]), _item("y", depends_on=["x"])]
        assert compute_plan(items)["critical_path"] == ["a", "b", "c"]
        assert compute_plan(self._diamond())["critical_path"] == ["a", "b", "d"]

    def test_response_plan_matches_compute_plan(self):
        store = TodoStore()
        out = _call(store, self._diamond(), title="T")
        assert out["plan"] == compute_plan(store.read(), title="T")


def _overlap_case(writes_a, writes_b):
    """Through the store, so ``writes`` get the same path normalization as a real todo call."""
    store = TodoStore()
    store.write([_item("a", writes=writes_a), _item("b", writes=writes_b)])
    return store.plan()


def assert_overlapping_writes_serialized():
    """Shared by the real test and the negative control below."""
    for writes_a, writes_b in ((["src/*.py"], ["src/app.py"]),  # glob vs path
                               (["src/app.py"], ["src/*.py"]),  # the other direction
                               (["docs"], ["docs/guide/intro.md"]),  # directory prefix
                               (["pkg/a.py", "web/"], ["web/index.html"])):
        plan = _overlap_case(writes_a, writes_b)
        assert plan["ready"] == ["a"], (writes_a, writes_b)
        assert plan["blocked"] == ["b"]
        assert plan["waves"] == [["a"], ["b"]]
        assert plan["critical_path"] == ["a", "b"]
        assert [(s["id"], s["after"]) for s in plan["serialized"]] == [("b", "a")]
    # Never two overlapping writers in one ready batch, even three-way.
    plan = compute_plan([_item("a", writes=["x/*"]), _item("b", writes=["y"]),
                         _item("c", writes=["x/1"]), _item("d", writes=["x/2", "y/z"])])
    assert plan["ready"] == ["a", "b"]
    assert plan["waves"][0] == ["a", "b"]


class TestWritesOverlap:
    def test_overlapping_writes_serialized(self):
        assert_overlapping_writes_serialized()

    def test_serialized_entry_reports_patterns(self):
        plan = _overlap_case(["src/*.py"], ["src/app.py"])
        assert plan["serialized"] == [{"id": "b", "after": "a", "overlap": ["src/*.py", "src/app.py"]}]

    def test_disjoint_writes_run_together(self):
        for writes_a, writes_b in ((["src/a.py"], ["src/b.py"]),
                                   (["src/app"], ["src/application.py"]),  # not a path prefix
                                   ([], ["src/b.py"])):
            plan = _overlap_case(writes_a, writes_b)
            assert plan["ready"] == ["a", "b"], (writes_a, writes_b)
            assert plan["serialized"] == []

    def test_explicit_order_needs_no_implicit_edge(self):
        plan = compute_plan([_item("a", writes=["f"]), _item("b", writes=["f"], depends_on=["a"])])
        assert plan["serialized"] == []
        plan = compute_plan([_item("a", writes=["f"], depends_on=["b"]), _item("b", writes=["f"])])
        assert plan["serialized"] == []  # reverse explicit order wins, no cycle is created
        assert plan["ready"] == ["b"]

    def test_overlap_with_running_item_not_ready(self):
        plan = compute_plan([_item("a", writes=["f"]), _item("b", "in_progress", writes=["f"])])
        assert plan["ready"] == []
        assert plan["blocked"] == ["a"]
        # The running writer goes first even though it is later in the list.
        assert plan["serialized"] == [{"id": "a", "after": "b", "overlap": ["f", "f"]}]

    def test_completed_writer_releases(self):
        plan = compute_plan([_item("a", "completed", writes=["f"]), _item("b", writes=["f"])])
        assert plan["ready"] == ["b"]
        assert plan["serialized"] == []

    def test_negative_control_ignoring_overlap_is_caught(self, monkeypatch):
        """A scheduler that ignores ``writes`` must fail the serialization check."""
        monkeypatch.setattr(todo_mod, "_writes_overlap", lambda a, b: None)
        with pytest.raises(AssertionError):
            assert_overlapping_writes_serialized()

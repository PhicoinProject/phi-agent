"""Rejected background units retain parent cancellation ownership (upstream946111cb11)."""

import json
import threading
import time
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

from agent.interrupt_control import InterruptControlMixin
from tools import delegate_tool_dispatch as dispatch
from tools.delegate_tool_child_run import _attach_child


class Parent(InterruptControlMixin):
    def __init__(self):
        self.session_id = "test-parent"
        self._active_children = []
        self._active_children_lock = threading.Lock()
        self._execution_thread_id = None
        self._interrupt_requested = False
        self._hard_interrupt_requested = threading.Event()
        self.quiet_mode = True


class Child:
    def __init__(self):
        self.stops = []

    def interrupt(self, message=None):
        self.stops.append((message, False))

    def hard_interrupt(self, message=None):
        self.stops.append((message, True))


@pytest.mark.parametrize("hard", [False, True])
def test_late_child_inherits_parent_stop_kind(hard):
    parent, child = Parent(), Child()
    (parent.hard_interrupt if hard else parent.interrupt)("stop reason")
    _attach_child(parent, child)
    assert parent._active_children == [child]
    assert child.stops == [("stop reason", hard)]


@pytest.mark.parametrize("hard", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_rejected_unit_is_reattached_and_pending_siblings_never_detached(monkeypatch, hard, partial):
    parent = Parent()
    children = [Child() for _ in range(3 if partial else 1)]
    parent._active_children.extend(children)
    tasks = [{"goal": "test"} for child in children]
    batch = dispatch._Batch(
        task_list=tasks, children=[(index, tasks[index], child) for index, child in enumerate(children)],
        parent_agent=parent, creds={"model": "test"}, context=None, top_role="leaf", max_children=len(children),
        live_deleg_id=None, live_writers=[], live_paths=[], origin_wake_sid="", origin_ui_session_id="",
        origin_owner_transport=None, origin_owner_session_record=None, origin_session_history_delivery=False,
        overall_start=time.monotonic(),
    )
    units = [dispatch.replace(batch, children=[entry]) for entry in batch.children]
    monkeypatch.setattr(dispatch, "_units_of", lambda batch: units)
    monkeypatch.setattr(dispatch, "_resolve_async_wake_sid", lambda *args: "wake")
    monkeypatch.setattr(dispatch, "_resolve_async_session_key", lambda *args: ("session", "ui"))
    monkeypatch.setattr("tools.delegate_tool._get_max_async_children", lambda: 3)
    rejected = 1 if partial else 0

    def admit(unit, unit_id, slot_key, routing):
        index, _, child = unit.children[0]
        assert child not in parent._active_children
        if index == rejected:
            (parent.hard_interrupt if hard else parent.interrupt)("stop reason")
            if partial:
                assert children[2] in parent._active_children
                assert children[2].stops == [("stop reason", hard)]
                assert children[0].stops == []
            return {"status": "rejected", "error": "test capacity"}
        return {"status": "dispatched", "delegation_id": unit_id}

    monkeypatch.setattr(dispatch, "_dispatch_unit", admit)

    def inline(unit, **options):
        assert options.get("honor_parent_interrupt", True)
        child = unit.children[0][2]
        assert child in parent._active_children
        assert child.stops == [("stop reason", hard)]
        return {"results": [{"status": "interrupted"}]}

    monkeypatch.setattr(dispatch, "_execute_and_aggregate", inline)

    def sync(batch, note):
        inline(batch)
        return json.dumps({"note": note})

    monkeypatch.setattr(dispatch, "_run_sync_with_note", sync)
    monkeypatch.setattr(dispatch, "_dispatched_payload", lambda *args: {"status": "dispatched"})
    result = json.loads(dispatch._dispatch_background(batch))
    assert result["status"] == "dispatched" if partial else result["note"] == "at_capacity"


@pytest.mark.parametrize("hard", [False, True])
def test_admission_stop_reaches_real_fallback_worker_and_cleanup(monkeypatch, tmp_path, hard):
    from agent.turn_context import _bind_interrupt_scope
    from tools.interrupt import is_interrupted, set_interrupt

    monkeypatch.setenv("PHI_HOME", str(tmp_path))
    monkeypatch.delenv("PHI_IGNORE_USER_CONFIG", raising=False)
    (tmp_path / "config.yaml").write_text("delegation:\n  max_concurrent_children: 1\n  worktree_isolation: false\n")

    class WorkerChild(Parent):
        def __init__(self):
            super().__init__()
            self.session_id = "test-worker-child"
            self._delegate_role = "leaf"
            self._delegate_depth = 1
            self._delegate_saved_tool_names = []
            self._credential_pool = None
            self._subagent_id = None
            self.tool_progress_callback = None
            self.model = "test-model"
            self.started = threading.Event()
            self.release = threading.Event()
            self.finished = threading.Event()
            self.closed = threading.Event()
            self.observed = None
            self.closed_early = False

        def run_conversation(self, **kwargs):
            _bind_interrupt_scope(self, lambda: SimpleNamespace(_set_interrupt=set_interrupt))
            try:
                self.observed = (self._interrupt_message, self._hard_interrupt_requested.is_set(), is_interrupted())
                self.started.set()
                assert self.release.wait(10)
                return {"final_response": "", "completed": False, "interrupted": True, "api_calls": 0, "messages": []}
            finally:
                self.clear_interrupt()
                self.finished.set()

        def get_activity_summary(self):
            return {"api_call_count": 0}

        def close(self):
            self.closed_early = not self.finished.is_set()
            self.closed.set()

    parent, child = Parent(), WorkerChild()
    parent._active_children.append(child)
    tasks = [{"goal": "test cancellation"}]
    batch = dispatch._Batch(
        task_list=tasks, children=[(0, tasks[0], child)], parent_agent=parent,
        creds={"model": child.model}, context=None, top_role="leaf", max_children=1,
        live_deleg_id=None, live_writers=[], live_paths=[], origin_wake_sid="",
        origin_ui_session_id="", origin_owner_transport=None, origin_owner_session_record=None,
        origin_session_history_delivery=False, overall_start=time.monotonic(),
    )
    monkeypatch.setattr(dispatch, "_resolve_async_wake_sid", lambda *args: "wake")
    monkeypatch.setattr(dispatch, "_resolve_async_session_key", lambda *args: ("session", "ui"))

    def reject(*args):
        assert child not in parent._active_children
        (parent.hard_interrupt if hard else parent.interrupt)("during admission")
        return {"status": "rejected", "error": "test capacity"}

    monkeypatch.setattr(dispatch, "_dispatch_unit", reject)
    outcome = Future()

    def run():
        try:
            outcome.set_result(json.loads(dispatch._dispatch_background(batch)))
        except BaseException as error:
            outcome.set_exception(error)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    try:
        assert child.started.wait(5)
        assert child.observed == ("during admission", hard, True)
        assert not outcome.done()
        assert not child.closed.is_set()
        child.release.set()
        result = outcome.result(timeout=5)
        assert result["results"][0]["status"] == "interrupted"
        assert child.finished.is_set() and child.closed.is_set()
        assert not child.closed_early
        assert parent._active_children == []
    finally:
        child.release.set()
        worker.join(timeout=5)
        assert not worker.is_alive()
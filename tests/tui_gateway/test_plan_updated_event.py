"""plan.updated: the todo snapshot plus its computed plan block, emitted beside todo.updated whenever
the todo store changes — a todo tool result or plan_run's mid-run progress."""

import json

import pytest
from pydantic import ValidationError

from tools.todo_tool import TodoStore
from tui_gateway import server
from tui_gateway.contracts.events import PlanUpdatedPayload


@pytest.fixture
def events(monkeypatch):
    sid = "plan-updated-test"
    recorded = []
    session = {"agent": None, "edit_snapshots": {}, "tool_started_at": {}, "tool_progress_mode": "off"}
    monkeypatch.setitem(server._sessions, sid, session)
    monkeypatch.setattr(server, "_tool_progress_enabled", lambda _sid: False)
    monkeypatch.setattr(server, "_tool_lifecycle_required_for_ui", lambda _name: False)
    monkeypatch.setattr(server, "_emit", lambda event, event_sid, payload=None: recorded.append((event, payload)))
    return sid, session, recorded


def _store():
    store = TodoStore()
    store.write([{"id": "a", "content": "parse", "status": "pending", "assignee": "agent", "writes": ["src/*"]},
                 {"id": "b", "content": "lint", "status": "pending", "writes": ["src/x.py"]}])
    store.set_title("Ship it")
    return store


@pytest.mark.parametrize("tool", ["todo_list", "plan_run"])
def test_tool_result_emits_todo_then_plan(events, tool):
    sid, session, recorded = events
    state = _store().state()
    server._on_tool_complete(sid, "call-1", tool, {}, json.dumps(state))
    names = [name for name, _ in recorded]
    assert names[-2:] == ["todo.updated", "plan.updated"]
    todo, plan = recorded[-2][1], recorded[-1][1]
    assert todo == {"todos": state["todos"], "revision": state["revision"]}
    assert plan == {**todo, "plan": state["plan"]}
    assert plan["plan"]["serialized"] == [{"id": "b", "after": "a", "overlap": ["src/*", "src/x.py"]}]
    PlanUpdatedPayload.model_validate(plan)
    assert session["todo_state"] == todo


def test_result_without_plan_keeps_todo_only(events):
    sid, _, recorded = events
    server._on_tool_complete(sid, "call-1", "todo_list", {}, json.dumps({"todos": [], "revision": 2}))
    assert [name for name, _ in recorded][-1] == "todo.updated"
    assert "plan.updated" not in [name for name, _ in recorded]


def test_plan_run_error_emits_nothing(events):
    sid, _, recorded = events
    server._on_tool_complete(sid, "call-1", "plan_run", {}, json.dumps({"error": "no"}))
    assert not {"todo.updated", "plan.updated"} & {name for name, _ in recorded}


def test_plan_run_progress_bypasses_tool_progress_off(events):
    """plan_run reports each wave's store change while it is still running."""
    sid, session, recorded = events
    state = _store().state()
    server._on_tool_progress(sid, "plan.updated", "plan_run", None, None, state=state)
    assert [name for name, _ in recorded] == ["todo.updated", "plan.updated"]
    assert recorded[-1][1]["plan"] == state["plan"]
    assert session["todo_state"]["revision"] == state["revision"]


def test_contract_rejects_unknown_plan_keys():
    state = _store().state()
    payload = {"todos": state["todos"], "revision": state["revision"], "plan": state["plan"]}
    PlanUpdatedPayload.model_validate(payload)
    with pytest.raises(ValidationError):
        PlanUpdatedPayload.model_validate({**payload, "plan": {**payload["plan"], "extra": 1}})

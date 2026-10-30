"""The fixed plan-graph rule rides beside the parallel-tool-call guidance, once."""

from types import SimpleNamespace

import pytest

from agent.prompt_builder import PARALLEL_TOOL_CALL_GUIDANCE, PLAN_GRAPH_GUIDANCE
from agent.system_prompt import build_system_prompt

PLAN_TOOLS = {"todo_list", "plan_run", "delegate_task", "read_file"}


def _agent(**overrides):
    base = dict(
        load_soul_identity=False, skip_context_files=True, valid_tool_names=PLAN_TOOLS,
        _task_completion_guidance=False, _tool_use_enforcement=False, _environment_probe=False,
        _kanban_worker_guidance="", _memory_store=None, _memory_manager=None, model="", provider="",
        platform="", pass_session_id=False, session_id="", _emit_status=lambda *_a, **_kw: None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("agent.prompt_builder.load_soul_md", lambda *a, **kw: "")
    monkeypatch.setattr("agent.prompt_builder.build_environment_hints", lambda *a, **kw: "")


def test_rule_text_is_short_and_names_the_tools():
    assert len(PLAN_GRAPH_GUIDANCE) < 400
    for word in ("todo_list", "depends_on", "writes", "assignee", "plan_run", "parallel"):
        assert word in PLAN_GRAPH_GUIDANCE


def test_rule_present_exactly_once_next_to_parallel_guidance():
    prompt = build_system_prompt(_agent())
    assert prompt.count(PLAN_GRAPH_GUIDANCE) == 1
    assert prompt.count(PARALLEL_TOOL_CALL_GUIDANCE) == 1
    assert prompt.index(PLAN_GRAPH_GUIDANCE) > prompt.index(PARALLEL_TOOL_CALL_GUIDANCE)


def test_rule_follows_the_parallel_guidance_switch():
    assert PLAN_GRAPH_GUIDANCE not in build_system_prompt(_agent(_parallel_tool_call_guidance=False))


@pytest.mark.parametrize("missing", ["plan_run", "todo_list", "delegate_task"])
def test_rule_needs_the_plan_tools(missing):
    """A leaf child (no delegate_task) or a session without the todo toolset can't follow it."""
    prompt = build_system_prompt(_agent(valid_tool_names=PLAN_TOOLS - {missing}))
    assert PLAN_GRAPH_GUIDANCE not in prompt
    assert PARALLEL_TOOL_CALL_GUIDANCE in prompt


def test_rule_kept_when_todo_list_is_deferred_behind_the_bridge():
    """todo_list is deferred by default; with the tool_call bridge loaded it is still callable."""
    prompt = build_system_prompt(_agent(valid_tool_names=PLAN_TOOLS - {"todo_list"} | {"tool_search", "tool_call"}))
    assert prompt.count(PLAN_GRAPH_GUIDANCE) == 1

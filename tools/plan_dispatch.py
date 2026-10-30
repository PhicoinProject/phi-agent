"""plan_run: execute the todo plan graph in parallel. Every ready item with ``assignee: agent``
is handed to a subagent through the delegate entry (one ``tasks`` batch per wave, capped), marked
in_progress first and completed — or back to pending with the error — afterwards; then the next
wave is dispatched until no agent item is ready. Items with overlapping ``writes`` never share a
batch because compute_plan never lists them as ready together."""

import json
import logging
from typing import Any, Optional

from tools.todo_tool import TodoStore, check_todo_requirements

logger = logging.getLogger(__name__)

DEFAULT_MAX_PARALLEL = 4


def _agents_config() -> dict:
    from phi_cli.config import load_config_readonly
    return load_config_readonly().get("agents") or {}


def _parallel_cap(requested: Any) -> int:
    """min(delegation.max_concurrent_children, agents.max_parallel (default 4), requested)."""
    from tools.delegate_tool_config import _get_max_concurrent_children

    try:
        configured = max(1, int(_agents_config().get("max_parallel", DEFAULT_MAX_PARALLEL)))
    except (TypeError, ValueError):
        configured = DEFAULT_MAX_PARALLEL
    cap = min(_get_max_concurrent_children(), configured)
    return cap if requested is None else min(cap, max(1, int(requested)))


def _gate(store: Optional[TodoStore], parent_agent: Any) -> Optional[str]:
    if store is None:
        return "TodoStore not initialized"
    if parent_agent is None:
        return "plan_run requires a parent agent context."
    from tools.delegate_tool_config import _get_max_spawn_depth

    depth, max_depth = getattr(parent_agent, "_delegate_depth", 0), _get_max_spawn_depth()
    if depth >= max_depth:
        return (f"plan_run cannot spawn subagents here: this agent runs at depth {depth}, the leaf level for "
                f"delegation.max_spawn_depth={max_depth}. Do the agent items yourself (set assignee to self) "
                "or raise delegation.max_spawn_depth.")
    names = getattr(parent_agent, "valid_tool_names", None)
    if names is not None and "delegate_task" not in names:
        return "plan_run needs subagent delegation, which is not enabled in this session."
    return None


def _context(items: dict[str, dict[str, Any]], item: dict[str, Any], title: str) -> Optional[str]:
    """The plan title plus the recorded results of the item's dependencies."""
    lines = [f"Plan: {title}"] if title else []
    results = [f"- [{d}] {items[d]['content']}: {items[d]['result']}"
               for d in item.get("depends_on", ()) if items.get(d, {}).get("result")]
    if results:
        lines += ["Results of prerequisite tasks:", *results]
    return "\n".join(lines) or None


def _apply_results(store: TodoStore, batch: list[str], raw: Any) -> bool:
    """Record each child's outcome on its item; True when the whole call failed (stop dispatching)."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        error = data.get("error") if isinstance(data, dict) else None
        error = error or f"unexpected delegation result: {str(raw)[:200]}"
        store.write([{"id": i, "status": "pending", "result": f"error: {error}"} for i in batch], merge=True)
        return True
    by_index = {r.get("task_index"): r for r in data["results"] if isinstance(r, dict)}
    updates = []
    for n, item_id in enumerate(batch):
        entry = by_index.get(n, {})
        if entry.get("status") == "completed":
            updates.append({"id": item_id, "status": "completed", "result": entry.get("summary") or "completed"})
        else:
            detail = entry.get("error") or entry.get("summary") or "no result returned"
            updates.append({"id": item_id, "status": "pending",
                            "result": f"{entry.get('status') or 'failed'}: {detail}"})
    store.write(updates, merge=True)
    return False


def _emit(parent_agent: Any, store: TodoStore) -> None:
    callback = getattr(parent_agent, "tool_progress_callback", None)
    if callback is None:
        return
    try:
        callback("plan.updated", "plan_run", None, None, state=store.state())
    except Exception as e:  # a UI relay must never strand items in_progress
        logger.debug("plan.updated progress callback failed: %s", e)


def plan_run(max_parallel: Any = None, store: Optional[TodoStore] = None, parent_agent: Any = None) -> str:
    """Dispatch ready agent items wave by wave; returns the todo state plus ``dispatched`` batches."""
    from tools.registry import tool_error

    error = _gate(store, parent_agent)
    if error:
        return tool_error(error)
    try:
        cap = _parallel_cap(max_parallel)
    except (TypeError, ValueError):
        return tool_error(f"max_parallel must be a positive integer, got {max_parallel!r}")
    from tools import delegate_tool

    dispatched: list[list[str]] = []
    attempted: set[str] = set()  # a failed item is not retried within the same call
    while True:
        items = {t["id"]: t for t in store.read()}
        batch = [i for i in store.plan()["ready"]
                 if items[i].get("assignee") == "agent" and i not in attempted][:cap]
        if not batch:
            break
        attempted.update(batch)
        dispatched.append(batch)
        tasks = []
        for item_id in batch:
            task = {"goal": items[item_id]["content"]}
            context = _context(items, items[item_id], store.title)
            if context:
                task["context"] = context
            tasks.append(task)
        store.write([{"id": i, "status": "in_progress"} for i in batch], merge=True)
        _emit(parent_agent, store)
        try:
            raw = delegate_tool.delegate_task(tasks=tasks, background=False, parent_agent=parent_agent)
        except Exception as e:  # release the batch instead of stranding it in_progress
            raw = {"error": str(e)}
        failed = _apply_results(store, batch, raw)
        _emit(parent_agent, store)
        if failed:
            break
    return json.dumps({**store.state(), "dispatched": dispatched}, ensure_ascii=False)


PLAN_RUN_SCHEMA = {
    "name": "plan_run",
    "description": (
        "Run the current todo plan in parallel: every ready item with assignee=agent goes to its own "
        "subagent (goal = item content, context = plan title + results of its dependencies). Items are "
        "marked in_progress, then completed with the subagent's summary as result, or back to pending "
        "with the error. Continues wave by wave until no agent item is ready. Items whose writes overlap "
        "never run together. Returns the updated list and plan."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "max_parallel": {
                "type": "integer",
                "minimum": 1,
                "description": "Optional cap on subagents per wave (default: the configured limit)."
            }
        },
        "required": []
    }
}


from tools.registry import registry

registry.register(
    name="plan_run", toolset="todo", schema=PLAN_RUN_SCHEMA, check_fn=check_todo_requirements,
    handler=lambda args, **kw: plan_run(
        max_parallel=args.get("max_parallel"), store=kw.get("store"), parent_agent=kw.get("parent_agent")),
    emoji="🗺️")

// Read-only view of the agent's todo plan graph from `plan.updated`: title and
// progress, the critical path, then each wave's tasks with status, assignee and
// dependencies. No controls; the agent owns the plan.

import { useEffect, useState } from "react";
import type { GatewayEvent, PlanUpdatedPayload } from "@phi/shared";
import { fmt } from "@/components/shell/use-shell-strings";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import type { PanelStrings } from "@/i18n/types";
import { cn } from "@/lib/utils";

type TodoStatus = "pending" | "in_progress" | "completed" | "cancelled";

export interface PlanTodo {
  id: string;
  content: string;
  status: TodoStatus;
  depends_on: string[];
  assignee: "self" | "agent";
}

export interface PlanView {
  title: string;
  done: number;
  total: number;
  waves: PlanTodo[][];
  /** Live tasks the schedule left out of every wave. */
  rest: PlanTodo[];
  criticalPath: string[];
  /** "agent-N" numbering by first appearance in wave order (the backend only says "agent"). */
  agentIndex: Map<string, number>;
}

const STATUSES: readonly TodoStatus[] = ["pending", "in_progress", "completed", "cancelled"];

function parseTodo(raw: unknown): PlanTodo | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.id !== "string" || !r.id) return null;
  const status = STATUSES.includes(r.status as TodoStatus) ? (r.status as TodoStatus) : "pending";
  return {
    id: r.id,
    content: typeof r.content === "string" ? r.content : "",
    status,
    depends_on: Array.isArray(r.depends_on) ? r.depends_on.filter((d): d is string => typeof d === "string") : [],
    assignee: r.assignee === "agent" ? "agent" : "self",
  };
}

/** Null when the payload holds no live task: the Plan button stays hidden. */
export function planView(payload: PlanUpdatedPayload | null): PlanView | null {
  if (!payload) return null;
  const todos = (payload.todos ?? []).map(parseTodo).filter((t): t is PlanTodo => t !== null);
  const live = todos.filter((t) => t.status !== "cancelled");
  if (live.length === 0) return null;
  const byId = new Map(live.map((t) => [t.id, t]));
  const placed = new Set<string>();
  const waves = (payload.plan?.waves ?? [])
    .map((wave) =>
      wave.flatMap((id) => {
        const todo = byId.get(id);
        if (!todo || placed.has(id)) return [];
        placed.add(id);
        return [todo];
      }),
    )
    .filter((wave) => wave.length > 0);
  const rest = live.filter((t) => !placed.has(t.id));
  const agentIndex = new Map<string, number>();
  for (const todo of [...waves.flat(), ...rest]) {
    if (todo.assignee === "agent") agentIndex.set(todo.id, agentIndex.size + 1);
  }
  return {
    title: payload.plan?.title ?? "",
    done: live.filter((t) => t.status === "completed").length,
    total: live.length,
    waves,
    rest,
    criticalPath: payload.plan?.critical_path ?? [],
    agentIndex,
  };
}

export function planLabel(view: PlanView, p: PanelStrings): string {
  return fmt(p.planProgress, { done: view.done, total: view.total });
}

interface PlanFeed {
  on(type: "plan.updated", handler: (event: GatewayEvent<"plan.updated">) => void): () => void;
}

/** Latest `plan.updated` payload from an events feed; resets when the feed changes. */
export function usePlanUpdates(feed: PlanFeed | null): PlanUpdatedPayload | null {
  const [payload, setPayload] = useState<PlanUpdatedPayload | null>(null);
  useEffect(() => {
    setPayload(null);
    if (!feed) return;
    return feed.on("plan.updated", (event) => {
      if (event.payload) setPayload(event.payload);
    });
  }, [feed]);
  return payload;
}

function progressBar(done: number, total: number, width = 8): string {
  const filled = total > 0 ? Math.round((done / total) * width) : 0;
  return `[${"#".repeat(filled)}${"-".repeat(width - filled)}]`;
}

function statusLabel(status: TodoStatus, p: PanelStrings): string {
  const label = status === "completed" ? p.planStatusDone : status === "in_progress" ? p.planStatusRun : p.planStatusWait;
  return `[${label.padEnd(4)}]`;
}

function TaskRow({ todo, view, p }: { todo: PlanTodo; view: PlanView; p: PanelStrings }) {
  const agent = view.agentIndex.get(todo.id);
  return (
    <li
      data-task-id={todo.id}
      data-status={todo.status}
      className={cn(
        "grid grid-cols-[auto_auto_1fr] items-baseline gap-x-2 font-mono text-xs",
        todo.status === "completed" && "opacity-60",
      )}
    >
      <span className={cn(todo.status === "in_progress" && "text-midground")}>{statusLabel(todo.status, p)}</span>
      <span className="font-semibold">{todo.id}</span>
      <span className="min-w-0">
        <span className="break-words">{todo.content}</span>{" "}
        <span data-testid="plan-assignee" className="opacity-70">
          {agent ? fmt(p.planAgent, { n: agent }) : p.planSelf}
        </span>
        {todo.depends_on.length > 0 && (
          <span data-testid="plan-deps" className="opacity-70">
            {" "}
            {`<- ${todo.depends_on.join(" ")}`}
          </span>
        )}
      </span>
    </li>
  );
}

export function PlanPanel({ payload }: { payload: PlanUpdatedPayload | null }) {
  const p = usePanelStrings();
  const view = planView(payload);
  if (!view) return <p className="text-sm opacity-70">{p.planEmpty}</p>;
  return (
    <div data-testid="plan-panel" className="flex flex-col gap-3">
      <p className="font-mono text-sm">
        <span className="font-semibold">{view.title}</span>{" "}
        <span data-testid="plan-progress">
          {progressBar(view.done, view.total)} {view.done}/{view.total}
        </span>
      </p>
      {view.criticalPath.length > 0 && (
        <p data-testid="plan-critical-path" className="font-mono text-xs opacity-80">
          {fmt(p.planCriticalPath, { path: view.criticalPath.join(" > ") })}
        </p>
      )}
      {view.waves.map((wave, i) => (
        <section key={i} data-testid="plan-wave" className="flex flex-col gap-1">
          <h3 className="font-mono text-xs uppercase tracking-wider opacity-70">{fmt(p.planWave, { n: i + 1 })}</h3>
          <ul className="flex flex-col gap-1">
            {wave.map((todo) => (
              <TaskRow key={todo.id} todo={todo} view={view} p={p} />
            ))}
          </ul>
        </section>
      ))}
      {view.rest.length > 0 && (
        <ul className="flex flex-col gap-1">
          {view.rest.map((todo) => (
            <TaskRow key={todo.id} todo={todo} view={view} p={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

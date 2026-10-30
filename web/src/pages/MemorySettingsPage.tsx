import { useCallback, useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { Badge } from "@phi/ui/ui/components/badge";
import { Button } from "@phi/ui/ui/components/button";
import { Card, CardContent } from "@phi/ui/ui/components/card";
import { Input } from "@phi/ui/ui/components/input";
import { Progress } from "@phi/ui/ui/components/progress";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { H2 } from "@phi/ui/ui/components/typography/h2";
import { fmt, useShellStrings } from "@/components/shell/use-shell-strings";
import type { ShellStrings } from "@/i18n/types";
import { errorMessage } from "@/lib/api-error";
import { memoryStoreApi } from "@/lib/api-memory-store";
import type { MemoryBudget, MemoryEntry, MemoryTarget, MemoryUsage } from "@/lib/api-memory-store";

interface MemoryView {
  usage: MemoryUsage;
  hard: MemoryEntry[];
  soft: MemoryEntry[];
  /** The search the soft list was fetched with ("" = unfiltered). */
  q: string;
  /** Epoch seconds when the lists were fetched; the "used Nd ago" reference. */
  loadedAt: number;
}

type RunAction = (action: () => Promise<unknown>) => Promise<boolean>;

async function loadView(q: string): Promise<MemoryView> {
  const [usage, hard, soft] = await Promise.all([
    memoryStoreApi.usage(),
    memoryStoreApi.entries({ tier: "hard" }),
    memoryStoreApi.entries({ tier: "soft", q: q || undefined }),
  ]);
  return { usage, hard: hard.entries, soft: soft.entries, q, loadedAt: Date.now() / 1000 };
}

/** 3100 → "3.1k", 4000 → "4k", 950 → "950". */
function compact(n: number): string {
  return n < 1000 ? String(n) : `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
}

function usedLabel(lastUsedAt: number | null, now: number, s: ShellStrings): string {
  if (lastUsedAt == null) return s.memNeverUsed;
  const days = Math.floor((now - lastUsedAt) / 86400);
  return days < 1 ? s.memUsedToday : fmt(s.memUsedDaysAgo, { days });
}

function targetLabel(target: MemoryTarget, s: ShellStrings): string {
  return target === "user" ? s.memTargetUser : s.memTargetMemory;
}

function BudgetBar({ target, budget, s }: { target: MemoryTarget; budget: MemoryBudget; s: ShellStrings }) {
  const label = targetLabel(target, s);
  const value = `${compact(budget.used)}/${compact(budget.limit)}`;
  const pct = budget.limit > 0 ? Math.min(100, (budget.used / budget.limit) * 100) : 0;
  const over = budget.used > budget.limit;
  return (
    <div data-testid={`mem-budget-${target}`} className="flex min-w-48 flex-1 items-center gap-2 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span
        data-testid={`mem-budget-${target}-value`}
        title={`${budget.used} / ${budget.limit}`}
        className={over ? "font-mono text-destructive" : "font-mono text-text-secondary"}
      >
        {value}
      </span>
      <Progress
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={budget.limit}
        aria-valuenow={budget.used}
        aria-valuetext={value}
        value={pct}
      />
    </div>
  );
}

function SectionHeader({ id, title, hint, children }: { id: string; title: string; hint: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <span id={id} className="text-sm font-medium uppercase tracking-wider text-foreground">
        {title}
      </span>
      <span className="text-xs text-muted-foreground">{hint}</span>
      {children ? <div className="ml-auto flex min-w-0 flex-1 flex-wrap items-center justify-end gap-4">{children}</div> : null}
    </div>
  );
}

interface ActionButtonProps {
  action: string;
  label: string;
  disabled: boolean;
  onClick: () => void;
}

function ActionButton({ action, label, disabled, onClick }: ActionButtonProps) {
  return (
    <Button type="button" size="sm" ghost data-action={action} disabled={disabled} onClick={onClick}>
      {label}
    </Button>
  );
}

function TargetTag({ entry, s }: { entry: MemoryEntry; s: ShellStrings }) {
  // Memory is the default target; only user entries are tagged.
  if (entry.target !== "user") return null;
  return (
    <span data-testid="mem-target" className="shrink-0 font-mono text-xs text-muted-foreground">
      {s.memTargetUser}
    </span>
  );
}

const ROW_CN = "flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 py-1 text-sm";

function HardRow({ entry, busy, run, s }: { entry: MemoryEntry; busy: boolean; run: RunAction; s: ShellStrings }) {
  const [draft, setDraft] = useState<string | null>(null);
  const pinned = entry.priority > 0;

  const onSave = async (e: FormEvent) => {
    e.preventDefault();
    const text = draft?.trim();
    if (!text || text === entry.text) return;
    if (await run(() => memoryStoreApi.edit(entry.id, text))) setDraft(null);
  };

  return (
    <li data-testid="mem-entry" data-id={entry.id} data-tier="hard" className={ROW_CN}>
      <Badge tone="outline" data-testid="mem-kind" className="shrink-0">
        {entry.kind}
      </Badge>
      <TargetTag entry={entry} s={s} />
      {draft !== null ? (
        <form className="flex min-w-0 flex-1 items-center gap-2" onSubmit={(e) => void onSave(e)}>
          <Input
            aria-label={s.memEditLabel}
            value={draft}
            disabled={busy}
            onChange={(e) => setDraft(e.currentTarget.value)}
            className="min-w-0 flex-1"
          />
          <Button type="submit" size="sm" data-action="save" disabled={busy || !draft.trim() || draft.trim() === entry.text}>
            {s.save}
          </Button>
          <ActionButton action="cancel" label={s.cancel} disabled={busy} onClick={() => setDraft(null)} />
        </form>
      ) : (
        <>
          <span data-testid="mem-text" className="min-w-0 flex-1 break-words text-foreground">
            {entry.text}
          </span>
          <div className="flex shrink-0 items-center gap-1">
            <ActionButton
              action="pin"
              label={pinned ? s.memUnpin : s.memPin}
              disabled={busy}
              onClick={() => void run(() => memoryStoreApi.pin(entry.id, !pinned))}
            />
            <ActionButton action="edit" label={s.memEdit} disabled={busy} onClick={() => setDraft(entry.text)} />
            <ActionButton
              action="demote"
              label={s.memDemote}
              disabled={busy}
              onClick={() => void run(() => memoryStoreApi.demote(entry.id))}
            />
            <ActionButton
              action="archive"
              label={s.archive}
              disabled={busy}
              onClick={() => void run(() => memoryStoreApi.archive(entry.id))}
            />
          </div>
        </>
      )}
    </li>
  );
}

interface SoftRowProps {
  entry: MemoryEntry;
  searching: boolean;
  now: number;
  busy: boolean;
  run: RunAction;
  s: ShellStrings;
}

function SoftRow({ entry, searching, now, busy, run, s }: SoftRowProps) {
  return (
    <li data-testid="mem-entry" data-id={entry.id} data-tier="soft" className={ROW_CN}>
      {searching && typeof entry.score === "number" ? (
        <span data-testid="mem-score" title={s.memScore} className="w-10 shrink-0 font-mono text-text-secondary">
          {entry.score.toFixed(2)}
        </span>
      ) : null}
      <TargetTag entry={entry} s={s} />
      <span data-testid="mem-text" className="min-w-0 flex-1 break-words text-foreground">
        {entry.text}
      </span>
      <span data-testid="mem-used" className="shrink-0 text-xs text-muted-foreground">
        {usedLabel(entry.last_used_at, now, s)}
      </span>
      <div className="flex shrink-0 items-center gap-1">
        <ActionButton
          action="promote"
          label={s.memPromote}
          disabled={busy}
          onClick={() => void run(() => memoryStoreApi.promote(entry.id))}
        />
        <ActionButton
          action="archive"
          label={s.archive}
          disabled={busy}
          onClick={() => void run(() => memoryStoreApi.archive(entry.id))}
        />
      </div>
    </li>
  );
}

function EmptyLine({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>;
}

export default function MemorySettingsPage() {
  const s = useShellStrings();
  const hardId = useId();
  const softId = useId();
  const [view, setView] = useState<MemoryView | null>(null);
  const [query, setQuery] = useState("");
  /** The submitted search; the soft list is filtered by it. */
  const [activeQuery, setActiveQuery] = useState("");
  /** Bumped after every successful action to refetch lists and usage. */
  const [version, setVersion] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    loadView(activeQuery).then(
      (next) => {
        if (!alive) return;
        setView(next);
        setLoadError(null);
      },
      (e: unknown) => alive && setLoadError(errorMessage(e)),
    );
    return () => {
      alive = false;
    };
  }, [activeQuery, version]);

  const run = useCallback<RunAction>(async (action) => {
    setBusy(true);
    try {
      await action();
      setActionError(null);
      setVersion((v) => v + 1);
      return true;
    } catch (e) {
      setActionError(errorMessage(e));
      return false;
    } finally {
      setBusy(false);
    }
  }, []);

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    setActiveQuery(query.trim());
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <H2 variant="sm">{s.memTitle}</H2>
        <form role="search" data-testid="mem-search" className="flex items-center gap-2" onSubmit={onSearch}>
          <Input
            type="search"
            aria-label={s.memSearch}
            placeholder={s.memSearch}
            value={query}
            onChange={(e) => setQuery(e.currentTarget.value)}
            className="w-56"
          />
          <Button type="submit" size="sm" outlined>
            {s.memSearchButton}
          </Button>
        </form>
      </div>
      <div aria-live="polite">
        {actionError ? (
          <p role="alert" data-testid="mem-error" className="text-sm text-destructive">
            {fmt(s.memActionFailed, { error: actionError })}
          </p>
        ) : null}
        {loadError && view ? (
          <p role="alert" className="text-sm text-destructive">
            {fmt(s.memLoadFailed, { error: loadError })}
          </p>
        ) : null}
      </div>
      <Card>
        <CardContent className="grid gap-6">
          {!view ? (
            loadError ? (
              <p role="alert" className="text-sm text-destructive">
                {fmt(s.memLoadFailed, { error: loadError })}
              </p>
            ) : (
              <Spinner />
            )
          ) : (
            <>
              <section aria-labelledby={hardId} data-testid="mem-hard" className="grid gap-2">
                <SectionHeader id={hardId} title={s.memHard} hint={s.memHardHint}>
                  <BudgetBar target="memory" budget={view.usage.hard.memory} s={s} />
                  <BudgetBar target="user" budget={view.usage.hard.user} s={s} />
                </SectionHeader>
                {view.hard.length === 0 ? (
                  <EmptyLine>{s.memNoHard}</EmptyLine>
                ) : (
                  <ul className="grid">
                    {view.hard.map((entry) => (
                      <HardRow key={entry.id} entry={entry} busy={busy} run={run} s={s} />
                    ))}
                  </ul>
                )}
              </section>
              <section aria-labelledby={softId} data-testid="mem-soft" className="grid gap-2">
                <SectionHeader id={softId} title={s.memSoft} hint={s.memSoftHint}>
                  <span data-testid="mem-soft-count" className="font-mono text-sm text-text-secondary">
                    {fmt(s.memSoftCount, { count: view.usage.soft_count })}
                  </span>
                </SectionHeader>
                {view.soft.length === 0 ? (
                  <EmptyLine>{view.q ? s.memNoMatches : s.memNoSoft}</EmptyLine>
                ) : (
                  <ul className="grid">
                    {view.soft.map((entry) => (
                      <SoftRow
                        key={entry.id}
                        entry={entry}
                        searching={view.q !== ""}
                        now={view.loadedAt}
                        busy={busy}
                        run={run}
                        s={s}
                      />
                    ))}
                  </ul>
                )}
              </section>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

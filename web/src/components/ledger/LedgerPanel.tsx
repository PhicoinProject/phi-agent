// A room's ledger: newest first, coloured by kind, kind filter chips and a
// debounced live search. Superseded entries stay visible, greyed, with the id
// that replaced them. Path refs open in Files.

import { useEffect, useState } from "react";
import { Link } from "react-router";
import { Search } from "lucide-react";
import { Input } from "@phi/ui/ui/components/input";
import { fmt } from "@/components/shell/use-shell-strings";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import type { PanelStrings } from "@/i18n/types";
import { errorMessage } from "@/lib/api-error";
import { LEDGER_KINDS, workspaceApi, type LedgerEntry, type LedgerKind } from "@/lib/api-workspace";
import { cn } from "@/lib/utils";

export const LEDGER_SEARCH_DEBOUNCE_MS = 300;
const LEDGER_LIMIT = 200;

const KIND_CLASS: Record<LedgerKind, string> = {
  decision: "border-l-midground text-midground",
  fact: "border-l-sky-500 text-sky-600",
  result: "border-l-emerald-500 text-emerald-600",
  blocker: "border-l-destructive text-destructive",
  todo: "border-l-amber-500 text-amber-600",
  note: "border-l-current/30 opacity-80",
  step: "border-l-current/20 opacity-70",
};

function kindLabel(kind: LedgerKind, p: PanelStrings): string {
  const labels: Record<LedgerKind, string> = {
    decision: p.ledgerKindDecision,
    fact: p.ledgerKindFact,
    result: p.ledgerKindResult,
    blocker: p.ledgerKindBlocker,
    todo: p.ledgerKindTodo,
    note: p.ledgerKindNote,
    step: p.ledgerKindStep,
  };
  return labels[kind];
}

const isKind = (kind: string): kind is LedgerKind => (LEDGER_KINDS as readonly string[]).includes(kind);

function tsValue(ts: LedgerEntry["ts"]): number {
  if (typeof ts === "number") return ts < 1e12 ? ts * 1000 : ts;
  const parsed = Date.parse(ts);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function formatTs(ts: LedgerEntry["ts"]): string {
  const ms = tsValue(ts);
  return ms ? new Date(ms).toLocaleString() : String(ts);
}

/** File paths (relative or absolute, with a separator or an extension); not URLs or commit SHAs. */
function isPathRef(ref: string): boolean {
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(ref) || /^[0-9a-f]{7,40}$/i.test(ref)) return false;
  return ref.includes("/") || /\.[A-Za-z0-9]{1,8}$/.test(ref);
}

function Ref({ value }: { value: string }) {
  if (isPathRef(value)) {
    return (
      <Link to={`/files?path=${encodeURIComponent(value)}`} className="font-mono underline-offset-2 hover:underline">
        {value}
      </Link>
    );
  }
  if (/^https?:\/\//i.test(value)) {
    return (
      <a href={value} target="_blank" rel="noreferrer" className="font-mono underline-offset-2 hover:underline">
        {value}
      </a>
    );
  }
  return <span className="font-mono">{value}</span>;
}

function Entry({ entry, p }: { entry: LedgerEntry; p: PanelStrings }) {
  const kind = isKind(entry.kind) ? entry.kind : "note";
  const superseded = entry.status === "superseded" || entry.superseded_by != null;
  return (
    <li
      data-entry-id={entry.id}
      data-kind={entry.kind}
      data-superseded={superseded || undefined}
      className={cn("flex flex-col gap-1 border-l-2 py-1 pl-2", KIND_CLASS[kind], superseded && "opacity-50")}
    >
      <div className="flex flex-wrap items-baseline gap-2 font-mono text-xs">
        <span>#{entry.id}</span>
        <span className="uppercase tracking-wider">{kindLabel(kind, p)}</span>
        <span className="opacity-70">{formatTs(entry.ts)}</span>
        {superseded && entry.superseded_by != null && (
          <span data-testid="ledger-replaced">{fmt(p.ledgerReplacedBy, { id: entry.superseded_by })}</span>
        )}
      </div>
      <p className={cn("whitespace-pre-wrap break-words text-sm text-foreground", superseded && "line-through")}>
        {entry.text}
      </p>
      {entry.refs?.length > 0 && (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-foreground opacity-80">
          {entry.refs.map((ref) => (
            <li key={ref}>
              <Ref value={ref} />
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function LedgerPanel({ roomId }: { roomId: string }) {
  const p = usePanelStrings();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [kind, setKind] = useState<LedgerKind | null>(null);
  const [entries, setEntries] = useState<LedgerEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(query.trim()), LEDGER_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(id);
  }, [query]);

  useEffect(() => {
    let alive = true;
    workspaceApi
      .getLedger(roomId, { q: debounced || undefined, kind: kind ?? undefined, include_superseded: true, limit: LEDGER_LIMIT })
      .then(
        (res) => {
          if (!alive) return;
          setEntries([...(res.entries ?? [])].sort((a, b) => tsValue(b.ts) - tsValue(a.ts)));
          setError(null);
        },
        (e: unknown) => alive && setError(errorMessage(e)),
      );
    return () => {
      alive = false;
    };
  }, [roomId, debounced, kind]);

  return (
    <div data-testid="ledger-panel" className="flex min-h-0 flex-col gap-3">
      <label className="relative flex items-center">
        <Search className="pointer-events-none absolute left-2 h-4 w-4 opacity-60" />
        <Input
          type="search"
          aria-label={p.ledgerSearch}
          placeholder={p.ledgerSearch}
          value={query}
          className="pl-8"
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      <div role="group" aria-label={p.ledgerSearch} className="flex flex-wrap gap-1">
        {[null, ...LEDGER_KINDS].map((k) => (
          <button
            key={k ?? "all"}
            type="button"
            data-kind-chip={k ?? "all"}
            aria-pressed={kind === k}
            className={cn(
              "min-h-9 rounded px-2 text-xs",
              kind === k ? "bg-midground/15 text-midground" : "opacity-70 hover:opacity-100",
            )}
            onClick={() => setKind(k)}
          >
            {k ? kindLabel(k, p) : p.ledgerAllKinds}
          </button>
        ))}
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {fmt(p.ledgerLoadFailed, { error })}
        </p>
      ) : entries && entries.length === 0 ? (
        <p className="text-sm opacity-70">{p.ledgerEmpty}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {entries?.map((entry) => (
            <Entry key={entry.id} entry={entry} p={p} />
          ))}
        </ul>
      )}
    </div>
  );
}

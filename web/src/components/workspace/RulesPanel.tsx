// The room's rules (its AGENTS.md): a plain textarea with a character counter.
// The server enforces the limit; its 413 message is shown as is.

import { useEffect, useState } from "react";
import { Button } from "@phi/ui/ui/components/button";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { fmt, useShellStrings } from "@/components/shell/use-shell-strings";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import { errorMessage } from "@/lib/api-error";
import { workspaceApi } from "@/lib/api-workspace";
import { cn } from "@/lib/utils";

export const RULES_MAX_CHARS = 8000;

export function RulesPanel({ roomId }: { roomId: string }) {
  const p = usePanelStrings();
  const s = useShellStrings();
  const [content, setContent] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const [max, setMax] = useState(RULES_MAX_CHARS);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    setContent(null);
    setError(null);
    setStatus(null);
    workspaceApi.getRules(roomId).then(
      (rules) => {
        if (!alive) return;
        setContent(rules.content ?? "");
        setSaved(rules.content ?? "");
        if (rules.max_chars > 0) setMax(rules.max_chars);
      },
      (e: unknown) => {
        if (!alive) return;
        setContent("");
        setError(fmt(p.rulesLoadFailed, { error: errorMessage(e) }));
      },
    );
    return () => {
      alive = false;
    };
  }, [roomId, p]);

  const save = async () => {
    if (content === null || saving) return;
    setSaving(true);
    setError(null);
    setStatus(null);
    try {
      const next = await workspaceApi.putRules(roomId, content);
      const text = next?.content ?? content;
      setSaved(text);
      setContent(text);
      setStatus(s.saved);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  if (content === null) return <Spinner />;
  const over = content.length > max;
  return (
    <div data-testid="rules-panel" className="flex min-h-0 flex-col gap-2">
      <p className="text-xs opacity-70">{p.rulesHint}</p>
      <textarea
        aria-label={s.rules}
        value={content}
        rows={14}
        spellCheck={false}
        className="min-h-48 w-full flex-1 resize-y rounded border border-current/20 bg-transparent p-2 font-mono text-sm"
        onChange={(e) => {
          setContent(e.target.value);
          setStatus(null);
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <span data-testid="rules-counter" className={cn("font-mono text-xs", over ? "text-destructive" : "opacity-70")}>
          {fmt(p.rulesCounter, { count: content.length, max })}
        </span>
        {status && (
          <span role="status" className="text-xs opacity-70">
            {status}
          </span>
        )}
        <Button
          type="button"
          size="sm"
          className="ml-auto"
          disabled={saving || content === saved}
          aria-busy={saving}
          onClick={() => void save()}
        >
          {s.save}
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

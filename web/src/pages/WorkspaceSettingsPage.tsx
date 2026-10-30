import { useCallback, useEffect, useId, useState, type ReactNode } from "react";
import { Button } from "@phi/ui/ui/components/button";
import { Card, CardContent } from "@phi/ui/ui/components/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@phi/ui/ui/components/dialog";
import { Select, SelectOption } from "@phi/ui/ui/components/select";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { Toast } from "@phi/ui/ui/components/toast";
import { H2 } from "@phi/ui/ui/components/typography/h2";
import { useToast } from "@phi/ui/hooks/use-toast";
import { fmt, useShellStrings } from "@/components/shell/use-shell-strings";
import type { ShellStrings } from "@/i18n/types";
import { errorMessage } from "@/lib/api-error";
import { FENCE_MODES, workspaceApi } from "@/lib/api-workspace";
import type {
  FenceMode,
  WorkspaceCheck,
  WorkspaceCheckIssue,
  WorkspaceSettings,
} from "@/lib/api-workspace";

const DEPTH_OPTIONS = [2, 3, 4, 5, 6, 7, 8];

type SettingsPatch = Partial<Pick<WorkspaceSettings, "max_space_depth" | "default_fence">>;

function isFenceMode(value: string): value is FenceMode {
  return (FENCE_MODES as readonly string[]).includes(value);
}

function fenceLabels(s: ShellStrings): Record<FenceMode, string> {
  return { approve: s.wsFenceApprove, strict: s.wsFenceStrict, off: s.wsFenceOff };
}

interface SettingRowProps {
  label: string;
  hint?: string;
  testId: string;
  children: ReactNode;
}

/** Labelled row; the group carries the accessible name for the control inside. */
export function SettingRow({ label, hint, testId, children }: SettingRowProps) {
  const labelId = useId();
  const hintId = useId();
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      aria-describedby={hint ? hintId : undefined}
      data-testid={testId}
      className="grid gap-2"
    >
      <span id={labelId} className="text-sm font-medium text-foreground">
        {label}
      </span>
      {children}
      {hint ? (
        <span id={hintId} className="text-xs text-muted-foreground">
          {hint}
        </span>
      ) : null}
    </div>
  );
}

function RootRow({ root, s }: { root: string; s: ShellStrings }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="grid gap-2">
      <span className="text-sm font-medium text-foreground">{s.wsRoot}</span>
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        <span
          data-testid="ws-root"
          title={root}
          className="min-w-0 flex-1 break-all font-courier text-sm text-text-secondary select-all"
        >
          {root}
        </span>
        <Button type="button" size="sm" outlined onClick={() => setOpen(true)}>
          {s.wsChange}
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>{s.wsChangeTitle}</DialogTitle>
            <DialogDescription>{s.wsChangeBody}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" outlined onClick={() => setOpen(false)}>
              {s.cancel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function issueLabel(issue: WorkspaceCheckIssue, s: ShellStrings): string {
  return issue.kind === "missing_dir" ? s.wsMissingDir : s.wsUnmappedDir;
}

function IssueList({ check, error, s }: { check: WorkspaceCheck | null; error: string | null; s: ShellStrings }) {
  if (error) {
    return (
      <p role="alert" data-testid="ws-issues" className="text-sm text-destructive">
        {fmt(s.loadFailed, { error })}
      </p>
    );
  }
  if (!check) return null;
  if (check.issues.length === 0) {
    return (
      <p data-testid="ws-issues" className="text-sm text-muted-foreground">
        {s.wsNoIssues}
      </p>
    );
  }
  return (
    <ul data-testid="ws-issues" className="grid gap-2">
      {check.issues.map((issue, i) => (
        <li
          key={`${i}:${issue.kind}:${issue.path}`}
          data-kind={issue.kind}
          className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1 text-sm"
        >
          <span className="font-medium text-destructive">{issueLabel(issue, s)}</span>
          <span className="min-w-0 break-all font-courier text-xs text-text-secondary">{issue.path}</span>
          {issue.kind === "missing_dir" ? (
            <span className="font-courier text-xs text-muted-foreground">{issue.room_id}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function MappingsSection({ s }: { s: ShellStrings }) {
  const [check, setCheck] = useState<WorkspaceCheck | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      setCheck(await workspaceApi.check());
      setError(null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  }, []);

  // Initial check (also supplies the mapping count); the button re-runs it.
  useEffect(() => {
    let alive = true;
    workspaceApi
      .check()
      .then(
        (next) => alive && setCheck(next),
        (e: unknown) => alive && setError(errorMessage(e)),
      )
      .finally(() => alive && setChecking(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="grid gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-baseline gap-2 text-sm">
          <span className="font-medium text-foreground">{s.wsMappings}</span>
          <span data-testid="ws-mappings" className="font-mono text-text-secondary">
            {check ? check.rooms : "—"}
          </span>
        </div>
        <Button
          type="button"
          size="sm"
          outlined
          data-testid="ws-check"
          disabled={checking}
          aria-busy={checking}
          onClick={() => void runCheck()}
        >
          {checking ? s.wsChecking : s.wsCheck}
        </Button>
      </div>
      <div aria-live="polite">
        <IssueList check={check} error={error} s={s} />
      </div>
    </div>
  );
}

export default function WorkspaceSettingsPage() {
  const s = useShellStrings();
  const { toast, showToast } = useToast();
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    workspaceApi.getSettings().then(
      (next) => alive && setSettings(next),
      (e: unknown) => alive && setLoadError(errorMessage(e)),
    );
    return () => {
      alive = false;
    };
  }, []);

  /** Optimistic save; `previous` restores only the fields this save touched. */
  const save = useCallback(
    async (patch: SettingsPatch, previous: SettingsPatch) => {
      setSettings((cur) => (cur ? { ...cur, ...patch } : cur));
      setSaving(true);
      try {
        const next = await workspaceApi.putSettings(patch);
        setSettings((cur) => (cur ? { ...cur, ...next } : next));
        showToast(s.saved, "success");
      } catch (e) {
        setSettings((cur) => (cur ? { ...cur, ...previous } : cur));
        showToast(fmt(s.saveFailed, { error: errorMessage(e) }), "error");
      } finally {
        setSaving(false);
      }
    },
    [s, showToast],
  );

  const onDepth = (value: string) => {
    const depth = Number(value);
    if (!settings || !Number.isInteger(depth) || depth === settings.max_space_depth) return;
    void save({ max_space_depth: depth }, { max_space_depth: settings.max_space_depth });
  };

  const onFence = (value: string) => {
    if (!settings || !isFenceMode(value) || value === settings.default_fence) return;
    void save({ default_fence: value }, { default_fence: settings.default_fence });
  };

  const labels = fenceLabels(s);

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
      <Toast toast={toast} />
      <H2 variant="sm">{s.wsTitle}</H2>
      <Card>
        <CardContent className="grid gap-6">
          {loadError ? (
            <p role="alert" className="text-sm text-destructive">
              {fmt(s.loadFailed, { error: loadError })}
            </p>
          ) : !settings ? (
            <Spinner />
          ) : (
            <>
              <RootRow root={settings.root} s={s} />
              <SettingRow label={s.wsDepth} hint={s.wsDepthHint} testId="ws-depth">
                <Select value={String(settings.max_space_depth)} disabled={saving} onValueChange={onDepth}>
                  {DEPTH_OPTIONS.map((n) => (
                    <SelectOption key={n} value={String(n)}>
                      {String(n)}
                    </SelectOption>
                  ))}
                </Select>
              </SettingRow>
              <SettingRow label={s.wsFence} testId="ws-fence">
                <Select value={settings.default_fence} disabled={saving} onValueChange={onFence}>
                  {FENCE_MODES.map((mode) => (
                    <SelectOption key={mode} value={mode}>
                      {labels[mode]}
                    </SelectOption>
                  ))}
                </Select>
              </SettingRow>
            </>
          )}
          <MappingsSection s={s} />
        </CardContent>
      </Card>
    </div>
  );
}

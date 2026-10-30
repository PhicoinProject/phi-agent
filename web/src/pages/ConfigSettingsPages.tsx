// Settings → Agents / Voice / Shortcuts / Computer: small forms over existing config keys
// (GET/PUT /api/config, which deep-merges the patch). The two browser-side
// voice preferences have no config key and live in localStorage (voice-prefs).

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { Card, CardContent } from "@phi/ui/ui/components/card";
import { Input } from "@phi/ui/ui/components/input";
import { Select, SelectOption } from "@phi/ui/ui/components/select";
import { Spinner } from "@phi/ui/ui/components/spinner";
import { Switch } from "@phi/ui/ui/components/switch";
import { Toast } from "@phi/ui/ui/components/toast";
import { H2 } from "@phi/ui/ui/components/typography/h2";
import { useToast } from "@phi/ui/hooks/use-toast";
import { fmt, useShellStrings } from "@/components/shell/use-shell-strings";
import { DEFAULT_VOICE_SHORTCUT } from "@/components/voice/MicButton";
import { VOICE_AUTO_SEND_KEY, VOICE_RELEASE_FILL_KEY, readFlag, writeFlag } from "@/components/voice/voice-prefs";
import { usePanelStrings } from "@/components/workspace/use-panel-strings";
import { SettingRow } from "@/pages/WorkspaceSettingsPage";
import { api } from "@/lib/api";
import { errorMessage } from "@/lib/api-error";

type Config = Record<string, unknown>;
type Section = Record<string, unknown>;

export const CHILDREN_OPTIONS = Array.from({ length: 16 }, (_, i) => i + 1);
export const STT_PROVIDERS = ["local", "groq", "openai", "mistral", "elevenlabs", "deepinfra", "xai"] as const;
export const GEOMETRY_OPTIONS = ["1280x720", "1440x900", "1600x900", "1920x1080", "2560x1440"] as const;
export const IDLE_OPTIONS = [0, 10, 15, 30, 60, 120] as const;

function section(cfg: Config | null, key: string): Section {
  const value = cfg?.[key];
  return value && typeof value === "object" ? (value as Section) : {};
}

/** Distinct, ordered options with the current value kept even when it is off-list. */
function withCurrent<T extends string | number>(options: readonly T[], current: T | undefined): T[] {
  return current === undefined || options.includes(current) ? [...options] : [...options, current];
}

/** Load the config once; `save` patches one section optimistically and toasts the result. */
function useConfigForm() {
  const s = useShellStrings();
  const { toast, showToast } = useToast();
  const [config, setConfig] = useState<Config | null>(null);
  const configRef = useRef(config);
  configRef.current = config;
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let alive = true;
    api.getConfig().then(
      (cfg) => alive && setConfig(cfg),
      (e: unknown) => alive && setLoadError(errorMessage(e)),
    );
    return () => {
      alive = false;
    };
  }, []);

  const save = useCallback(
    async (key: string, patch: Section) => {
      const previous = section(configRef.current, key);
      setConfig((cur) => (cur ? { ...cur, [key]: { ...section(cur, key), ...patch } } : cur));
      setSaving(true);
      try {
        await api.saveConfig({ [key]: patch });
        showToast(s.saved, "success");
      } catch (e) {
        setConfig((cur) => (cur ? { ...cur, [key]: previous } : cur));
        showToast(fmt(s.saveFailed, { error: errorMessage(e) }), "error");
      } finally {
        setSaving(false);
      }
    },
    [s, showToast],
  );

  return { config, loadError, saving, save, toast };
}

function SettingsFrame({
  title,
  form,
  children,
}: {
  title: string;
  form: ReturnType<typeof useConfigForm>;
  children: (config: Config) => ReactNode;
}) {
  const p = usePanelStrings();
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-4">
      <Toast toast={form.toast} />
      <H2 variant="sm">{title}</H2>
      <Card>
        <CardContent className="grid gap-6">
          {form.loadError ? (
            <p role="alert" className="text-sm text-destructive">
              {fmt(p.configLoadFailed, { error: form.loadError })}
            </p>
          ) : !form.config ? (
            <Spinner />
          ) : (
            children(form.config)
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/** Text field saved on blur / Enter when it changed. */
function CommitInput({
  value,
  label,
  disabled,
  placeholder,
  onCommit,
}: {
  value: string;
  label: string;
  disabled?: boolean;
  placeholder?: string;
  onCommit: (value: string) => void;
}) {
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);
  const commit = () => {
    const next = draft.trim();
    if (next !== value) onCommit(next);
  };
  return (
    <Input
      aria-label={label}
      value={draft}
      disabled={disabled}
      placeholder={placeholder}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Enter") commit();
      }}
    />
  );
}

/** A browser-local on/off preference. */
function useLocalFlag(key: string): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(() => readFlag(key));
  const set = useCallback(
    (next: boolean) => {
      setOn(next);
      writeFlag(key, next);
    },
    [key],
  );
  return [on, set];
}

export function AgentsSettingsPage() {
  const p = usePanelStrings();
  const form = useConfigForm();
  return (
    <SettingsFrame title={p.agentsTitle} form={form}>
      {(config) => {
        const delegation = section(config, "delegation");
        const max = typeof delegation.max_concurrent_children === "number" ? delegation.max_concurrent_children : undefined;
        const model = typeof delegation.model === "string" ? delegation.model : "";
        return (
          <>
            <SettingRow label={p.agentsMaxChildren} hint={p.agentsMaxChildrenHint} testId="agents-max-children">
              <Select
                value={max === undefined ? "" : String(max)}
                disabled={form.saving}
                onValueChange={(value) => {
                  const n = Number(value);
                  if (Number.isInteger(n) && n >= 1 && n !== max) void form.save("delegation", { max_concurrent_children: n });
                }}
              >
                {withCurrent(CHILDREN_OPTIONS, max).map((n) => (
                  <SelectOption key={n} value={String(n)}>
                    {String(n)}
                  </SelectOption>
                ))}
              </Select>
            </SettingRow>
            <SettingRow label={p.agentsModel} hint={p.agentsModelHint} testId="agents-model">
              <CommitInput
                label={p.agentsModel}
                value={model}
                disabled={form.saving}
                onCommit={(next) => void form.save("delegation", { model: next })}
              />
            </SettingRow>
          </>
        );
      }}
    </SettingsFrame>
  );
}

export function VoiceSettingsPage() {
  const p = usePanelStrings();
  const form = useConfigForm();
  const [autoSend, setAutoSend] = useLocalFlag(VOICE_AUTO_SEND_KEY);
  const [releaseFill, setReleaseFill] = useLocalFlag(VOICE_RELEASE_FILL_KEY);
  return (
    <SettingsFrame title={p.voiceTitle} form={form}>
      {(config) => {
        const provider = section(config, "stt").provider;
        const current = typeof provider === "string" && provider ? provider : "";
        return (
          <>
            <SettingRow label={p.voiceProvider} testId="voice-provider">
              <Select
                value={current}
                disabled={form.saving}
                onValueChange={(value) => {
                  if (value && value !== current) void form.save("stt", { provider: value });
                }}
              >
                {/* "Auto-detect" is the unset key; a deep-merge save cannot unset it again. */}
                {!current && <SelectOption value="">{p.voiceProviderAuto}</SelectOption>}
                {withCurrent<string>(STT_PROVIDERS, current || undefined).map((name) => (
                  <SelectOption key={name} value={name}>
                    {name}
                  </SelectOption>
                ))}
              </Select>
            </SettingRow>
            <SettingRow label={p.voiceAutoSend} hint={p.voiceAutoSendHint} testId="voice-auto-send">
              <Switch checked={autoSend} onCheckedChange={setAutoSend} aria-label={p.voiceAutoSend} />
            </SettingRow>
            <SettingRow label={p.voiceReleaseFill} hint={p.voiceReleaseFillHint} testId="voice-release-fill">
              <Switch checked={releaseFill} onCheckedChange={setReleaseFill} aria-label={p.voiceReleaseFill} />
            </SettingRow>
            <p className="text-sm text-muted-foreground" data-testid="voice-shortcuts-link">
              <Link to="/settings/shortcuts" className="underline underline-offset-2 hover:text-foreground">
                {p.voiceShortcutsLink}
              </Link>
            </p>
          </>
        );
      }}
    </SettingsFrame>
  );
}

export function ShortcutsSettingsPage() {
  const p = usePanelStrings();
  const form = useConfigForm();
  return (
    <SettingsFrame title={p.shortcutsTitle} form={form}>
      {(config) => {
        const shortcut = section(config, "voice").web_shortcut;
        return (
          <>
            <SettingRow label={p.voiceShortcut} hint={p.voiceShortcutHint} testId="shortcut-dictation">
              <CommitInput
                label={p.voiceShortcut}
                value={typeof shortcut === "string" ? shortcut : ""}
                placeholder={DEFAULT_VOICE_SHORTCUT}
                disabled={form.saving}
                onCommit={(next) => void form.save("voice", { web_shortcut: next })}
              />
            </SettingRow>
            <p className="text-sm text-muted-foreground">{p.shortcutsEscNote}</p>
          </>
        );
      }}
    </SettingsFrame>
  );
}

export function ComputerSettingsPage() {
  const p = usePanelStrings();
  const form = useConfigForm();
  return (
    <SettingsFrame title={p.computerTitle} form={form}>
      {(config) => {
        const desktop = section(config, "bot_desktop");
        const geometry = typeof desktop.geometry === "string" ? desktop.geometry : undefined;
        const idle = typeof desktop.idle_stop_minutes === "number" ? desktop.idle_stop_minutes : undefined;
        return (
          <>
            <SettingRow label={p.computerGeometry} testId="computer-geometry">
              <Select
                value={geometry ?? ""}
                disabled={form.saving}
                onValueChange={(value) => {
                  if (value && value !== geometry) void form.save("bot_desktop", { geometry: value });
                }}
              >
                {withCurrent<string>(GEOMETRY_OPTIONS, geometry).map((g) => (
                  <SelectOption key={g} value={g}>
                    {g.replace("x", " × ")}
                  </SelectOption>
                ))}
              </Select>
            </SettingRow>
            <SettingRow label={p.computerIdle} testId="computer-idle">
              <Select
                value={idle === undefined ? "" : String(idle)}
                disabled={form.saving}
                onValueChange={(value) => {
                  const n = Number(value);
                  if (value !== "" && Number.isFinite(n) && n >= 0 && n !== idle) {
                    void form.save("bot_desktop", { idle_stop_minutes: n });
                  }
                }}
              >
                {withCurrent<number>(IDLE_OPTIONS, idle).map((n) => (
                  <SelectOption key={n} value={String(n)}>
                    {n === 0 ? p.computerIdleNever : fmt(p.computerIdleMinutes, { n })}
                  </SelectOption>
                ))}
              </Select>
            </SettingRow>
          </>
        );
      }}
    </SettingsFrame>
  );
}

import { useMemo } from "react";
import { useI18n } from "@/i18n";
import { enShell } from "@/i18n/en";
import type { ShellStrings } from "@/i18n/types";

/** Shell strings for the active locale; missing keys fall back to English. */
export function useShellStrings(): ShellStrings {
  const { t } = useI18n();
  return useMemo(() => ({ ...enShell, ...t?.shell }), [t]);
}

/** Fills `{key}` placeholders. */
export function fmt(template: string, vars: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m));
}

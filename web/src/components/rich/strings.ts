import { useI18n } from "@/i18n";
import { en } from "@/i18n/en";
import type { RichTranslations } from "@/i18n/types";

const FALLBACK = en.rich as RichTranslations;

/** Rich-rendering strings; locales without a `rich` section use English. */
export function useRichStrings(): RichTranslations {
  const { t } = useI18n();
  return t.rich ? { ...FALLBACK, ...t.rich } : FALLBACK;
}

export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) =>
    key in values ? String(values[key]) : match,
  );
}

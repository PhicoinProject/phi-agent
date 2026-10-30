import { useMemo } from "react";
import { useI18n } from "@/i18n";
import { enPanels } from "@/i18n/en";
import type { PanelStrings } from "@/i18n/types";

/** Panel strings for the active locale; missing keys fall back to English. */
export function usePanelStrings(): PanelStrings {
  const { t } = useI18n();
  return useMemo(() => ({ ...enPanels, ...t?.panels }), [t]);
}

import { useLayoutEffect } from "react";
import { ExternalLink } from "lucide-react";
import { useI18n } from "@/i18n";
import { usePageHeader } from "@/contexts/usePageHeader";
import { cn } from "@/lib/utils";
import { PluginSlot } from "@/plugins";

export const PHI_DOCS_URL = "https://github.com/PhicoinProject/phi-agent/blob/main/website/docs/";

const DS_BUTTON_OUTLINED_LINK_CN = cn(
  "group relative inline-flex h-9 items-center gap-2 rounded-md px-4",
  "text-sm font-semibold",
  "text-midground bg-transparent border border-midground/25 hover:border-midground/40 hover:bg-midground/5 transition-colors",
);

export default function DocsPage() {
  const { t } = useI18n();
  const { setEnd } = usePageHeader();

  useLayoutEffect(() => {
    setEnd(
      <a
        href={PHI_DOCS_URL}
        target="_blank"
        rel="noopener noreferrer"
        className={DS_BUTTON_OUTLINED_LINK_CN}
      >
        <ExternalLink className="size-3.5" />
        {t.app.openDocumentation}
      </a>,
    );
    return () => {
      setEnd(null);
    };
  }, [setEnd, t]);

  return (
    <div
      className={cn(
        "flex min-h-0 w-full min-w-0 flex-1 flex-col",
        "pt-1 sm:pt-2",
      )}
    >
      <PluginSlot name="docs:top" />
      <iframe
        title={t.app.nav.documentation}
        src={PHI_DOCS_URL}
        className={cn(
          "min-h-0 w-full min-w-0 flex-1",
          "rounded-sm border border-current/20",
          // Docusaurus paints over a transparent <html> / <body> and
          // relies on the browser's canvas color (light by default) to
          // fill the viewport. Inheriting the dashboard's dark color
          // scheme makes that canvas dark, so the docs body text — which
          // is tuned for a light canvas — becomes near-invisible. Force a
          // light color scheme + white background on the iframe element so
          // the docs render cleanly regardless of the active dashboard
          // theme or the user's prefers-color-scheme.
          "[color-scheme:light] bg-white",
        )}
        sandbox="allow-scripts allow-same-origin allow-popups allow-forms"
        referrerPolicy="no-referrer-when-downgrade"
      />
      <PluginSlot name="docs:bottom" />
    </div>
  );
}

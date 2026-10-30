import { useEffect, useState } from "react";
import { CodeBlock } from "./CodeBlock";
import { useRichStrings } from "./strings";

type MermaidApi = (typeof import("mermaid"))["default"];

let mermaidLoader: Promise<MermaidApi> | null = null;
let renderSeq = 0;

/** Loaded on first diagram only, so mermaid stays out of the main chunk. */
function loadMermaid(): Promise<MermaidApi> {
  mermaidLoader ??= import("mermaid").then(({ default: mermaid }) => {
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: "dark",
      flowchart: { htmlLabels: false },
    });
    return mermaid;
  });
  return mermaidLoader;
}

function svgDataUrl(svg: string): string {
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

// Re-render at most this often while a streaming reply is still typing.
const RENDER_DEBOUNCE_MS = 250;

export function MermaidBlock({ code }: { code: string }) {
  const s = useRichStrings();
  const [image, setImage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const timer = window.setTimeout(() => {
      renderSeq += 1;
      const id = `phi-mermaid-${renderSeq}`;
      loadMermaid()
        .then((mermaid) => mermaid.render(id, code))
        .then(({ svg }) => {
          if (cancelled) return;
          setImage(svgDataUrl(svg));
          setFailed(false);
        })
        .catch(() => {
          if (!cancelled) setFailed(true);
        });
    }, RENDER_DEBOUNCE_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [code]);

  // The SVG is shown through <img>, never inserted into the page DOM.
  return (
    <figure className="space-y-1" data-mermaid>
      {image && !failed ? (
        <img src={image} alt={s.diagram} className="max-w-full" />
      ) : (
        <CodeBlock code={code} language="mermaid" />
      )}
      {failed && <figcaption className="text-xs text-destructive">{s.diagramFailed}</figcaption>}
    </figure>
  );
}

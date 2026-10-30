import { useState, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import { fill, useRichStrings } from "./strings";

export interface CodeBlockProps {
  code: string;
  language?: string;
  /** Collapse after this many lines; 0 never collapses. */
  collapseAfter?: number;
  /** Highlighted `<code>` element; plain text when omitted. */
  children?: ReactNode;
}

// `leading-relaxed` line height and `py-2.5` padding of the <pre> below.
const LINE_HEIGHT_EM = 1.625;
const PADDING_Y = "1.25rem";

export function countLines(code: string): number {
  const trimmed = code.endsWith("\n") ? code.slice(0, -1) : code;
  return trimmed ? trimmed.split("\n").length : 0;
}

export function CodeBlock({ code, language, collapseAfter = 30, children }: CodeBlockProps) {
  const s = useRichStrings();
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const lineCount = countLines(code);
  const collapsible = collapseAfter > 0 && lineCount > collapseAfter;
  const collapsed = collapsible && !expanded;

  const copy = async () => {
    if (!(await copyTextToClipboard(code))) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="border border-border bg-secondary/60" data-code-block={language || "text"}>
      <div className="flex items-center gap-2 border-b border-border px-3 py-1 text-xs text-muted-foreground">
        <span className="font-mono">{language || "text"}</span>
        <span>{fill(s.lines, { count: lineCount })}</span>
        <Button
          ghost
          size="xs"
          type="button"
          className="ml-auto"
          onClick={() => void copy()}
          aria-label={copied ? s.copied : s.copyCode}
          title={copied ? s.copied : s.copyCode}
        >
          {copied ? <Check /> : <Copy />}
        </Button>
      </div>
      <pre
        className={cn(
          "px-3 py-2.5 text-xs font-mono leading-relaxed overflow-x-auto",
          // phi-ui's global `code` rule paints selection colours; inside a block the token colours rule.
          "[&>code]:bg-transparent [&>code]:text-foreground",
          collapsed && "overflow-y-hidden",
        )}
        style={
          collapsed
            ? { maxHeight: `calc(${collapseAfter * LINE_HEIGHT_EM}em + ${PADDING_Y})` }
            : undefined
        }
      >
        {children ?? <code>{code}</code>}
      </pre>
      {collapsible && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="w-full border-t border-border px-3 py-1 text-left text-xs text-primary hover:bg-secondary"
        >
          {expanded ? s.showLess : fill(s.showAll, { count: lineCount })}
        </button>
      )}
    </div>
  );
}

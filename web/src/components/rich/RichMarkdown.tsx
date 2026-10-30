import { createContext, useContext, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components, type ExtraProps, type Options } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import "katex/dist/katex.min.css";
import "./rich.css";
import { cn } from "@/lib/utils";
import { CodeBlock } from "./CodeBlock";
import { FileCard } from "./FileCard";
import { FilePreview } from "./FilePreview";
import type { PreviewFile } from "./file-kind";
import { parseMediaSegments } from "./MediaLine";
import { MermaidBlock } from "./MermaidBlock";
import { useRichStrings } from "./strings";

export interface RichMarkdownProps {
  content: string;
  /** Reply still arriving: shows a caret and defers the half-typed last line. */
  streaming?: boolean;
  /** Collapse fenced code longer than this many lines; 0 never collapses. */
  collapseCodeAfter?: number;
  /** Open a file card in the host's preview panel; RichMarkdown opens its own when omitted. */
  onOpenFile?: (file: PreviewFile) => void;
  className?: string;
}

// No rehype-raw: raw HTML in a reply stays text, never DOM.
const REMARK_PLUGINS: Options["remarkPlugins"] = [remarkGfm, remarkMath];
const REHYPE_PLUGINS: Options["rehypePlugins"] = [
  rehypeKatex,
  [rehypeHighlight, { plainText: ["text", "txt", "plain"] }],
];

interface RichContextValue {
  collapseAfter: number;
  openFile?: (file: PreviewFile) => void;
}

// Components below are module-level (stable identity, so code blocks keep
// their expanded state while a reply streams); per-render options come here.
const RichContext = createContext<RichContextValue>({ collapseAfter: 30 });

/** The slice of a hast node the overrides read. */
interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  properties?: { className?: unknown };
  children?: HastNode[];
}

function hastText(node: HastNode | undefined): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  return (node.children ?? []).map(hastText).join("");
}

function hastClassName(node: HastNode | undefined): string | undefined {
  const classes = node?.properties?.className;
  return Array.isArray(classes) ? classes.join(" ") : undefined;
}

function codeLanguage(code: HastNode | undefined): string {
  const classes = code?.properties?.className;
  const list: unknown[] = Array.isArray(classes) ? classes : [];
  const match = list.find(
    (name): name is string => typeof name === "string" && name.startsWith("language-"),
  );
  return match ? match.slice("language-".length) : "";
}

function isLocalPath(src: string): boolean {
  return /^(?:\/(?!\/)|~\/|[A-Za-z]:[\\/])/.test(src);
}

const LINK_CLASS =
  "text-primary underline underline-offset-2 decoration-primary/30 hover:decoration-primary/60 transition-colors";

function MarkdownLink({ node, href, children, className, ...rest }: ComponentPropsWithoutRef<"a"> & ExtraProps) {
  // In-page anchors (footnotes) stay in the tab; everything else opens a new one.
  const external = !href?.startsWith("#");
  return (
    <a
      {...rest}
      href={href}
      className={cn(LINK_CLASS, className)}
      target={external ? "_blank" : undefined}
      rel={external ? "noopener noreferrer" : undefined}
    >
      {children}
    </a>
  );
}

/** Re-emit rehype-highlight's token spans inside our own <code>. */
function HastChildren({ node }: { node: HastNode | undefined }) {
  return (node?.children ?? []).map((child, index) =>
    child.type === "text" ? (
      child.value
    ) : (
      <span key={index} className={hastClassName(child)}>
        <HastChildren node={child} />
      </span>
    ),
  );
}

function PreBlock({ node }: ComponentPropsWithoutRef<"pre"> & ExtraProps) {
  const { collapseAfter } = useContext(RichContext);
  const code = (node as HastNode | undefined)?.children?.find((child) => child.tagName === "code");
  // mdast-util-to-hast appends a newline to every code value.
  const text = hastText(code).replace(/\n$/, "");
  const language = codeLanguage(code);
  if (language === "mermaid") return <MermaidBlock code={text} />;
  return (
    <CodeBlock code={text} language={language} collapseAfter={collapseAfter}>
      <code className={hastClassName(code)}>
        <HastChildren node={code} />
      </code>
    </CodeBlock>
  );
}

// Images never auto-load: local paths become file cards, URLs plain links.
function MarkdownImage({ src, alt }: ComponentPropsWithoutRef<"img"> & ExtraProps) {
  const { openFile } = useContext(RichContext);
  const s = useRichStrings();
  if (typeof src === "string" && isLocalPath(src)) {
    return <FileCard file={{ path: src }} onOpen={openFile} />;
  }
  if (typeof src !== "string" || !src) return <span>{alt || s.image}</span>;
  return (
    <a href={src} className={LINK_CLASS} target="_blank" rel="noopener noreferrer">
      {alt || s.image}
    </a>
  );
}

function heading(Tag: "h1" | "h2" | "h3" | "h4", size: string) {
  return function Heading({ node, className, ...rest }: ComponentPropsWithoutRef<"h1"> & ExtraProps) {
    // Keep className/id: the GFM footnote heading relies on `sr-only`.
    return <Tag {...rest} className={cn(size, className)} />;
  };
}

const COMPONENTS: Components = {
  a: MarkdownLink,
  pre: PreBlock,
  img: MarkdownImage,
  table: ({ children }) => (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">{children}</table>
    </div>
  ),
  th: ({ children, style }) => (
    <th style={style} className="border border-border bg-secondary/60 px-2 py-1 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children, style }) => (
    <td style={style} className="border border-border px-2 py-1 align-top">
      {children}
    </td>
  ),
  ul: ({ children, className }) => {
    const tasks = className?.includes("contains-task-list");
    return (
      <ul className={cn(className, "space-y-0.5", tasks ? "list-none pl-1" : "list-disc pl-5")}>{children}</ul>
    );
  },
  ol: ({ children, className, start }) => (
    <ol start={start} className={cn(className, "space-y-0.5 list-decimal pl-5")}>
      {children}
    </ol>
  ),
  h1: heading("h1", "text-base font-bold"),
  h2: heading("h2", "text-sm font-bold"),
  h3: heading("h3", "text-sm font-semibold"),
  h4: heading("h4", "text-sm font-medium"),
  hr: () => <hr className="border-border" />,
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border pl-3 text-muted-foreground">{children}</blockquote>
  ),
};

const CONTAINER_CLASS = cn(
  "phi-rich text-sm text-foreground leading-relaxed space-y-2 break-words",
  "[&_:not(pre)>code]:bg-secondary/60 [&_:not(pre)>code]:px-1.5 [&_:not(pre)>code]:py-0.5",
  "[&_:not(pre)>code]:text-xs [&_:not(pre)>code]:font-mono [&_:not(pre)>code]:text-primary/90",
);

export function RichMarkdown({
  content,
  streaming = false,
  collapseCodeAfter = 30,
  onOpenFile,
  className,
}: RichMarkdownProps) {
  const [ownPreview, setOwnPreview] = useState<PreviewFile | null>(null);
  const openFile = onOpenFile ?? setOwnPreview;
  const segments = parseMediaSegments(content, { streaming });

  return (
    <RichContext value={{ collapseAfter: collapseCodeAfter, openFile }}>
      <div className={cn(CONTAINER_CLASS, className)}>
        {segments.map((segment, index) =>
          segment.type === "file" ? (
            <div key={index}>
              <FileCard file={{ path: segment.path }} onOpen={openFile} />
            </div>
          ) : (
            <ReactMarkdown
              key={index}
              remarkPlugins={REMARK_PLUGINS}
              rehypePlugins={REHYPE_PLUGINS}
              components={COMPONENTS}
            >
              {segment.text}
            </ReactMarkdown>
          ),
        )}
        {streaming && (
          <span
            aria-hidden
            className="inline-block w-[0.5em] h-[1em] ml-0.5 align-[-0.15em] bg-foreground/50 animate-pulse"
          />
        )}
        {!onOpenFile && <FilePreview file={ownPreview} onClose={() => setOwnPreview(null)} />}
      </div>
    </RichContext>
  );
}

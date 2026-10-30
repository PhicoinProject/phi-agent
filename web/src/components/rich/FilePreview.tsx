import { useEffect, useMemo, useRef, useState, useSyncExternalStore, type ComponentType, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Check, Copy, Download, FolderOpen, Maximize2, Minimize2, X } from "lucide-react";
import { Button } from "@phi/ui/ui/components/button";
import { Spinner } from "@phi/ui/ui/components/spinner";
import type { ManagedFileReadResponse } from "@/lib/api-files";
import { copyTextToClipboard } from "@/lib/clipboard";
import { cn } from "@/lib/utils";
import {
  fileExtension,
  fileKind,
  fileName,
  formatFileSize,
  languageForPath,
  type FileKind,
  type PreviewFile,
} from "./file-kind";
import { dataUrlBytes, dataUrlText, fileDownloadUrl, fileStreamUrl, useManagedFile } from "./file-source";
import { ImageViewer } from "./ImageViewer";
import { PdfViewer } from "./PdfViewer";
import { RichMarkdown } from "./RichMarkdown";
import { useRichStrings } from "./strings";

export interface FilePreviewProps {
  /** File to show; null keeps the panel closed. */
  file: PreviewFile | null;
  onClose: () => void;
  /** Reveal the file in the Files page; the button is hidden when omitted. */
  onOpenInFiles?: (path: string) => void;
}

interface ViewerProps {
  file: PreviewFile;
  /** Follow a file card inside a previewed Markdown file. */
  openFile: (file: PreviewFile) => void;
}

// Above this size text is shown plain: highlighting a huge file stalls the tab.
const LARGE_TEXT_CHARS = 256 * 1024;
const NARROW_QUERY = "(max-width: 767px)";

function subscribeNarrow(onChange: () => void): () => void {
  if (typeof window.matchMedia !== "function") return () => {};
  const query = window.matchMedia(NARROW_QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function isNarrow(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia(NARROW_QUERY).matches;
}

/** Fence `text` as a code block whose fence no line inside can close. */
export function fencedCode(text: string, language: string): string {
  const longest = (text.match(/`{3,}/g) ?? []).reduce((max, run) => Math.max(max, run.length), 2);
  const fence = "`".repeat(longest + 1);
  return `${fence}${language}\n${text.replace(/\n$/, "")}\n${fence}`;
}

function triggerDownload(path: string, name: string) {
  const link = document.createElement("a");
  link.href = fileDownloadUrl(path);
  link.download = name;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

function Notice({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "error" }) {
  return (
    <p className={cn("flex items-center gap-2 p-4 text-sm", tone === "error" ? "text-destructive" : "text-muted-foreground")}>
      {children}
    </p>
  );
}

/** Loads the file through /api/files/read and hands the payload to `children`. */
function LoadedFile({ path, children }: { path: string; children: (file: ManagedFileReadResponse) => ReactNode }) {
  const s = useRichStrings();
  const state = useManagedFile(path);
  if (state.status === "loading") {
    return (
      <Notice>
        <Spinner /> {s.loading}
      </Notice>
    );
  }
  if (state.status === "error") return <Notice tone="error">{s.loadFailed}</Notice>;
  return children(state.file);
}

function ImageFileViewer({ file }: ViewerProps) {
  const name = file.name || fileName(file.path);
  return <LoadedFile path={file.path}>{(loaded) => <ImageViewer src={loaded.data_url} alt={name} />}</LoadedFile>;
}

function PdfBody({ dataUrl }: { dataUrl: string }) {
  const data = useMemo(() => dataUrlBytes(dataUrl), [dataUrl]);
  return <PdfViewer data={data} />;
}

function PdfFileViewer({ file }: ViewerProps) {
  return <LoadedFile path={file.path}>{(loaded) => <PdfBody dataUrl={loaded.data_url} />}</LoadedFile>;
}

function TextBody({ dataUrl, file, openFile }: ViewerProps & { dataUrl: string }) {
  const s = useRichStrings();
  const text = useMemo(() => dataUrlText(dataUrl), [dataUrl]);
  if (text.length > LARGE_TEXT_CHARS) {
    return (
      <div className="space-y-2 p-3">
        <p className="text-xs text-muted-foreground">{s.largeFilePlain}</p>
        <pre className="overflow-x-auto text-xs font-mono leading-relaxed">{text}</pre>
      </div>
    );
  }
  const content = fileKind(file.path) === "markdown" ? text : fencedCode(text, languageForPath(file.path));
  return (
    <div className="p-3">
      <RichMarkdown content={content} collapseCodeAfter={0} onOpenFile={openFile} />
    </div>
  );
}

function TextFileViewer(props: ViewerProps) {
  return <LoadedFile path={props.file.path}>{(loaded) => <TextBody {...props} dataUrl={loaded.data_url} />}</LoadedFile>;
}

function MediaViewer({ file, element: Element }: ViewerProps & { element: "audio" | "video" }) {
  const s = useRichStrings();
  const [failed, setFailed] = useState(false);
  if (failed) return <Notice tone="error">{s.playbackFailed}</Notice>;
  return (
    <div className="flex h-full items-center justify-center p-3">
      <Element
        controls
        preload="metadata"
        src={fileStreamUrl(file.path)}
        onError={() => setFailed(true)}
        className={Element === "video" ? "max-h-full max-w-full" : "w-full"}
      />
    </div>
  );
}

function OtherFileViewer({ file }: ViewerProps) {
  const s = useRichStrings();
  const rows: [string, string][] = [
    [s.sizeLabel, formatFileSize(file.size) || "—"],
    [s.typeLabel, file.mimeType || fileExtension(file.path).toUpperCase() || "—"],
    [s.pathLabel, file.path],
  ];
  return (
    <div className="space-y-3 p-4 text-sm">
      <p className="text-muted-foreground">{s.noPreview}</p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="break-all font-mono">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const VIEWERS: Record<FileKind, ComponentType<ViewerProps>> = {
  image: ImageFileViewer,
  audio: (props) => <MediaViewer {...props} element="audio" />,
  video: (props) => <MediaViewer {...props} element="video" />,
  pdf: PdfFileViewer,
  markdown: TextFileViewer,
  code: TextFileViewer,
  text: TextFileViewer,
  other: OtherFileViewer,
};

function PreviewFooter({ file, onOpenInFiles }: { file: PreviewFile; onOpenInFiles?: (path: string) => void }) {
  const s = useRichStrings();
  const [copied, setCopied] = useState(false);
  const copyPath = async () => {
    if (!(await copyTextToClipboard(file.path))) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
      {onOpenInFiles && (
        <Button outlined size="sm" type="button" prefix={<FolderOpen />} onClick={() => onOpenInFiles(file.path)}>
          {s.openInFiles}
        </Button>
      )}
      <Button
        outlined
        size="sm"
        type="button"
        prefix={<Download />}
        onClick={() => triggerDownload(file.path, file.name || fileName(file.path))}
      >
        {s.download}
      </Button>
      <Button ghost size="sm" type="button" prefix={copied ? <Check /> : <Copy />} onClick={() => void copyPath()}>
        {copied ? s.copied : s.copyPath}
      </Button>
    </div>
  );
}

/**
 * File preview: a right-hand panel on desktop, a full-screen sheet below
 * 768px. Esc closes. The viewer is picked from the extension.
 */
export function FilePreview({ file, onClose, onOpenInFiles }: FilePreviewProps) {
  const s = useRichStrings();
  const narrow = useSyncExternalStore(subscribeNarrow, isNarrow, () => false);
  const [maximized, setMaximized] = useState(false);
  // A file card followed inside a previewed Markdown file, until `file` changes.
  const [nested, setNested] = useState<{ from: string; file: PreviewFile } | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  // Latest onClose without re-running the effect: hosts often pass an inline
  // callback, and re-focusing the panel on every render would steal focus.
  const onCloseRef = useRef(onClose);
  const open = file !== null;

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    panelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCloseRef.current();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!file) return null;
  const shown = nested?.from === file.path ? nested.file : file;
  const kind = fileKind(shown.path);
  const Viewer = VIEWERS[kind];
  const fullScreen = narrow || maximized;
  const size = formatFileSize(shown.size);

  return createPortal(
    <div
      ref={panelRef}
      tabIndex={-1}
      role="dialog"
      aria-modal={fullScreen}
      aria-label={s.preview}
      data-file-preview={narrow ? "sheet" : "panel"}
      className={cn(
        "fixed z-[100] flex flex-col border-border bg-card text-foreground shadow-2xl outline-none",
        fullScreen ? "inset-0" : "inset-y-0 right-0 w-[min(44rem,55vw)] border-l",
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="min-w-0 flex-1 truncate font-mono text-sm" title={shown.path}>
          {shown.name || fileName(shown.path)}
        </span>
        {size && <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{size}</span>}
        {!narrow && (
          <Button
            ghost
            size="xs"
            type="button"
            onClick={() => setMaximized(!maximized)}
            aria-label={maximized ? s.restorePreview : s.expandPreview}
            title={maximized ? s.restorePreview : s.expandPreview}
          >
            {maximized ? <Minimize2 /> : <Maximize2 />}
          </Button>
        )}
        <Button ghost size="xs" type="button" onClick={onClose} aria-label={s.closePreview} title={s.closePreview}>
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto" data-viewer={kind}>
        <Viewer key={shown.path} file={shown} openFile={(next) => setNested({ from: file.path, file: next })} />
      </div>
      <PreviewFooter file={shown} onOpenInFiles={onOpenInFiles} />
    </div>,
    document.body,
  );
}

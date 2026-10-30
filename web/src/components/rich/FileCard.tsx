import { File, FileCode, FileHeadphone, FileImage, FilePlay, FileText, type LucideIcon } from "lucide-react";
import { fileKind, fileName, formatFileSize, type FileKind, type PreviewFile } from "./file-kind";
import { fill, useRichStrings } from "./strings";

const KIND_ICONS: Record<FileKind, LucideIcon> = {
  image: FileImage,
  audio: FileHeadphone,
  video: FilePlay,
  pdf: FileText,
  markdown: FileText,
  code: FileCode,
  text: FileText,
  other: File,
};

export interface FileCardProps {
  file: PreviewFile;
  onOpen?: (file: PreviewFile) => void;
}

/** Compact inline card for a file mentioned in a reply; click opens the preview. */
export function FileCard({ file, onOpen }: FileCardProps) {
  const s = useRichStrings();
  const kind = fileKind(file.path);
  const Icon = KIND_ICONS[kind];
  const name = file.name || fileName(file.path);
  const size = formatFileSize(file.size);

  return (
    <button
      type="button"
      onClick={() => onOpen?.(file)}
      disabled={!onOpen}
      title={file.path}
      aria-label={fill(s.openFile, { name })}
      data-file-kind={kind}
      className="inline-flex max-w-full items-center gap-2 border border-border bg-secondary/60 px-2.5 py-1.5 text-left text-xs transition hover:border-primary/60 hover:bg-secondary disabled:cursor-default"
    >
      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 truncate font-mono text-foreground">{name}</span>
      {size && <span className="shrink-0 tabular-nums text-muted-foreground">{size}</span>}
      {onOpen && <span className="shrink-0 font-semibold uppercase tracking-[0.08em] text-primary">{s.open}</span>}
    </button>
  );
}

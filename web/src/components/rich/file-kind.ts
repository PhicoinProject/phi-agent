/** Which preview viewer a file path gets, decided by extension only. */
export type FileKind =
  | "image"
  | "audio"
  | "video"
  | "pdf"
  | "markdown"
  | "code"
  | "text"
  | "other";

// Audio/video lists mirror the backend's streamable set (/api/files/stream
// answers 415 for anything else).
const KIND_BY_EXTENSION: Record<string, FileKind> = {
  png: "image",
  jpg: "image",
  jpeg: "image",
  gif: "image",
  webp: "image",
  svg: "image",
  avif: "image",
  mp3: "audio",
  wav: "audio",
  ogg: "audio",
  opus: "audio",
  flac: "audio",
  m4a: "audio",
  mp4: "video",
  webm: "video",
  mov: "video",
  mkv: "video",
  avi: "video",
  pdf: "pdf",
  md: "markdown",
  markdown: "markdown",
  txt: "text",
  log: "text",
  csv: "text",
  tsv: "text",
};

// highlight.js language names (lowlight "common" set).
const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  ts: "typescript",
  tsx: "typescript",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  py: "python",
  rb: "ruby",
  go: "go",
  rs: "rust",
  java: "java",
  kt: "kotlin",
  c: "c",
  h: "c",
  cc: "cpp",
  cpp: "cpp",
  hpp: "cpp",
  cs: "csharp",
  php: "php",
  sh: "bash",
  bash: "bash",
  zsh: "bash",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  toml: "ini",
  ini: "ini",
  xml: "xml",
  html: "xml",
  css: "css",
  scss: "scss",
  sql: "sql",
  swift: "swift",
  lua: "lua",
  r: "r",
  diff: "diff",
  patch: "diff",
};

export function fileName(path: string): string {
  const parts = path.split(/[\\/]/);
  return parts[parts.length - 1] || path;
}

export function fileExtension(path: string): string {
  const name = fileName(path);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

export function fileKind(path: string): FileKind {
  const ext = fileExtension(path);
  if (LANGUAGE_BY_EXTENSION[ext]) return "code";
  return KIND_BY_EXTENSION[ext] ?? "other";
}

export function isPreviewablePath(path: string): boolean {
  return fileKind(path) !== "other";
}

/** highlight.js language for a code file, "" when plain text. */
export function languageForPath(path: string): string {
  return LANGUAGE_BY_EXTENSION[fileExtension(path)] ?? "";
}

export function formatFileSize(size: number | null | undefined): string {
  if (size === null || size === undefined || !Number.isFinite(size)) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  if (size < 1024 * 1024 * 1024) return `${(size / (1024 * 1024)).toFixed(1)} MB`;
  return `${(size / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

/** A file a card or the preview panel points at. */
export interface PreviewFile {
  path: string;
  name?: string;
  size?: number | null;
  mimeType?: string;
}

import { isPreviewablePath } from "./file-kind";

export type MediaSegment =
  | { type: "markdown"; text: string }
  | { type: "file"; path: string; source: "media" | "path" };

// Same rules as the TUI (ui-tui/src/components/markdown.tsx): the whole line
// is the directive, optionally wrapped in a quote or backtick.
export const MEDIA_LINE_RE = /^\s*[`"']?MEDIA:\s*(\S+?)[`"']?\s*$/;
export const AUDIO_DIRECTIVE_RE = /^\s*\[\[audio_as_voice\]\]\s*$/;
// A line that is nothing but an absolute path (POSIX, ~/, or Windows drive).
const BARE_PATH_RE = /^\s*[`"']?((?:~\/|\/(?!\/)|[A-Za-z]:[\\/])[^\s`"']+)[`"']?\s*$/;
const FENCE_RE = /^ {0,3}(`{3,}|~{3,})(.*)$/;

export function mediaLinePath(
  line: string,
): { path: string; source: "media" | "path" } | null {
  const media = MEDIA_LINE_RE.exec(line);
  if (media) return { path: media[1], source: "media" };
  const bare = BARE_PATH_RE.exec(line);
  if (bare && isPreviewablePath(bare[1])) return { path: bare[1], source: "path" };
  return null;
}

/** Track fenced-code state so paths inside code blocks stay code. */
function nextFence(open: string | null, line: string): string | null {
  const match = FENCE_RE.exec(line);
  if (!match) return open;
  const marker = match[1];
  if (open === null) return marker;
  const closes =
    marker[0] === open[0] && marker.length >= open.length && match[2].trim() === "";
  return closes ? null : open;
}

/**
 * Split assistant text into markdown runs and file references. While
 * `streaming`, the unfinished last line stays markdown so a half-typed path
 * does not flash a card.
 */
export function parseMediaSegments(
  text: string,
  options: { streaming?: boolean } = {},
): MediaSegment[] {
  const segments: MediaSegment[] = [];
  const lines = text.split("\n");
  let buffer: string[] = [];
  let fence: string | null = null;
  const flush = () => {
    const chunk = buffer.join("\n");
    buffer = [];
    if (chunk.trim()) segments.push({ type: "markdown", text: chunk });
  };

  lines.forEach((line, index) => {
    const inFence = fence !== null;
    fence = nextFence(fence, line);
    const partial = options.streaming && index === lines.length - 1;
    if (inFence || fence !== null || partial) {
      buffer.push(line);
      return;
    }
    if (AUDIO_DIRECTIVE_RE.test(line)) return;
    const file = mediaLinePath(line);
    if (!file) {
      buffer.push(line);
      return;
    }
    flush();
    segments.push({ type: "file", ...file });
  });
  flush();
  return segments;
}

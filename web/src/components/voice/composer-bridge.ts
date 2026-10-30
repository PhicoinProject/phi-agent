/**
 * Where dictated text goes: the active composer. A text composer (the new-chat box, the Rich
 * composer) wins over the terminal while it is mounted; the terminal (PTY) is the fallback.
 * The most recently registered sink of a kind wins.
 */
import { useEffect, useRef } from "react";

export type ComposerKind = "text" | "pty";

/** Text for the terminal as one bracketed paste: never run line by line, never auto-submitted. */
export function bracketedPaste(text: string): string {
  return `\x1b[200~${text}\x1b[201~`;
}

export interface ComposerSink {
  /** Put text into the composer without sending it. */
  insert: (text: string) => void;
  /** Send what the composer holds. */
  submit: () => void;
}

interface Entry {
  kind: ComposerKind;
  sink: ComposerSink;
}

const entries: Entry[] = [];

export function registerComposer(kind: ComposerKind, sink: ComposerSink): () => void {
  const entry = { kind, sink };
  entries.push(entry);
  return () => {
    const i = entries.indexOf(entry);
    if (i >= 0) entries.splice(i, 1);
  };
}

export function activeComposer(): ComposerSink | null {
  for (const kind of ["text", "pty"] as const) {
    for (let i = entries.length - 1; i >= 0; i--) if (entries[i].kind === kind) return entries[i].sink;
  }
  return null;
}

/** Registers `sink` while mounted (null = none); the latest callbacks are always used. */
export function useComposerSink(kind: ComposerKind, sink: ComposerSink | null): void {
  const ref = useRef(sink);
  ref.current = sink;
  const enabled = sink !== null;
  useEffect(() => {
    if (!enabled) return;
    return registerComposer(kind, {
      insert: (text) => ref.current?.insert(text),
      submit: () => ref.current?.submit(),
    });
  }, [kind, enabled]);
}

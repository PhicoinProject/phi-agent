// Test doubles shared by the voice component tests: a scriptable WebSocket and mic stack.
import { act } from "react";
import { vi } from "vitest";

import type { BlobRecorder, DictationDeps, DictationSocket, Pcm } from "./useDictation";

type Listener = (ev: Event) => void;

/** Drain pending promises / timers (getUserMedia, FileReader, upload) inside act. */
export function settle() {
  return act(async () => {
    for (let i = 0; i < 6; i++) await new Promise((r) => setTimeout(r, 0));
  });
}

/** jsdom runs without an origin here, so localStorage is undefined: stub a Map-backed one. */
export function stubLocalStorage() {
  const store = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    clear: () => store.clear(),
    getItem: (key: string) => store.get(key) ?? null,
    removeItem: (key: string) => void store.delete(key),
    setItem: (key: string, value: string) => void store.set(key, String(value)),
  });
}

/** A recording 2D context for `<canvas>` (jsdom has none) and a manual requestAnimationFrame. */
export function stubCanvas() {
  const ctx = { clearRect: vi.fn(), fillRect: vi.fn(), fillStyle: "", setTransform: vi.fn() };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(ctx as unknown as CanvasRenderingContext2D);
  let frames = new Map<number, FrameRequestCallback>();
  let next = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    frames.set(++next, cb);
    return next;
  });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => void frames.delete(id));
  return {
    ctx,
    /** Animation frames waiting to run. */
    pending: () => frames.size,
    /** Run the frames requested so far. */
    flushFrames: () => {
      const due = frames;
      frames = new Map();
      act(() => due.forEach((cb) => cb(performance.now())));
    },
    /** Heights of the bars drawn by the last `count` fillRect calls, left to right. */
    bars: (count: number) => ctx.fillRect.mock.calls.slice(-count).map((c) => c[3] as number),
  };
}

export class FakeSocket implements DictationSocket {
  binaryType: BinaryType = "blob";
  readyState = 0;
  url: string;
  sent: Array<string | ArrayBufferLike | ArrayBufferView> = [];
  closeCode: number | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(url: string) {
    this.url = url;
  }

  addEventListener(type: string, listener: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  send(data: string | ArrayBufferLike | ArrayBufferView) {
    if (this.readyState !== 1) throw new Error("send before open");
    this.sent.push(data);
  }

  close(code?: number) {
    this.closeCode = code ?? 1000;
    this.readyState = 3;
  }

  private emit(type: string, ev: Event) {
    for (const l of this.listeners.get(type) ?? []) l(ev);
  }

  serverOpen() {
    this.readyState = 1;
    this.emit("open", new Event("open"));
  }

  serverSend(message: unknown) {
    this.emit("message", new MessageEvent("message", { data: JSON.stringify(message) }));
  }

  serverClose(code = 1011) {
    this.readyState = 3;
    this.emit("close", new CloseEvent("close", { code }));
  }

  /** JSON control messages the client sent, in order. */
  json(): unknown[] {
    return this.sent.filter((d): d is string => typeof d === "string").map((d) => JSON.parse(d));
  }

  /** Binary PCM frames the client sent, as sample arrays. */
  pcm(): number[][] {
    return this.sent
      .filter((d) => typeof d !== "string")
      .map((d) => Array.from(new Int16Array(ArrayBuffer.isView(d) ? d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength) : d)));
  }
}

export function fakeMic(overrides: Partial<DictationDeps> = {}) {
  const sockets: FakeSocket[] = [];
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] } as unknown as MediaStream;
  const captureStop = vi.fn();
  let onPcm: ((pcm: Pcm) => void) | null = null;
  const recorder = {
    discard: vi.fn(),
    stop: vi.fn(async () => new Blob(["webm-opus-bytes"], { type: "audio/webm;codecs=opus" })),
  };
  const transcribe = vi.fn(async () => "  uploaded words ");
  const getUserMedia = vi.fn(async () => stream);
  const deps: DictationDeps = {
    createSocket: (url) => {
      const s = new FakeSocket(url);
      sockets.push(s);
      return s;
    },
    getUserMedia,
    secureContext: true,
    startCapture: vi.fn(async (_stream: MediaStream, cb: (pcm: Pcm) => void) => {
      onPcm = cb;
      return { sampleRate: 16000, stop: captureStop };
    }),
    startRecorder: vi.fn(() => recorder as BlobRecorder),
    streamUrl: async () => "ws://dashboard.test/api/audio/transcribe-stream?token=t",
    transcribe,
    ...overrides,
  };
  return {
    captureStop,
    deps,
    /** Push one PCM chunk from the (fake) audio graph. */
    emitPcm: (samples: number[]) => onPcm?.(Int16Array.from(samples)),
    getUserMedia,
    recorder,
    get socket() {
      const s = sockets.at(-1);
      if (!s) throw new Error("no socket opened");
      return s;
    },
    sockets,
    track,
    transcribe,
  };
}

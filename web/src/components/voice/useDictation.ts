/**
 * Browser dictation for the dashboard. Mic PCM (16 kHz s16le mono) streams to
 * `/api/audio/transcribe-stream` WHILE the user speaks, so partial text arrives as it is recognized
 * and the transcript lands right at end of take (server contract: `phi_cli/web_routers/audio.py`):
 *
 *   client → {"sample_rate": N}, then binary s16le mono PCM frames, {"eos": true}
 *   server → {"type":"partial","text"}, {"type":"final","transcript"}, {"type":"error","message"}
 *
 * A MediaRecorder runs alongside. When the server answers `error` (no live speech-to-text, provider
 * failure) or the socket drops before the final, the recorded blob is transcribed through
 * `POST /api/audio/transcribe` instead. Closing the socket without `eos` is the server's cancel.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { buildWsUrl, fetchJSON } from "@/lib/api";

import { readMicDeviceId, writeMicDeviceId } from "./voice-prefs";

export type DictationState = "idle" | "requesting" | "recording" | "finalizing" | "error";
export type DictationDisabledReason = "insecure" | "unsupported" | null;

export const TARGET_SAMPLE_RATE = 16000;

export interface DictationSocket {
  binaryType: BinaryType;
  readonly readyState: number;
  send(data: string | ArrayBufferView<ArrayBuffer>): void;
  close(code?: number): void;
  addEventListener(type: "open" | "message" | "close" | "error", listener: (ev: Event) => void): void;
}

export interface PcmCapture {
  /** Rate of the Int16 chunks handed to `onPcm`. */
  sampleRate: number;
  stop(): void;
}

/** Little-endian s16 mono samples; backed by a plain ArrayBuffer so WebSocket.send accepts them. */
export type Pcm = Int16Array<ArrayBuffer>;
export type StartPcmCapture = (stream: MediaStream, onPcm: (pcm: Pcm) => void) => Promise<PcmCapture>;

export interface BlobRecorder {
  /** Finish the take; resolves with the recording (null when nothing was captured). */
  stop(): Promise<Blob | null>;
  discard(): void;
}

export type StartBlobRecorder = (stream: MediaStream) => BlobRecorder | null;

/** Injection points for tests; production uses the browser defaults below. */
export interface DictationDeps {
  getUserMedia?: (constraints: MediaStreamConstraints) => Promise<MediaStream>;
  createSocket?: (url: string) => DictationSocket;
  streamUrl?: () => Promise<string>;
  startCapture?: StartPcmCapture;
  startRecorder?: StartBlobRecorder;
  transcribe?: (dataUrl: string, mimeType: string) => Promise<string>;
  secureContext?: boolean;
  /** Device menu (MicDevicePicker): list inputs, and subscribe to plug/unplug (returns unsubscribe). */
  enumerateDevices?: () => Promise<MediaDeviceInfo[]>;
  onDeviceChange?: (listener: () => void) => () => void;
}

export interface DictationOptions {
  deps?: DictationDeps;
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
}

export interface Dictation {
  state: DictationState;
  partial: string;
  final: string;
  error: string | null;
  disabledReason: DictationDisabledReason;
  /** Live microphone level (0..1) of the current take; 0 when idle. */
  meter: LevelMeter;
  start: () => Promise<void>;
  stop: () => void;
  cancel: () => void;
}

/** Mic level outside React state: one update per PCM chunk would re-render the footer ~8×/s. */
export interface LevelMeter {
  readonly level: number;
  subscribe(listener: (level: number) => void): () => void;
}

export function createLevelMeter(): LevelMeter & { push(level: number): void } {
  let level = 0;
  const listeners = new Set<(level: number) => void>();
  return {
    get level() {
      return level;
    },
    push(next) {
      level = next;
      for (const listener of listeners) listener(next);
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

/** RMS of s16 samples on a dBFS scale: -60 dB (and silence) → 0, 0 dB → 1. */
export function pcmLevel(pcm: Int16Array): number {
  if (!pcm.length) return 0;
  let sum = 0;
  for (let i = 0; i < pcm.length; i++) sum += pcm[i] * pcm[i];
  const rms = Math.sqrt(sum / pcm.length) / 0x8000;
  if (rms <= 0) return 0;
  return Math.max(0, Math.min(1, 1 + (20 * Math.log10(rms)) / 60));
}

export function floatToS16(input: Float32Array): Pcm {
  const out = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    out[i] = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
  }
  return out;
}

/** Stateful float→s16 resampler to `outputRate`; each output sample averages its input window,
 *  and the fractional read position carries over so chunk boundaries do not drift. */
export function createDownsampler(inputRate: number, outputRate = TARGET_SAMPLE_RATE) {
  const ratio = inputRate / outputRate;
  if (ratio <= 1) return floatToS16;
  let pos = 0;
  return (input: Float32Array): Pcm => {
    const out = new Int16Array(Math.ceil(input.length / ratio) + 1);
    let n = 0;
    for (; pos < input.length; pos += ratio) {
      const from = Math.floor(pos);
      const to = Math.max(from + 1, Math.min(input.length, Math.floor(pos + ratio)));
      let sum = 0;
      for (let i = from; i < to; i++) sum += input[i];
      const s = Math.max(-1, Math.min(1, sum / (to - from)));
      out[n++] = Math.round(s < 0 ? s * 0x8000 : s * 0x7fff);
    }
    pos -= input.length;
    return out.subarray(0, n);
  };
}

// Batches 2048 samples per message so the main thread is not woken for every 128-sample render quantum.
const WORKLET_SOURCE = `
class PhiPcmTap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice(0)); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor("phi-pcm-tap", PhiPcmTap);
`;

/** AudioWorklet tap, ScriptProcessor where worklets are unavailable. Both are wired through to the
 *  destination (some engines only pull connected nodes); neither writes its output, so it is silent. */
export const startPcmCapture: StartPcmCapture = async (stream, onPcm) => {
  const AudioCtx =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!AudioCtx) throw new Error("Web Audio is not available");
  const ctx = new AudioCtx();
  const source = ctx.createMediaStreamSource(stream);
  const downsample = createDownsampler(ctx.sampleRate);
  const emit = (chunk: Float32Array) => {
    const pcm = downsample(chunk);
    if (pcm.length) onPcm(pcm);
  };
  let node: AudioNode;
  try {
    if (!ctx.audioWorklet || typeof AudioWorkletNode === "undefined") throw new Error("no AudioWorklet");
    const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: "application/javascript" }));
    try {
      await ctx.audioWorklet.addModule(url);
    } finally {
      URL.revokeObjectURL(url);
    }
    const tap = new AudioWorkletNode(ctx, "phi-pcm-tap", { channelCount: 1, numberOfInputs: 1, numberOfOutputs: 1 });
    tap.port.onmessage = (e: MessageEvent<Float32Array>) => emit(e.data);
    node = tap;
  } catch {
    const tap = ctx.createScriptProcessor(4096, 1, 1);
    tap.onaudioprocess = (e) => emit(e.inputBuffer.getChannelData(0));
    node = tap;
  }
  source.connect(node);
  node.connect(ctx.destination);
  if (ctx.state === "suspended") await ctx.resume().catch(() => undefined);
  return {
    sampleRate: Math.min(ctx.sampleRate, TARGET_SAMPLE_RATE),
    stop: () => {
      source.disconnect();
      node.disconnect();
      void ctx.close().catch(() => undefined);
    },
  };
};

const RECORDER_MIME_TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus", "audio/ogg"];

export const startBlobRecorder: StartBlobRecorder = (stream) => {
  if (typeof MediaRecorder === "undefined") return null;
  const mimeType = RECORDER_MIME_TYPES.find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
  const chunks: Blob[] = [];
  let rec: MediaRecorder;
  try {
    rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    rec.start();
  } catch {
    return null;
  }
  const collect = () => (chunks.length ? new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" }) : null);
  return {
    discard: () => {
      rec.ondataavailable = null;
      rec.onstop = null;
      if (rec.state !== "inactive") rec.stop();
    },
    stop: () =>
      new Promise<Blob | null>((resolve) => {
        if (rec.state === "inactive") return resolve(collect());
        rec.onstop = () => resolve(collect());
        rec.stop();
      }),
  };
};

async function transcribeUpload(dataUrl: string, mimeType: string): Promise<string> {
  const res = await fetchJSON<{ transcript?: string }>("/api/audio/transcribe", {
    body: JSON.stringify({ data_url: dataUrl, mime_type: mimeType }),
    headers: { "Content-Type": "application/json" },
    method: "POST",
  });
  return res.transcript ?? "";
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("could not read the recording"));
    reader.readAsDataURL(blob);
  });
}

/** Capture constraints; `deviceId` pins the microphone saved in the device menu. */
export function micConstraints(deviceId: string | null): MediaStreamConstraints {
  const audio: MediaTrackConstraints = { channelCount: 1, echoCancellation: true, noiseSuppression: true };
  return { audio: deviceId ? { ...audio, deviceId: { exact: deviceId } } : audio };
}

function micErrorMessage(err: unknown): string {
  const name = (err as { name?: string } | null)?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError") return "Microphone permission was denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found";
  return err instanceof Error && err.message ? err.message : "Could not open the microphone";
}

interface Session {
  stream: MediaStream | null;
  capture: PcmCapture | null;
  recorder: BlobRecorder | null;
  recording: Promise<Blob | null> | null;
  socket: DictationSocket | null;
  /** PCM captured before the socket opened. */
  queue: Pcm[];
  open: boolean;
  /** Still streaming to the live endpoint; false once it failed and the upload is the way out. */
  live: boolean;
  stopping: boolean;
}

export function useDictation({ deps = {}, onFinal, onPartial }: DictationOptions = {}): Dictation {
  const [state, setState] = useState<DictationState>("idle");
  const [partial, setPartial] = useState("");
  const [final, setFinal] = useState("");
  const [error, setError] = useState<string | null>(null);

  const depsRef = useRef(deps);
  depsRef.current = deps;
  const callbacksRef = useRef({ onFinal, onPartial });
  callbacksRef.current = { onFinal, onPartial };
  const sessionRef = useRef<Session | null>(null);
  const [meter] = useState(createLevelMeter);

  const secure = deps.secureContext ?? (typeof window !== "undefined" && window.isSecureContext);
  const canCapture = Boolean(deps.getUserMedia ?? (typeof navigator !== "undefined" && navigator.mediaDevices?.getUserMedia));
  const disabledReason: DictationDisabledReason = !secure ? "insecure" : !canCapture ? "unsupported" : null;

  const teardown = useCallback((session: Session) => {
    if (sessionRef.current === session) sessionRef.current = null;
    session.capture?.stop();
    session.capture = null;
    const ws = session.socket;
    session.socket = null;
    session.queue = [];
    if (ws && ws.readyState < 2) ws.close(1000);
    session.recorder?.discard();
    session.recorder = null;
    session.stream?.getTracks().forEach((t) => t.stop());
    session.stream = null;
    meter.push(0);
  }, [meter]);

  const finish = useCallback(
    (session: Session, text: string) => {
      if (sessionRef.current !== session) return;
      teardown(session);
      setPartial("");
      setFinal(text);
      setState("idle");
      callbacksRef.current.onFinal?.(text);
    },
    [teardown],
  );

  const fail = useCallback(
    (session: Session, message: string) => {
      if (sessionRef.current !== session) return;
      teardown(session);
      setError(message);
      setState("error");
    },
    [teardown],
  );

  const upload = useCallback(
    async (session: Session) => {
      session.recording ??= session.recorder?.stop() ?? Promise.resolve(null);
      const blob = await session.recording;
      if (sessionRef.current !== session) return;
      if (!blob || blob.size === 0) return fail(session, "No audio was captured");
      try {
        const dataUrl = await blobToDataUrl(blob);
        const text = await (depsRef.current.transcribe ?? transcribeUpload)(dataUrl, blob.type || "audio/webm");
        finish(session, text.trim());
      } catch (err) {
        fail(session, err instanceof Error ? err.message : String(err));
      }
    },
    [fail, finish],
  );

  /** The live endpoint is out (server error, socket drop): keep recording, upload at the end. */
  const dropLive = useCallback(
    (session: Session, reason: string) => {
      if (!session.live || sessionRef.current !== session) return;
      session.live = false;
      session.queue = [];
      const ws = session.socket;
      session.socket = null;
      if (ws && ws.readyState < 2) ws.close(1000);
      if (!session.recorder) return fail(session, reason);
      if (session.stopping) void upload(session);
    },
    [fail, upload],
  );

  const openSocket = useCallback(
    (session: Session, url: string, sampleRate: number) => {
      const ws = (depsRef.current.createSocket ?? ((u: string) => new WebSocket(u)))(url);
      ws.binaryType = "arraybuffer";
      session.socket = ws;
      ws.addEventListener("open", () => {
        if (session.socket !== ws) return;
        ws.send(JSON.stringify({ sample_rate: sampleRate }));
        session.open = true;
        for (const pcm of session.queue) ws.send(pcm);
        session.queue = [];
        if (session.stopping) ws.send(JSON.stringify({ eos: true }));
      });
      ws.addEventListener("message", (ev) => {
        if (session.socket !== ws) return;
        const data = (ev as MessageEvent).data;
        if (typeof data !== "string") return;
        let msg: { message?: string; text?: string; transcript?: string; type?: string };
        try {
          msg = JSON.parse(data);
        } catch {
          return;
        }
        if (msg.type === "partial" && typeof msg.text === "string") {
          setPartial(msg.text);
          callbacksRef.current.onPartial?.(msg.text);
        } else if (msg.type === "final") {
          finish(session, (msg.transcript ?? "").trim());
        } else if (msg.type === "error") {
          dropLive(session, msg.message || "Live transcription failed");
        }
      });
      const onGone = () => {
        if (session.socket === ws) dropLive(session, "Live transcription connection closed");
      };
      ws.addEventListener("close", onGone);
      ws.addEventListener("error", onGone);
    },
    [dropLive, finish],
  );

  const start = useCallback(async () => {
    if (disabledReason || sessionRef.current) return;
    const d = depsRef.current;
    const session: Session = {
      capture: null, live: true, open: false, queue: [], recorder: null, recording: null,
      socket: null, stopping: false, stream: null,
    };
    sessionRef.current = session;
    setPartial("");
    setFinal("");
    setError(null);
    setState("requesting");

    const getUserMedia = d.getUserMedia ?? ((c: MediaStreamConstraints) => navigator.mediaDevices.getUserMedia(c));
    const savedId = readMicDeviceId();
    try {
      session.stream = await getUserMedia(micConstraints(savedId));
    } catch (err) {
      const name = (err as { name?: string } | null)?.name;
      if (!savedId || (name !== "OverconstrainedError" && name !== "NotFoundError")) {
        return fail(session, micErrorMessage(err));
      }
      // The saved microphone is gone: forget it and take the system default, once.
      writeMicDeviceId(null);
      if (sessionRef.current !== session) return teardown(session);
      try {
        session.stream = await getUserMedia(micConstraints(null));
      } catch (retryErr) {
        return fail(session, micErrorMessage(retryErr));
      }
    }
    if (sessionRef.current !== session) return teardown(session);

    session.recorder = (d.startRecorder ?? startBlobRecorder)(session.stream);
    try {
      session.capture = await (d.startCapture ?? startPcmCapture)(session.stream, (pcm) => {
        // Metered even after the live stream failed: the take continues for the upload.
        if (sessionRef.current === session && !session.stopping) meter.push(pcmLevel(pcm));
        if (!session.live) return;
        if (session.open && session.socket) session.socket.send(pcm);
        else session.queue.push(pcm);
      });
    } catch {
      session.live = false;
    }
    if (sessionRef.current !== session) return teardown(session);
    if (session.stopping) {
      // Released while the audio graph was starting: stop() already took the upload path.
      session.capture?.stop();
      session.capture = null;
      return;
    }

    if (session.capture) {
      const sampleRate = session.capture.sampleRate;
      try {
        const url = await (d.streamUrl ?? (() => buildWsUrl("/api/audio/transcribe-stream")))();
        if (sessionRef.current !== session) return teardown(session);
        if (session.stopping) return;
        openSocket(session, url, sampleRate);
      } catch {
        session.live = false;
      }
    }
    if (!session.live && !session.recorder) return fail(session, "Microphone capture is not available in this browser");
    setState("recording");
  }, [disabledReason, fail, meter, openSocket, teardown]);

  const stop = useCallback(() => {
    const session = sessionRef.current;
    if (!session || session.stopping) return;
    // Nothing captured yet (still waiting on the permission prompt): there is no take to finish.
    if (!session.stream) {
      teardown(session);
      setState("idle");
      return;
    }
    session.stopping = true;
    setState("finalizing");
    session.capture?.stop();
    session.capture = null;
    session.recording = session.recorder?.stop() ?? null;
    // The mic light goes off once the recorder has its last chunk; the session keeps the blob.
    void (session.recording ?? Promise.resolve(null)).then(() => session.stream?.getTracks().forEach((t) => t.stop()));
    if (session.live && session.socket) {
      if (session.open) session.socket.send(JSON.stringify({ eos: true }));
    } else {
      void upload(session);
    }
  }, [teardown, upload]);

  const cancel = useCallback(() => {
    const session = sessionRef.current;
    if (session) teardown(session);
    setPartial("");
    setError(null);
    setState("idle");
  }, [teardown]);

  useEffect(
    () => () => {
      if (sessionRef.current) teardown(sessionRef.current);
    },
    [teardown],
  );

  return { cancel, disabledReason, error, final, meter, partial, start, state, stop };
}

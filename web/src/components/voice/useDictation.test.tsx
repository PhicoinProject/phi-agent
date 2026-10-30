// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fakeMic, settle, stubLocalStorage } from "./fakes";
import {
  createDownsampler,
  floatToS16,
  pcmLevel,
  useDictation,
  type Dictation,
  type DictationDeps,
} from "./useDictation";
import { MIC_DEVICE_KEY } from "./voice-prefs";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;

afterEach(() => {
  act(() => root?.unmount());
  root = null;
});

function renderDictation(deps: DictationDeps) {
  const onPartial = vi.fn();
  const onFinal = vi.fn();
  const result = { current: null as unknown as Dictation };
  function Harness() {
    result.current = useDictation({ deps, onFinal, onPartial });
    return null;
  }
  root = createRoot(document.createElement("div"));
  act(() => root!.render(<Harness />));
  return { onFinal, onPartial, result };
}

describe("useDictation live stream", () => {
  it("announces the rate, flushes queued PCM, streams partials and lands the final", async () => {
    const mic = fakeMic();
    const { onFinal, onPartial, result } = renderDictation(mic.deps);
    expect(result.current.state).toBe("idle");

    act(() => void result.current.start());
    expect(result.current.state).toBe("requesting");
    await settle();
    expect(result.current.state).toBe("recording");
    expect(mic.socket.url).toContain("/api/audio/transcribe-stream");
    expect(mic.socket.binaryType).toBe("arraybuffer");

    mic.emitPcm([1, 2, 3]); // before the socket opened: queued, not sent
    expect(mic.socket.sent).toEqual([]);
    act(() => mic.socket.serverOpen());
    mic.emitPcm([4, 5]);
    expect(typeof mic.socket.sent[0]).toBe("string");
    expect(mic.socket.json()).toEqual([{ sample_rate: 16000 }]);
    expect(mic.socket.pcm()).toEqual([[1, 2, 3], [4, 5]]);

    act(() => mic.socket.serverSend({ text: "hello wor", type: "partial" }));
    expect(result.current.partial).toBe("hello wor");
    expect(onPartial).toHaveBeenLastCalledWith("hello wor");

    act(() => void result.current.stop());
    expect(result.current.state).toBe("finalizing");
    expect(mic.captureStop).toHaveBeenCalled();
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });

    act(() => mic.socket.serverSend({ provider: "stub", transcript: " hello world ", type: "final" }));
    await settle();
    expect(result.current.state).toBe("idle");
    expect(result.current.final).toBe("hello world");
    expect(onFinal).toHaveBeenCalledWith("hello world");
    expect(mic.transcribe).not.toHaveBeenCalled();
    expect(mic.recorder.discard).toHaveBeenCalled();
    expect(mic.track.stop).toHaveBeenCalled();
  });

  it("falls back to uploading the recorded blob when the server answers error", async () => {
    const mic = fakeMic();
    const { onFinal, result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    act(() => mic.socket.serverOpen());
    act(() => mic.socket.serverSend({ message: "no live speech-to-text configured", type: "error" }));
    expect(result.current.state).toBe("recording"); // the recorder keeps capturing
    expect(mic.socket.closeCode).not.toBeNull();

    act(() => void result.current.stop());
    await settle();
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(mic.transcribe).toHaveBeenCalledTimes(1);
    const [dataUrl, mimeType] = mic.transcribe.mock.calls[0] as unknown as [string, string];
    expect(dataUrl).toMatch(/^data:audio\/webm.*;base64,/);
    expect(mimeType).toBe("audio/webm;codecs=opus");
    expect(result.current.state).toBe("idle");
    expect(result.current.final).toBe("uploaded words");
    expect(onFinal).toHaveBeenCalledWith("uploaded words");
  });

  it("falls back when the socket drops after eos without a final", async () => {
    const mic = fakeMic();
    const { result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    act(() => mic.socket.serverOpen());
    act(() => void result.current.stop());
    expect(mic.socket.json().at(-1)).toEqual({ eos: true });
    act(() => mic.socket.serverClose(1011));
    await settle();
    expect(mic.transcribe).toHaveBeenCalledTimes(1);
    expect(result.current.final).toBe("uploaded words");
  });

  it("reports an upload failure as the error state", async () => {
    const mic = fakeMic({ transcribe: vi.fn(async () => Promise.reject(new Error("503: STT down"))) });
    const { onFinal, result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    act(() => mic.socket.serverSend({ message: "x", type: "error" }));
    act(() => void result.current.stop());
    await settle();
    expect(result.current.state).toBe("error");
    expect(result.current.error).toContain("STT down");
    expect(onFinal).not.toHaveBeenCalled();
  });

  it("goes to error when microphone permission is denied", async () => {
    const getUserMedia = vi.fn(async () => Promise.reject(new DOMException("denied", "NotAllowedError")));
    const mic = fakeMic({ getUserMedia });
    const { result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    expect(result.current.state).toBe("error");
    expect(result.current.error).toMatch(/permission/i);
    expect(mic.sockets).toHaveLength(0);
  });

  it("cancel closes the socket without eos, discards the take and ignores late messages", async () => {
    const mic = fakeMic();
    const { onFinal, result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    act(() => mic.socket.serverOpen());
    mic.emitPcm([7]);
    act(() => mic.socket.serverSend({ text: "half", type: "partial" }));

    act(() => result.current.cancel());
    expect(result.current.state).toBe("idle");
    expect(result.current.partial).toBe("");
    expect(mic.socket.closeCode).not.toBeNull();
    expect(mic.socket.json()).not.toContainEqual({ eos: true });
    expect(mic.recorder.discard).toHaveBeenCalled();
    expect(mic.track.stop).toHaveBeenCalled();

    act(() => mic.socket.serverSend({ transcript: "late", type: "final" }));
    await settle();
    expect(result.current.final).toBe("");
    expect(onFinal).not.toHaveBeenCalled();
    expect(mic.transcribe).not.toHaveBeenCalled();
  });

  it("is disabled outside a secure context and start() does not touch the microphone", async () => {
    const mic = fakeMic({ secureContext: false });
    const { result } = renderDictation(mic.deps);
    expect(result.current.disabledReason).toBe("insecure");
    act(() => void result.current.start());
    await settle();
    expect(mic.getUserMedia).not.toHaveBeenCalled();
    expect(result.current.state).toBe("idle");
  });
});

describe("useDictation saved microphone", () => {
  const AUDIO = { channelCount: 1, echoCancellation: true, noiseSuppression: true };
  const micError = (name: string) => Object.assign(new Error(name), { name });

  beforeEach(() => stubLocalStorage());
  afterEach(() => vi.unstubAllGlobals());

  it.each(["OverconstrainedError", "NotFoundError"])(
    "a saved device that is gone (%s) falls back to the default once and is forgotten",
    async (name) => {
      window.localStorage.setItem(MIC_DEVICE_KEY, "usb-gone");
      const mic = fakeMic();
      mic.getUserMedia.mockRejectedValueOnce(micError(name));
      const { result } = renderDictation(mic.deps);

      act(() => void result.current.start());
      await settle();
      expect(mic.getUserMedia).toHaveBeenCalledTimes(2);
      expect(mic.getUserMedia).toHaveBeenNthCalledWith(1, { audio: { ...AUDIO, deviceId: { exact: "usb-gone" } } });
      expect(mic.getUserMedia).toHaveBeenNthCalledWith(2, { audio: AUDIO });
      expect(window.localStorage.getItem(MIC_DEVICE_KEY)).toBeNull();
      expect(result.current.state).toBe("recording");
      act(() => result.current.cancel());
    },
  );

  it("retries only once, and never without a saved device or on a permission error", async () => {
    window.localStorage.setItem(MIC_DEVICE_KEY, "usb-gone");
    const none = fakeMic();
    none.getUserMedia.mockRejectedValue(micError("NotFoundError"));
    const first = renderDictation(none.deps);
    act(() => void first.result.current.start());
    await settle();
    expect(none.getUserMedia).toHaveBeenCalledTimes(2);
    expect(first.result.current.state).toBe("error");
    expect(first.result.current.error).toBe("No microphone was found");

    act(() => void first.result.current.start());
    await settle();
    expect(none.getUserMedia).toHaveBeenCalledTimes(3);
    expect(none.getUserMedia).toHaveBeenLastCalledWith({ audio: AUDIO });
    act(() => root?.unmount());

    window.localStorage.setItem(MIC_DEVICE_KEY, "usb-1");
    const denied = fakeMic();
    denied.getUserMedia.mockRejectedValue(micError("NotAllowedError"));
    const second = renderDictation(denied.deps);
    act(() => void second.result.current.start());
    await settle();
    expect(denied.getUserMedia).toHaveBeenCalledTimes(1);
    expect(second.result.current.state).toBe("error");
    expect(window.localStorage.getItem(MIC_DEVICE_KEY)).toBe("usb-1");
  });
});

describe("PCM conversion", () => {
  it("clamps float samples into s16 range", () => {
    expect(Array.from(floatToS16(Float32Array.from([0, 1, -1, 2, -2, 0.5])))).toEqual([
      0, 32767, -32768, 32767, -32768, 16384,
    ]);
  });

  it("downsamples 48 kHz to 16 kHz with the fractional position carried across chunks", () => {
    const down = createDownsampler(48000);
    const a = down(new Float32Array(1000).fill(0.25));
    const b = down(new Float32Array(1000).fill(0.25));
    expect(a.length + b.length).toBe(Math.ceil(2000 / 3));
    expect(a.length).toBe(334);
    expect(new Set([...a, ...b])).toEqual(new Set([Math.round(0.25 * 32767)]));
  });

  it("passes 16 kHz input through unchanged", () => {
    const down = createDownsampler(16000);
    expect(down(new Float32Array(10)).length).toBe(10);
  });
});

/** `n` s16 samples of a sine at `amplitude` (0..1 of full scale). */
function sine(n: number, amplitude: number): number[] {
  return Array.from({ length: n }, (_, i) => Math.round(amplitude * 0x7fff * Math.sin((2 * Math.PI * 440 * i) / 16000)));
}

describe("microphone level", () => {
  it("pcmLevel is 0 for silence and the noise floor, high for a loud sine", () => {
    expect(pcmLevel(new Int16Array(0))).toBe(0);
    expect(pcmLevel(new Int16Array(640))).toBe(0);
    expect(pcmLevel(Int16Array.from({ length: 640 }, (_, i) => (i % 2 ? 1 : -1)))).toBeLessThan(0.05);
    expect(pcmLevel(Int16Array.from(sine(640, 0.5)))).toBeGreaterThan(0.3);
    expect(pcmLevel(Int16Array.from(sine(640, 0.5)))).toBeLessThanOrEqual(1);
    // Louder input reads higher: the meter follows the voice, it is not just on/off.
    expect(pcmLevel(Int16Array.from(sine(640, 0.05)))).toBeLessThan(pcmLevel(Int16Array.from(sine(640, 0.5))));
  });

  it("the meter follows the captured PCM without re-rendering, and drops to 0 when the take ends", async () => {
    const mic = fakeMic();
    let renders = 0;
    const result = { current: null as unknown as Dictation };
    function Harness() {
      renders++;
      result.current = useDictation({ deps: mic.deps });
      return null;
    }
    root = createRoot(document.createElement("div"));
    act(() => root!.render(<Harness />));
    const meter = result.current.meter;
    const seen: number[] = [];
    const unsubscribe = meter.subscribe((level) => seen.push(level));
    expect(meter.level).toBe(0);

    act(() => void result.current.start());
    await settle();
    const rendersBefore = renders;
    mic.emitPcm(new Array(640).fill(0)); // still queued: the socket is not open yet
    expect(meter.level).toBeLessThan(0.01);
    mic.emitPcm(sine(640, 0.5));
    expect(meter.level).toBeGreaterThan(0.3);
    act(() => mic.socket.serverOpen());
    mic.emitPcm(new Array(640).fill(0));
    expect(meter.level).toBeLessThan(0.01);
    expect(seen.slice(-3).map((v) => v > 0.3)).toEqual([false, true, false]);
    expect(renders).toBe(rendersBefore); // levels are not React state: no render per chunk
    expect(result.current.meter).toBe(meter);

    mic.emitPcm(sine(640, 0.5));
    act(() => result.current.cancel());
    expect(meter.level).toBe(0);
    unsubscribe();
    mic.emitPcm(sine(640, 0.5));
    expect(seen.at(-1)).toBe(0);
  });

  it("keeps metering after the live stream failed and the take falls back to the upload", async () => {
    const mic = fakeMic();
    const { result } = renderDictation(mic.deps);
    act(() => void result.current.start());
    await settle();
    act(() => mic.socket.serverSend({ message: "no live stt", type: "error" }));
    mic.emitPcm(sine(640, 0.5));
    expect(result.current.meter.level).toBeGreaterThan(0.3);
  });
});

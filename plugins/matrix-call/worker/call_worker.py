#!/usr/bin/env python3
"""Phi MatrixRTC call media worker.

One process per call: joins a LiveKit room with Element-Call-compatible per-participant E2EE,
transcribes the listened-to participants (energy VAD gated by Silero -> STT) and speaks text (TTS) on one mic track.

Protocol: JSON lines. Commands on stdin, events on stdout, logs on stderr.
  in:  {"cmd":"join","url","jwt","own_identity","own_key_b64","own_key_index","listen_to":[identity]}
       {"cmd":"set_key","identity","key_b64","index"}   (before or after the participant joins; may rotate)
       {"cmd":"listen","identity"}   (one more participant to transcribe: the callee of a call we placed)
       {"cmd":"say","utt_id","text"}  {"cmd":"stop_speaking"}  {"cmd":"leave"}
  out: joined(identity, room), participant_joined/participant_left(identity), local_track_subscribed(track_sid),
       speech_start(identity), barge_in(identity), utterance(identity, text, t_start, t_end, audio_s, stt_ms, vad),
       speech_dropped(identity), say_started(utt_id, ttfa_ms), say_done(utt_id, audio_s, peak, rms),
       say_interrupted(utt_id, reason: barge_in|stop_speaking|leave), vad_fallback(reason), error(msg), left; every
       event has "ts". Each speech_start is followed by one utterance or speech_dropped (too short, no words, STT
       failed); barge_in comes in between once the speech has gone on for MATRIX_CALL_BARGE_IN_MS.
       local_track_subscribed: the other side subscribed to our mic track (before that our speech reaches no one).
       utterance.vad: "silero" (neural gate on the energy VAD) or "energy" (the gate failed: see vad_fallback).
       say_done: audio_s, peak and rms (int16) of the frames pushed to the track; a say that played silence shows 0.
Secrets (JWT, keys) are never logged; keys are referred to by sha256[:8].
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import urllib.request
import uuid
import wave

import numpy as np
from livekit import rtc

log = logging.getLogger("call_worker")

STT_URL = os.environ.get("MATRIX_CALL_STT_URL", "http://127.0.0.1:18800/v1/audio/transcriptions")
STT_MODEL = os.environ.get("MATRIX_CALL_STT_MODEL", "Qwen/Qwen3-ASR-1.7B")
TTS_URL = os.environ.get("MATRIX_CALL_TTS_URL", "http://127.0.0.1:8880/v1/audio/speech")
TTS_VOICE = os.environ.get("MATRIX_CALL_TTS_VOICE", "zf_xiaoxiao")
EOU_SILENCE_MS = int(os.environ.get("MATRIX_CALL_EOU_SILENCE_MS", "1200"))  # silence that ends an utterance
BARGE_IN_MS = int(os.environ.get("MATRIX_CALL_BARGE_IN_MS", "600"))  # continuous speech that stops ours
VAD_MODEL = os.environ.get("MATRIX_CALL_VAD_MODEL", "")

IN_RATE = 16000  # remote audio is resampled to this for VAD and STT
OUT_RATE = 48000  # published mic track
FRAME_MS = 20
BRIDGE_MS = 100  # a dip this short between syllables does not break continuous speech (barge-in)

# Element Call's MatrixKeyProvider: BaseKeyProvider({ratchetWindowSize: 10, keyringSize: 256}),
# raw 16-byte keys imported as HKDF material, livekit-client's default ratchet salt.
KEY_RING_SIZE = 256
RATCHET_WINDOW = 10
RATCHET_SALT = b"LKFrameEncryptionKey"


# ---------------------------------------------------------------- pure helpers

def decode_key(key_b64: str) -> bytes:
    """Decode a MatrixRTC media key (base64, padded or unpadded, standard or url-safe)."""
    s = key_b64.strip().replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    try:
        key = base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as e:
        raise ValueError("key is not valid base64") from e
    if not key:
        raise ValueError("key is empty")
    return key


def key_fp(key: bytes) -> str:
    return hashlib.sha256(key).hexdigest()[:8]


def check_index(index: object) -> int:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < KEY_RING_SIZE:
        raise ValueError(f"key index must be an int in [0, {KEY_RING_SIZE})")
    return index


_SENTENCE_BREAK = re.compile(r"(?<=[。！？!?；;\n])|(?<=[.…])(?=\s)")


def split_sentences(text: str) -> list[str]:
    """Split on CJK/ASCII sentence ends; drop pieces without any word character."""
    parts = (p.strip() for p in _SENTENCE_BREAK.split(text))
    return [p for p in parts if re.search(r"\w", p)]


def has_words(text: str) -> bool:
    return bool(re.search(r"\w", text))


def load_vad(path: str):
    """An onnxruntime session of the Silero VAD v6 model at `path` (raises without onnxruntime or the model)."""
    import onnxruntime
    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = opts.inter_op_num_threads = 1
    return onnxruntime.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])


class SileroGate:
    """Is the caller speaking? Silero VAD over 32 ms chunks (with the model's 64 samples of context and its state
    carried over), with hysteresis: speech from a chunk at `enter` or over until one under `stay`. Called with every
    20 ms frame; the answer is that of the latest whole chunk. One per stream: it holds that stream's state."""

    CHUNK, CONTEXT = 512, 64

    def __init__(self, session, enter: float = 0.5, stay: float = 0.35):
        self.session, self.enter, self.stay = session, enter, stay
        self.h = np.zeros((1, 1, 128), np.float32)
        self.c = np.zeros((1, 1, 128), np.float32)
        self.context = np.zeros(self.CONTEXT, np.float32)
        self.buf = np.zeros(0, np.float32)
        self.speech = False

    def __call__(self, frame: np.ndarray) -> bool:
        self.buf = np.concatenate([self.buf, frame.astype(np.float32) / 32768.0])
        while len(self.buf) >= self.CHUNK:
            chunk, self.buf = self.buf[:self.CHUNK], self.buf[self.CHUNK:]
            prob, self.h, self.c = self.session.run(
                None, {"input": np.concatenate([self.context, chunk])[None], "h": self.h, "c": self.c})
            self.context = chunk[-self.CONTEXT:]
            p = float(np.ravel(prob)[0])
            self.speech = p >= (self.stay if self.speech else self.enter)
        return self.speech


class EnergyVAD:
    """Energy VAD over 20 ms frames with an adaptive noise floor, and optionally a speech gate.

    feed() returns ("start", t) when speech begins, ("barge_in", t) once it has gone on for
    `barge_in_ms` without a dip longer than BRIDGE_MS, and ("end", pcm, t_start, t_end) when an
    utterance ends (`end_silence_ms` of silence, or the 30 s cap). Utterances with < 300 ms of
    voiced frames are dropped: ("drop", t) instead of "end" (their "start" has already fired).
    Times are whatever clock the caller passes as `now` (the time of the last sample fed).
    With a `gate` (frame -> bool, e.g. a SileroGate) a frame is voiced only if loud enough and the gate says speech:
    steady noise is loud enough for half a minute after digital silence (the floor's slow rise below).
    """

    def __init__(self, rate: int = IN_RATE, end_silence_ms: int = 1200, min_speech_ms: int = 300,
                 max_utt_ms: int = 30000, preroll_ms: int = 300, barge_in_ms: int = 600, gate=None):
        self.rate = rate
        self.gate = gate
        self.n = rate * FRAME_MS // 1000
        self.end_frames = end_silence_ms // FRAME_MS
        self.min_voiced = min_speech_ms // FRAME_MS
        self.max_frames = max_utt_ms // FRAME_MS
        self.preroll = preroll_ms // FRAME_MS
        self.barge_frames = barge_in_ms // FRAME_MS
        self.bridge = BRIDGE_MS // FRAME_MS
        self.warmup = 500 // FRAME_MS
        self.warm_rms: list[float] = []
        self.floor = 1e-3
        self.buf = np.zeros(0, dtype=np.int16)
        self.recent: list[tuple[np.ndarray, bool, float]] = []  # (frame, voiced, t_end) while idle
        self.utt: list[np.ndarray] | None = None
        self.t_start = self.t_last_voiced = 0.0
        self.voiced = self.silence = 0
        self.run, self.gap, self.barged = 0, self.bridge + 1, False  # continuous speech: frames, dip, reported

    def _is_voiced(self, rms: float) -> bool:
        if len(self.warm_rms) < self.warmup:
            # First 0.5 s: the floor is the median of everything heard so far, so noise present from the first
            # frame is learnt at once instead of being one long "utterance" while the slow rise below catches up
            # (Phase A: 8 s at -40 dBFS, 18 s at -30 dBFS). Speech in this window is mostly missed; the fast drop
            # below brings the floor back down at its first pause.
            self.warm_rms.append(rms)
            self.floor = max(1e-4, float(np.median(self.warm_rms)))
            return rms > max(4.0 * self.floor, 0.003)
        voiced = rms > max(4.0 * self.floor, 0.003)  # ~12 dB over the floor, never below -50 dBFS
        # Floor drops fast and rises ~1 dB/s, so noise that appears mid-call is absorbed, slowly: -40 dBFS after
        # -60 dBFS background is a ~9 s "utterance", after digital silence ~28 s.
        self.floor = max(1e-4, 0.5 * (self.floor + rms) if rms < self.floor else self.floor * 1.0023)
        return voiced

    def feed(self, pcm: np.ndarray, now: float) -> list[tuple]:
        self.buf = np.concatenate([self.buf, pcm.astype(np.int16, copy=False)])
        nframes = len(self.buf) // self.n
        out: list[tuple] = []
        for i in range(nframes):
            frame = self.buf[i * self.n:(i + 1) * self.n]
            t_end = now - (len(self.buf) - (i + 1) * self.n) / self.rate
            x = frame.astype(np.float32) / 32768.0
            voiced = self._is_voiced(float(np.sqrt(np.mean(x * x))))
            if self.gate is not None:
                voiced = self.gate(frame) and voiced  # the gate sees every frame: it keeps its own state
            out += self._frame(frame, voiced, t_end)
        self.buf = self.buf[nframes * self.n:]
        return out

    def _frame(self, frame: np.ndarray, voiced: bool, t_end: float) -> list[tuple]:
        if voiced:
            if self.gap > self.bridge:
                self.run, self.barged = 0, False
            self.run += self.gap + 1 if self.run else 1
            self.gap = 0
        else:
            self.gap += 1
        out = self._segment(frame, voiced, t_end)
        if self.utt is not None and voiced and not self.barged and self.run >= self.barge_frames:
            self.barged = True
            out.append(("barge_in", t_end))
        return out

    def _segment(self, frame: np.ndarray, voiced: bool, t_end: float) -> list[tuple]:
        if self.utt is None:
            self.recent = (self.recent + [(frame, voiced, t_end)])[-self.preroll:]
            window = [v for _, v, _ in self.recent[-10:]]
            if sum(window) < 6:
                return []
            first = next(i for i, (_, v, _) in enumerate(self.recent) if v)
            self.t_start = self.recent[first][2] - FRAME_MS / 1000
            self.utt = [f for f, _, _ in self.recent]
            self.voiced = sum(v for _, v, _ in self.recent)
            self.silence = 0
            self.t_last_voiced = t_end
            self.recent = []
            return [("start", t_end)]
        self.utt.append(frame)
        if voiced:
            self.voiced += 1
            self.silence = 0
            self.t_last_voiced = t_end
        else:
            self.silence += 1
        if self.silence < self.end_frames and len(self.utt) < self.max_frames:
            return []
        utt, voiced_frames = self.utt, self.voiced
        self.utt = None
        keep = len(utt) - max(0, self.silence - 10)  # keep 200 ms of trailing silence
        if voiced_frames < self.min_voiced:
            return [("drop", t_end)]
        return [("end", np.concatenate(utt[:keep]), self.t_start, self.t_last_voiced)]


def parse_wav(data: bytes) -> tuple[int, np.ndarray]:
    """Parse 16-bit PCM WAV, tolerating streamed headers (0xFFFFFFFF sizes). Returns (rate, mono)."""
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, rate, channels = 12, 0, 1
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt ":
            fmt, channels, rate = int.from_bytes(body[0:2], "little"), int.from_bytes(body[2:4], "little"), int.from_bytes(body[4:8], "little")
            if fmt != 1 or int.from_bytes(body[14:16], "little") != 16:
                raise ValueError("only 16-bit PCM WAV is supported")
        elif cid == b"data":
            pcm = np.frombuffer(body[:len(body) // (2 * channels) * 2 * channels], dtype="<i2")
            return rate, pcm.reshape(-1, channels)[:, 0].copy()
        pos += 8 + size + (size & 1)
    raise ValueError("WAV has no data chunk")


def to_wav(pcm: np.ndarray, rate: int) -> bytes:
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.astype("<i2").tobytes())
    return bio.getvalue()


# ---------------------------------------------------------------- STT / TTS (blocking, run in threads)

def stt(pcm: np.ndarray) -> str:
    boundary = uuid.uuid4().hex
    body = b"".join([
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{STT_MODEL}\r\n'.encode(),
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="utt.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n".encode(),
        to_wav(pcm, IN_RATE),
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    req = urllib.request.Request(STT_URL, data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("text", "")


TTS_VOICE_EN = os.environ.get("MATRIX_CALL_TTS_VOICE_EN", "af_heart")
# Latin runs (words, acronyms, model names like "GPT-6 Luna") go to an English voice: the Chinese voice spells them as
# Chinese syllables ("Sonnet" -> 核酸呢). Each run is synthesized on its own and the PCM concatenated.
_LATIN = re.compile(r"[A-Za-z][A-Za-z0-9 .'+/\-]*[A-Za-z0-9]|[A-Za-z]")


def lang_runs(text: str) -> list[tuple[str, str]]:
    runs, i = [], 0
    for m in _LATIN.finditer(text):
        if m.start() > i:
            runs.append((TTS_VOICE, text[i:m.start()]))
        runs.append((TTS_VOICE_EN, m.group()))
        i = m.end()
    if i < len(text):
        runs.append((TTS_VOICE, text[i:]))
    return [(v, s) for v, s in runs if s.strip(" ，,。.、")]


def _tts_one(text: str, voice: str) -> tuple[int, np.ndarray]:
    body = json.dumps({"model": "kokoro", "input": text, "voice": voice, "response_format": "wav"}).encode()
    req = urllib.request.Request(TTS_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return parse_wav(r.read())


def tts(text: str) -> tuple[int, np.ndarray]:
    runs = lang_runs(text)
    if len(runs) <= 1:
        return _tts_one(text, runs[0][0] if runs else TTS_VOICE)
    parts = [_tts_one(s, v) for v, s in runs]
    rate = parts[0][0]
    return rate, np.concatenate([resample_to(r, p, rate) for r, p in parts])


def resample_to(rate: int, pcm: np.ndarray, target: int) -> np.ndarray:
    if rate == target or len(pcm) == 0:
        return pcm
    n = int(round(len(pcm) * target / rate))
    return np.interp(np.linspace(0, len(pcm) - 1, n), np.arange(len(pcm)), pcm.astype(np.float64)).astype(pcm.dtype)


def resample(rate: int, pcm: np.ndarray) -> np.ndarray:
    if rate == OUT_RATE:
        return pcm
    rs = rtc.AudioResampler(rate, OUT_RATE, num_channels=1, quality=rtc.AudioResamplerQuality.HIGH)
    frames = rs.push(bytearray(pcm.astype("<i2").tobytes())) + rs.flush()
    return np.concatenate([np.frombuffer(f.data, dtype=np.int16) for f in frames]) if frames else pcm[:0]


# ---------------------------------------------------------------- worker

class _Redact(logging.Filter):
    """Belt and braces: scrub JWTs and the secrets we were handed from every log record."""

    secrets: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = re.sub(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", "<jwt>", msg)
        clean = re.sub(r"(access_token=)[^&\s]+", r"\1<redacted>", clean)
        for s in self.secrets:
            clean = clean.replace(s, "<secret>")
        if clean != msg:
            record.msg, record.args = clean, None
        return True


class CallWorker:
    def __init__(self, out=None) -> None:
        self.out = out or sys.stdout  # event stream
        self.room: rtc.Room | None = None
        self.source: rtc.AudioSource | None = None
        self.own_identity = ""
        self.own_index = 0
        self.own_track_sid = ""
        self.listen_to: set[str] = set()
        self.keys: dict[str, tuple[bytes, int]] = {}  # identity -> latest (key, index)
        self.listeners: dict[str, asyncio.Task] = {}  # track sid -> listen task
        self.say_q: asyncio.Queue = asyncio.Queue()
        self.stt_q: asyncio.Queue = asyncio.Queue()
        self.play_task: asyncio.Task | None = None
        self.current_utt = ""
        self.vad_mode = "silero"  # "energy" once the model could not be loaded
        self.vad_session = None
        self.done = asyncio.Event()
        self.bg: list[asyncio.Task] = []

    # ---- io

    def emit(self, event: str, **fields) -> None:
        self.out.write(json.dumps({"event": event, "ts": round(time.time(), 3), **fields}, ensure_ascii=False) + "\n")
        self.out.flush()

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=1 << 20)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        self.bg = [asyncio.create_task(self._speaker_loop()), asyncio.create_task(self._stt_loop())]
        stdin = asyncio.create_task(self._read_commands(reader))
        await asyncio.wait([stdin, asyncio.create_task(self.done.wait())], return_when=asyncio.FIRST_COMPLETED)
        await self.leave()

    async def _read_commands(self, reader: asyncio.StreamReader) -> None:
        while line := await reader.readline():
            try:
                cmd = json.loads(line)
                await self.handle(cmd)
            except Exception as e:  # noqa: BLE001 - one bad command must not kill the call
                log.exception("command failed")
                self.emit("error", msg=f"{type(e).__name__}: {e}")
            if self.done.is_set():
                return

    async def handle(self, cmd: dict) -> None:
        c = cmd.get("cmd")
        if c == "join":
            await self.join(cmd["url"], cmd["jwt"], cmd["own_identity"], cmd["own_key_b64"],
                            check_index(cmd.get("own_key_index", 0)), cmd.get("listen_to", []))
        elif c == "set_key":
            _Redact.secrets.add(cmd["key_b64"])
            self.set_key(cmd["identity"], decode_key(cmd["key_b64"]), check_index(cmd["index"]))
        elif c == "listen":
            self.listen(cmd["identity"])
        elif c == "say":
            if self.source is None:
                raise RuntimeError("say before join")
            self.say_q.put_nowait((str(cmd["utt_id"]), cmd["text"], time.monotonic()))
        elif c == "stop_speaking":
            self.interrupt("stop_speaking")
        elif c == "leave":
            self.done.set()
        else:
            raise ValueError(f"unknown cmd {c!r}")

    # ---- room / keys

    async def join(self, url: str, jwt: str, own_identity: str, own_key_b64: str, own_index: int,
                   listen_to: list[str]) -> None:
        if self.room is not None:
            raise RuntimeError("already joined")
        _Redact.secrets.update({jwt, own_key_b64})
        self.own_identity, self.own_index = own_identity, own_index
        self.listen_to.update(listen_to)
        self.keys[own_identity] = (decode_key(own_key_b64), own_index)

        room = self.room = rtc.Room()
        room.on("participant_connected", lambda p: self.emit("participant_joined", identity=p.identity))
        room.on("participant_disconnected", lambda p: self.emit("participant_left", identity=p.identity))
        room.on("track_published", lambda pub, p: self._maybe_subscribe(pub, p))
        room.on("track_subscribed", self._on_track_subscribed)
        room.on("track_unsubscribed", lambda track, pub, p: self._stop_listener(pub.sid))
        # The caller's side subscribed to our mic: from here on what we say can reach them.
        room.on("local_track_subscribed", lambda track: self.emit("local_track_subscribed", track_sid=track.sid))
        room.on("e2ee_state_changed", lambda p, s: log.info("e2ee state %s: %s", p.identity, rtc.EncryptionState.Name(s)))
        room.on("disconnected", lambda reason: (log.info("room disconnected: %s", reason), self.done.set()))

        opts = rtc.KeyProviderOptions(
            shared_key=None,  # per-participant keys
            ratchet_salt=RATCHET_SALT,
            ratchet_window_size=RATCHET_WINDOW,
            key_ring_size=KEY_RING_SIZE,
            key_derivation_function=rtc.KeyDerivationFunction.HKDF,
        )
        await room.connect(url, jwt, rtc.RoomOptions(
            auto_subscribe=False,
            encryption=rtc.E2EEOptions(key_provider_options=opts, encryption_type=rtc.EncryptionType.GCM),
        ))
        for identity, (key, index) in self.keys.items():
            self._apply_key(identity, key, index)

        self.source = rtc.AudioSource(OUT_RATE, 1)
        track = rtc.LocalAudioTrack.create_audio_track("phi-voice", self.source)
        # Element Call publishes audio with red disabled (RED is incompatible with E2EE through the SFU).
        pub = await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE, dtx=True, red=False))
        self.own_track_sid = pub.sid
        self._set_own_key_index()

        self.emit("joined", identity=room.local_participant.identity, room=room.name)
        for p in room.remote_participants.values():
            self.emit("participant_joined", identity=p.identity)
            for tpub in p.track_publications.values():
                self._maybe_subscribe(tpub, p)

    def set_key(self, identity: str, key: bytes, index: int) -> None:
        self.keys[identity] = (key, index)
        if self.room is not None:
            self._apply_key(identity, key, index)
            if identity == self.own_identity:
                self.own_index = index
                self._set_own_key_index()
        else:
            log.info("key queued for %s idx=%d fp=%s", identity, index, key_fp(key))

    def _apply_key(self, identity: str, key: bytes, index: int) -> None:
        self.room.e2ee_manager.key_provider.set_key(identity, key, index)
        log.info("key set for %s idx=%d fp=%s", identity, index, key_fp(key))

    def _set_own_key_index(self) -> None:
        if not self.own_track_sid:
            return
        for fc in self.room.e2ee_manager.frame_cryptors():
            if fc.participant_identity == self.own_identity and fc.track_sid == self.own_track_sid:
                fc.set_key_index(self.own_index)
                log.info("own track encrypts with key idx=%d", self.own_index)
                return
        self.emit("error", msg="no frame cryptor for own track")

    # ---- listening

    def listen(self, identity: str) -> None:
        """Transcribe one more participant. A call we place starts listening to nobody: the callee's device is known
        only once their call membership appears, and by then their audio may be published already."""
        self.listen_to.add(identity)
        if self.room is not None:
            for p in self.room.remote_participants.values():
                if p.identity == identity:
                    for pub in p.track_publications.values():
                        self._maybe_subscribe(pub, p)

    def _maybe_subscribe(self, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant) -> None:
        if p.identity in self.listen_to and pub.kind == rtc.TrackKind.KIND_AUDIO and not pub.subscribed:
            pub.set_subscribed(True)

    def _on_track_subscribed(self, track: rtc.Track, pub: rtc.RemoteTrackPublication, p: rtc.RemoteParticipant) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO and p.identity in self.listen_to and pub.sid not in self.listeners:
            self.listeners[pub.sid] = asyncio.create_task(self._listen(track, p.identity))

    def _stop_listener(self, sid: str) -> None:
        task = self.listeners.pop(sid, None)
        if task:
            task.cancel()

    def _speech_gate(self) -> SileroGate | None:
        """A Silero gate for one more stream; None (energy only) without onnxruntime or the model: a warning and a
        vad_fallback event, once a call, and the call goes on."""
        if self.vad_mode == "silero" and self.vad_session is None:
            try:
                self.vad_session = load_vad(VAD_MODEL)
            except Exception as e:  # noqa: BLE001 - an energy VAD is worse, but a call
                self.vad_mode = "energy"
                log.warning("speech gate unavailable, VAD is energy only: %s: %s", type(e).__name__, e)
                self.emit("vad_fallback", reason=f"{type(e).__name__}: {e}")
        return SileroGate(self.vad_session) if self.vad_mode == "silero" else None

    async def _listen(self, track: rtc.Track, identity: str) -> None:
        log.info("listening to %s", identity)
        vad = EnergyVAD(end_silence_ms=EOU_SILENCE_MS, barge_in_ms=BARGE_IN_MS, gate=self._speech_gate())
        stream = rtc.AudioStream(track, sample_rate=IN_RATE, num_channels=1, frame_size_ms=FRAME_MS)
        samples, peak = 0, 0
        try:
            async for fe in stream:
                pcm = np.frombuffer(fe.frame.data, dtype=np.int16)
                samples, peak = samples + len(pcm), max(peak, int(np.abs(pcm.astype(np.int32)).max(initial=0)))
                for ev in vad.feed(pcm, time.time()):
                    self._vad_event(identity, ev)
        finally:
            # Tells "no audio" from "undecryptable audio": with a wrong key the stream still runs, but carries no
            # speech (peak 0 to 2190 in three Phase A wrong-key runs, ~21000 with the right key).
            log.info("stopped listening to %s: %.1fs audio, peak %d", identity, samples / IN_RATE, peak)
            await stream.aclose()

    def _vad_event(self, identity: str, ev: tuple) -> None:
        if ev[0] == "start":
            self.emit("speech_start", identity=identity)
        elif ev[0] == "barge_in":
            # Only speech that goes on stops ours: a backchannel ("嗯", "对") does not cut us off.
            self.emit("barge_in", identity=identity)
            if self.play_task is not None and not self.play_task.done():
                self.interrupt("barge_in")
        elif ev[0] == "drop":
            self.emit("speech_dropped", identity=identity)
        else:
            self.stt_q.put_nowait((identity, *ev[1:]))

    async def _stt_loop(self) -> None:
        while True:
            identity, pcm, t_start, t_end = await self.stt_q.get()
            t0 = time.monotonic()
            try:
                text = (await asyncio.to_thread(stt, pcm)).strip()
            except Exception as e:  # noqa: BLE001
                self.emit("error", msg=f"stt failed: {e}")
                self.emit("speech_dropped", identity=identity)
                continue
            stt_ms = round((time.monotonic() - t0) * 1000)
            if not has_words(text):
                log.info("dropped empty STT result (%.2fs audio)", len(pcm) / IN_RATE)
                self.emit("speech_dropped", identity=identity)
                continue
            self.emit("utterance", identity=identity, text=text, t_start=round(t_start, 3), t_end=round(t_end, 3),
                      audio_s=round(len(pcm) / IN_RATE, 2), stt_ms=stt_ms, vad=self.vad_mode)

    # ---- speaking

    async def _speaker_loop(self) -> None:
        while True:
            utt_id, text, t_cmd = await self.say_q.get()
            self.current_utt = utt_id
            self.play_task = asyncio.create_task(self._say(utt_id, text, t_cmd))
            await asyncio.wait([self.play_task])
            if not self.play_task.cancelled() and self.play_task.exception():
                self.emit("error", msg=f"say {utt_id} failed: {self.play_task.exception()}")
            self.play_task = None

    async def _say(self, utt_id: str, text: str, t_cmd: float) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)

        async def synthesize() -> None:  # runs one sentence ahead of playback
            try:
                for s in split_sentences(text):
                    rate, pcm = await asyncio.to_thread(tts, s)
                    await q.put(resample(rate, pcm))
                await q.put(None)
            except Exception as e:  # noqa: BLE001
                await q.put(e)

        producer = asyncio.create_task(synthesize())
        n = OUT_RATE * FRAME_MS // 1000
        started = False
        pushed, peak, energy = 0, 0, 0.0  # what went to the track, for say_done: a silent say shows as such
        try:
            while (pcm := await q.get()) is not None:
                if isinstance(pcm, Exception):
                    raise pcm
                pcm = np.concatenate([pcm, np.zeros(-len(pcm) % n, dtype=np.int16)])
                pushed += len(pcm)
                peak = max(peak, int(np.abs(pcm.astype(np.int32)).max(initial=0)))
                energy += float(np.square(pcm, dtype=np.float64).sum())
                for i in range(0, len(pcm), n):
                    await self.source.capture_frame(rtc.AudioFrame(pcm[i:i + n].tobytes(), OUT_RATE, 1, n))
                    if not started:
                        started = True
                        self.emit("say_started", utt_id=utt_id, ttfa_ms=round((time.monotonic() - t_cmd) * 1000))
            await self.source.wait_for_playout()
            self.emit("say_done", utt_id=utt_id, audio_s=round(pushed / OUT_RATE, 2), peak=peak,
                      rms=round((energy / pushed) ** 0.5) if pushed else 0)
        finally:
            producer.cancel()

    def interrupt(self, reason: str) -> None:
        dropped = []
        while not self.say_q.empty():
            dropped.append(self.say_q.get_nowait()[0])
        if self.play_task is not None and not self.play_task.done():
            self.play_task.cancel()
            self.source.clear_queue()
            self.emit("say_interrupted", utt_id=self.current_utt, reason=reason)
        for utt_id in dropped:
            self.emit("say_interrupted", utt_id=utt_id, reason=reason)

    async def leave(self) -> None:
        self.interrupt("leave")
        for t in [*self.listeners.values(), *self.bg]:
            t.cancel()
        if self.room is not None and self.room.isconnected():
            await self.room.disconnect()
        self.emit("left")


def main() -> None:
    # Native code in the livekit FFI prints to fd 1; keep the event stream clean by giving it a
    # private copy of stdout and pointing fd 1 at stderr.
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")
    os.dup2(2, 1)
    handler = logging.StreamHandler(sys.stderr)
    handler.addFilter(_Redact())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.basicConfig(level=os.environ.get("MATRIX_CALL_LOG_LEVEL", "INFO"), handlers=[handler])
    asyncio.run(CallWorker(out).run())


if __name__ == "__main__":
    main()

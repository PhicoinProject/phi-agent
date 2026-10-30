"""One MatrixRTC call at a time: answer an allowed caller or ring one, run the media worker, feed utterances to Phi,
hang up."""
from __future__ import annotations

import asyncio
import contextvars
import itertools
import json
import logging
import os
import re
import time
import unicodedata
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from mautrix.types import EventType, PaginationDirection, RoomID

from . import keys, lk_token, membership, phone, ring, speech
from .worker_proc import Worker

logger = logging.getLogger(__name__)

CALL_MEMBER_STATE = EventType.find(membership.CALL_MEMBER, t_class=EventType.Class.STATE)
NO_CALLER_S = 45  # caller absent from LiveKit this long → hang up
WORKER_CLOSE_S = 3  # the worker's leave; runs alongside our membership {}
REQUEST_S = 10  # deadline of every Matrix request of a call (aiohttp's own default is 300 s)
HANG_UP_S = 2  # our part of the adapter's disconnect(): the gateway gives all of it 5 s, then cancels it
HANG_UP_REQUEST_S = 1.5  # a request on that path
RING_S = ring.LIFETIME_MS // 1000  # a call we place that nobody joins in this time is not answered
KEY_HOLD_S = 60  # a caller's key that came before their call membership is applied when it comes this soon
MAX_HELD_KEYS = 64  # held keys of all rooms together; the oldest go first
UNANSWERED = {"no_answer": "📞 未接通", "declined": "📞 对方已拒绝"}  # outcome of a call we placed → notice
# A turn of the caller: their utterances until they have been silent for the merge window after one.
MAX_TURN_S = 30  # of the caller's audio in one turn
OPEN_SPEECH_S = 40  # speech the worker never reported the end of holds a turn back no longer than this
HOLD_S = 4  # a turn begun this soon after the previous one went in, while the agent works on it, continues it
MERGE_IN_S = 15  # a held turn goes in together with the one it continues when the agent has said nothing this long
RELEASE_S = 2  # a held turn goes in this long after the agent's answer …
SETTLE_S = 0.5  # … or this long after the gateway posts it: the agent's turn is over then
STOP = re.compile(r"(?<![a-z])stop(?![a-z])|等一下|别说了|停", re.I)  # a real interruption, however soon it comes
FILLER = re.compile(r"(?:嗯|恩|啊|哦|噢|唔|うん|はい|okay|ok|yeah|uh|um|mm|hmm|好|对|是)+")  # a backchannel's words

# The voice instruction rides in the user text of the call's first utterance, not in the system prompt: a
# channel_prompt there changes the cached prompt prefix in the middle of the session. Every turn carries VOICE, a
# reminder of it.
VOICE = "[语音通话·简短回答] "
HINT = ("[语音通话：这是一通电话。我说的话来自语音识别，可能有错字，请按意思理解。你的回答会被朗读出来：只说一两句口语短句，"
        "一般不超过 60 个字，先说结论；不用 markdown、列表、代码、链接或文件路径；细节发到聊天里，回答中简短说一句"
        "“详情见聊天”；我追问时再展开]")
# The phone session's own instruction, once per call in place of HINT: the session is a dispatcher on a fast model.
PHONE_HINT = (HINT[:-1] + "。这是专用的电话会话，跑在快模型上，只负责和我说话：要花时间的任务不要在这里做，"
              "用 send_message 发到对应的房间，交给那个房间的主 agent 去做，告诉我发到了哪里；要查进度就用 session_search "
              "看那个房间的会话]")


@dataclass(frozen=True)
class Settings:
    allowed_callers: frozenset[str]
    worker_python: str
    worker_env: dict[str, str]  # MATRIX_CALL_* for the worker (STT/TTS endpoints)
    livekit_service_url: str  # the JWT service of the LiveKit focus for calls we place (Element X's focus)
    merge_window_ms: int = 1000  # silence after an utterance before its turn goes to the agent
    # The phone session (phone.py): one thread of the DM room holds every call, on its own fast model. Off: the
    # calls run in the room's own session, on the room's model, as before.
    phone_session: bool = False
    phone_model: str = ""
    phone_provider: str = ""


@dataclass
class Placed:
    """A call we placed, as the control socket reports it; kept after the call so its outcome can be read."""
    call_id: str
    room_id: str
    user: str
    outcome: str = "ringing"  # → answered | no_answer | declined | failed
    reason: str = ""
    notification_id: str = ""  # our ring event: a decline relates to it


@dataclass(eq=False)
class Call:
    # The other party. For a call we place, a stand-in (room, user, our focus) until their membership comes.
    caller: membership.Join
    key: bytes
    started: float  # wall clock when the answer began
    worker: Worker | None = None
    state_sent: bool = False
    connected_at: float | None = None  # worker "joined"
    ended: bool = False
    utterances: int = 0  # the caller's turns (backchannels not counted)
    source: object = None  # SessionSource of the room session, set on "joined"
    session_id: str | None = None  # the agent session whose turn is spoken, bound in pre_llm_call
    turn_id: str | None = None  # the turn whose replies are spoken
    pending: list[str] = field(default_factory=list)  # injected VOICE texts not yet seen by pre_llm_call
    start_marker_due: bool = False
    speaking: set[str] = field(default_factory=set)  # say utt_ids not yet done/interrupted
    said: set[tuple[str, str]] = field(default_factory=set)  # (turn_id, text) already spoken
    muted: str | None = None  # the turn a barge-in cut our speech on: its replies are written down, not spoken
    transcript: Path | None = None
    tasks: dict[str, asyncio.Task] = field(default_factory=dict)  # answer, reader, finish and the lanes (_queue)
    timers: dict[str, asyncio.TimerHandle] = field(default_factory=dict)  # no_caller, expiry, ring
    placed: Placed | None = None  # set on a call we placed
    answered: bool = True  # False while a call we placed rings
    rang_ms: int | None = None  # our ring's sender_ts: only a callee membership made after it answers
    join_sent: bool = False  # the worker has its join: keys can go to it
    in_room: bool = False  # the worker is in the LiveKit room ("joined")
    present: set[str] = field(default_factory=set)  # LiveKit identities in the room besides ours
    parts: list[dict] = field(default_factory=list)  # the caller's utterances of the turn being put together
    hearing: int = 0  # the caller's speech the worker has not reported the end of yet (speech_start)
    overlap: bool = False  # we spoke while that speech went on
    began: float | None = None  # when the caller began the turn being put together
    injected_at: float | None = None  # when the last turn went to the agent
    working: bool = False  # the agent has not answered that turn yet
    last_text: str = ""  # its text
    last_token: Utterance | None = None  # and its token
    answering: str | None = None  # the agent's turn that carries it, once it has started
    last_output: float | None = None  # the agent's last interim reply to it
    held: list[str] = field(default_factory=list)  # turns that continue it, held until the agent answers
    release_due: bool = False  # the held turns go in with the turn the caller is saying now


@dataclass(eq=False)
class Utterance:
    """One utterance handed to the gateway: what busy-router made of it, as far as the gateway's posts tell."""
    call: Call
    asked: str | None = None  # "btw" or "bg" once the gateway acked a side question made of it; None once answered


# The utterance the running code works for. Each injection runs in a task of its own (_queue) that sets it, and the
# gateway handles a /btw or /bg busy-router makes of the utterance inside that task: base.handle_message →
# _handle_message_while_active → the busy handler (run_busy.py) → _dispatch_inline_reply, which posts the started
# notice. The side question (slash_commands._handle_btw_command) and the background task (_handle_background_command)
# are tasks it creates, and a task copies the context: their posts carry the token too. A /btw or /bg typed into the
# room comes in through the sync loop without one, and its answer is not spoken.
_injected: contextvars.ContextVar[Utterance | None] = contextvars.ContextVar("matrix_call_injected", default=None)


def _duration(seconds: float) -> str:
    s = int(round(seconds))
    h, m, s = s // 3600, s % 3600 // 60, s % 60
    return (f"{h}小时" if h else "") + (f"{m}分" if h or m else "") + f"{s}秒"


def _stamp(t: float) -> str:
    return datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")


async def _request(aw, timeout: float | None = None):
    return await asyncio.wait_for(aw, timeout or REQUEST_S)


def _posted(key: str, content: str, tail: bool = False) -> re.Match | None:
    """``content`` as the gateway renders the i18n template ``key`` (with whatever locale layer is registered, such
    as busy-router's short notices). Group "body" is the {answer} field, or with ``tail`` what follows the template."""
    from agent.i18n import t
    pattern = "".join("(?P<body>.*)" if part == "{answer}" else ".*?" if re.fullmatch(r"\{\w+\}", part)
                      else re.escape(part) for part in re.split(r"(\{\w+\})", t(key)))
    return re.fullmatch(pattern + ("(?P<body>.*)" if tail else ""), content, re.S)


def _backchannel(text: str) -> bool:
    """Only fillers ("嗯。", "うん", "OK!"): the caller listening, not saying something."""
    core = re.sub(r"[\W_]+", "", text).lower()
    return not core or FILLER.fullmatch(core) is not None


def _join(texts: list[str]) -> str:
    """Utterances of one turn as one text: a space between Latin words, none next to CJK."""
    out = ""
    for text in texts:
        wide = out and (unicodedata.east_asian_width(out[-1]) in "WF" or unicodedata.east_asian_width(text[0]) in "WF")
        out += text if not out or wide else " " + text
    return out


# What the gateway says about a turn rather than in it, posted in full or as a notice's head. A reply never carries
# one today, but nothing of the kind is ever read out to the caller.
STATUS = [f"gateway.errors.{k}" for k in (
    "generic_failed", "generic_failed_with_hint", "interrupted_before_start", "stopped_before_finishing",
    "no_response", "previous_turn_cleanup", "unexpected_silence", "history_unavailable", "no_credentials",
    "rate_limited", "auth_failed", "bad_request", "connection_interrupted", "unreachable", "connection_unknown",
    "context_overflow", "usage_limit_resets", "provider_kept_failing", "session_storage_unavailable",
    "session_storage_unavailable_disk")] + [f"gateway.busy.{k}" for k in (
    "another_turn_running", "draining_maintenance", "drain_queued", "drain_rejected", "drain_rejected_new_work",
    "slash_rejected")]
STATUS_HEADS = [f"gateway.busy.{k}_head" for k in (
    "queued", "interrupting", "steered", "steered_subagents", "redirected", "subagent_working", "compressing")] + [
    "gateway.queue.queued"]
# turn_finalizer's own text for a turn that stopped on a tool result, when the explainer is turned off
NO_REPLY_FALLBACK = "No reply: the turn stopped while a tool result was still pending."


def _unspoken(text: str) -> str:
    """``text`` without the gateway's status texts: the explainer the agent appends to a turn that ended without a
    usable reply ("⚠️ No reply: …", after the reply's fragment if any), the failed-turn notices and the busy, queue
    and error notices. What is left is the agent's answer."""
    from agent.i18n import t
    from agent.turn_failure_copy import FAILED_TURN_NOTICE, PARTIAL_FAILED_TURN_NOTICE
    explainer = t("explainer.no_reply_prefix").strip()
    kept = []
    for paragraph in text.split("\n\n"):
        p = paragraph.strip()
        if explainer and p.startswith(explainer) or p.startswith(NO_REPLY_FALLBACK):
            break  # the explanation runs to the end
        if (p in (FAILED_TURN_NOTICE, PARTIAL_FAILED_TURN_NOTICE) or any(_posted(k, p) for k in STATUS)
                or any(_posted(k, p, tail=True) for k in STATUS_HEADS)):
            continue
        kept.append(paragraph)
    return "\n\n".join(kept).strip()


class Calls:
    def __init__(self, client, adapter, settings: Settings, make_worker=Worker, now=time.time, call_later=None):
        self.client, self.adapter, self.settings = client, adapter, settings
        self.make_worker, self.now = make_worker, now
        self.call_later = call_later  # the turn timers' scheduler; None: the running loop's
        self.loop: asyncio.AbstractEventLoop | None = None  # the gateway loop; hooks hop onto it
        self.call: Call | None = None
        # Allowed callers' current call memberships, room → state_key → Join: the devices our key must reach.
        self.members: dict[str, dict[str, membership.Join]] = {}
        # Allowed callers' keys, room → LiveKit identity → (when received, key). Element X may send its key before
        # its call membership reaches us, and while we are still answering, before the worker is there to take it.
        self.keys: dict[str, dict[str, tuple[float, keys.Received]]] = {}
        self.placed: Placed | None = None  # the last call we placed
        self._seen: deque[str] = deque(maxlen=256)  # event ids: a state event can come in both state and timeline
        self._ignored: set[str] = set()
        self._utt_ids = itertools.count(1)
        self._tasks: set[asyncio.Task] = set()
        self.on_idle = None  # called once when the line is free again: a reload hands over then (__init__.py)

    def inherit(self, old: Calls) -> None:
        """Take over what the controller this one replaces knew outside a call: the callers' memberships and keys,
        the events seen, and the call placed last (the tool may still be reading its outcome)."""
        self.members, self.keys, self.placed = old.members, old.keys, old.placed
        self._seen, self._ignored = old._seen, old._ignored

    @property
    def mxid(self) -> str:
        return str(self.client.mxid)

    @property
    def device_id(self) -> str:
        return str(self.client.device_id)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(task)  # keep a reference until done
        task.add_done_callback(self._tasks.discard)
        return task

    def _queue(self, call: Call, lane: str, make, what: str) -> asyncio.Task:
        """Run ``make()`` after the lane's previous step, without the caller waiting for it: notices, transcript
        lines and injected utterances each keep their order and never hold up the worker's events."""
        previous = call.tasks.get(lane)

        async def step():
            if previous is not None:
                await asyncio.wait([previous])  # not gather: cancelling this step must not cancel the earlier one
            try:
                await make()
            except Exception as exc:
                logger.warning("matrix-call: %s failed: %s: %s", what, type(exc).__name__, exc)

        call.tasks[lane] = task = self._spawn(step())
        return task

    # ------------------------------------------------------------------ Matrix events

    async def on_state(self, evt) -> None:
        """mautrix handler for call.member state events. Decides without awaiting, so events never interleave."""
        self.loop = asyncio.get_running_loop()
        raw = evt.serialize()
        raw.setdefault("room_id", str(getattr(evt, "room_id", "") or ""))
        ev = membership.parse(raw)
        if ev is None or not ev.event_id or ev.event_id in self._seen or ev.user_id == self.mxid:
            return
        self._seen.append(ev.event_id)
        if ev.user_id not in self.settings.allowed_callers:
            if ev.user_id not in self._ignored:
                self._ignored.add(ev.user_id)
                logger.info("matrix-call: ignoring calls from %s (not in allowed_callers)", ev.user_id)
            return
        call = self.call
        if isinstance(ev, membership.Leave):
            self.members.get(ev.room_id, {}).pop(ev.state_key, None)
            if call and not call.ended and ev.room_id == call.caller.room_id and ev.state_key == call.caller.state_key:
                self._hang_up_soon(call, "caller left")
            return
        if ev.expires_at_ms <= self.now() * 1000:
            logger.info("matrix-call: call membership %s from %s already expired, ignored", ev.event_id, ev.user_id)
            return
        known = self.members.setdefault(ev.room_id, {})
        new_device = ev.state_key not in known
        known[ev.state_key] = ev
        if call and not call.ended:
            if ev.room_id != call.caller.room_id or ev.user_id != call.caller.user_id:
                logger.info("matrix-call: busy in %s, ignoring call from %s in %s",
                            call.caller.room_id, ev.user_id, ev.room_id)
            elif not call.answered:
                # A membership the callee made before our ring (a call they never left, and its refreshes, which
                # keep the first join's created_ts) is not them picking up. Their ts is the homeserver's clock,
                # ours is this host's: a human answers seconds after the ring, well past any skew between them.
                if call.rang_ms is not None and ev.created_ms > call.rang_ms:
                    self._picked_up(call, ev)
                else:
                    logger.info("matrix-call: call membership %s of %s predates our ring, not an answer",
                                ev.event_id, ev.user_id)
            elif ev.state_key == call.caller.state_key:
                call.caller = ev  # refreshed membership: new expiry
                self._arm(call, "expiry", ev.expires_at_ms / 1000 - self.now(), "caller membership expired")
            elif new_device and call.worker is not None:
                self._spawn(self._send_key(call, [ev]))  # another device of the caller joined the call
            return
        logger.info("matrix-call: answering %s in %s (device %s)", ev.user_id, ev.room_id, ev.device_id)
        call = self.call = Call(caller=ev, key=keys.new_key(), started=self.now())
        self._arm(call, "no_caller", NO_CALLER_S, f"caller not in the LiveKit room after {NO_CALLER_S} s")
        self._arm(call, "expiry", ev.expires_at_ms / 1000 - self.now(), "caller membership expired")
        call.tasks["answer"] = self._spawn(self._answering(call, self._answer(call)))

    async def on_keys(self, evt) -> None:
        """mautrix handler for to-device io.element.call.encryption_keys (decrypted by OlmMachine)."""
        self.loop = asyncio.get_running_loop()
        got = keys.received(evt)
        if got is None or got.sender not in self.settings.allowed_callers:
            return
        try:
            genuine = await _request(keys.from_claimed_device(self.client.crypto, got))
        except Exception as exc:
            logger.warning("matrix-call: device check for %s failed: %s: %s", got.identity, type(exc).__name__, exc)
            genuine = False
        if not genuine:
            logger.warning("matrix-call: key from %s not from the device it claims, dropped", got.identity)
            return
        # Held even without a call in its room (js-sdk keeps keys per room too): the call it is for may be about to
        # start, and the answer applies what was held for it.
        self.keys.setdefault(got.room_id, {})[got.identity] = (self.now(), got)  # latest key per identity
        self._purge_keys()
        logger.info("matrix-call: key from %s index %d fp %s", got.identity, got.index, keys.fp_b64(got.key_b64))
        call = self.call
        if (call and not call.ended and call.answered and call.join_sent and got.room_id == call.caller.room_id):
            await self._set_key(call, got)

    def _purge_keys(self) -> None:
        """Drop expired keys, and the oldest beyond MAX_HELD_KEYS: an allowed caller's devices could send keys for
        any number of rooms, and nothing else ever removes one held for a room without a call."""
        now = self.now()
        held = sorted((t, room, identity) for room, ids in self.keys.items() for identity, (t, _) in ids.items())
        for i, (t, room, identity) in enumerate(held):
            if now - t > KEY_HOLD_S or i < len(held) - MAX_HELD_KEYS:
                del self.keys[room][identity]
        for room in [room for room, ids in self.keys.items() if not ids]:
            del self.keys[room]

    def _held(self, room: str) -> list[keys.Received]:
        now = self.now()
        return [got for t, got in self.keys.get(room, {}).values() if now - t <= KEY_HOLD_S]

    async def on_decline(self, evt) -> None:
        """mautrix handler for org.matrix.msc4310.rtc.decline (decrypted): the callee turned down our ring."""
        raw = evt.serialize()
        call = self.call
        if (call is None or call.ended or call.answered or call.placed is None
                or raw.get("room_id") != call.placed.room_id or raw.get("sender") != call.placed.user
                or not ring.declines(raw.get("content"), call.placed.notification_id)):
            return
        self._unanswered(call, "declined", "callee declined")

    # ------------------------------------------------------------------ answer / hang up

    async def _answering(self, call: Call, step) -> None:
        try:
            await step
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("matrix-call: answering failed: %s: %s", type(exc).__name__, exc)
            self._hang_up_soon(call, "answer failed")

    async def _answer(self, call: Call) -> None:
        t0 = time.monotonic()
        await self._send_member(call)
        await self._start_media(call)
        logger.info("matrix-call: join sent %.1f s after the call event (key fp %s)",
                    time.monotonic() - t0, keys.fp(call.key))

    async def _send_member(self, call: Call) -> str:
        """Our call.member in the call's room; returns its event id."""
        # Set before the request: a hang-up that cancels it mid-flight cannot know whether the server applied it,
        # and an extra {} is harmless.
        call.state_sent = True
        return str(await _request(self.client.send_state_event(
            RoomID(call.caller.room_id), CALL_MEMBER_STATE, membership.content(self.mxid, self.device_id, call.caller),
            state_key=membership.state_key(self.mxid, self.device_id))))

    async def _start_media(self, call: Call) -> None:
        caller = call.caller
        url, jwt = await _request(lk_token.fetch(self.client, caller.service_url, caller.room_id, self.device_id))
        call.worker = self.make_worker(self.settings.worker_python, self.settings.worker_env)
        await call.worker.start()
        call.tasks["reader"] = self._spawn(self._read(call))
        # A call we place listens to nobody yet: which device of the callee joins is known once they answer, and
        # the answer (_picked_up) greets them when the join is out by then. Decided here, without awaiting since.
        listen = [caller.identity] if call.answered else []
        call.join_sent = True
        await call.worker.send("join", url=url, jwt=jwt, own_identity=f"{self.mxid}:{self.device_id}",
                               own_key_b64=keys.b64(call.key), own_key_index=0, listen_to=listen)
        if listen:
            await self._greet(call)

    async def _greet(self, call: Call, listen: bool = False) -> None:
        """Once the worker has its join and the caller is known: hear them, give them our key, take theirs."""
        caller = call.caller
        if listen:
            await call.worker.send("listen", identity=caller.identity)
        now_ms = self.now() * 1000
        await self._send_key(call, [j for j in self.members.get(caller.room_id, {}).values()
                                    if j.user_id == caller.user_id and j.expires_at_ms > now_ms])
        for got in self._held(caller.room_id):
            await self._set_key(call, got)

    # ------------------------------------------------------------------ placing a call

    async def ring(self, user: str) -> dict:
        """Ring ``user`` (control socket) in their DM room with us. Replies once it rings."""
        self.loop = asyncio.get_running_loop()
        if user not in self.settings.allowed_callers:
            return {"ok": False, "error": f"{user} is not in allowed_callers"}
        if self.call is not None:
            return {"ok": False, "error": "busy: a call is active"}
        try:
            room = await _request(self._dm_room(user))
        except Exception as exc:
            logger.warning("matrix-call: no room to ring %s: %s: %s", user, type(exc).__name__, exc)
            return {"ok": False, "error": f"room lookup failed: {type(exc).__name__}"}
        if room is None:
            return {"ok": False, "error": f"no DM room with {user}"}
        if self.call is not None:  # one came in during the lookup
            return {"ok": False, "error": "busy: a call is active"}
        placed = self.placed = Placed(uuid.uuid4().hex[:12], room, user)
        logger.info("matrix-call: calling %s in %s (call %s)", user, room, placed.call_id)
        # The callee's device and membership are unknown until they answer; the LiveKit room is ours, as Element X
        # names it: the room id on the configured focus.
        callee = membership.Join(room, user, "", "", "", 0, self.settings.livekit_service_url, room)
        call = self.call = Call(caller=callee, key=keys.new_key(), started=self.now(), placed=placed, answered=False)
        task = call.tasks["answer"] = self._spawn(self._place(call))
        await asyncio.wait([task])  # not awaited directly: a client that goes away must not cancel the call
        if placed.outcome == "failed":
            return {"ok": False, "error": placed.reason, "call_id": placed.call_id}
        return {"ok": True, "status": placed.outcome, "call_id": placed.call_id, "room_id": room}

    async def _dm_room(self, user: str) -> str | None:
        """The 1:1 room of ``user`` and us: listed for them in our m.direct, joined by us, and with just the two of us
        as its joined members (the server's list, not our cache), so a group room m.direct lists by mistake is never
        rung. Of several, the one with the latest event."""
        direct = await self.adapter._fetch_m_direct()
        listed = direct.get(user) if isinstance(direct, dict) else None
        rooms = []
        for room in dict.fromkeys(r for r in (listed if isinstance(listed, list) else []) if isinstance(r, str)):
            if room in self.adapter._joined_rooms:
                joined = await self.client.get_joined_members(RoomID(room))
                if {str(u) for u in joined} == {self.mxid, user}:
                    rooms.append(room)
        if len(rooms) > 1:
            latest = {}
            for room in rooms:
                page = await self.client.get_messages(RoomID(room), PaginationDirection.BACKWARD, limit=1)
                latest[room] = max((e.timestamp for e in page.events), default=0)
            rooms.sort(key=latest.get, reverse=True)
        return rooms[0] if rooms else None

    async def _place(self, call: Call) -> None:
        """MatrixRTCSession: join (our membership, then the media), then sendCallNotify relating to our membership."""
        placed = call.placed
        try:
            member_id = await self._send_member(call)
            await self._start_media(call)
            # The room is encrypted: the client's send encrypts it (Megolm), as it does the adapter's messages. In
            # the 1:1 DM, js-sdk's `m.mentions.room` notifies the callee and nobody else.
            call.rang_ms = int(self.now() * 1000)  # before the send: the callee may pick up before it returns
            placed.notification_id = str(await _request(self.client.send_message_event(
                RoomID(placed.room_id), ring.NOTIFICATION_EVENT, ring.notification(member_id, call.rang_ms))))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("matrix-call: ringing failed: %s: %s", type(exc).__name__, exc)
            self._hang_up_soon(call, f"ringing failed: {type(exc).__name__}")
            return
        logger.info("matrix-call: ringing %s (notification %s)", placed.user, placed.notification_id)
        if not call.answered and not call.ended:
            call.timers["ring"] = asyncio.get_running_loop().call_later(
                RING_S, self._unanswered, call, "no_answer", f"not answered in {RING_S} s")

    def _picked_up(self, call: Call, ev: membership.Join) -> None:
        """The callee's call membership: from here on the call is one we answered."""
        logger.info("matrix-call: %s answered in %s (device %s)", ev.user_id, ev.room_id, ev.device_id)
        call.caller, call.answered, call.placed.outcome = ev, True, "answered"
        timer = call.timers.pop("ring", None)
        if timer is not None:
            timer.cancel()
        if ev.identity not in call.present:
            self._arm(call, "no_caller", NO_CALLER_S, f"callee not in the LiveKit room after {NO_CALLER_S} s")
        self._arm(call, "expiry", ev.expires_at_ms / 1000 - self.now(), "caller membership expired")
        if call.join_sent:  # otherwise _start_media greets them with the join
            call.tasks["greet"] = self._spawn(self._answering(call, self._greet(call, listen=True)))
        if call.in_room:
            self._spawn(self._connected(call))

    def _unanswered(self, call: Call, outcome: str, reason: str) -> None:
        if not call.answered and not call.ended:
            call.placed.outcome, call.placed.reason = outcome, reason
            self._hang_up_soon(call, reason)

    def status(self) -> dict:
        call = self.call
        state = ("idle" if call is None else "ending" if call.ended else "in_call" if call.answered else "ringing")
        return {"ok": True, "state": state, "direction": None if call is None else "out" if call.placed else "in",
                "room_id": call.caller.room_id if call else None, "user": call.caller.user_id if call else None,
                "placed": asdict(self.placed) if self.placed else None}

    async def _send_key(self, call: Call, joins: list[membership.Join]) -> None:
        body = keys.content(call.key, 0, call.caller.room_id, self.mxid, self.device_id, int(self.now() * 1000))
        sent = await keys.send(self.client.crypto, [(j.user_id, j.device_id) for j in joins], body,
                               (self.mxid, self.device_id), timeout=REQUEST_S)
        logger.info("matrix-call: our key (fp %s) sent to %d device(s)", keys.fp(call.key), sent)

    async def _set_key(self, call: Call, got: keys.Received) -> None:
        if got.sender == call.caller.user_id:
            await call.worker.send("set_key", identity=got.identity, key_b64=got.key_b64, index=got.index)

    async def shutdown(self, reason: str, request_s: float | None = None) -> None:
        """Hang up the call, if there is one, and wait until that is done. ``request_s`` is the deadline of each
        Matrix request on the way (the disconnect path is short of time)."""
        call = self.call
        if call is None:
            return
        self._hang_up_soon(call, reason, request_s)  # a hang-up already under way is the one waited for
        # Shielded: a caller that stops waiting (the disconnect deadline) does not stop the worker from being closed.
        await asyncio.shield(call.tasks["finish"])

    def _hang_up_soon(self, call: Call, reason: str, request_s: float | None = None) -> None:
        """From a handler or timer: the call counts as ended at once, so an event handled before the hang-up task
        runs (Element X's leave and rejoin can arrive in one sync) already finds the line free."""
        if not call.ended:
            call.ended = True
            if call.placed is not None and call.placed.outcome == "ringing":
                call.placed.outcome, call.placed.reason = "failed", reason
            call.tasks["finish"] = self._spawn(self._finish(call, reason, request_s))

    async def _finish(self, call: Call, reason: str, request_s: float | None) -> None:
        logger.info("matrix-call: hanging up (%s)", reason)
        for timer in call.timers.values():
            timer.cancel()
        try:
            # What the caller said last still goes to the agent: the turn being put together, the turns held.
            self._turn(call, closing=True)
            if call.held:
                self._inject(call, ([call.last_text] if call.working else []) + call.held)
        except Exception:
            logger.exception("matrix-call: the caller's last turn could not go to the agent")
        steps = [call.tasks[name] for name in ("answer", "greet") if name in call.tasks]
        for step in steps:
            step.cancel()
        await asyncio.gather(*steps, return_exceptions=True)
        room = call.caller.room_id
        if call.connected_at is not None:
            end = self.now()
            took = _duration(end - call.connected_at)
            self._log(call, "event", event="end", duration_s=round(end - call.connected_at, 1),
                      utterances=call.utterances)
            self._notify(call, f"📞 通话结束（时长{took}，共{call.utterances}句）", request_s)
        elif call.placed is not None and call.placed.outcome in UNANSWERED:
            self._notify(call, UNANSWERED[call.placed.outcome], request_s)  # no conversation: no transcript, no marker
        # Element X leaves and rejoins within seconds (seen in the capture); a call answered while this one was
        # still hanging up uses the same state key and needs the caller's keys that already arrived for it.
        successor = self.call is not None and self.call is not call and self.call.caller.room_id == room

        async def leave():
            if call.state_sent and not successor:
                try:
                    await _request(self.client.send_state_event(
                        RoomID(room), CALL_MEMBER_STATE, {}, state_key=membership.state_key(self.mxid, self.device_id)),
                        request_s)
                except Exception as exc:
                    logger.warning("matrix-call: could not clear our call membership: %s: %s",
                                   type(exc).__name__, exc)

        async def stop_worker():
            if call.worker is not None:
                await call.worker.close(WORKER_CLOSE_S if request_s is None else min(WORKER_CLOSE_S, request_s))

        await asyncio.gather(leave(), stop_worker())
        reader = call.tasks.get("reader")
        if reader is not None:
            await asyncio.gather(reader, return_exceptions=True)
        if call.connected_at is not None:
            await self._marker(call, f"[语音通话结束] 开始 {_stamp(call.connected_at)}，结束 {_stamp(end)}，"
                                     f"时长 {took}，共 {call.utterances} 句")
        if self.call is call:
            self.call = None
        if not (self.call is not None and self.call.caller.room_id == room):
            self.keys.pop(room, None)
        if self.call is None and self.on_idle is not None:
            on_idle, self.on_idle = self.on_idle, None
            on_idle()
        # The end notice and the last transcript lines; utterances still on their way to the agent go on.
        lanes = [call.tasks[lane] for lane in ("notice", "transcript") if lane in call.tasks]
        if lanes:
            await asyncio.wait(lanes, timeout=request_s or REQUEST_S)

    def _later(self, call: Call, name: str, delay: float, fn, *args) -> None:
        """Call ``fn(*args)`` in ``delay`` seconds, instead of what ``name`` was due to call."""
        self._cancel(call, name)
        call_later = self.call_later or asyncio.get_running_loop().call_later
        call.timers[name] = call_later(max(delay, 0), fn, *args)

    def _cancel(self, call: Call, name: str) -> None:
        timer = call.timers.pop(name, None)
        if timer is not None:
            timer.cancel()

    def _arm(self, call: Call, name: str, delay: float, reason: str) -> None:
        old = call.timers.pop(name, None)
        if old is not None:
            old.cancel()
        call.timers[name] = asyncio.get_running_loop().call_later(
            max(delay, 0), self._hang_up_soon, call, reason)

    # ------------------------------------------------------------------ worker events

    async def _read(self, call: Call) -> None:
        try:
            async for ev in call.worker.events():
                try:
                    await self._on_worker(call, ev)
                except Exception:
                    logger.exception("matrix-call: worker event %s failed", ev.get("event"))
        except Exception as exc:
            # The worker's stdout carries protocol lines only (its fd 1 goes to stderr), so a line that cannot be
            # read is a broken worker. The line itself is not logged: it may hold anything.
            logger.error("matrix-call: worker output unreadable, hanging up: %s: %s", type(exc).__name__, exc)
            self._hang_up_soon(call, "worker output unreadable")
            return
        self._hang_up_soon(call, "worker exited")

    async def _on_worker(self, call: Call, ev: dict) -> None:
        kind, caller = ev.get("event"), call.caller.identity
        if kind == "joined":
            call.in_room = True
            if call.answered:  # a call we placed is connected when the callee answers (_picked_up)
                await self._connected(call)
        elif kind == "participant_joined":
            call.present.add(ev.get("identity"))
            if ev.get("identity") == caller:
                timer = call.timers.pop("no_caller", None)
                if timer is not None:
                    timer.cancel()
        elif kind == "participant_left":
            call.present.discard(ev.get("identity"))
            if ev.get("identity") == caller and not call.ended:
                self._arm(call, "no_caller", NO_CALLER_S, f"caller gone from the LiveKit room for {NO_CALLER_S} s")
        elif kind == "speech_start":
            self._hearing(call)
        elif kind == "barge_in":  # speech that went on for barge_in_ms: a backchannel does not cut us off
            # Only if it cut our speech is the rest of that turn stale, until the caller's next turn goes in; over
            # our silence (the agent still thinking) its answer is what the caller waits for.
            if call.speaking:
                call.muted = call.turn_id
            await self._stop_speaking(call)
        elif kind == "speech_dropped":  # too short, no words: a cough, a click
            self._heard(call)
        elif kind == "utterance":
            # Stage logs are INFO and hold no words (they are in the transcript) and no keys.
            logger.info("matrix-call: caller utterance: %s s audio, stt %s ms, vad %s",
                        ev.get("audio_s"), ev.get("stt_ms"), ev.get("vad"))
            await self._utterance(call, ev)
        elif kind == "say_started":
            logger.info("matrix-call: say %s started: ttfa %s ms", ev.get("utt_id"), ev.get("ttfa_ms"))
        elif kind == "say_done":
            logger.info("matrix-call: say %s done: %s s audio, peak %s, rms %s",
                        ev.get("utt_id"), ev.get("audio_s"), ev.get("peak"), ev.get("rms"))
            call.speaking.discard(ev.get("utt_id"))
        elif kind == "say_interrupted":
            logger.info("matrix-call: say %s interrupted: %s", ev.get("utt_id"), ev.get("reason"))
            call.speaking.discard(ev.get("utt_id"))
        elif kind == "local_track_subscribed":  # until then nothing we say reaches the caller
            logger.info("matrix-call: our audio track %s subscribed", ev.get("track_sid"))
        elif kind == "vad_fallback":
            logger.info("matrix-call: speech gate fell back to energy VAD: %s", ev.get("reason"))
        elif kind == "error":
            msg = str(ev.get("msg", ""))
            logger.warning("matrix-call: worker error: %s", msg)
            failed = re.match(r"say (\S+) failed", msg)
            if failed:
                call.speaking.discard(failed.group(1))
            elif not call.in_room:  # join failed: the worker stays up but idle
                self._hang_up_soon(call, "worker could not join")
        elif kind == "left":
            self._hang_up_soon(call, "worker left")

    async def _connected(self, call: Call) -> None:
        room, user = call.caller.room_id, call.caller.user_id
        try:
            call.source = await _request(self._voice_source(room, user))
        except Exception:
            # Without the room's session source no utterance can reach the agent: a call nobody answers.
            logger.exception("matrix-call: no session source for %s, hanging up", room)
            self._hang_up_soon(call, "no session source")
            return
        if call.ended:
            return
        call.connected_at = self.now()
        logger.info("matrix-call: in the call %.1f s after the call event", call.connected_at - call.started)
        safe_room = re.sub(r"[^A-Za-z0-9._-]", "_", room)
        call.transcript = (_phi_home() / "call_transcripts"
                           / f"{safe_room}_{datetime.fromtimestamp(call.started).strftime('%Y%m%d-%H%M%S')}.jsonl")
        self._log(call, "event", event="start", **{"callee" if call.placed else "caller": user}, room=room)
        self._notify(call, "📞 通话已接通")
        if self._session_id(call) is None:
            call.start_marker_due = True  # a brand-new room session: write it once the first turn binds
        else:
            self._spawn(self._start_marker(call))

    # ------------------------------------------------------------------ the caller's turns

    def _hearing(self, call: Call) -> None:
        """The caller began to speak: the turn being put together waits for what they say."""
        if call.ended:
            return
        call.overlap = bool(call.speaking) or (call.overlap and call.hearing > 0)
        call.hearing += 1
        call.began = call.began or self.now()
        self._later(call, "turn", OPEN_SPEECH_S, self._heard, call, True)

    def _heard(self, call: Call, everything: bool = False) -> None:
        """Speech of the caller ended without words (``everything``: all their speech counts as ended)."""
        call.hearing = 0 if everything else max(0, call.hearing - 1)
        if not call.hearing:
            self._pause(call)

    def _pause(self, call: Call) -> None:
        """The caller is silent: their turn goes to the agent unless they go on within the merge window."""
        if call.parts:
            self._later(call, "turn", self.settings.merge_window_ms / 1000, self._turn, call)
            return
        call.began = None
        self._cancel(call, "turn")
        if call.release_due:
            self._release(call)

    async def _utterance(self, call: Call, ev: dict) -> None:
        if call.ended:
            return
        call.hearing = max(0, call.hearing - 1)
        text = str(ev.get("text") or "").strip()
        if not text:
            if not call.hearing:
                self._pause(call)
            return
        stop = STOP.search(text)
        if stop:
            await self._stop_speaking(call)  # however short: the caller means it
        try:
            audio = max(0.0, float(ev["t_end"]) - float(ev["t_start"]))
        except (KeyError, TypeError, ValueError):
            audio = 0.0
        if call.parts and sum(p["audio"] for p in call.parts) + audio > MAX_TURN_S:
            self._turn(call)  # full: this utterance begins the next one
        call.began = call.began or self.now()
        call.parts.append({"text": text, "t_start": ev.get("t_start"), "t_end": ev.get("t_end"), "audio": audio,
                           "over": call.overlap or bool(call.speaking)})
        if stop or sum(p["audio"] for p in call.parts) >= MAX_TURN_S:
            self._turn(call)
        elif not call.hearing:
            self._pause(call)

    def _turn(self, call: Call, closing: bool = False) -> None:
        """The caller's turn is complete. A backchannel over our speech, or while the agent works, only goes to the
        transcript; while we wait for the caller it is their answer. A turn begun within HOLD_S of the last one
        going in, while the agent still works on that, continues it: it waits for the answer (and does not
        interrupt the agent, with busy_input_mode interrupt). Anything else goes to the agent now."""
        self._cancel(call, "turn")
        parts, began = call.parts, call.began
        call.parts, call.began = [], self.now() if call.hearing else None
        if not parts:
            return
        text = _join([p["text"] for p in parts])
        t_start, t_end = parts[0]["t_start"], parts[-1]["t_end"]
        if _backchannel(text) and (call.working or call.speaking or any(p["over"] for p in parts)):
            self._log(call, "caller", kind="backchannel", text=text, t_start=t_start, t_end=t_end)
            if call.release_due and not call.hearing:
                self._release(call)
            return
        call.utterances += 1
        self._log(call, "caller", text=text, t_start=t_start, t_end=t_end)
        self._notify(call, f"🎙️ {text}")
        now = self.now()
        if call.release_due:  # the held turns were due while the caller spoke: this one goes in with them
            texts = ([call.last_text] if call.working else []) + call.held + [text]
        elif (call.working and not closing and not STOP.search(text) and call.injected_at is not None
              and (began or now) - call.injected_at < HOLD_S):
            call.held.append(text)
            self._later(call, "hold", max(call.injected_at, call.last_output or 0) + MERGE_IN_S - now,
                        self._release, call)
            return
        else:
            texts = call.held + [text]
        self._inject(call, texts, parts)
        if not call.ended:
            # The running turn stays the caller's: busy-router may make this a /btw, /bg or /queue, and the turn
            # goes on. The new turn's own takes over when it starts (on_turn).
            self._spawn(self._stop_speaking(call))

    def _release(self, call: Call) -> None:
        """The held turns go to the agent: after its answer, or when it has said nothing for MERGE_IN_S, merged
        with the turn they continue (that one is interrupted). While the caller speaks they wait for that turn."""
        self._cancel(call, "hold")
        if not call.held:
            call.release_due = False
        elif call.hearing or call.parts:
            call.release_due = True
        else:
            self._inject(call, ([call.last_text] if call.working else []) + call.held)

    def _inject(self, call: Call, texts: list[str], parts: list[dict] | None = None) -> None:
        if call.source is None:
            logger.warning("matrix-call: no session source yet, the caller's turn is dropped")
            return
        text = _join(texts)
        first = call.injected_at is None
        call.injected_at, call.working, call.last_text, call.last_output = self.now(), True, text, None
        call.answering, call.muted = None, None
        call.held, call.release_due = [], False
        self._cancel(call, "hold")
        voice = VOICE + text
        call.pending.append(voice)
        from gateway.platforms.event import MessageEvent, MessageType
        hint = PHONE_HINT if self.settings.phone_session else HINT
        event = MessageEvent(text=f"{hint}\n{voice}" if first else voice,
                             message_type=MessageType.VOICE, source=call.source, raw_message={"utterances": parts or []},
                             user_id=call.caller.user_id, user_name=call.source.user_name)
        token = call.last_token = Utterance(call)

        async def inject():
            _injected.set(token)  # the step's own task: only what the gateway does with this turn sees it
            await self.adapter.handle_message(event)

        # handle_message can take seconds (busy-router classifies a message that arrives mid-turn); meanwhile the
        # caller may talk over the reply, and that barge-in must not wait.
        self._queue(call, "inject", inject, "turn to the agent")

    async def _stop_speaking(self, call: Call) -> None:
        if call.speaking:
            call.speaking.clear()
            await call.worker.send("stop_speaking")

    # ------------------------------------------------------------------ hooks (called on the loop by speech.Hooks)

    def on_turn(self, session_id: str, turn_id: str, user_message: str, platform: str, task_id: str | None = None):
        call = self.call
        if call is None or call.ended or call.connected_at is None or platform != "matrix" or not session_id:
            return
        hits = [v for v in call.pending if v in user_message]
        call.pending = [v for v in call.pending if v not in hits]
        main = self._main_session(call)
        # Spoken from now on: a turn of the room's session (task_id keeps its store id when compaction gives the
        # agent a new session id) or, while the room has no session yet, the turn that carries our utterance. A /bg
        # task runs in a session of its own; its result is spoken when the gateway posts it (on_send).
        if not (main in (session_id, task_id) if main else hits or session_id == call.session_id):
            return
        call.session_id, call.turn_id = session_id, turn_id
        if VOICE + call.last_text in hits:
            call.answering = turn_id
        if call.start_marker_due:
            call.start_marker_due = False
            self._spawn(self._start_marker(call))

    def on_reply(self, session_id: str, turn_id: str, text: str, kind: str) -> None:
        call = self.call
        if (call is None or call.ended or call.worker is None or not session_id or session_id != call.session_id
                or not turn_id or turn_id != call.turn_id):
            return
        if turn_id == call.answering:
            self._answered(call, kind == "final")
        if (turn_id, text) in call.said:
            return
        call.said.add((turn_id, text))
        if turn_id == call.muted:
            self._log(call, "agent", kind=kind, text=text, muted=True)
            return
        self._say(call, text, kind)

    def _answered(self, call: Call, final: bool) -> None:
        """The agent said something on the caller's last turn (not on one before: that may answer while the last
        waits for it); ``final``: its answer. Held turns go in once the gateway has posted that (on_send), or
        RELEASE_S after it: injected earlier, they would interrupt the turn before its answer is out, and the
        gateway drops an interrupted turn's answer."""
        call.last_output = self.now()
        if final:
            call.working = False
        if call.held:
            self._later(call, "hold", RELEASE_S if final else MERGE_IN_S, self._release, call)

    def on_send(self, chat_id, content, metadata) -> None:
        """Each message the adapter is about to send (on the loop). A /btw answer and a /bg result reach the room
        this way and not as a turn's reply; they are spoken when they answer a /btw or /bg that busy-router made of
        an utterance of this call, which the gateway acked under the same token (_injected). Anything else the
        gateway posts (tool progress, approvals, our notices, the final reply the hook already spoke, the answer to
        a /btw typed into the room) is not."""
        call, token = self.call, _injected.get()
        if (call is None or call.ended or call.worker is None or call.connected_at is None
                or str(chat_id) != call.caller.room_id or not isinstance(content, str)
                or (metadata or {}).get("_interim_send")):
            return
        if call.held and not call.working and (metadata or {}).get("notify"):
            self._later(call, "hold", SETTLE_S, self._release, call)  # the answer's post: the turn is over
        if token is None or token.call is not call:
            return
        last = token is call.last_token
        if _posted("gateway.btw.started", content):
            token.asked = "btw"
        elif _posted("gateway.background.started", content):
            token.asked = "bg"
            if last:  # a background task now: nothing the turns held for it should wait for
                self._answered(call, True)
        # busy-router posts no "started" notice for a /btw (it stays internal), so the answer itself may be the
        # first post the side question makes.
        elif token.asked in ("btw", None) and (m := _posted("gateway.btw.answer", content)):
            token.asked = None
            if last:  # the caller's last turn became the side question: this is its answer
                self._answered(call, True)
            self._say(call, m["body"], "btw")
        elif token.asked == "btw" and _posted("gateway.btw.failed", content):
            token.asked = None
            if last:
                self._answered(call, True)
        elif token.asked == "bg" and (m := _posted("gateway.background.complete_header", content, tail=True)):
            token.asked = None
            from agent.i18n import t
            if m["body"].strip() != t("gateway.background.no_response"):
                self._say(call, m["body"], "bg")
        elif token.asked == "bg" and (_posted("gateway.background.failed", content)
                                      or _posted("gateway.background.no_credentials", content)):
            token.asked = None

    def _say(self, call: Call, text: str, kind: str) -> None:
        self._log(call, "agent", kind=kind, text=text)
        say = speech.spoken(_unspoken(text))
        if say:
            utt_id = f"a{next(self._utt_ids)}"
            call.speaking.add(utt_id)
            call.overlap = call.overlap or call.hearing > 0
            logger.info("matrix-call: say %s sent: %d chars (%s)", utt_id, len(say), kind)
            self._spawn(call.worker.send("say", utt_id=utt_id, text=say))

    # ------------------------------------------------------------------ room, session, transcript

    async def _voice_source(self, room: str, user: str):
        # The fields _resolve_message_context gives a text message from this sender, minus its per-message parts
        # (message_id, synthetic thread): the utterance must land in the room's session, not a fresh thread. With the
        # phone session on, that is the room's phone thread instead: the session of every call (phone.py).
        a = self.adapter
        identity = await a._resolve_room_identity(room)
        chat_type = "dm" if await a._is_dm_room(room) else "group"
        name = await a._get_display_name(room, user)
        on = bool(getattr(self.settings, "phone_session", False))
        thread = await phone.thread_root(a, room) if on else None
        if on and not thread:
            raise RuntimeError("no phone thread")  # never fall back into the room's chat session
        source = a.build_source(chat_id=room, chat_name=identity.display_name, chat_type=chat_type, user_id=user,
                                user_name=name, chat_topic=identity.room_topic, guild_id=identity.server_name,
                                thread_id=thread, parent_chat_id=room if thread else None)
        if thread:
            runner = getattr(a, "gateway_runner", None)
            if runner is not None:
                await phone.pin_model(runner, source, self.settings.phone_model, self.settings.phone_provider)
        return source

    def _main_session(self, call: Call) -> str | None:
        """The store id of the room's session, the one a message from the room runs in; None while it has none."""
        runner = getattr(self.adapter, "gateway_runner", None)
        try:
            return runner.session_store.peek_session_id(runner._session_key_for_source(call.source))
        except Exception:
            return None

    def _session_id(self, call: Call) -> str | None:
        return self._main_session(call) or call.session_id

    async def _start_marker(self, call: Call) -> None:
        name = call.source.user_name or call.caller.user_id
        who = f"打给 {name} 的" if call.placed else f"{name} 发起的"
        await self._marker(call, f"[语音通话开始] {_stamp(call.connected_at)}，{who}语音通话已接通")

    async def _marker(self, call: Call, text: str) -> None:
        sid = self._session_id(call)
        if sid is None:
            logger.warning("matrix-call: no session for %s, call marker not written", call.caller.room_id)
            return
        from gateway.mirror import mirror_to_session
        # role="user": a marker is not the agent speaking (see mirror_to_session's docstring)
        await asyncio.to_thread(mirror_to_session, "matrix", call.caller.room_id, text,
                                source_label="matrix-call", role="user", session_id=sid)

    def _notify(self, call: Call, body: str, request_s: float | None = None) -> None:
        room = call.caller.room_id
        content = {"msgtype": "m.notice", "body": body}
        thread = getattr(call.source, "thread_id", None)
        if thread:  # the phone session's notices belong in its thread
            content["m.relates_to"] = {"rel_type": "m.thread", "event_id": thread, "is_falling_back": True,
                                       "m.in_reply_to": {"event_id": thread}}
        self._queue(call, "notice", lambda: _request(self.client.send_message_event(
            RoomID(room), EventType.ROOM_MESSAGE, content), request_s), f"notice to {room}")

    def _log(self, call: Call, role: str, **fields) -> None:
        if call.transcript is None:
            return
        path = call.transcript
        line = json.dumps({"ts": datetime.now().astimezone().isoformat(timespec="milliseconds"), "role": role,
                           **fields}, ensure_ascii=False) + "\n"
        self._queue(call, "transcript", lambda: asyncio.to_thread(_append, path, line), "transcript write")


def _append(path: Path, text: str) -> None:
    # The transcript is the whole conversation: owner-only, also where an earlier version made the directory 0755.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a", encoding="utf-8") as f:
        f.write(text)


def _phi_home() -> Path:
    from phi_constants import get_phi_home
    return Path(get_phi_home())

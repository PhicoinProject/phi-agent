"""matrix-call: answer Element X (MatrixRTC) calls from allowed callers and talk through Phi; ring them when the
agent asks through the control socket (``tools/call.py``).

Settings live in ``plugins.entries.matrix-call.settings`` (see DEFAULTS). The media runs in ``worker/call_worker.py``
under its own venv, because LiveKit is not installed in the gateway's."""
from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial

from . import call, control, keys, ring
from .call import CALL_MEMBER_STATE, Calls, Settings
from .speech import Hooks

logger = logging.getLogger(__name__)

DEFAULTS = {
    "allowed_callers": [],
    "worker_python": "",  # a venv with livekit + onnxruntime; required to answer calls
    "stt_url": "http://127.0.0.1:18800/v1/audio/transcriptions",
    "stt_model": "Qwen/Qwen3-ASR-1.7B",
    "tts_url": "http://127.0.0.1:8880/v1/audio/speech",
    "tts_voice": "zf_xiaoxiao",
    "livekit_service_url": "",  # the focus of calls we place: the homeserver's Element Call LiveKit JWT service
    "eou_silence_ms": 1200,  # the caller's silence that ends an utterance
    "merge_window_ms": 1000,  # further silence before a turn goes to the agent; speech within it joins the turn
    "barge_in_ms": 600,  # the caller's continuous speech that stops ours
    "vad_model": "",  # without it the VAD is energy only
    # The phone session (phone.py): every call in one thread of the DM room, on a fast model of its own. Opt-in.
    "phone_session": False,
    "phone_model": "",  # e.g. a fast chat model; empty keeps the gateway model
    "phone_provider": "",  # empty uses the active provider
}
WORKER_ENV = {"stt_url": "MATRIX_CALL_STT_URL", "stt_model": "MATRIX_CALL_STT_MODEL",
              "tts_url": "MATRIX_CALL_TTS_URL", "tts_voice": "MATRIX_CALL_TTS_VOICE",
              "eou_silence_ms": "MATRIX_CALL_EOU_SILENCE_MS", "barge_in_ms": "MATRIX_CALL_BARGE_IN_MS",
              "vad_model": "MATRIX_CALL_VAD_MODEL"}

ADOPT_S = 30  # a call held over a reload is hung up when no new instance of the plugin takes it over in this time
HELD = "_matrix_call_held"  # adapter attribute: (controller, timer) an unload left for the instance loaded next

_settings: Settings | None = None
_controllers: list[Calls] = []  # one per wired Matrix client
_control: control.Server | None = None  # started by the first factory call, on the gateway loop
_MISSING = object()


def read_settings(ctx) -> Settings:
    def get(key):
        return ctx.get_config(key, DEFAULTS[key])

    callers = get("allowed_callers")
    if isinstance(callers, str):
        callers = [callers]
    return Settings(allowed_callers=frozenset(str(c) for c in callers or []),
                    worker_python=str(get("worker_python")),
                    worker_env={env: str(get(key)) for key, env in WORKER_ENV.items()},
                    livekit_service_url=str(get("livekit_service_url")),
                    merge_window_ms=int(get("merge_window_ms")),
                    phone_session=str(get("phone_session")).strip().lower() in ("true", "1", "yes", "on"),
                    phone_model=str(get("phone_model") or ""), phone_provider=str(get("phone_provider") or ""))


def matrix_call_factory(client, adapter) -> None:
    """Platform handler factory: the Matrix adapter calls it from connect() with its mautrix client, on the gateway
    loop; again after a reconnect (a new client) and when a reload of this plugin re-wires the live adapter."""
    global _control
    held = _take_held(adapter)
    for old in [c for c in _controllers if c.adapter is adapter]:
        _forget(old, "reconnected")
    if held is not None and held.call is not None and held.client is client:
        # A reload during a call: the call goes on with the controller (and the code) it started with, now ours to
        # run; one of this code takes over once the line is free.
        held.on_idle = partial(_renew, held)
        calls = held
    else:
        if held is not None and held.call is not None:  # held on a client the adapter has replaced since
            _forget(held, "reconnected")
        calls = _controller(client, adapter, held)
    _controllers.append(calls)
    if _control is None and calls.loop is not None:
        _control = control.Server(lambda: _controllers[-1] if _controllers else None)
        _control.start(calls.loop)
    _wrap(adapter, "disconnect", _disconnect)
    _wrap(adapter, "send", _send)
    logger.info("matrix-call: answering calls from %s", ", ".join(sorted(_settings.allowed_callers)) or "nobody")


def _controller(client, adapter, previous: Calls | None) -> Calls:
    calls = Calls(client, adapter, _settings)
    if previous is not None:
        calls.inherit(previous)
    try:
        calls.loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    client.add_event_handler(CALL_MEMBER_STATE, calls.on_state)
    client.add_event_handler(keys.KEYS_EVENT, calls.on_keys)
    client.add_event_handler(ring.DECLINE_EVENT, calls.on_decline)
    return calls


def _renew(old: Calls) -> None:
    """The call adopted over a reload is over: a controller of the code loaded now replaces the one it ran on."""
    if old in _controllers:
        _forget(old, "renewed")
        _controllers.append(_controller(old.client, old.adapter, old))


def _wrap(adapter, name: str, make) -> None:
    """Put our wrapper of ``adapter.<name>`` in front of the adapter's own, once per plugin load. An instance
    attribute: unload puts back what was there (normally nothing, so the class method is back)."""
    current = getattr(adapter, name)
    if getattr(current, "_matrix_call", None) is _controllers:
        return
    wrapper = make(adapter, current)
    wrapper.__wrapped__, wrapper._matrix_call = current, _controllers
    wrapper._saved = vars(adapter).get(name, _MISSING)
    setattr(adapter, name, wrapper)


def _unwrap(adapter, name: str) -> None:
    wrapper = vars(adapter).get(name)
    if getattr(wrapper, "_matrix_call", None) is not _controllers:
        return
    if wrapper._saved is _MISSING:
        delattr(adapter, name)
    else:
        setattr(adapter, name, wrapper._saved)


def _disconnect(adapter, original):
    # There is no shutdown hook, and disconnect() closes the client, so the hang-up (our call.member back to {})
    # has to run before it. The gateway gives disconnect() 5 s and then cancels it: our part gets HANG_UP_S, and
    # the adapter's own disconnect runs whatever happens to it, also on cancel.
    async def disconnect(*args, **kwargs):
        mine = [c for c in _controllers if c.adapter is adapter]
        try:
            await asyncio.wait_for(asyncio.gather(*(c.shutdown("gateway disconnect", call.HANG_UP_REQUEST_S)
                                                    for c in mine)), call.HANG_UP_S)
        except asyncio.TimeoutError:
            logger.warning("matrix-call: hang-up on disconnect took over %s s, disconnecting anyway", call.HANG_UP_S)
        except Exception:
            logger.exception("matrix-call: hang-up on disconnect failed")
        finally:
            result = await original(*args, **kwargs)
        return result

    return disconnect


def _send(adapter, original):
    # A /btw answer and a /bg result reach the room through send() and never pass a turn hook; the call speaks
    # those (Calls.on_send) when they answer a side question of the caller. Read before the send: encrypting and
    # posting take a while, and the side question's answer may already be on its way while the started notice
    # that counts it is still being sent.
    async def send(chat_id, content, reply_to=None, metadata=None, **kwargs):
        for c in [c for c in _controllers if c.adapter is adapter]:
            try:
                c.on_send(chat_id, content, metadata)
            except Exception:
                logger.exception("matrix-call: reading a sent message failed")
        return await original(chat_id, content, reply_to=reply_to, metadata=metadata, **kwargs)

    return send


def _forget(c: Calls, reason: str) -> None:
    """Take a controller off its client, on the gateway loop; a call it has is hung up."""
    c.client.remove_event_handler(CALL_MEMBER_STATE, c.on_state)
    c.client.remove_event_handler(keys.KEYS_EVENT, c.on_keys)
    c.client.remove_event_handler(ring.DECLINE_EVENT, c.on_decline)
    if c in _controllers:
        _controllers.remove(c)
    if c.call is not None and c.loop is not None and c.loop.is_running():
        c.loop.create_task(c.shutdown(reason))


def _detach(c: Calls) -> None:
    """Unload, on the loop. The controller is left on the adapter for the instance a reload loads next (HELD).
    Off a call it is taken off its client now and leaves only what it knew. A call that is on goes on: the
    controller stays on its client, hearing the caller's leave, their keys and the worker, until the next instance
    adopts it; if none comes in ADOPT_S (the plugin was disabled, or failed to load), the call is hung up."""
    timer = None
    if c.call is not None and c.loop is not None and c.loop.is_running():
        _controllers.remove(c)
        c.on_idle = partial(_forget, c, "plugin unloaded")  # over before anyone adopts it: answer no more calls
        timer = c.loop.call_later(ADOPT_S, _drop, c)
    else:
        _forget(c, "plugin unloaded")
    setattr(c.adapter, HELD, (c, timer))
    if not any(o.adapter is c.adapter for o in _controllers):
        _unwrap(c.adapter, "disconnect")
        _unwrap(c.adapter, "send")
    wired = getattr(c.adapter, "_plugin_handlers_wired", None)
    if wired:  # the adapter skips factories it has wired on this client; let a re-enable wire us again
        wired.difference_update({k for k in wired if k[1] == matrix_call_factory.__qualname__})


def _drop(c: Calls) -> None:
    """Nobody took over the held controller in ADOPT_S: hang up its call."""
    if vars(c.adapter).get(HELD, (None,))[0] is c:
        delattr(c.adapter, HELD)
    if c.call is not None:
        _forget(c, "plugin unloaded, not reloaded")


def _take_held(adapter) -> Calls | None:
    held = vars(adapter).pop(HELD, None)
    if held is None:
        return None
    c, timer = held
    if timer is not None:
        timer.cancel()
    return c


def _unload() -> None:
    # Phi runs on_unload on the thread that discovers plugins: for `phi plugins enable/reload` that is the
    # control socket's executor, while the loop goes on dispatching Matrix events through these very handlers.
    global _control
    for c in list(_controllers):
        _on_loop(c.loop, partial(_detach, c))
    if _control is not None:
        _on_loop(_control.loop, _control.close)
        _control = None


def _on_loop(loop, fn) -> None:
    try:
        here = asyncio.get_running_loop()
    except RuntimeError:
        here = None
    if loop is None or here is loop or loop.is_closed() or not loop.is_running():
        fn()
    else:
        loop.call_soon_threadsafe(fn)


def _rewire_live_gateway() -> None:
    """After a reload the adapters are connected already and do not run our factory again by themselves (the
    gateway's re-wire listener fires for newly loaded plugins only): ask the running gateway to re-wire them."""
    run = sys.modules.get("gateway.run")  # never imported here: that module bootstraps the gateway process
    try:
        runner = run._gateway_runner_ref()
    except Exception:
        return
    loop = getattr(runner, "_gateway_loop", None)
    if loop is not None and not loop.is_closed() and loop.is_running():
        loop.call_soon_threadsafe(runner._rewire_plugin_handlers)


def register(ctx) -> None:
    global _settings
    _settings = read_settings(ctx)
    hooks = Hooks(_controllers)
    ctx.register_platform_handler("matrix", matrix_call_factory)
    ctx.register_hook("pre_llm_call", hooks.pre_llm_call)
    ctx.register_hook("post_llm_call", hooks.post_llm_call)
    ctx.register_hook("on_interim_message", hooks.on_interim_message)
    ctx.on_unload(_unload)
    _rewire_live_gateway()

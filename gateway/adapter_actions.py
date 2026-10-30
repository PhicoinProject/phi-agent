"""Named actions a platform plugin runs on its live adapter, for processes that have no adapter.

A plugin registers ``register_adapter_action(platform, name, fn)`` with ``async fn(adapter, args) -> dict``;
the dashboard (or any local process) calls :func:`call_adapter_action`, which asks the running gateway
over the control socket (verb ``adapter-action``) to run it on that profile's connected adapter, on the
gateway loop. The Matrix space mirror uses this to write a workspace move/rename/create-space to Matrix
before the map changes (design §七).

An answer is the action's dict; a failure is ``{"error": str, "status": int}`` (HTTP-style status),
and ``None`` from :func:`call_adapter_action` means no running gateway answered.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

AdapterAction = Callable[[Any, dict], Awaitable[dict]]

ACTION_TIMEOUT = 25.0
_ACTIONS: dict[tuple[str, str], AdapterAction] = {}


def register_adapter_action(platform: str, name: str, fn: AdapterAction) -> None:
    """Make ``fn`` callable as ``platform``/``name``; registering again replaces it (plugin reload)."""
    _ACTIONS[((platform or "").strip().lower(), name)] = fn


def get_adapter_action(platform: str, name: str) -> Optional[AdapterAction]:
    return _ACTIONS.get(((platform or "").strip().lower(), name))


def _profile_adapters(runner: Any, gateway_home: Path, requested: Path) -> Optional[dict]:
    """The adapters serving ``requested``: the gateway's own, a served profile's, or None (not served)."""
    from phi_constants import phi_home_key
    req_key = phi_home_key(requested)
    if req_key == phi_home_key(gateway_home):
        return getattr(runner, "adapters", None) or {}
    served = (getattr(runner, "_served_profile_homes", None) or {}).items()
    name = next((str(n) for n, h in served if phi_home_key(h) == req_key), None)
    if name is None:
        return None
    if name == (getattr(runner, "_primary_profile_name", None) or "default"):
        return getattr(runner, "adapters", None) or {}
    return (getattr(runner, "_profile_adapters", None) or {}).get(name) or {}


def adapter_action_verb(runner: Any, loop: asyncio.AbstractEventLoop) -> Callable[..., dict]:
    """Control-socket ``adapter-action``: params ``{home, platform, action, args}``. Runs the registered
    action on the requested home's connected adapter, on the gateway loop, with that home in scope."""

    def _handler(params: Optional[dict] = None) -> dict:
        from phi_constants import get_phi_home, reset_phi_home_override, set_phi_home_override
        params = params or {}
        platform, name = str(params.get("platform") or ""), str(params.get("action") or "")
        fn = get_adapter_action(platform, name)
        if fn is None:
            return {"error": f"The gateway has no {platform} action {name!r}; update or restart it.", "status": 404}
        gateway_home = Path(get_phi_home())
        requested = Path(str(params.get("home") or gateway_home)).expanduser()
        adapters = _profile_adapters(runner, gateway_home, requested)
        if adapters is None:
            return {"error": "This profile is not served by the running gateway.", "status": 503}
        adapter = next((a for p, a in adapters.items() if getattr(p, "value", str(p)) == platform), None)
        if adapter is None:
            return {"error": f"{platform} is not connected for this profile.", "status": 503}
        args = params.get("args") if isinstance(params.get("args"), dict) else {}

        async def _run() -> Any:
            token = set_phi_home_override(str(requested))
            try:
                return await fn(adapter, args)
            finally:
                reset_phi_home_override(token)

        future = asyncio.run_coroutine_threadsafe(_run(), loop)
        try:
            answer = future.result(timeout=ACTION_TIMEOUT)
        except concurrent.futures.TimeoutError:
            future.cancel()
            return {"error": f"{platform} did not answer in time.", "status": 504}
        except Exception as exc:
            logger.exception("adapter action %s/%s failed", platform, name)
            return {"error": f"{type(exc).__name__}: {exc}", "status": 500}
        return answer if isinstance(answer, dict) else {"error": "The action gave no answer.", "status": 500}

    return _handler


def call_adapter_action(platform: str, action: str, args: dict, *,
                        timeout: float = ACTION_TIMEOUT + 5) -> Optional[dict]:
    """Run ``platform``/``action`` on the live adapter of the current home's gateway. Asks the gateway of
    the current home first, then the root gateway (a multiplexer serving several profiles). Returns the
    answer dict, or None when no gateway answered. Blocking: call off the event loop."""
    from gateway.control_socket import query_gateway_control
    from phi_constants import get_default_phi_root, get_phi_home, phi_home_key
    home = Path(get_phi_home())
    params = {"home": str(home), "platform": platform, "action": action, "args": args}
    targets = [home]
    root = Path(get_default_phi_root())
    if phi_home_key(root) != phi_home_key(home):
        targets.append(root)
    for target in targets:
        answer = query_gateway_control(target, "adapter-action", params=params, timeout=timeout)
        if answer is not None:
            return answer
    return None

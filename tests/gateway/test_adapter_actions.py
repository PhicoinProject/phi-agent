"""Control-socket ``adapter-action``: a local process runs a platform plugin's action on the live adapter.

The dashboard has no Matrix client; the Matrix space mirror registers its write-back as adapter actions
and the dashboard asks the running gateway for them. The action runs on the gateway loop, against the
adapter of the profile that asked, with that profile's home in scope; every failure is an answer with
an HTTP-style status, never a hang or an action on another profile's adapter.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from gateway import adapter_actions
from gateway.adapter_actions import adapter_action_verb, call_adapter_action, register_adapter_action
from gateway.config import Platform
from gateway.control_socket import GatewayControlServer
from phi_constants import get_default_phi_root, get_phi_home, reset_phi_home_override, set_phi_home_override


@pytest.fixture
def gateway_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        loop.close()


@pytest.fixture(autouse=True)
def _own_registry(monkeypatch):
    monkeypatch.setattr(adapter_actions, "_ACTIONS", {})


def _runner(tmp_path):
    beta_home = tmp_path / "profiles" / "beta"
    beta_home.mkdir(parents=True)
    return SimpleNamespace(
        adapters={Platform.MATRIX: "default-matrix"},
        _primary_profile_name="default",
        _served_profile_homes={"default": Path(get_phi_home()), "beta": beta_home},
        _profile_adapters={"beta": {Platform.MATRIX: "beta-matrix"}},
    ), beta_home


def _ask(server, params):
    raw = json.dumps({"verb": "adapter-action", "id": 1, "params": params}).encode()
    response = json.loads(server.handle_request_line(raw).decode())
    assert response["ok"] is True, response
    return response["result"]


def test_action_runs_on_the_gateway_loop_against_the_asking_profile(tmp_path, gateway_loop):
    runner, beta_home = _runner(tmp_path)
    seen = []

    async def move(adapter, args):
        seen.append((adapter, args, str(get_phi_home()), asyncio.get_running_loop()))
        return {"room": {"room_id": args["room_id"]}}

    register_adapter_action("matrix", "space_mirror.move", move)
    server = GatewayControlServer(home=tmp_path, verb_handlers={
        "adapter-action": adapter_action_verb(runner, gateway_loop)})

    answer = _ask(server, {"home": str(beta_home), "platform": "matrix", "action": "space_mirror.move",
                           "args": {"room_id": "r1"}})
    assert answer == {"room": {"room_id": "r1"}}
    assert seen == [("beta-matrix", {"room_id": "r1"}, str(beta_home), gateway_loop)]

    assert _ask(server, {"home": str(get_phi_home()), "platform": "matrix",
                         "action": "space_mirror.move", "args": {"room_id": "r2"}}) == {"room": {"room_id": "r2"}}
    assert seen[-1][0] == "default-matrix"


def test_unknown_action_unserved_profile_and_missing_platform_are_errors(tmp_path, gateway_loop):
    runner, beta_home = _runner(tmp_path)
    runner._profile_adapters = {"beta": {}}
    calls = []

    async def move(adapter, args):
        calls.append(adapter)
        return {}

    register_adapter_action("matrix", "space_mirror.move", move)
    verb = adapter_action_verb(runner, gateway_loop)

    unknown = verb({"home": str(beta_home), "platform": "matrix", "action": "space_mirror.nope"})
    assert unknown["status"] == 404
    stranger = verb({"home": str(tmp_path / "elsewhere"), "platform": "matrix", "action": "space_mirror.move"})
    assert stranger["status"] == 503 and "not served" in stranger["error"]
    offline = verb({"home": str(beta_home), "platform": "matrix", "action": "space_mirror.move"})
    assert offline["status"] == 503 and "not connected" in offline["error"]
    assert calls == []


def test_failing_slow_or_answerless_actions_become_error_answers(tmp_path, gateway_loop, monkeypatch):
    runner, _beta = _runner(tmp_path)

    async def boom(adapter, args):
        raise RuntimeError("homeserver exploded")

    async def slow(adapter, args):
        await asyncio.sleep(30)

    async def silent(adapter, args):
        return None

    for name, fn in (("boom", boom), ("slow", slow), ("silent", silent)):
        register_adapter_action("matrix", name, fn)
    monkeypatch.setattr(adapter_actions, "ACTION_TIMEOUT", 0.2)
    verb = adapter_action_verb(runner, gateway_loop)

    failed = verb({"platform": "matrix", "action": "boom"})
    assert failed["status"] == 500 and "homeserver exploded" in failed["error"]
    assert verb({"platform": "matrix", "action": "slow"})["status"] == 504
    assert verb({"platform": "matrix", "action": "silent"})["status"] == 500


def test_call_asks_the_profile_gateway_then_the_root_multiplexer(monkeypatch):
    from gateway import control_socket

    root = Path(get_default_phi_root())
    beta = root / "profiles" / "beta"
    asked = []
    replies = {}

    def query(home, verb, *, params=None, timeout=None):
        asked.append((Path(home), verb, params))
        return replies.get(Path(home))

    monkeypatch.setattr(control_socket, "query_gateway_control", query)
    token = set_phi_home_override(str(beta))
    try:
        replies[root] = {"room": {"room_id": "r1"}}
        assert call_adapter_action("matrix", "space_mirror.rename", {"room_id": "r1"}) == {"room": {"room_id": "r1"}}
        assert [a[0] for a in asked] == [beta, root]
        assert all(a[1] == "adapter-action" for a in asked)
        assert asked[0][2] == {"home": str(beta), "platform": "matrix", "action": "space_mirror.rename",
                               "args": {"room_id": "r1"}}

        asked.clear()
        replies[beta] = {"error": "matrix is not connected for this profile.", "status": 503}
        assert call_adapter_action("matrix", "space_mirror.rename", {})["status"] == 503
        assert [a[0] for a in asked] == [beta]

        asked.clear()
        replies.clear()
        assert call_adapter_action("matrix", "space_mirror.rename", {}) is None
        assert [a[0] for a in asked] == [beta, root]
    finally:
        reset_phi_home_override(token)

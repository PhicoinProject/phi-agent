"""A chat lane captured before the gateway began serving a second profile keeps working after it.

Background: ``_binding`` stamps ``transport_profile`` into a native row's provenance only while
the process multiplexes profiles. Creating a second profile hot-serves it in the same process
(``run_profile_reconcile``), so every row the default profile committed earlier — a chat's
committed route envelope that background-process notices and queued turns are restored from —
lacks the key. ``restore_provenance`` compared the stored dict with a freshly computed one by
equality, so every such restore raised ``profile_mismatch``: process notices for that chat were
refused once a minute and the lane's queued turns paused, until the chat sent a new message.
"""
import weakref
from pathlib import Path

import pytest

from gateway.config import GatewayConfig, Platform
from gateway.platforms.event import MessageEvent, MessageType
from gateway.run import GatewayRunner
from gateway.run_runtime import initialize_gateway_runtime
from gateway.runtime_ownership import process_ownership
from gateway.session import SessionSource
from gateway.session_ingress_context import (
    capture_provenance, native_callback, register_transport_home, restore_provenance)

from phi_state_runtime import RuntimeStoreError


class _FakeAdapter:
    """Weakref-able stand-in for a live platform adapter."""


def _homes(tmp_path, monkeypatch):
    root = tmp_path / ".phi"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("PHI_HOME", str(root))
    import phi_state
    monkeypatch.setattr(phi_state, "DEFAULT_DB_PATH", phi_state._IMPORT_DEFAULT_DB_PATH)
    second = root / "profiles" / "guest"
    second.mkdir(parents=True, mode=0o700)
    (second / "config.yaml").write_text("{}")
    return root, second


def _source(adapter):
    source = SessionSource(platform=Platform.BLUEBUBBLES, chat_id="any;-;+155****0001", chat_type="dm",
                           user_id="+155****0001", user_name="Ann")
    source._transport_adapter_ref = weakref.ref(adapter)
    return source


def _start_multiplexing(runner, root, second):
    """What run_profile_reconcile does when a second profile appears: same process, now multiplexed."""
    runner.config.multiplex_profiles = True
    runner.config._runtime_profile_homes = (("default", root), ("guest", second))


async def _restore_after_hot_serve(tmp_path, monkeypatch, *, stored):
    root, second = _homes(tmp_path, monkeypatch)
    runner = GatewayRunner(GatewayConfig())
    process_ownership.reserve([root, second])
    try:
        await initialize_gateway_runtime(runner)
        register_transport_home(runner, None, root)
        adapter = _FakeAdapter()
        runner.adapters = {Platform.BLUEBUBBLES: adapter}
        runner._is_user_authorized_for_source = lambda *a, **k: True
        event = MessageEvent(text="hello", message_type=MessageType.TEXT, source=_source(adapter),
                             message_id="probe-msg")
        with native_callback(runner, event, root, None):
            captured = capture_provenance(runner, event)
        assert "transport_profile" not in captured, "single-profile capture carries no transport_profile"
        _start_multiplexing(runner, root, second)
        provenance = stored(captured)
        return restore_provenance(runner, _source(adapter), provenance), root
    finally:
        for authority in list(getattr(runner, "session_authorities", []) or []):
            authority.db.close()
        for home in (root, second):
            process_ownership.release(home)


@pytest.mark.asyncio
async def test_a_row_captured_before_a_second_profile_restores_after_it(tmp_path, monkeypatch):
    runtime_home, root = await _restore_after_hot_serve(tmp_path, monkeypatch, stored=dict)
    assert Path(runtime_home) == root


@pytest.mark.asyncio
async def test_a_row_naming_another_binding_is_still_refused(tmp_path, monkeypatch):
    """Only the missing key is tolerated: a different connector stays a mismatch."""
    with pytest.raises(RuntimeStoreError) as exc:
        await _restore_after_hot_serve(tmp_path, monkeypatch,
                                       stored=lambda p: {**p, "connector": "another-credential"})
    assert exc.value.reason == "profile_mismatch"

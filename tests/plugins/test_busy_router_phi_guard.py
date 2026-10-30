"""guard: busy-router ships bundled and routes a mid-turn message.

busy-router (plugins/busy-router) classifies a message that arrives while the chat's agent is busy
into A (leave to busy_input_mode), B (/btw), C (/bg) or D (/queue) with one structured decision
call. It acts on the busy path, which stock Hermes does not hook: gateway/run_busy.py carries the
PHI patch 0004 that runs pre_gateway_dispatch there. Both halves must survive every stable
sync, so these tests load the shipped plugin and drive the real routing function.
"""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "plugins" / "busy-router"


def _load():
    spec = importlib.util.spec_from_file_location("phi_busy_router_guard", PLUGIN / "__init__.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Ctx:
    def __init__(self, settings):
        self.settings, self.hooks = settings, {}

    def get_config(self, key, default=None):
        return self.settings.get(key, default)

    def register_hook(self, name, fn):
        self.hooks[name] = fn

    def register_locale(self, lang, strings):
        pass


class _Gateway:
    def __init__(self, running=True, authorized=True):
        self.running, self.authorized = running, authorized
        self.session_store = None

    def _session_key_for_source(self, source):
        return "agent:main:matrix:dm:!room"

    def _is_session_running(self, key):
        return self.running

    def _is_user_authorized(self, source):
        return self.authorized

    def _peek_session_state(self, key):
        return SimpleNamespace(turn=SimpleNamespace(event=SimpleNamespace(text="refactor the parser")))


def _event(text):
    return SimpleNamespace(text=text, internal=False, media_urls=[], media_types=[],
                           source=SimpleNamespace(chat_id="!room"))


def _with_label(mod, monkeypatch, label):
    monkeypatch.setattr(mod, "_read_history", lambda *a, **k: [])
    monkeypatch.setattr(mod, "classify", lambda *a, **k: (label, {label: 0.9} if label else {}))


def test_plugin_is_bundled_and_registers_the_dispatch_hook():
    assert (PLUGIN / "plugin.yaml").is_file()
    assert "pre_gateway_dispatch" in (PLUGIN / "plugin.yaml").read_text(encoding="utf-8")
    mod = _load()
    ctx = _Ctx({})
    mod.register(ctx)
    assert "pre_gateway_dispatch" in ctx.hooks


@pytest.mark.parametrize("label,verb", [("B", "btw"), ("C", "bg"), ("D", "queue")])
def test_busy_message_is_rewritten_to_the_classified_command(monkeypatch, label, verb):
    mod = _load()
    mod.register(_Ctx({"endpoint": "http://127.0.0.1:9/v1/chat/completions", "decision_model": "m"}))
    _with_label(mod, monkeypatch, label)
    out = asyncio.run(mod.route(_event("how far along are you with that"), _Gateway()))
    assert out == {"action": "rewrite", "text": f"/{verb} how far along are you with that"}


@pytest.mark.parametrize("case", ["correction", "idle", "slash", "fragment"])
def test_everything_else_passes_through(monkeypatch, case):
    mod = _load()
    settings = {"endpoint": "http://127.0.0.1:9/v1", "decision_model": "m"}
    mod.register(_Ctx(settings))
    _with_label(mod, monkeypatch, "A" if case == "correction" else "C")
    text = {"slash": "/status", "fragment": "ok"}.get(case, "use the new schema instead please")
    gw = _Gateway(running=case != "idle")
    assert asyncio.run(mod.route(_event(text), gw)) is None


def test_classifier_errors_never_block_the_message(monkeypatch):
    mod = _load()
    mod.register(_Ctx({"endpoint": "http://127.0.0.1:9/v1", "decision_model": "m"}))
    monkeypatch.setattr(mod, "_read_history", lambda *a, **k: [])

    def boom(*a, **k):
        raise TimeoutError("decision endpoint down")
    monkeypatch.setattr(mod, "classify", boom)
    assert asyncio.run(mod._on_dispatch(event=_event("start a new report on GPUs"), gateway=_Gateway())) is None


def test_classify_reads_the_structured_decision(monkeypatch):
    mod = _load()
    seen = {}

    class _Resp:
        def read(self):
            content = json.dumps({"answers": {"route": {"label": "C", "probabilities": {"C": 0.8, "A": 0.2}}}})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    def fake_urlopen(req, timeout):
        seen["body"] = json.loads(req.data)
        return _Resp()
    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    label, probs = mod.classify("task", "new thing", "http://x/v1/chat/completions", "m")
    assert (label, probs) == ("C", {"C": 0.8, "A": 0.2})
    assert seen["body"]["model"] == "m"

# The busy-path hook itself (gateway/run_busy.py, PHI patch 0004) is enforced at build time:
# rules.fix_rick_features raises when its anchor is missing, so a stable sync cannot drop it.


def test_bundled_busy_router_is_enabled_by_default():
    from phi_cli.plugins_discovery import gate_manifest
    from phi_cli.plugins_manifest import PluginManifest
    m = PluginManifest(name="busy-router", source="bundled", path=str(PLUGIN), key="busy-router")
    assert gate_manifest(m, disabled=set(), enabled=None).action == "load"
    assert gate_manifest(m, disabled={"busy-router"}, enabled=None).action == "placeholder"


def test_without_a_decision_model_the_chat_model_decides_with_reasoning_off(monkeypatch):
    mod = _load()
    mod.register(_Ctx({}))
    monkeypatch.setattr(mod, "_read_history", lambda *a, **k: [])
    seen = {}

    def fake_call_llm(**kw):
        seen.update(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="C"))])
    import agent.auxiliary_client as aux
    monkeypatch.setattr(aux, "call_llm", fake_call_llm)
    out = asyncio.run(mod.route(_event("start a new report on GPUs"), _Gateway()))
    assert out == {"action": "rewrite", "text": "/bg start a new report on GPUs"}
    assert seen["reasoning_config"]["enabled"] is False
    assert seen["max_tokens"] <= 16


def test_a_routed_side_question_posts_no_btw_marker():
    """Routing is internal: a message busy-router turns into /btw shows only its answer, no "btw" notice."""
    mod = _load()
    ctx = _Ctx({})
    locales = {}
    ctx.register_locale = lambda lang, strings: locales.setdefault(lang, {}).update(strings)
    mod.register(ctx)
    assert locales["en"]["gateway.btw.started"] == ""
    assert "btw" not in locales["en"]["gateway.btw.answer"].lower()

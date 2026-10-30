"""G6 — cross-profile authorization isolation for the gateway (PHI port).

Upstream provenance (frozen target 4baf4269ffb1385e2317f4e872b3b8d3128a6199):
  - 2912c36aa41c2e33f3f61d16de0a3897a1e6cef1  Adolanium
      gateway/authz_mixin.py: _auth_env delegates to _platform_gate_env so a
      scoped miss under multiplex returns the default instead of os.environ.
      (The same commit's tools/bot_relay.py hunk is EXCLUDED: PHI does not
      ship bot_relay and we do not resurrect deleted components.)
  - d7e4204e77edb278508862b4e2094819c9ae180b  chelsealong
      weixin / wecom construction-time authz reads + gateway/run.py startup
      guard GATEWAY_ALLOW_ALL_USERS.
  - 7befc1d2dd76f436758aeacfb625557ecefe798c  aniruddhaadak80
      signal `_sig_secret`, yuanbao `_yb_secret`, and the live `_open_dm_opted_in`
      admission gates on weixin / yuanbao / wecom.

Behaviour pinned here (all four are real PHI gaps read out of PHI source):

  A. gateway/authz_mixin._auth_env — a scoped miss under multiplex must NOT
     fall through to os.environ. It backs _is_user_authorized's platform
     allow-all (:579), the platform/group/global allowlists (:613-619) and the
     last-chance GATEWAY_ALLOW_ALL_USERS (:703).
  B. Adapter helpers — signal._sig_secret and yuanbao._yb_secret do not exist
     in PHI at all; weixin._wx_secret and wecom._get_scoped_secret exist but
     the authorization reads bypass them with raw os.getenv.
  C. Live admission gates — weixin/yuanbao/wecom `_open_dm_opted_in` read raw
     os.getenv, so the default profile's allow-all admits a secondary profile's
     senders.
  D. gateway/run._own_policy_open_startup_violation reads GATEWAY_ALLOW_ALL_USERS
     with raw os.getenv while every adjacent read already uses the scoped
     _getenv.

Deliberate PHI deviation guarded below (PHI-G6-DEV-1): `_auth_env` keeps its
empty-name short circuit and str()/strip() coercion so a non-str scope value
cannot reach `.lower()` in the callers. Upstream's one-line delegation
inherits that from _platform_gate_env; we assert it directly so a later
upstream merge cannot silently drop it.
"""

from __future__ import annotations

import contextlib
import os

import pytest

from agent import secret_scope as ss


@contextlib.contextmanager
def _scope(secrets):
    token = ss.set_secret_scope(secrets)
    try:
        yield
    finally:
        ss.reset_secret_scope(token)


@pytest.fixture(autouse=True)
def _reset_multiplex():
    """Multiplex is a process global; never leak it between tests."""
    previous = ss.is_multiplex_active()
    try:
        yield
    finally:
        ss.set_multiplex_active(previous)


@pytest.fixture
def multiplex_on():
    ss.set_multiplex_active(True)
    yield


# ── A. authz_mixin._auth_env ─────────────────────────────────────────────


class TestAuthEnvIsolation:
    def test_scoped_value_wins(self, monkeypatch, multiplex_on):
        from gateway.authz_mixin import _auth_env

        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "111")
        with _scope({"TELEGRAM_ALLOWED_USERS": "222"}):
            assert _auth_env("TELEGRAM_ALLOWED_USERS") == "222"

    def test_scoped_miss_returns_default_not_environ(self, monkeypatch, multiplex_on):
        """The core #72348 leak: profile A's process-env allowlist and
        allow-all flags must not answer profile B's gate."""
        from gateway.authz_mixin import _auth_env

        monkeypatch.setenv("TELEGRAM_ALLOWED_USERS", "profile-A")
        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        monkeypatch.setenv("TELEGRAM_ALLOW_ALL_USERS", "true")
        with _scope({"UNRELATED": "x"}):
            assert _auth_env("TELEGRAM_ALLOWED_USERS") == ""
            assert _auth_env("GATEWAY_ALLOW_ALL_USERS") == ""
            assert _auth_env("TELEGRAM_ALLOW_ALL_USERS") == ""

    def test_single_profile_keeps_legacy_environ(self, monkeypatch):
        """No scope / multiplex off: identical to the legacy os.getenv read."""
        from gateway.authz_mixin import _auth_env

        monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "42")
        assert _auth_env("GATEWAY_ALLOWED_USERS") == "42"

    def test_scope_without_multiplex_still_overlays_environ(self, monkeypatch):
        """Multiplex OFF + scope installed is the cron-overlay contract: a
        scoped miss legitimately falls through. Pins the boundary so the fix
        cannot be over-applied into a blindfold."""
        from gateway.authz_mixin import _auth_env

        monkeypatch.setenv("GATEWAY_ALLOWED_USERS", "42")
        with _scope({"UNRELATED": "x"}):
            assert _auth_env("GATEWAY_ALLOWED_USERS") == "42"

    def test_phi_deviation_empty_name_and_coercion(self, multiplex_on):
        """PHI-G6-DEV-1: empty name short circuits, and a non-str scope value
        is coerced+stripped so callers' `.lower()` cannot explode.

        The empty-name guard is load-bearing, not cosmetic: PHI's
        ``_is_user_authorized`` calls ``_auth_env(platform_env_map.get(
        source.platform, ""))`` — an unmapped platform passes "". Without the
        short circuit a scope carrying an empty-string KEY would answer that
        lookup and be parsed as an allowlist (fail-open). Probe-verified: the
        unguarded variant returns the scope's empty-key value here."""
        from gateway.authz_mixin import _auth_env

        assert _auth_env("", "fallback") == "fallback"
        with _scope({"": "evil-empty-key"}):
            assert _auth_env("", "fallback") == "fallback"
            assert _auth_env("") == ""
        with _scope({"GATEWAY_ALLOWED_USERS": "  42  "}):
            assert _auth_env("GATEWAY_ALLOWED_USERS") == "42"


class TestIsUserAuthorizedIsolation:
    """End-to-end through the real authz entry point, not just the helper."""

    @staticmethod
    def _runner():
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, MagicMock

        from gateway.config import GatewayConfig, Platform
        from gateway.run import GatewayRunner

        runner = object.__new__(GatewayRunner)
        runner.config = GatewayConfig(multiplex_profiles=True)
        secondary = SimpleNamespace(
            send=AsyncMock(),
            enforces_own_access_policy=False,
            _dm_policy="allowlist",
            _group_policy="pairing",
        )
        runner.adapters = {Platform.QQBOT: secondary}
        runner._profile_adapters = {}
        runner.pairing_store = MagicMock()
        runner.pairing_store.is_approved.return_value = False
        return runner

    @staticmethod
    def _dm_source():
        from gateway.config import Platform
        from gateway.session import SessionSource

        return SessionSource(
            platform=Platform.QQBOT,
            user_id="user-1",
            chat_id="dm-chat",
            chat_type="dm",
        )

    def test_scope_miss_does_not_inherit_environ_allowlist(
        self, monkeypatch, multiplex_on
    ):
        monkeypatch.setenv("QQ_ALLOWED_USERS", "user-1")
        runner = self._runner()
        with _scope({}):
            assert runner._is_user_authorized(self._dm_source()) is False

    def test_scope_miss_does_not_inherit_gateway_allow_all(
        self, monkeypatch, multiplex_on
    ):
        """GATEWAY_ALLOW_ALL_USERS is the last-chance fail-open flag."""
        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        runner = self._runner()
        with _scope({}):
            assert runner._is_user_authorized(self._dm_source()) is False

    def test_scoped_allowlist_still_admits_its_own_sender(
        self, monkeypatch, multiplex_on
    ):
        """Not-too-wide: the fix must not deny a profile its OWN allowlist."""
        monkeypatch.setenv("QQ_ALLOWED_USERS", "")
        runner = self._runner()
        with _scope({"QQ_ALLOWED_USERS": "user-1"}):
            assert runner._is_user_authorized(self._dm_source()) is True


# ── B. adapter scoped helpers ────────────────────────────────────────────

_HELPERS = [
    ("plugins.platforms.weixin.adapter", "_wx_secret", "WEIXIN_ALLOWED_USERS"),
    ("plugins.platforms.yuanbao.adapter", "_yb_secret", "YUANBAO_DM_POLICY"),
    ("plugins.platforms.signal.adapter", "_sig_secret", "SIGNAL_ALLOWED_USERS"),
    ("plugins.platforms.wecom.adapter", "_get_scoped_secret", "WECOM_ALLOWED_USERS"),
]


def _helper(module_path, name):
    module = __import__(module_path, fromlist=[name])
    return getattr(module, name)


@pytest.mark.parametrize("module_path,helper_name,var", _HELPERS)
def test_helper_reads_profile_scope_first(module_path, helper_name, var, monkeypatch):
    monkeypatch.setenv(var, "FROM-DEFAULT-ENV")
    helper = _helper(module_path, helper_name)
    with _scope({var: "from-profile-scope"}):
        assert helper(var, "") == "from-profile-scope"


@pytest.mark.parametrize("module_path,helper_name", [(m, h) for m, h, _ in _HELPERS])
def test_helper_does_not_leak_default_env_into_scoped_miss(
    module_path, helper_name, monkeypatch, multiplex_on
):
    monkeypatch.setenv("WEIXIN_ALLOW_ALL_USERS", "true")
    monkeypatch.setenv("YUANBAO_ALLOW_ALL_USERS", "true")
    monkeypatch.setenv("SIGNAL_ALLOWED_USERS", "*")
    monkeypatch.setenv("WECOM_ALLOW_ALL_USERS", "true")
    helper = _helper(module_path, helper_name)
    with _scope({}):
        assert helper("WEIXIN_ALLOW_ALL_USERS", "") == ""
        assert helper("YUANBAO_ALLOW_ALL_USERS", "") == ""
        assert helper("WECOM_ALLOW_ALL_USERS", "") == ""
        assert helper("SIGNAL_ALLOWED_USERS", "restricted-default") == "restricted-default"


@pytest.mark.parametrize("module_path,helper_name,var", _HELPERS)
def test_helper_falls_back_to_environ_without_scope(
    module_path, helper_name, var, monkeypatch
):
    """Single-profile deployments keep os.environ authoritative."""
    monkeypatch.setenv(var, "legacy-env-value")
    helper = _helper(module_path, helper_name)
    assert helper(var, "") == "legacy-env-value"


@pytest.mark.parametrize("module_path,helper_name,var", _HELPERS)
def test_helper_unscoped_under_multiplex_does_not_raise(
    module_path, helper_name, var, monkeypatch, multiplex_on
):
    """The DEFAULT profile constructs its adapters UNSCOPED while the
    multiplexer is active; a bare get_secret would raise UnscopedSecretError
    and crash that adapter's startup. Every helper must absorb it."""
    monkeypatch.setenv(var, "default-profile-value")
    helper = _helper(module_path, helper_name)
    assert helper(var, "") == "default-profile-value"


# ── C. live admission gates ──────────────────────────────────────────────


class TestOpenDmGates:
    def test_weixin_gate_ignores_default_env_under_scope(
        self, monkeypatch, multiplex_on
    ):
        from plugins.platforms.weixin.adapter import WeixinAdapter

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        monkeypatch.setenv("WEIXIN_ALLOW_ALL_USERS", "true")
        adapter = WeixinAdapter.__new__(WeixinAdapter)
        with _scope({}):
            assert adapter._open_dm_opted_in() is False

    def test_weixin_gate_honors_scoped_opt_in(self, multiplex_on):
        """Not-too-narrow: a profile that DID opt in must still open."""
        from plugins.platforms.weixin.adapter import WeixinAdapter

        adapter = WeixinAdapter.__new__(WeixinAdapter)
        with _scope({"WEIXIN_ALLOW_ALL_USERS": "yes"}):
            assert adapter._open_dm_opted_in() is True

    def test_yuanbao_gate_ignores_default_env_under_scope(
        self, monkeypatch, multiplex_on
    ):
        from plugins.platforms.yuanbao.adapter import AccessPolicy

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        monkeypatch.setenv("YUANBAO_ALLOW_ALL_USERS", "true")
        policy = AccessPolicy(
            dm_policy="open", dm_allow_from=[], group_policy="pairing",
            group_allow_from=[],
        )
        with _scope({}):
            assert policy._open_dm_opted_in() is False

    def test_yuanbao_gate_honors_scoped_opt_in(self, multiplex_on):
        from plugins.platforms.yuanbao.adapter import AccessPolicy

        policy = AccessPolicy(
            dm_policy="open", dm_allow_from=[], group_policy="pairing",
            group_allow_from=[],
        )
        with _scope({"GATEWAY_ALLOW_ALL_USERS": "true"}):
            assert policy._open_dm_opted_in() is True

    def test_wecom_gate_ignores_default_env_under_scope(
        self, monkeypatch, multiplex_on
    ):
        from plugins.platforms.wecom.adapter import WeComAdapter

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        monkeypatch.setenv("WECOM_ALLOW_ALL_USERS", "true")
        adapter = WeComAdapter.__new__(WeComAdapter)
        with _scope({}):
            assert adapter._open_dm_opted_in() is False

    def test_wecom_gate_honors_scoped_opt_in(self, multiplex_on):
        from plugins.platforms.wecom.adapter import WeComAdapter

        adapter = WeComAdapter.__new__(WeComAdapter)
        with _scope({"WECOM_ALLOW_ALL_USERS": "true"}):
            assert adapter._open_dm_opted_in() is True

    def test_gates_unscoped_single_profile_keep_environ(self, monkeypatch):
        """Multiplex off, no scope: the legacy env opt-in still opens."""
        from plugins.platforms.weixin.adapter import WeixinAdapter
        from plugins.platforms.wecom.adapter import WeComAdapter
        from plugins.platforms.yuanbao.adapter import AccessPolicy

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        assert WeixinAdapter.__new__(WeixinAdapter)._open_dm_opted_in() is True
        assert WeComAdapter.__new__(WeComAdapter)._open_dm_opted_in() is True
        assert AccessPolicy(
            dm_policy="open", dm_allow_from=[], group_policy="pairing",
            group_allow_from=[],
        )._open_dm_opted_in() is True


# ── C2. construction-time authorization reads ────────────────────────────


class TestScopedConstruction:
    def test_wecom_construction_reads_scope_not_environ(
        self, monkeypatch, multiplex_on
    ):
        from gateway.config import PlatformConfig
        from plugins.platforms.wecom.adapter import WeComAdapter

        monkeypatch.setenv("WECOM_DM_POLICY", "pairing")
        monkeypatch.setenv("WECOM_ALLOWED_USERS", "default-user")
        with _scope(
            {"WECOM_DM_POLICY": "allowlist", "WECOM_ALLOWED_USERS": "scoped-user"}
        ):
            adapter = WeComAdapter(PlatformConfig(enabled=True))
        assert adapter._dm_policy == "allowlist"
        assert adapter._allow_from == ["scoped-user"]

    def test_wecom_scoped_miss_does_not_admit_default_allowlist(
        self, monkeypatch, multiplex_on
    ):
        from gateway.config import PlatformConfig
        from plugins.platforms.wecom.adapter import WeComAdapter

        monkeypatch.setenv("WECOM_DM_POLICY", "allowlist")
        monkeypatch.setenv("WECOM_ALLOWED_USERS", "default-user")
        with _scope({"SOMETHING_ELSE": "x"}):
            adapter = WeComAdapter(PlatformConfig(enabled=True))
        assert adapter._dm_policy == "pairing"
        assert adapter._allow_from == []

    def test_signal_construction_reads_scope_not_environ(
        self, monkeypatch, multiplex_on
    ):
        from gateway.config import PlatformConfig
        from plugins.platforms.signal.adapter import SignalAdapter

        monkeypatch.setenv("SIGNAL_ALLOWED_USERS", "default-user")
        monkeypatch.setenv("SIGNAL_GROUP_ALLOWED_USERS", "default-group-user")
        with _scope(
            {
                "SIGNAL_ALLOWED_USERS": "scoped-user",
                "SIGNAL_GROUP_ALLOWED_USERS": "scoped-group-user",
            }
        ):
            adapter = SignalAdapter(PlatformConfig(enabled=True))
        assert adapter.dm_allow_from == {"scoped-user"}
        assert adapter.group_allow_from == {"scoped-group-user"}

    def test_signal_scoped_miss_does_not_inherit_default_allowlist(
        self, monkeypatch, multiplex_on
    ):
        from gateway.config import PlatformConfig
        from plugins.platforms.signal.adapter import SignalAdapter

        monkeypatch.setenv("SIGNAL_GROUP_ALLOWED_USERS", "default-group-user")
        with _scope({"SOMETHING_ELSE": "x"}):
            adapter = SignalAdapter(PlatformConfig(enabled=True))
        assert adapter.group_allow_from == set()

    def test_weixin_construction_reads_scope_not_environ(
        self, monkeypatch, multiplex_on
    ):
        from gateway.config import PlatformConfig
        from plugins.platforms.weixin.adapter import WeixinAdapter

        monkeypatch.setenv("WEIXIN_DM_POLICY", "pairing")
        monkeypatch.setenv("WEIXIN_ALLOWED_USERS", "default-user")
        with _scope(
            {"WEIXIN_DM_POLICY": "allowlist", "WEIXIN_ALLOWED_USERS": "scoped-user"}
        ):
            adapter = WeixinAdapter(PlatformConfig(enabled=True))
        assert adapter._dm_policy == "allowlist"
        assert adapter._allow_from == ["scoped-user"]

    def test_yuanbao_construction_reads_scope_not_environ(
        self, monkeypatch, multiplex_on
    ):
        """Drive the REAL YuanbaoAdapter.__init__ and assert through the
        AccessPolicy it actually installs — reconstructing the helper calls
        in the test would not catch a reverted adapter read."""
        from gateway.config import PlatformConfig
        from plugins.platforms.yuanbao.adapter import YuanbaoAdapter

        monkeypatch.setenv("YUANBAO_DM_POLICY", "allowlist")
        monkeypatch.setenv("YUANBAO_DM_ALLOW_FROM", "default-user")
        monkeypatch.setenv("YUANBAO_GROUP_ALLOW_FROM", "default-group-user")
        cfg = PlatformConfig(
            extra={
                "app_id": "k",
                "app_secret": "s",
                "ws_url": "wss://test.example.com/ws",
                "api_domain": "https://test.example.com",
            }
        )
        with _scope(
            {
                "YUANBAO_DM_POLICY": "allowlist",
                "YUANBAO_DM_ALLOW_FROM": "scoped-user",
                "YUANBAO_GROUP_ALLOW_FROM": "scoped-group-user",
            }
        ):
            adapter = YuanbaoAdapter(cfg)
        policy = adapter._access_policy
        assert policy.is_dm_allowed("scoped-user") is True
        assert policy.is_dm_allowed("default-user") is False
        assert policy._group_allow_from == ["scoped-group-user"]

    def test_yuanbao_scoped_miss_does_not_inherit_default_allowlist(
        self, monkeypatch, multiplex_on
    ):
        """Scoped miss: the default profile's allowlist must not admit, and
        the policy default must stay 'pairing' rather than the env value."""
        from gateway.config import PlatformConfig
        from plugins.platforms.yuanbao.adapter import YuanbaoAdapter

        monkeypatch.setenv("YUANBAO_DM_POLICY", "open")
        monkeypatch.setenv("YUANBAO_DM_ALLOW_FROM", "default-user")
        cfg = PlatformConfig(
            extra={
                "app_id": "k",
                "app_secret": "s",
                "ws_url": "wss://test.example.com/ws",
                "api_domain": "https://test.example.com",
            }
        )
        with _scope({"SOMETHING_ELSE": "x"}):
            adapter = YuanbaoAdapter(cfg)
        policy = adapter._access_policy
        assert policy._dm_policy == "pairing"
        assert policy.is_dm_allowed("default-user") is False
        assert policy.is_dm_allowed("unapproved-user") is False

    def test_yuanbao_empty_scope_value_falls_back_to_pairing(
        self, monkeypatch, multiplex_on
    ):
        """PHI-G6-DEV-3: the 'pairing' default sits OUTSIDE the helper call,
        so an empty-STRING scope value still yields 'pairing'. Passing the
        default into _yb_secret instead would store '' and make the policy
        comparison fall through to a non-default branch."""
        from gateway.config import PlatformConfig
        from plugins.platforms.yuanbao.adapter import YuanbaoAdapter

        cfg = PlatformConfig(
            extra={
                "app_id": "k",
                "app_secret": "s",
                "ws_url": "wss://test.example.com/ws",
                "api_domain": "https://test.example.com",
            }
        )
        with _scope({"YUANBAO_DM_POLICY": "", "YUANBAO_GROUP_POLICY": ""}):
            adapter = YuanbaoAdapter(cfg)
        assert adapter._access_policy._dm_policy == "pairing"
        assert adapter._access_policy._group_policy == "pairing"


# ── D. startup guard ─────────────────────────────────────────────────────


class TestStartupGuard:
    @staticmethod
    def _cfg():
        from gateway.config import GatewayConfig, Platform, PlatformConfig

        cfg = GatewayConfig(multiplex_profiles=True)
        cfg.platforms = {
            Platform.WECOM: PlatformConfig(enabled=True, extra={"dm_policy": "open"}),
        }
        return cfg

    def test_default_env_opt_in_does_not_satisfy_scoped_profile(
        self, monkeypatch, multiplex_on
    ):
        from gateway.run import _own_policy_open_startup_violation

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        with _scope({"SOMETHING_ELSE": "x"}):
            violation = _own_policy_open_startup_violation(self._cfg())
        assert violation is not None
        assert "wecom" in violation.lower()

    def test_scoped_opt_in_is_honored(self, monkeypatch, multiplex_on):
        from gateway.run import _own_policy_open_startup_violation

        monkeypatch.delenv("GATEWAY_ALLOW_ALL_USERS", raising=False)
        with _scope({"GATEWAY_ALLOW_ALL_USERS": "true"}):
            assert _own_policy_open_startup_violation(self._cfg()) is None

    def test_single_profile_env_opt_in_still_passes(self, monkeypatch):
        """No scope, multiplex off: legacy env opt-in must keep working —
        otherwise the fix turns into a startup-abort regression."""
        from gateway.run import _own_policy_open_startup_violation

        monkeypatch.setenv("GATEWAY_ALLOW_ALL_USERS", "true")
        assert _own_policy_open_startup_violation(self._cfg()) is None

"""Model and adapter proxy parity from the frozen upstream main fixes."""

import pytest

from agent.process_bootstrap import _get_proxy_for_base_url
from agent.proxy_bypass import should_bypass_proxy
from gateway.platforms.base import is_host_excluded_by_no_proxy, resolve_proxy_url


@pytest.fixture
def proxy_env(monkeypatch):
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy", "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp:3128")
    monkeypatch.setattr("gateway.platforms.base.gateway_trust_env", lambda: True)
    monkeypatch.setattr("gateway.platforms.base._detect_macos_system_proxy", lambda: None)
    return monkeypatch


@pytest.mark.parametrize("no_proxy, host", [
    ("10.0.0.0/8", "10.1.2.3"),
    ("*.internal", "svc.internal"),
    ("*.slack.com", "slack.com"),
    (".slack.com", "slack.com"),
    ("localhost,.corp.example", "llm.corp.example"),
    ("api.example.com:8443", "api.example.com:8443"),
])
def test_llm_and_adapter_bypass_the_same_entries(proxy_env, no_proxy, host):
    proxy_env.setenv("NO_PROXY", no_proxy)
    assert should_bypass_proxy(host)
    assert _get_proxy_for_base_url(f"https://{host}/v1") is None
    assert resolve_proxy_url(target_hosts=host) is None


def test_unmatched_hosts_and_ports_keep_proxy(proxy_env):
    proxy_env.setenv("NO_PROXY", "10.0.0.0/8,*.internal,api.example.com:8443")
    for host in ("api.openai.com", "api.example.com:443", "notinternal"):
        assert _get_proxy_for_base_url(f"https://{host}/v1") == "http://proxy.corp:3128"
        assert resolve_proxy_url(target_hosts=host) == "http://proxy.corp:3128"
    assert not is_host_excluded_by_no_proxy("slack.com")
    assert is_host_excluded_by_no_proxy("files.slack.com", "slack.com")
    assert not should_bypass_proxy("notslack.com", no_proxy_value="*.slack.com")


def test_invalid_port_does_not_raise_or_drop_proxy(proxy_env):
    proxy_env.setenv("NO_PROXY", "other.example")
    for port in ("notaport", "99999"):
        assert _get_proxy_for_base_url(f"http://host:{port}/v1") == "http://proxy.corp:3128"
    proxy_env.setenv("NO_PROXY", "host")
    assert _get_proxy_for_base_url("http://host:notaport/v1") is None
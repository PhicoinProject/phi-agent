"""Direct HTTPS on the `phi dashboard` listener (dashboard.tls / --tls-*).

Browsers only open the microphone on a secure origin, so a dashboard reached from another device
needs https: the cert/key pair must reach uvicorn, a self-signed pair is created once and reused,
and every URL printed or opened for this listener must say https.
"""
import contextlib
import hashlib
import json
import os
import ssl
import stat
import sys
import threading
import time
import types
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gateway import host_rendezvous as hr
from phi_cli import dashboard_tls, main_dashboard, web_server, web_server_lifecycle
from phi_cli.dashboard_tls import (
    DashboardTLS,
    DashboardTLSError,
    ensure_self_signed_cert,
    resolve_dashboard_tls,
    san_names,
    trust_for_node_child,
    uvicorn_ssl_kwargs,
)
from tests.phi_cli.test_ipv6_url_authorities import _stub_uvicorn

x509 = pytest.importorskip("cryptography.x509")


@pytest.fixture(autouse=True)
def _restore_app_state(monkeypatch):
    """start_server stores the TLS choice on the shared app; never leak it into other tests."""
    monkeypatch.setattr(web_server.app.state, "dashboard_tls", None, raising=False)


@pytest.fixture(params=["cryptography", "openssl"])
def backend(request, monkeypatch):
    if request.param == "openssl":
        from phi_platform.resolver import locate_command

        if not locate_command("openssl").command:
            pytest.skip("openssl CLI not installed")
        monkeypatch.setattr(dashboard_tls, "_cryptography_available", lambda: False)
    return request.param


@pytest.fixture
def tls(tmp_path):
    cert, key = ensure_self_signed_cert(tmp_path / "pair", san_names("127.0.0.1"))
    return DashboardTLS(str(cert), str(key), self_signed=True)


def _load(cert_file):
    return x509.load_pem_x509_certificate(Path(cert_file).read_bytes())


def _sans(cert_file):
    san = _load(cert_file).extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    return set(san.get_values_for_type(x509.DNSName)), {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}


def _fingerprint(cert_file):
    return hashlib.sha256(Path(cert_file).read_bytes()).hexdigest()


# ── config → uvicorn ──────────────────────────────────────────────────────


def test_build_uvicorn_server_passes_the_pair_and_plain_http_passes_none(monkeypatch, tls):
    captured = _stub_uvicorn(monkeypatch)
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)

    web_server._build_uvicorn_server("127.0.0.1", 9119, tls=tls)
    assert captured["ssl_certfile"] == tls.cert_file
    assert captured["ssl_keyfile"] == tls.key_file

    captured.clear()
    web_server._build_uvicorn_server("127.0.0.1", 9119)
    assert "ssl_certfile" not in captured and "ssl_keyfile" not in captured
    assert uvicorn_ssl_kwargs(None) == {}


def test_tls_is_off_by_default(tmp_path):
    from phi_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["dashboard"]["tls"] == {
        "cert_file": "", "key_file": "", "self_signed": False, "hosts": []}
    assert resolve_dashboard_tls(DEFAULT_CONFIG["dashboard"], "0.0.0.0", home=tmp_path) is None
    assert resolve_dashboard_tls({}, "127.0.0.1", home=tmp_path) is None
    assert not (tmp_path / "dashboard_tls").exists()


def test_config_pair_is_used_and_cli_flags_win(tmp_path):
    own_cert, own_key = ensure_self_signed_cert(tmp_path / "own", ["localhost"])
    cfg = {"tls": {"cert_file": str(own_cert), "key_file": str(own_key)}}

    from_cfg = resolve_dashboard_tls(cfg, "127.0.0.1", home=tmp_path)
    assert from_cfg == DashboardTLS(str(own_cert), str(own_key), self_signed=False)

    # --tls-self-signed beats configured files (even broken ones).
    broken = {"tls": {"cert_file": str(tmp_path / "missing.pem"), "key_file": str(tmp_path / "missing.key")}}
    flagged = resolve_dashboard_tls(broken, "127.0.0.1", self_signed=True, home=tmp_path)
    assert flagged.self_signed and Path(flagged.cert_file) == tmp_path / "dashboard_tls" / "cert.pem"

    # --tls-cert/--tls-key beat config self_signed, which is then never generated.
    other = tmp_path / "other"
    pair = resolve_dashboard_tls(
        {"tls": {"self_signed": "true"}}, "127.0.0.1",
        cert_file=str(own_cert), key_file=str(own_key), home=other)
    assert pair == DashboardTLS(str(own_cert), str(own_key))
    assert not (other / "dashboard_tls").exists()


def test_half_pair_missing_file_or_mismatched_key_is_a_clear_error(tmp_path):
    cert_a, key_a = ensure_self_signed_cert(tmp_path / "a", ["localhost"])
    _cert_b, key_b = ensure_self_signed_cert(tmp_path / "b", ["localhost"])

    with pytest.raises(DashboardTLSError, match="both"):
        resolve_dashboard_tls({}, "127.0.0.1", cert_file=str(cert_a), home=tmp_path)
    with pytest.raises(DashboardTLSError, match="does not exist"):
        resolve_dashboard_tls(
            {}, "127.0.0.1", cert_file=str(tmp_path / "nope.pem"), key_file=str(key_a), home=tmp_path)
    with pytest.raises(DashboardTLSError, match="cannot load"):
        resolve_dashboard_tls({}, "127.0.0.1", cert_file=str(cert_a), key_file=str(key_b), home=tmp_path)


# ── self-signed ───────────────────────────────────────────────────────────


def test_self_signed_covers_configured_hosts_and_is_reused(tmp_path, backend):
    cfg = {"tls": {"self_signed": True, "hosts": ["phi.example.test", "198.51.100.7"]}}

    first = resolve_dashboard_tls(cfg, "192.0.2.10", home=tmp_path)

    assert first.self_signed
    assert Path(first.cert_file) == tmp_path / "dashboard_tls" / "cert.pem"
    assert Path(first.key_file) == tmp_path / "dashboard_tls" / "key.pem"
    dns, ips = _sans(first.cert_file)
    assert {"localhost", "phi.example.test"} <= dns
    assert {"127.0.0.1", "192.0.2.10", "198.51.100.7"} <= ips
    cert = _load(first.cert_file)
    assert cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is False
    life = cert.not_valid_after_utc - cert.not_valid_before_utc
    assert timedelta(days=825) <= life <= timedelta(days=825, minutes=10)
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(first.key_file).st_mode) == 0o600

    fingerprint = _fingerprint(first.cert_file)
    second = resolve_dashboard_tls(cfg, "192.0.2.10", home=tmp_path)
    assert second == first
    assert _fingerprint(second.cert_file) == fingerprint


def test_wildcard_bind_is_not_a_san_and_names_are_normalised():
    assert san_names("0.0.0.0") == ["localhost", "127.0.0.1"]
    assert san_names("::") == ["localhost", "127.0.0.1"]
    assert san_names("[::1]", ["Phi.Example.Test", "localhost"]) == [
        "localhost", "127.0.0.1", "::1", "phi.example.test"]
    with pytest.raises(DashboardTLSError):
        san_names("127.0.0.1", ["bad host\nDNS:evil.example.test"])


def test_expired_or_narrower_cert_is_regenerated(tmp_path, backend):
    names = ["localhost", "127.0.0.1"]
    cert, _key = ensure_self_signed_cert(tmp_path, names)
    original = _fingerprint(cert)

    ensure_self_signed_cert(tmp_path, names, now=datetime.now(UTC) + timedelta(days=824))
    assert _fingerprint(cert) == original

    ensure_self_signed_cert(tmp_path, names, now=datetime.now(UTC) + timedelta(days=826))
    renewed = _fingerprint(cert)
    assert renewed != original

    ensure_self_signed_cert(tmp_path, [*names, "phi.example.test"])
    assert _fingerprint(cert) != renewed
    assert "phi.example.test" in _sans(cert)[0]


def test_no_cryptography_and_no_openssl_fails_clearly(tmp_path, monkeypatch):
    import phi_platform.resolver as resolver

    monkeypatch.setattr(dashboard_tls, "_cryptography_available", lambda: False)
    monkeypatch.setattr(resolver, "locate_command", lambda _name: types.SimpleNamespace(command=()))

    with pytest.raises(DashboardTLSError, match="cryptography.*openssl"):
        resolve_dashboard_tls({"tls": {"self_signed": True}}, "127.0.0.1", home=tmp_path)
    assert not (tmp_path / "dashboard_tls" / "cert.pem").exists()


# ── https everywhere the URL appears ──────────────────────────────────────


def _launch(monkeypatch, capsys, tmp_path, tls):
    """Run start_server against a stub uvicorn; return (console text, URLs the browser got)."""
    captured = _stub_uvicorn(monkeypatch)
    monkeypatch.setenv("PHI_GATEWAY_LOCK_DIR", str(tmp_path / "locks"))
    calls = []
    monkeypatch.setattr(web_server, "_maybe_open_browser", lambda *a, **kw: calls.append((a, kw)))
    try:
        web_server.start_server(host="127.0.0.1", port=9119, open_browser=True, tls=tls)
        record = hr.read_record(hr.ROLE_SERVE, include_stale=True)
    finally:
        hr.release_host_lock(hr.ROLE_SERVE)
    io = capsys.readouterr()

    import webbrowser

    opened = []

    class _ImmediateThread:
        def __init__(self, *, target, daemon):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(web_server_lifecycle.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(web_server_lifecycle.time, "sleep", lambda _s: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setenv("DISPLAY", ":0")
    for args, kwargs in calls:
        web_server_lifecycle._maybe_open_browser(*args, **kwargs)
    return io.out + io.err, opened, captured, record


def _assert_https_everywhere(console, opened):
    assert "Phi Web UI → https://127.0.0.1:9119" in console
    assert "http://" not in console
    assert opened == ["https://127.0.0.1:9119"]


def test_banner_browser_and_host_record_say_https(monkeypatch, capsys, tmp_path, tls):
    console, opened, captured, record = _launch(monkeypatch, capsys, tmp_path, tls)

    _assert_https_everywhere(console, opened)
    assert captured["ssl_certfile"] == tls.cert_file
    assert record is not None and record.scheme == "https"


def test_wrong_variant_printing_http_with_tls_on_is_rejected(monkeypatch, capsys, tmp_path, tls):
    """Negative control: a listener that serves TLS but advertises http:// must fail the contract."""
    monkeypatch.setattr(web_server, "dashboard_url_scheme", lambda _tls: "http")
    console, opened, _captured, _record = _launch(monkeypatch, capsys, tmp_path, tls)

    with pytest.raises(AssertionError):
        _assert_https_everywhere(console, opened)


def test_plain_listener_still_says_http(monkeypatch, capsys, tmp_path):
    console, opened, captured, record = _launch(monkeypatch, capsys, tmp_path, None)

    assert "Phi Web UI → http://127.0.0.1:9119" in console
    assert opened == ["http://127.0.0.1:9119"]
    assert "ssl_certfile" not in captured
    assert record is not None and record.scheme == "http"


def test_host_record_scheme_round_trips_and_old_records_are_http():
    record = hr.HostRecord(
        role=hr.ROLE_SERVE, pid=4242, create_time=None, host="127.0.0.1", port=9119,
        protocol_version=hr.HOST_PROTOCOL_VERSION, token_fingerprint="", profiles=(),
        updated_at="", scheme="https")
    payload = record.to_json()
    back = hr.HostRecord.from_json(payload)
    assert back.scheme == "https" and hr.dial_scheme(back) == "https"
    assert isinstance(hr.dial_urlopen_kwargs(back)["context"], ssl.SSLContext)

    payload.pop("scheme")
    assert hr.HostRecord.from_json(payload).scheme == "http"
    payload["scheme"] = "javascript"
    legacy = hr.HostRecord.from_json(payload)
    assert legacy.scheme == "http" and hr.dial_urlopen_kwargs(legacy) == {}


def test_attach_opens_the_https_url_of_a_tls_dashboard(monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    record = types.SimpleNamespace(host="127.0.0.1", port=9119, pid=4242, role="dashboard", scheme="https")
    monkeypatch.setattr(main_dashboard, "_host_backend_attachment", lambda: record)
    monkeypatch.setattr(main_dashboard, "_is_desktop_owned_backend", lambda: False)
    monkeypatch.setattr(main_dashboard, "_explicit_endpoint_flags", lambda: set())
    monkeypatch.setattr(hr, "probe_owner", lambda _r: {"servesSpa": True, "pid": 4242})
    monkeypatch.setattr("phi_cli.profiles.get_active_profile_name", lambda: "worker_x")

    args = types.SimpleNamespace(host="127.0.0.1", port=9119, no_open=False, isolated=False, open_profile="")
    with pytest.raises(SystemExit) as exc:
        main_dashboard._attach_to_host_backend(args, headless_backend=False)

    assert exc.value.code == 0
    assert opened == ["https://127.0.0.1:9119/?profile=worker_x"]


def test_embedded_chat_dials_back_over_wss_and_trusts_the_cert(monkeypatch, tmp_path, tls):
    from phi_cli import web_server_chat

    state = web_server.app.state
    monkeypatch.setattr(state, "bound_host", "127.0.0.1", raising=False)
    monkeypatch.setattr(state, "bound_port", 9119, raising=False)
    monkeypatch.setattr(state, "auth_required", False, raising=False)
    monkeypatch.delenv("PHI_DASHBOARD_WS_HOST", raising=False)

    monkeypatch.setattr(state, "dashboard_tls", tls)
    assert web_server_chat._build_gateway_ws_url().startswith("wss://127.0.0.1:9119/api/ws?")
    monkeypatch.setattr(state, "dashboard_tls", None)
    assert web_server_chat._build_gateway_ws_url().startswith("ws://127.0.0.1:9119/api/ws?")

    env = {}
    trust_for_node_child(env, tls, directory=tmp_path / "ca")
    assert env["NODE_EXTRA_CA_CERTS"] == tls.cert_file

    corp = tmp_path / "corp.pem"
    corp.write_text("-----BEGIN CERTIFICATE-----\nQUFBQQ==\n-----END CERTIFICATE-----\n")
    env = {"NODE_EXTRA_CA_CERTS": str(corp)}
    trust_for_node_child(env, tls, directory=tmp_path / "ca")
    bundle = Path(env["NODE_EXTRA_CA_CERTS"]).read_text()
    assert "QUFBQQ==" in bundle and Path(tls.cert_file).read_text().strip() in bundle

    env = {}
    trust_for_node_child(env, None)
    assert env == {}


# ── end to end over a real socket ─────────────────────────────────────────


@contextlib.contextmanager
def _serving(server):
    """Run a built uvicorn server in a thread on its ephemeral port; yield the port."""
    server.config.lifespan = "off"
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 30
        while not server.started:
            assert thread.is_alive() and time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.05)
        yield server.servers[0].sockets[0].getsockname()[1]
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def _get(url, context):
    try:
        with urllib.request.urlopen(url, context=context, timeout=10) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers


def test_dashboard_serves_https_with_a_verifiable_cert(monkeypatch, tls):
    monkeypatch.setattr(web_server.app.state, "auth_required", False, raising=False)
    monkeypatch.setattr(web_server.app.state, "bound_host", "127.0.0.1", raising=False)
    _config, server = web_server._build_uvicorn_server("127.0.0.1", 0, tls=tls)

    with _serving(server) as port:
        verified = ssl.create_default_context(cafile=tls.cert_file)
        status, body, _headers = _get(f"https://127.0.0.1:{port}/api/health", verified)
        assert status == 200 and json.loads(body)["ok"] is True

        with pytest.raises(urllib.error.URLError) as exc:
            urllib.request.urlopen(
                f"https://127.0.0.1:{port}/api/health", context=ssl.create_default_context(), timeout=10)
        assert isinstance(exc.value.reason, ssl.SSLCertVerificationError)

        status, _body, _headers = _get(f"https://127.0.0.1:{port}/", verified)
        assert status == (200 if (web_server.WEB_DIST / "index.html").is_file() else 404)


def test_auth_cookies_get_secure_only_over_https(tls):
    import uvicorn
    from fastapi import FastAPI, Request, Response
    from phi_cli.dashboard_auth import cookies

    mini = FastAPI()

    @mini.get("/set")
    async def _set(request: Request):
        response = Response("ok")
        cookies.set_sso_attempt_cookie(response, use_https=cookies.detect_https(request))
        return response

    def set_cookie(tls_choice):
        config = uvicorn.Config(
            mini, host="127.0.0.1", port=0, log_level="warning", log_config=None,
            **uvicorn_ssl_kwargs(tls_choice))
        with _serving(uvicorn.Server(config)) as port:
            scheme = "https" if tls_choice else "http"
            context = ssl.create_default_context(cafile=tls.cert_file) if tls_choice else None
            status, _body, headers = _get(f"{scheme}://127.0.0.1:{port}/set", context)
        assert status == 200
        return headers.get("set-cookie", "")

    over_https = set_cookie(tls)
    assert over_https.startswith(f"__Host-{cookies.SSO_ATTEMPT_COOKIE}=")
    assert "secure" in over_https.lower()

    over_http = set_cookie(None)
    assert over_http.startswith(f"{cookies.SSO_ATTEMPT_COOKIE}=")
    assert "secure" not in over_http.lower()

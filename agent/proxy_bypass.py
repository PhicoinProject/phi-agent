"""Shared NO_PROXY matching for model transports and gateway adapters."""

from __future__ import annotations

import ipaddress
import os
import re
from urllib.parse import urlsplit

PROXY_ENV_KEYS = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy")


def first_proxy_env_value() -> str:
    return next((value for key in PROXY_ENV_KEYS if (value := (os.environ.get(key) or "").strip())), "")


def split_host_port(value: str) -> tuple[str, int | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", None
    if "://" in raw or raw.startswith("//"):
        parsed = urlsplit(raw)
        host = parsed.hostname or ""
        try:
            port = parsed.port
        except ValueError:
            port = None
    elif raw.startswith("[") and "]" in raw:
        host, _, rest = raw[1:].partition("]")
        port = int(rest[1:]) if rest.startswith(":") and rest[1:].isdigit() else None
    elif raw.count(":") == 1 and raw.rpartition(":")[2].isdigit():
        host, _, port_text = raw.rpartition(":")
        port = int(port_text)
    else:
        host, port = raw.strip("[]"), None
    return host.lower().rstrip("."), port


def no_proxy_entries(no_proxy_value: str | None = None) -> list[str]:
    if no_proxy_value is None:
        no_proxy_value = ",".join(os.environ.get(key, "") for key in ("NO_PROXY", "no_proxy"))
    return [part for part in re.split(r"[\s,]+", no_proxy_value.strip()) if part]


# Loopback must never be dialed through a proxy. ``websockets>=14`` connects with
# ``proxy=True`` and resolves it via ``urllib.request.getproxies()`` — on macOS that reads the
# *system* proxy (``_scproxy``) even with no ``*_proxy`` env vars — so a local CDP endpoint
# (``ws://127.0.0.1:<port>/devtools/...``) is dialed through the proxy and the handshake dies
# with "did not receive a valid HTTP response" (#110565). ``urllib``'s bypass check honours
# NO_PROXY in both casings, so children get the entries appended; in-process dials pass
# ``proxy=None`` when the host is loopback.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def is_loopback_host(host: str | None) -> bool:
    """True for a host that must always bypass a proxy: ``localhost`` or any loopback IP literal
    (``127.x.x.x``, ``::1``, ``::ffff:127.0.0.1``)."""
    host = str(host or "").strip().lower().strip("[]")
    ip = _ip_or_none(host)
    return host == "localhost" or (ip is not None and ip.is_loopback)


def loopback_connect_kwargs(url: str) -> dict:
    """``websockets.connect`` kwargs for an in-process dial: ``{"proxy": None}`` when ``url``
    targets loopback (skip the library's system-proxy auto-detection), else ``{}`` so remote
    endpoints keep the default proxy behaviour."""
    return {"proxy": None} if is_loopback_host(split_host_port(url)[0]) else {}


def loopback_request_kwargs(url: str) -> dict:
    """``requests.get`` kwargs for an in-process HTTP dial (CDP ``/json/version`` discovery /
    readiness): ``{"proxies": {"http": None, "https": None}}`` when ``url`` targets loopback so
    ``requests`` skips ``getproxies()`` (env and macOS system proxy), else ``{}``."""
    return {"proxies": {"http": None, "https": None}} if is_loopback_host(split_host_port(url)[0]) else {}


def add_loopback_no_proxy(env: dict) -> dict:
    """Append the loopback hosts to ``NO_PROXY`` / ``no_proxy`` in ``env`` (both casings),
    keeping every operator-provided entry; returns ``env``. An operator ``*`` (bypass everything)
    already covers loopback and would stop being the wildcard once anything is appended to it."""
    if any("*" in no_proxy_entries(env.get(key) or "") for key in ("NO_PROXY", "no_proxy")):
        return env  # both casings: requests/urllib read ``no_proxy`` first, so a loopback-only one would win
    for key in ("NO_PROXY", "no_proxy"):
        entries = no_proxy_entries(env.get(key) or "")
        missing = [host for host in LOOPBACK_HOSTS if host not in entries]
        if missing:
            env[key] = ",".join(entries + missing)
    return env


def _ip_or_none(value: str, parse=ipaddress.ip_address):
    try:
        return parse(value)
    except ValueError:
        return None


def no_proxy_entry_matches(entry: str, host: str, port: int | None = None) -> bool:
    token = str(entry or "").strip().lower()
    if not token:
        return False
    if token == "*":
        return True
    token_host, token_port = split_host_port(token)
    if not token_host or (token_port is not None and (port is None or token_port != port)):
        return False
    host_ip = _ip_or_none(host)
    network = _ip_or_none(token_host, lambda value: ipaddress.ip_network(value, strict=False))
    if network is not None:
        return host_ip is not None and host_ip in network
    suffix = token_host.removeprefix("*").removeprefix(".")
    return host == suffix or host.endswith(f".{suffix}")


def should_bypass_proxy(
    target_hosts: str | list[str] | tuple[str, ...] | set[str] | None, *, no_proxy_value: str | None = None,
) -> bool:
    entries = no_proxy_entries(no_proxy_value)
    if not entries or not target_hosts:
        return False
    candidates = [target_hosts] if isinstance(target_hosts, str) else list(target_hosts)
    return any(
        host and any(no_proxy_entry_matches(entry, host, port) for entry in entries)
        for host, port in map(split_host_port, map(str, candidates))
    )
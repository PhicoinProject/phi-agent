"""Direct HTTPS on the ``phi dashboard`` listener.

Browsers only grant the microphone (``getUserMedia``) to secure contexts, so a dashboard opened
from another device needs https. ``dashboard.tls`` (or ``--tls-cert``/``--tls-key``/
``--tls-self-signed``) resolves to a cert/key pair handed straight to ``uvicorn.Config``; with
``self_signed`` the pair is created once under ``<PHI_HOME>/dashboard_tls/`` and reused until it
expires or stops covering the requested hosts.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import shutil
import ssl
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

VALID_DAYS = 825
TLS_DIR_NAME = "dashboard_tls"
CERT_NAME = "cert.pem"
KEY_NAME = "key.pem"
CHILD_CA_NAME = "node-extra-ca.pem"
_COMMON_NAME = "Phi Agent dashboard"
_WILDCARD_BINDS = frozenset({"", "0.0.0.0", "::", "*"})
_DNS_NAME = re.compile(r"^[A-Za-z0-9*_.-]+$")
_NO_BACKEND = ("cannot create a self-signed certificate: install the Python `cryptography` package "
               "or the `openssl` command, or set dashboard.tls.cert_file/key_file")


class DashboardTLSError(Exception):
    """TLS was requested but cannot be set up; the message is meant for the user."""


@dataclass(frozen=True)
class DashboardTLS:
    cert_file: str
    key_file: str
    self_signed: bool = False


def uvicorn_ssl_kwargs(tls: Optional[DashboardTLS]) -> dict[str, str]:
    """``uvicorn.Config`` kwargs for ``tls``; empty for plain http."""
    if tls is None:
        return {}
    return {"ssl_certfile": tls.cert_file, "ssl_keyfile": tls.key_file}


def url_scheme(tls: Optional[DashboardTLS]) -> str:
    return "https" if tls is not None else "http"


def default_tls_dir() -> Path:
    from phi_constants import get_phi_home

    return Path(get_phi_home()) / TLS_DIR_NAME


def _is_ip(name: str) -> bool:
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def _canonical(name: str) -> str:
    """Comparison key: IP literals compressed, DNS names lower-cased."""
    try:
        return str(ipaddress.ip_address(name))
    except ValueError:
        return name.lower()


def san_names(host: str, extra_hosts: Any = ()) -> list[str]:
    """SANs for the self-signed cert: localhost, 127.0.0.1, the bind host (unless a wildcard bind)
    and ``dashboard.tls.hosts``."""
    if isinstance(extra_hosts, str):
        extra_hosts = [extra_hosts]
    elif extra_hosts is None:
        extra_hosts = []
    elif not isinstance(extra_hosts, (list, tuple)):
        raise DashboardTLSError("dashboard.tls.hosts must be a list of host names or IP addresses")
    names: list[str] = []
    for raw in ("localhost", "127.0.0.1", host, *extra_hosts):
        name = str(raw or "").strip().strip("[]").split("%", 1)[0]
        if name in _WILDCARD_BINDS:
            continue
        if not _is_ip(name) and not _DNS_NAME.match(name):
            raise DashboardTLSError(f"{name!r} is not a host name or IP address")
        if _canonical(name) not in names:
            names.append(_canonical(name))
    return names


def resolve_dashboard_tls(
    dash_cfg: Any,
    host: str,
    *,
    cert_file: Optional[str] = None,
    key_file: Optional[str] = None,
    self_signed: bool = False,
    home: Optional[Path] = None,
) -> Optional[DashboardTLS]:
    """TLS for the listener, or ``None`` for plain http.

    CLI flags win over ``dashboard.tls``; on each side a cert/key pair wins over ``self_signed``.
    """
    from utils import is_truthy_value

    cfg = dash_cfg.get("tls") if isinstance(dash_cfg, dict) else None
    cfg = cfg if isinstance(cfg, dict) else {}
    if cert_file or key_file:
        return _user_pair(cert_file, key_file, "--tls-cert/--tls-key")
    if not self_signed:
        cfg_cert = str(cfg.get("cert_file") or "").strip()
        cfg_key = str(cfg.get("key_file") or "").strip()
        if cfg_cert or cfg_key:
            return _user_pair(cfg_cert, cfg_key, "dashboard.tls.cert_file/key_file")
        if not is_truthy_value(cfg.get("self_signed"), default=False):
            return None
    directory = Path(home) / TLS_DIR_NAME if home is not None else default_tls_dir()
    cert, key = ensure_self_signed_cert(directory, san_names(host, cfg.get("hosts")))
    return DashboardTLS(str(cert), str(key), self_signed=True)


def _user_pair(cert_file: Optional[str], key_file: Optional[str], source: str) -> DashboardTLS:
    if not (cert_file and key_file):
        raise DashboardTLSError(f"{source}: set both the certificate and the key file")
    cert, key = Path(cert_file).expanduser(), Path(key_file).expanduser()
    for path in (cert, key):
        if not path.is_file():
            raise DashboardTLSError(f"{source}: {path} does not exist")
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
    except (ssl.SSLError, OSError) as exc:
        raise DashboardTLSError(f"{source}: cannot load {cert} with {key}: {exc}") from None
    return DashboardTLS(str(cert), str(key))


def ensure_self_signed_cert(
    directory: Path, names: list[str], *, now: Optional[datetime] = None,
) -> tuple[Path, Path]:
    """``(cert, key)`` in ``directory``: reused while unexpired and covering ``names``, else
    (re)generated. The key is kept 0600."""
    now = now or datetime.now(UTC)
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    cert, key = directory / CERT_NAME, directory / KEY_NAME
    if cert.is_file() and key.is_file() and _reusable(cert, key, names, now):
        os.chmod(key, 0o600)
        return cert, key
    tmp = Path(tempfile.mkdtemp(prefix=".new-", dir=directory))
    try:
        new_cert, new_key = tmp / CERT_NAME, tmp / KEY_NAME
        if _cryptography_available():
            _generate_with_cryptography(new_cert, new_key, names, now)
        else:
            _generate_with_openssl(new_cert, new_key, names)
        os.chmod(new_key, 0o600)
        os.replace(new_key, key)
        os.replace(new_cert, cert)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    logger.info("Created a self-signed dashboard certificate for %s (%s)", ", ".join(names), cert)
    return cert, key


def _reusable(cert: Path, key: Path, names: list[str], now: datetime) -> bool:
    try:
        not_after, sans = read_cert(cert)
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
    except Exception:
        return False
    return not_after > now and {_canonical(n) for n in names} <= {_canonical(s) for s in sans}


def _cryptography_available() -> bool:
    try:
        import cryptography.x509  # noqa: F401
    except ImportError:
        return False
    return True


def _openssl(*args: str) -> str:
    from phi_platform.resolver import locate_command

    command = locate_command("openssl").command
    if not command:
        raise DashboardTLSError(_NO_BACKEND)
    try:
        done = subprocess.run([*command, *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise DashboardTLSError(f"openssl failed: {exc}") from None
    if done.returncode != 0:
        raise DashboardTLSError(f"openssl failed: {done.stderr.strip() or done.returncode}")
    return done.stdout


def read_cert(cert: Path) -> tuple[datetime, list[str]]:
    """``(not_after, SAN names)`` of a PEM certificate."""
    if _cryptography_available():
        from cryptography import x509

        obj = x509.load_pem_x509_certificate(cert.read_bytes())
        try:
            san = obj.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        except x509.ExtensionNotFound:
            return obj.not_valid_after_utc, []
        ips = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        return obj.not_valid_after_utc, [*san.get_values_for_type(x509.DNSName), *ips]
    out = _openssl("x509", "-in", str(cert), "-noout", "-enddate", "-ext", "subjectAltName")
    end = re.search(r"^notAfter=(.+)$", out, re.M)
    if not end:
        raise DashboardTLSError(f"cannot read the expiry of {cert}")
    not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(end.group(1).strip()), UTC)
    return not_after, [m.group(2) for m in re.finditer(r"(DNS|IP Address):([^,\s]+)", out)]


def _generate_with_cryptography(cert_path: Path, key_path: Path, names: list[str], now: datetime) -> None:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, _COMMON_NAME)])
    alt = [x509.IPAddress(ipaddress.ip_address(n)) if _is_ip(n) else x509.DNSName(n) for n in names]
    ski = x509.SubjectKeyIdentifier.from_public_key(key.public_key())
    # End-entity extensions only (CA:FALSE, serverAuth): Firefox rejects a CA cert used as a
    # server cert, and Python 3.13's strict verification wants both key identifiers.
    usage = x509.KeyUsage(
        digital_signature=True, content_commitment=False, key_encipherment=False,
        data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
        encipher_only=False, decipher_only=False)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=VALID_DAYS))
        .add_extension(x509.SubjectAlternativeName(alt), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(usage, critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(ski, critical=False)
        .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(ski), critical=False)
        .sign(key, hashes.SHA256())
    )
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))


def _generate_with_openssl(cert_path: Path, key_path: Path, names: list[str]) -> None:
    alt = ",".join(f"IP:{n}" if _is_ip(n) else f"DNS:{n}" for n in names)
    cnf = cert_path.with_name("openssl.cnf")
    cnf.write_text(
        "[req]\ndistinguished_name = dn\nx509_extensions = v3\nprompt = no\n"
        f"[dn]\nCN = {_COMMON_NAME}\n"
        "[v3]\nbasicConstraints = critical,CA:FALSE\n"
        "keyUsage = critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectKeyIdentifier = hash\n"
        "authorityKeyIdentifier = keyid:always\n"
        f"subjectAltName = {alt}\n",
        encoding="utf-8",
    )
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", str(VALID_DAYS),
             "-keyout", str(key_path), "-out", str(cert_path), "-config", str(cnf))


def trust_for_node_child(env: dict, tls: Optional[DashboardTLS], *, directory: Optional[Path] = None) -> None:
    """Make a Node child that dials this listener over wss trust its certificate.

    ``NODE_EXTRA_CA_CERTS`` takes one file, so an operator-set bundle is combined with the
    dashboard cert into ``<dir>/node-extra-ca.pem`` instead of being replaced.
    """
    if tls is None:
        return
    existing = str(env.get("NODE_EXTRA_CA_CERTS") or "").strip()
    if not existing or os.path.abspath(existing) == os.path.abspath(tls.cert_file):
        env["NODE_EXTRA_CA_CERTS"] = tls.cert_file
        return
    directory = Path(directory) if directory is not None else default_tls_dir()
    bundle = directory / CHILD_CA_NAME
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        parts = [Path(existing).read_text(encoding="utf-8"), Path(tls.cert_file).read_text(encoding="utf-8")]
        bundle.write_text("\n".join(p.strip() for p in parts) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Could not combine NODE_EXTRA_CA_CERTS with the dashboard certificate", exc_info=True)
        return
    env["NODE_EXTRA_CA_CERTS"] = str(bundle)

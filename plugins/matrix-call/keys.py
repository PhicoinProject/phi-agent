"""MatrixRTC media keys over Olm to-device, as js-sdk ``ToDeviceKeyTransport`` sends and checks them."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from dataclasses import dataclass

from mautrix.types import DecryptedOlmEvent, EventType, Serializable

logger = logging.getLogger(__name__)

KEYS_EVENT = EventType.find("io.element.call.encryption_keys", t_class=EventType.Class.TO_DEVICE)


def new_key() -> bytes:
    return os.urandom(16)  # js-sdk EncryptionManager: 16 random bytes per key


def fp(key: bytes) -> str:
    """The only form in which a key may appear in logs."""
    return hashlib.sha256(key).hexdigest()[:8]


def fp_b64(key_b64: str) -> str:
    """Fingerprint of a received key; padded or unpadded, standard or url-safe base64."""
    s = key_b64.strip()
    try:
        return fp(base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_" if "-" in s or "_" in s else None))
    except ValueError:
        return "invalid"


def b64(key: bytes) -> str:
    return base64.b64encode(key).decode()  # js-sdk encodeBase64: standard alphabet, padded


def content(key: bytes, index: int, room_id: str, user_id: str, device_id: str, now_ms: int) -> dict:
    return {
        "keys": {"index": index, "key": b64(key)},
        "room_id": room_id,
        "member": {"claimed_device_id": device_id, "id": f"{user_id}:{device_id}"},
        "session": {"call_id": "", "application": "m.call", "scope": "m.room"},
        "sent_ts": now_ms,
    }


async def send(crypto, targets: list[tuple[str, str]], body: dict, own: tuple[str, str], timeout: float = 10) -> int:
    """Olm-encrypt ``body`` to each (user, device) except our own; returns how many were sent.
    A device that cannot be fetched or encrypted to in ``timeout`` seconds (each request) is logged and skipped so
    the others still get the key."""
    sent = 0
    for user_id, device_id in targets:
        if (user_id, device_id) == own:
            continue
        try:
            device = await asyncio.wait_for(crypto.get_or_fetch_device(user_id, device_id), timeout)
            if device is None:
                logger.warning("matrix-call: no device keys for %s/%s, key not sent", user_id, device_id)
                continue
            await asyncio.wait_for(crypto.send_encrypted_to_device(device, KEYS_EVENT, body), timeout)
            sent += 1
        except Exception as exc:
            logger.warning("matrix-call: key to %s/%s failed: %s: %s", user_id, device_id, type(exc).__name__, exc)
    return sent


@dataclass(frozen=True)
class Received:
    room_id: str
    sender: str
    device_id: str
    key_b64: str
    index: int
    sender_key: str = ""  # Curve25519 identity key of the Olm session the event came through
    sender_device: str = ""  # set by OlmMachine only when the payload names it (Element X's does not)

    @property
    def identity(self) -> str:
        # The LiveKit identity of the sender's track. Built from the Olm-authenticated sender rather than
        # content.member.id, which the js-sdk itself marks as claimed information.
        return f"{self.sender}:{self.device_id}"


def received(evt) -> Received | None:
    """Validate an incoming key event like onToDeviceEvent + getValidEventContent; None = drop it.
    The caller still has to match ``room_id`` against the call (js-sdk: "Mismatch roomId").

    Only a ``DecryptedOlmEvent`` counts: that is what OlmMachine dispatches after decrypting an
    ``m.room.encrypted`` to-device event (the js-sdk wire-type check). A plaintext to-device event of the
    same type arrives as a ``ToDeviceEvent`` and is refused."""
    if not isinstance(evt, DecryptedOlmEvent):
        logger.warning("matrix-call: call keys from %s sent in clear, ignored", getattr(evt, "sender", "?"))
        return None
    if evt.type != KEYS_EVENT or not evt.sender:
        return None
    c = evt.content.serialize() if isinstance(evt.content, Serializable) else evt.content
    if not isinstance(c, dict) or not c.get("room_id"):
        return None
    keys, member = c.get("keys"), c.get("member")
    if not isinstance(keys, dict) or not keys.get("key") or not isinstance(member, dict):
        return None
    index, device = keys.get("index"), member.get("claimed_device_id")
    # typeof index === "number"; bool is excluded because Python counts it as an int
    if not isinstance(index, int) or isinstance(index, bool) or not device:
        return None
    return Received(str(c["room_id"]), str(evt.sender), str(device), str(keys["key"]), index,
                    str(getattr(evt, "sender_key", None) or ""), str(getattr(evt, "sender_device", None) or ""))


async def from_claimed_device(crypto, got: Received) -> bool:
    """Whether the key came through an Olm session with the device it claims (``member.claimed_device_id``), so a
    device of the caller cannot pass its key off as another one's: the session's sender key must be that device's
    identity key."""
    if (got.sender_device and got.sender_device != got.device_id) or not got.sender_key:
        return False
    device = await crypto.get_or_fetch_device(got.sender, got.device_id)
    return device is not None and str(device.identity_key) == got.sender_key

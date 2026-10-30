"""LiveKit JWT from the MatrixRTC JWT service (lk-jwt-service legacy ``/sfu/get``), as element-call openIDSFU.ts."""
from __future__ import annotations

import aiohttp
from mautrix.api import Method, Path
from mautrix.types import UserID


async def fetch(client, service_url: str, room_id: str, device_id: str) -> tuple[str, str]:
    """→ (livekit ws url, jwt). The JWT is a secret: callers pass it to the worker and never log it."""
    if not service_url.startswith("https://"):
        # The URL comes from the caller's state event; never hand our OpenID token to plain http.
        raise ValueError(f"refusing non-https JWT service {service_url!r}")
    openid = await client.api.request(Method.POST, Path.v3.user[UserID(client.mxid)].openid.request_token, {})
    # element-call sends the Matrix room id as "room" (the service checks we are in it); in Element X's
    # membership livekit_alias is that same room id.
    body = {"room": room_id, "openid_token": openid, "device_id": device_id}
    async with client.api.session.post(service_url.rstrip("/") + "/sfu/get", json=body,
                                       headers={"User-Agent": client.api.default_ua},
                                       timeout=aiohttp.ClientTimeout(total=10)) as resp:
        if resp.status != 200:
            raise RuntimeError(f"JWT service answered HTTP {resp.status}")
        data = await resp.json(content_type=None)
    if not data.get("url") or not data.get("jwt"):
        raise RuntimeError("JWT service reply lacks url/jwt")
    return str(data["url"]), str(data["jwt"])

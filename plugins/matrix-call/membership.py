"""MatrixRTC ``call.member`` state events, shaped like Element X's (js-sdk MembershipManager, legacy session data)."""
from __future__ import annotations

from dataclasses import dataclass

CALL_MEMBER = "org.matrix.msc3401.call.member"
EXPIRES_MS = 4 * 60 * 60 * 1000  # js-sdk DEFAULT_EXPIRE_DURATION; Element X sends exactly this


@dataclass(frozen=True)
class Join:
    room_id: str
    user_id: str  # the event sender: the server vouches for it, a v11 state_key does not
    device_id: str
    state_key: str
    event_id: str
    expires_at_ms: int
    service_url: str  # livekit_service_url of the caller's LiveKit focus = the JWT service
    alias: str  # livekit_alias = LiveKit room name
    created_ms: int = 0  # when the device joined the call: a refresh keeps the first join's created_ts

    @property
    def identity(self) -> str:
        # Legacy LiveKit identity: the transport carries livekit_service_url, so the JWT service names
        # participants ``${user}:${device}`` (not the hashed rtc-member id).
        return f"{self.user_id}:{self.device_id}"


@dataclass(frozen=True)
class Leave:
    room_id: str
    user_id: str
    state_key: str
    event_id: str


def parse(raw: dict) -> Join | Leave | None:
    """A raw state event (sync shape, ``room_id`` set) → Join, Leave, or None when it is not a room call."""
    key = raw.get("state_key")
    if raw.get("type") != CALL_MEMBER or not isinstance(key, str):
        return None
    room, sender, event_id = str(raw.get("room_id", "")), str(raw.get("sender", "")), str(raw.get("event_id", ""))
    c = raw.get("content") or {}
    if not c:
        return Leave(room, sender, key, event_id)
    # Only the room-wide call (call_id "" + scope m.room); checks follow checkSessionsMembershipData.
    if c.get("application") != "m.call" or c.get("call_id") != "" or c.get("scope", "m.room") != "m.room":
        return None
    device = c.get("device_id")
    focus = next((f for f in c.get("foci_preferred") or [] if isinstance(f, dict) and f.get("type") == "livekit"
                  and f.get("livekit_service_url") and f.get("livekit_alias")), None)
    if not isinstance(device, str) or not device or focus is None:
        return None
    # CallMembership.getAbsoluteExpiry: (created_ts ?? origin_server_ts) + (expires ?? 4 h)
    created, expires = c.get("created_ts"), c.get("expires")
    start = created if isinstance(created, int) else int(raw.get("origin_server_ts") or 0)
    expires = expires if isinstance(expires, int) else EXPIRES_MS
    return Join(room, sender, device, key, event_id, start + expires,
                str(focus["livekit_service_url"]), str(focus["livekit_alias"]), start)


def state_key(user_id: str, device_id: str) -> str:
    # makeMembershipStateKey for m.call/ROOM in a non-MSC3757 room version (the server runs v11): leading "_".
    return f"_{user_id}_{device_id}_m.call"


def content(user_id: str, device_id: str, caller: Join) -> dict:
    """Our membership: makeMyMembership with intent audio, publishing on the caller's LiveKit focus."""
    return {
        "application": "m.call",
        "call_id": "",
        "scope": "m.room",
        "device_id": device_id,
        "membershipID": f"{user_id}:{device_id}",
        "expires": EXPIRES_MS,
        "m.call.intent": "audio",
        "focus_active": {"type": "livekit", "focus_selection": "multi_sfu"},
        "foci_preferred": [{"type": "livekit", "livekit_service_url": caller.service_url,
                            "livekit_alias": caller.alias}],
    }

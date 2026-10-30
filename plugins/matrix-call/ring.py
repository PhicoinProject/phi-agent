"""Ringing someone: the MatrixRTC call notification (MSC4075) and its decline (MSC4310), as js-sdk sends them."""
from __future__ import annotations

from mautrix.types import EventType

NOTIFICATION = "org.matrix.msc4075.rtc.notification"
DECLINE = "org.matrix.msc4310.rtc.decline"
NOTIFICATION_EVENT = EventType.find(NOTIFICATION, t_class=EventType.Class.MESSAGE)
DECLINE_EVENT = EventType.find(DECLINE, t_class=EventType.Class.MESSAGE)

LIFETIME_MS = 90_000  # js-sdk sendCallNotify default (joinConfig.notificationLifetimeMs)
# computeSlotId of the room call's slot. Its legacy call_id is "", but js-sdk names that slot {m.call, "ROOM"}
# (MatrixRTCSessionManager's default slot; CallMembership maps "" to "ROOM"), so the receiver's session has this id.
SLOT_ID = "m.call#ROOM"


def notification(member_event_id: str, now_ms: int) -> dict:
    """MatrixRTCSession.sendCallNotify for a ring with intent audio, in its key order; it relates to our call.member
    event, which is how a receiver without slot support finds the call."""
    return {
        "slot_id": SLOT_ID,
        "m.mentions": {"user_ids": [], "room": True},
        "notification_type": "ring",
        "m.relates_to": {"event_id": member_event_id, "rel_type": "m.reference"},
        "sender_ts": now_ms,
        "lifetime": LIFETIME_MS,
        "msc4354_sticky_key": SLOT_ID,
        "m.call.intent": "audio",
    }


def declines(content: dict, notification_id: str) -> bool:
    """IRTCDeclineContent: an m.reference to the notification it declines."""
    rel = content.get("m.relates_to") if isinstance(content, dict) else None
    return (isinstance(rel, dict) and rel.get("rel_type") == "m.reference" and bool(notification_id)
            and rel.get("event_id") == notification_id)

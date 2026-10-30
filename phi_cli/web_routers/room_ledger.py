"""Room ledger REST (design §九): the dashboard's read-only view of ``<room>/.phi/ledger.db``.

Without ``q`` the ledger reads as a timeline, newest first; with ``q`` it is a fuzzy search. Every entry
carries ``superseded_by``. A room that never wrote a ledger answers with no entries and gets no file; an
unknown room is 404, a space (no directory) 400.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query

from phi_cli.web_routers._common import http_failure, scoped_to_thread

router = APIRouter()


async def _call(profile: Optional[str], label: str, fn: Callable[[], Any]) -> Any:
    """Run ``fn`` in the profile's home: unknown id → 404, refused input → 400, anything else → 500."""
    def _run():
        try:
            return fn()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    with http_failure(f"{label} failed", 500, "Room ledger error"):
        return await scoped_to_thread(profile, _run)


def _ledger(room_id: str):
    """The room's open Ledger, or None while it has no ledger file."""
    from agent.room_ledger import open_ledger
    from phi_cli import workspace_map

    path = workspace_map.get_room(room_id)["path"]
    if not path:
        raise ValueError(f"{room_id} is a space and has no ledger.")
    return open_ledger(path, create=False)


def _kinds(kind: str) -> Optional[tuple[str, ...]]:
    from agent.room_ledger import KINDS

    kinds = tuple(k.strip() for k in kind.split(",") if k.strip())
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}, not {', '.join(unknown)}")
    return kinds or None


@router.get("/api/workspace/rooms/{room_id}/ledger")
async def list_room_ledger(room_id: str, q: str = "", kind: str = "", include_superseded: bool = False,
                           limit: int = Query(50, ge=1, le=500), profile: Optional[str] = None):
    """``{entries}``: the timeline (newest first) or, with ``q``, the best matches."""
    def _run():
        kinds = _kinds(kind)
        ledger = _ledger(room_id)
        if ledger is None:
            return {"entries": []}
        if not q.strip():
            return {"entries": ledger.timeline(kinds, include_superseded=include_superseded, limit=limit)}
        hits = ledger.search(q, k=limit, include_superseded=include_superseded, kinds=kinds)
        for hit in hits:
            superseded = hit["status"] == "superseded"
            hit["superseded_by"] = (ledger.get(hit["id"]) or {}).get("superseded_by") if superseded else None
        return {"entries": hits}

    return await _call(profile, "GET /api/workspace/rooms/ledger", _run)


@router.get("/api/workspace/rooms/{room_id}/ledger/{entry_id}")
async def get_room_ledger_entry(room_id: str, entry_id: int, profile: Optional[str] = None):
    """``{entry}``: one entry with ``supersedes`` and ``superseded_by``."""
    def _run():
        ledger = _ledger(room_id)
        entry = None if ledger is None else ledger.get(entry_id)
        if entry is None:
            raise LookupError(f"No ledger entry #{entry_id} in {room_id}.")
        return {"entry": entry}

    return await _call(profile, "GET /api/workspace/rooms/ledger/entry", _run)

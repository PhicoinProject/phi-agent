"""``/api/memory/*`` for Settings > Memory (design §十): the global memory entries in ``memory.db``.

Hard entries form the always-on system-prompt block and are bounded by ``memory_char_limit`` /
``user_char_limit``; soft entries have no fixed limit and are recalled into a turn only when relevant.
``GET /api/memory`` stays the provider status route in ``ops``, so the list lives at
``/api/memory/entries``. Every change runs under the view's file lock and regenerates the read-only
MEMORY.md / USER.md view, as the memory tool does. A running session keeps its frozen prompt block.
"""

from __future__ import annotations

from typing import Callable, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from phi_cli.web_routers._common import config_scoped_to_thread, destructive_profile

router = APIRouter()

_SEARCH_LIMIT = 100


class MemoryEntryNew(BaseModel):
    target: str = "memory"
    tier: str = "hard"
    text: str
    kind: str = "note"


class MemoryEntryEdit(BaseModel):
    text: str


class MemoryEntryPin(BaseModel):
    pinned: bool = True


def _open_db():
    """The profile's memory.db with its configured hard limits, legacy markdown imported first."""
    from phi_constants import mkdir_under_phi_home
    from tools.memory_tool import get_builtin_memory_config
    from tools.memory_tool_db import memory_db_path, migrate_markdown, open_memory_db

    cfg = get_builtin_memory_config()
    mkdir_under_phi_home(memory_db_path().parent)
    db = open_memory_db({"memory": int(cfg.get("memory_char_limit", 4000)),
                         "user": int(cfg.get("user_char_limit", 4000))})
    if (unreadable := migrate_markdown(db)) is not None:
        db.close()
        raise HTTPException(status_code=503, detail=f"{unreadable.name} could not be read; nothing was changed")
    return db


def _change(target: str, fn: Callable) -> dict:
    """Run ``fn(db)`` under ``target``'s view lock, then regenerate the view; DB errors map to HTTP codes."""
    from agent.memory_db import TARGETS, MemoryFullError
    from tools.memory_tool_db import VIEW_FILES, memory_dir, write_view
    from tools.memory_tool_store import MemoryStore

    if target not in TARGETS:
        raise HTTPException(status_code=400, detail="target must be memory or user")
    with _open_db() as db, MemoryStore._file_lock(memory_dir() / VIEW_FILES[target]):
        try:
            entry_id = fn(db)
        except MemoryFullError as exc:
            raise HTTPException(status_code=409, detail=f"Memory full: {exc}") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        write_view(db, target)
    return {"ok": True, "id": entry_id}


def _change_entry(entry_id: int, fn: Callable) -> dict:
    """``_change`` for an existing active entry: ``fn(db, row)`` returns the resulting id."""
    with _open_db() as db:
        row = db.get(entry_id)
    if row is None or row["status"] != "active":
        raise HTTPException(status_code=404, detail=f"no active memory entry #{entry_id}")
    return _change(row["target"], lambda db: fn(db, row))


def _checked_text(text: str) -> str:
    from tools.memory_tool_store import _scan_memory_content

    if (threat := _scan_memory_content(text)) is not None:
        raise HTTPException(status_code=400, detail=threat)
    return text


@router.get("/api/memory/usage")
async def get_memory_usage(profile: Optional[str] = None):
    def _run():
        with _open_db() as db:
            hard = {}
            for target in ("memory", "user"):
                used, limit = db.hard_usage(target)
                hard[target] = {"used": used, "limit": limit}
            return {"hard": hard, "soft_count": len(db.entries(tier="soft"))}

    return await config_scoped_to_thread(profile, _run)


@router.get("/api/memory/entries")
async def list_memory_entries(tier: Optional[str] = None, target: Optional[str] = None, q: Optional[str] = None,
                              profile: Optional[str] = None):
    def _run():
        with _open_db() as db:
            try:
                if q and q.strip():
                    return {"entries": db.search(q, k=_SEARCH_LIMIT, target=target or None, tier=tier or None)}
                return {"entries": db.entries(target or None, tier or None)}
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await config_scoped_to_thread(profile, _run)


@router.post("/api/memory")
async def create_memory_entry(body: MemoryEntryNew, profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/memory")
    text = _checked_text(body.text)
    return await config_scoped_to_thread(
        profile, lambda: _change(body.target, lambda db: db.add(body.target, body.tier, text, body.kind)))


@router.patch("/api/memory/{entry_id:int}")
async def edit_memory_entry(entry_id: int, body: MemoryEntryEdit, profile: Optional[str] = None):
    profile = destructive_profile(profile, "PATCH /api/memory/{id}")
    text = _checked_text(body.text)
    return await config_scoped_to_thread(
        profile, lambda: _change_entry(entry_id, lambda db, row: db.replace(row["id"], text, target=row["target"])))


_ENTRY_ACTIONS = {
    "promote": lambda db, row: db.promote(row["id"], target=row["target"]),
    "demote": lambda db, row: db.demote(row["id"], target=row["target"]),
    "archive": lambda db, row: db.remove(row["id"], target=row["target"]),
}


@router.post("/api/memory/{entry_id:int}/pin")
async def pin_memory_entry(entry_id: int, body: Optional[MemoryEntryPin] = None, profile: Optional[str] = None):
    profile = destructive_profile(profile, "POST /api/memory/{id}/pin")
    priority = 1 if body is None or body.pinned else 0
    return await config_scoped_to_thread(
        profile, lambda: _change_entry(entry_id, lambda db, row: db.set_priority(row["id"], priority,
                                                                                 target=row["target"])))


@router.post("/api/memory/{entry_id:int}/{action}")
async def memory_entry_action(entry_id: int, action: str, profile: Optional[str] = None):
    if action not in _ENTRY_ACTIONS:
        raise HTTPException(status_code=404, detail=f"unknown memory action '{action}'")
    profile = destructive_profile(profile, f"POST /api/memory/{{id}}/{action}")
    return await config_scoped_to_thread(profile, lambda: _change_entry(entry_id, _ENTRY_ACTIONS[action]))

"""The memory tool's side of ``agent.memory_db`` (design §十): where the database lives, the one-time
import of legacy MEMORY.md / USER.md, and the read-only MEMORY.md / USER.md views regenerated from the
hard entries after every hard change. Views are never read back while the database holds rows."""

import json
import logging
import shutil
import time
from pathlib import Path
from typing import Iterable, Optional

from utils import atomic_write_text

logger = logging.getLogger("tools.memory_tool")

VIEW_FILES = {"memory": "MEMORY.md", "user": "USER.md"}
VIEW_HEADER = ("<!-- Phi Agent memory view: generated from memory.db (hard entries only). Edits here are not "
               "read back; change memory with the memory tool or Settings > Memory. -->")
IMPORT_MARKER = ".imported_to_memory_db"


def memory_dir() -> Path:
    from tools import memory_tool  # get_memory_dir is monkeypatched there
    return memory_tool.get_memory_dir()


def memory_db_path() -> Path:
    """``<PHI_HOME>/memory.db`` beside the memories dir; inside a relocated memories dir instead."""
    memories = memory_dir()
    return (memories.parent if memories.name == "memories" else memories) / "memory.db"


def open_memory_db(limits: Optional[dict] = None):
    from agent.memory_db import MemoryDB
    return MemoryDB(memory_db_path(), limits=limits)


def strip_view_header(raw: str) -> str:
    return raw[len(VIEW_HEADER):].lstrip("\n") if raw.startswith(VIEW_HEADER) else raw


def migrate_markdown(db) -> Optional[Path]:
    """Import MEMORY.md / USER.md into an empty ``db``, every entry as hard, leaving the files untouched,
    and record the counts in ``memories/.imported_to_memory_db``. Returns the path of a file that exists
    but cannot be read: then nothing is imported and the next call retries."""
    if not db.is_empty():
        return None
    from tools.memory_tool_store import MemoryStore

    texts = {}
    for target, name in VIEW_FILES.items():
        raw, read_ok = MemoryStore._read_raw_checked(memory_dir() / name)
        if not read_ok:
            return memory_dir() / name
        texts[target] = strip_view_header(raw)
    counts = db.import_markdown_once(texts["memory"], texts["user"])
    if counts and sum(counts.values()):
        marker = {"imported_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tier": "hard",
                  "entries": {VIEW_FILES[t]: n for t, n in counts.items()}}
        atomic_write_text(memory_dir() / IMPORT_MARKER, json.dumps(marker, indent=2) + "\n", tmp_prefix=".mem_")
        logger.info("Imported legacy memory into memory.db: %s", marker["entries"])
    return None


def write_view(db, target: str) -> None:
    """Regenerate one view from the hard entries; the caller holds ``MemoryStore._file_lock`` on it. A file
    with entries the database never held (a hand edit) or undecodable bytes is copied to ``.bak.<ts>``
    first; when that copy fails the view is left as it is rather than lose the text."""
    from phi_constants import mkdir_under_phi_home
    from tools.memory_tool_store import MemoryStore

    path = memory_dir() / VIEW_FILES[target]
    raw, read_ok = MemoryStore._read_raw_checked(path)
    known = {e["text"] for e in db.entries(target, include_inactive=True)}
    if not read_ok or any(e not in known for e in MemoryStore._parse_entries(raw)):
        backup = path.with_suffix(path.suffix + f".bak.{int(time.time())}")
        try:
            shutil.copyfile(path, backup)
        except OSError as exc:
            logger.warning("%s not regenerated: it holds text memory.db lacks and the backup failed (%s)",
                           path.name, exc)
            return
        logger.warning("%s held text memory.db lacks; saved it to %s before regenerating the view",
                       path.name, backup.name)
    mkdir_under_phi_home(path.parent)
    atomic_write_text(path, f"{VIEW_HEADER}\n{db.export_markdown(target)}", tmp_prefix=".mem_")


def export_views(db, targets: Iterable[str] = tuple(VIEW_FILES)) -> None:
    """Regenerate the views of ``targets`` under their file locks (for writers outside ``MemoryStore``)."""
    from tools.memory_tool_store import MemoryStore

    for target in targets:
        with MemoryStore._file_lock(memory_dir() / VIEW_FILES[target]):
            write_view(db, target)


def active_entry_count(targets: Iterable[str]) -> int:
    """Active entries of ``targets`` in memory.db; 0 when there is no database yet."""
    if not memory_db_path().exists():
        return 0
    with open_memory_db() as db:
        return sum(len(db.entries(target)) for target in targets)


def archive_targets(targets: Iterable[str]) -> int:
    """Archive every active entry of ``targets`` (memory reset); returns how many. The archived rows keep
    the database non-empty, so the views a reset deletes are never imported again."""
    if not memory_db_path().exists():
        return 0
    with open_memory_db() as db:
        return sum(db.archive_all(target) for target in targets)

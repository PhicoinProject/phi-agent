"""Room memory (design v2): the room's ``.phi/memory.md`` is a short index rebuilt from the room's ledger.

One rule: after every turn, if the ledger's live entries differ from those the memory was built from,
rebuild it in the background with the session's chat model. The ledger is the only input and the truth;
the memory records a fingerprint of the entries it was built from, so a rebuild happens exactly when the
ledger changed (an entry added, replaced or closed) and never otherwise. Every line cites its entry.
"""
import hashlib
import logging
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

LEDGER_ENTRIES = 120
ENTRY_CHARS = 300
MAX_CHARS = 4000
MAX_TOKENS = 1500
_CITE = re.compile(r"#\d+")
_STAMP = re.compile(r"^<!-- ledger: ([0-9a-f]{16}) -->\n?")

PROMPT = (
    "You maintain the memory of ONE project room of a coding/operations agent. Rebuild it from the room's "
    "ledger below (the source of truth; every entry listed is still in force; (done) marks a closed item). "
    f"Output Markdown bullet lines only, at most {MAX_CHARS} characters, no preamble.\n"
    "Rules:\n"
    "- Carry over every decision, open blocker and todo, fact and result, merged where they say the same "
    "thing; keep closed items only if a future session still needs them; drop routine steps that do not "
    "matter later.\n"
    "- Every line ends with the entries it rests on, like (#12, 2026-10-27).\n"
    "- Copy commands, paths, error strings, versions and SHAs verbatim.\n"
    "- If nothing is worth keeping, output exactly: NONE"
)

_running: set[Path] = set()
_lock = threading.Lock()


def _entries(room_dir: Path) -> list[dict]:
    from agent.room_ledger import open_ledger

    ledger = open_ledger(room_dir, create=False)
    if ledger is None:
        return []
    rows = ledger.timeline(include_superseded=False, limit=LEDGER_ENTRIES)
    return [r for r in reversed(rows)
            if not (r["kind"] == "step" and str(r["text"]).startswith(("Session started", "Session ended")))]


def fingerprint(entries: list[dict]) -> str:
    """What the memory depends on: the live entries' ids, statuses and texts."""
    raw = "\n".join(f"{e['id']}|{e['status']}|{e['text']}" for e in entries)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _built_from(room_dir: Path) -> str | None:
    from agent.room_binding import room_memory_path

    try:
        with open(room_memory_path(room_dir), encoding="utf-8") as fh:
            m = _STAMP.match(fh.readline())
    except OSError:
        return None
    return m.group(1) if m else None


def stale(room_dir: Path) -> bool:
    """Whether the ledger changed since the memory was built (no model call)."""
    entries = _entries(room_dir)
    if not any(e["kind"] != "step" for e in entries):
        return False
    return _built_from(room_dir) != fingerprint(entries)


def _ledger_text(entries: list[dict]) -> str:
    from agent.room_ledger import ledger_ref

    lines = []
    for e in entries:
        text = " ".join(str(e["text"]).split())[:ENTRY_CHARS]
        day = datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d")
        done = " (done)" if e["status"] == "done" else ""
        lines.append(f"{ledger_ref(e['id'])} {day} {e['kind']}{done}: {text}")
    return "\n".join(lines)


def _call_model(ledger_text: str) -> str:
    from agent.auxiliary_client import call_llm

    resp = call_llm(task="room_memory", messages=[
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"LEDGER (oldest first):\n{ledger_text}"},
    ], max_tokens=MAX_TOKENS, temperature=0, timeout=120)
    return (resp.choices[0].message.content or "").strip()


def clean(text: str) -> str:
    """Bullet lines only, within the cap; ``""`` for NONE or nothing usable."""
    text = re.sub(r"^```\w*\n?|\n?```$", "", text.strip()).strip()
    if not text or text.upper() == "NONE":
        return ""
    out, size = [], 0
    for ln in (ln.rstrip() for ln in text.splitlines() if ln.strip().startswith(("-", "*"))):
        if size + len(ln) + 1 > MAX_CHARS:
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out)


def strip_stamp(text: str) -> str:
    return _STAMP.sub("", text, count=1)


def write(room_dir: Path, text: str, stamp: str) -> Path:
    from agent.room_binding import room_memory_path

    path = room_memory_path(room_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".memory.", suffix=".md")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"<!-- ledger: {stamp} -->\n{text}\n")
    os.replace(tmp, path)
    return path


def rebuild(room_dir: Path) -> str | None:
    """Rebuild the memory from the ledger; returns the new text, ``None`` when kept as it was."""
    entries = _entries(room_dir)
    if not entries:
        return None
    stamp = fingerprint(entries)
    text = clean(_call_model(_ledger_text(entries)))
    if not text or not _CITE.search(text):
        logger.info("room-memory: %s kept (the draft was empty or cited no ledger entry)", room_dir)
        return None
    write(room_dir, text, stamp)
    logger.info("room-memory: %s rebuilt (%d chars)", room_dir, len(text))
    return text


def refresh(room_dir: Path) -> threading.Thread | None:
    """After a turn: rebuild in the background if the ledger changed; one rebuild per room at a time,
    and a change made while it ran is picked up by a second pass."""
    from agent.room_binding import room_memory_enabled

    if not room_memory_enabled() or not stale(room_dir):
        return None
    with _lock:
        if room_dir in _running:
            return None
        _running.add(room_dir)

    def run():
        try:
            for _ in range(2):
                before = fingerprint(_entries(room_dir))
                rebuild(room_dir)
                if fingerprint(_entries(room_dir)) == before:
                    break
        except Exception:
            logger.warning("room-memory: rebuilding %s failed", room_dir, exc_info=True)
        finally:
            with _lock:
                _running.discard(room_dir)

    thread = threading.Thread(target=run, name=f"room-memory-{room_dir.name[:20]}", daemon=True)
    thread.start()
    return thread

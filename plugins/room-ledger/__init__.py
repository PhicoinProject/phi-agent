"""room-ledger: the bound room's ledger (design §九) fills itself and is read back every turn.

Automatic entries are plain records of what tools did, never model calls: session start and end, plan
items moving to in_progress/completed/cancelled (once each), failed terminal commands with their exit
code, test summary lines, git commit SHAs and the files written or patched. Identical consecutive entries
collapse and secrets are redacted before anything is stored.

The ``ledger`` tool rides the built-in ``todo`` toolset, so it is offered wherever the Todo tool is.
``pre_llm_call`` adds the room's recent decisions and open blockers/todos to the user message (never the
system prompt). Without a bound room nothing is written anywhere; reading never creates the ledger file.
After every turn the room memory (``.phi/memory.md``, see ``room_memory.py``) is rebuilt from the ledger
if the ledger changed; the system prompt carries it (``agent.room_binding.room_memory_block``).
"""
import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path

from agent.redact import redact_sensitive_text
from agent.room_binding import current_room
from agent.room_ledger import ledger_ref, open_ledger
from tools.registry import tool_error, tool_result
from tools.todo_tool import is_todo_tool_name

logger = logging.getLogger(__name__)

TOOL_KINDS = ("decision", "fact", "blocker", "todo", "note", "result")
PLAN_STATUSES = ("in_progress", "completed", "cancelled")
FIXED_LINE = "Room ledger: search it (ledger search) before answering questions about earlier work here."
INJECT_ENTRIES = 10
INJECT_CHARS = 1500
LINE_CHARS = 150
COMMAND_CHARS = 200
MATCHES_PER_OUTPUT = 5

_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_TEST_SUMMARY = (
    re.compile(r"^=+ Summary: .+"),                                    # scripts/run_tests.sh
    re.compile(r"^=+ .*\b\d+ (passed|failed|errors?)\b.* =+"),         # pytest
    re.compile(r"^\d+ (passed|failed)\b.* in [\d.]+s"),                # pytest -q
    re.compile(r"^\s*Tests\s+.*\b\d+ (passed|failed)\b"),              # vitest
)
_COMMIT = re.compile(r"^\[(\S+(?: \S+)*?) ([0-9a-f]{7,40})\] (.+)$")

LEDGER_SCHEMA = {
    "name": "ledger",
    "description": (
        "Room ledger: the searchable record of this room's work, kept across sessions. Record decisions, "
        "facts and blockers as they happen (action add, with 2-5 keywords). When unsure about earlier work "
        "in this room, search it before answering. supersede corrects an entry (the old one stays, marked "
        "replaced); done closes a todo or blocker. Steps and test results are recorded automatically."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "search", "supersede", "done"]},
            "text": {"type": "string", "description": "add/supersede: the entry, one or two sentences."},
            "kind": {"type": "string", "enum": list(TOOL_KINDS), "description": "add: what the entry is."},
            "keywords": {"type": "array", "items": {"type": "string"},
                         "description": "add (required) / supersede (optional): 2-5 search keywords."},
            "refs": {"type": "array", "items": {"type": "string"},
                     "description": "add/supersede: related paths, commit SHAs or #ids."},
            "q": {"type": "string", "description": "search: what to look for."},
            "k": {"type": "integer", "description": "search: how many entries (default 8)."},
            "include_superseded": {"type": "boolean", "description": "search: also return replaced entries."},
            "id": {"type": "integer", "description": "supersede/done: the entry id (#id)."},
        },
        "required": ["action"],
    },
}

_lock = threading.RLock()
_last: dict[Path, tuple[str, str]] = {}       # room -> last (kind, text) written, for collapsing
_started: set[tuple[Path, str]] = set()        # (room, session) whose start is recorded
_plan_seen: set[tuple[Path, str, str, str]] = set()  # (room, session, item id, status)
_session_rooms: dict[str, Path] = {}           # session -> room it wrote to, for the end entry


def _redact(text: str) -> str:
    return redact_sensitive_text(str(text), force=True, redact_url_credentials=True)


def _one_line(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _room_dir() -> Path | None:
    room = current_room()
    return None if room is None else Path(room.dir).resolve()


def _record(room_dir: Path, kind: str, text: str, keywords=(), refs=(), session_id=None, task_id=None) -> None:
    """Append an automatic entry unless it repeats the room's previous one."""
    text = _redact(text)
    with _lock:
        if _last.get(room_dir) == (kind, text):
            return
        open_ledger(room_dir).add(text, kind, keywords=[_redact(k) for k in keywords],
                                  refs=[_redact(r) for r in refs], actor="phi", session_id=session_id,
                                  task_id=task_id)
        _last[room_dir] = (kind, text)
        if session_id:
            _session_rooms[session_id] = room_dir


def _as_dict(result) -> dict | None:
    if isinstance(result, dict):
        return result
    try:
        data = json.loads(result)
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _record_plan(room_dir: Path, data: dict, session_id, task_id) -> None:
    for item in data.get("todos") or ():
        if not isinstance(item, dict) or item.get("status") not in PLAN_STATUSES:
            continue
        key = (room_dir, str(session_id), str(item.get("id")), item["status"])
        with _lock:
            if key in _plan_seen:
                continue
            _plan_seen.add(key)
        _record(room_dir, "step", f"Plan item {item.get('id')} {item['status']}: "
                f"{_one_line(item.get('content', ''), COMMAND_CHARS)}", keywords=("plan", item["status"]),
                session_id=session_id, task_id=task_id)


def _record_terminal(room_dir: Path, command: str, data: dict, session_id, task_id) -> None:
    exit_code = data.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool) and exit_code != 0:
        head = (command.strip().splitlines() or [""])[0]
        _record(room_dir, "step", f"Command failed (exit {exit_code}): {_one_line(_redact(head), COMMAND_CHARS)}",
                keywords=("command", "failed"), session_id=session_id, task_id=task_id)
    output = data.get("output")
    if not isinstance(output, str) or not output:
        return
    summaries, commits = [], []
    for line in _ANSI.sub("", output).splitlines():
        if len(summaries) < MATCHES_PER_OUTPUT and any(p.search(line) for p in _TEST_SUMMARY):
            summaries.append(line.strip())
        elif len(commits) < MATCHES_PER_OUTPUT and "git" in command and (m := _COMMIT.match(line.strip())):
            commits.append(m)
    for line in summaries:
        _record(room_dir, "result", _one_line(line, COMMAND_CHARS), keywords=("test", "summary"),
                session_id=session_id, task_id=task_id)
    for m in commits:
        branch, sha, message = m.groups()
        _record(room_dir, "step", f"Commit {sha} on {branch}: {_one_line(message, 120)}",
                keywords=("commit", sha), refs=(sha,), session_id=session_id, task_id=task_id)


def _record_writes(room_dir: Path, tool_name: str, data: dict, session_id, task_id) -> None:
    verb = "Wrote" if tool_name == "write_file" else "Patched"
    for path in data.get("files_modified") or ():
        try:
            rel = str(Path(path).resolve().relative_to(room_dir))
        except (TypeError, ValueError):
            rel = str(path)
        _record(room_dir, "step", f"{verb} {rel}", keywords=("file", tool_name), refs=(rel,),
                session_id=session_id, task_id=task_id)


def _on_post_tool_call(tool_name=None, args=None, result=None, session_id=None, task_id=None, **_):
    try:
        room_dir = _room_dir()
        if room_dir is None or tool_name == "ledger":
            return
        data = _as_dict(result)
        if data is None:
            return
        if is_todo_tool_name(tool_name) and isinstance(data.get("todos"), list):
            _record_plan(room_dir, data, session_id, task_id)
        elif tool_name == "terminal":
            command = (args or {}).get("command") if isinstance(args, dict) else None
            _record_terminal(room_dir, command if isinstance(command, str) else "", data, session_id, task_id)
        elif tool_name in ("write_file", "patch") and not data.get("error"):
            _record_writes(room_dir, tool_name, data, session_id, task_id)
    except Exception as exc:
        logger.debug("room-ledger: post_tool_call skipped: %s", exc)


def _on_session_start(session_id=None, platform=None, **_):
    try:
        room_dir = _room_dir()
        if room_dir is None or not session_id:
            return
        with _lock:
            if (room_dir, session_id) in _started:
                return
            _started.add((room_dir, session_id))
        _record(room_dir, "step", f"Session started ({platform})" if platform else "Session started",
                keywords=("session", "start"), session_id=session_id)
    except Exception as exc:
        logger.debug("room-ledger: on_session_start skipped: %s", exc)


def _on_session_finalize(session_id=None, **_):
    """The real end of a session (``on_session_end`` fires after every turn); no room is bound here."""
    try:
        with _lock:
            room_dir = _session_rooms.get(session_id) if session_id else None
            if room_dir is None:
                return
            _record(room_dir, "step", "Session ended", keywords=("session", "end"), session_id=session_id)
            del _session_rooms[session_id]
            _started.discard((room_dir, session_id))
            _plan_seen.difference_update({k for k in _plan_seen if k[:2] == (room_dir, str(session_id))})
    except Exception as exc:
        logger.debug("room-ledger: on_session_finalize skipped: %s", exc)


def _on_session_end(**_):
    """After every turn (``on_session_end`` fires per turn): rebuild the room memory if the ledger changed."""
    try:
        room_dir = _room_dir()
        if room_dir is not None:
            _room_memory().refresh(room_dir)
    except Exception as exc:
        logger.debug("room-ledger: on_session_end skipped: %s", exc)


def _room_memory():
    """The sibling ``room_memory`` module (plugins load by file path, not as a package)."""
    global _ROOM_MEMORY
    if _ROOM_MEMORY is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("phi_room_ledger_memory", Path(__file__).with_name("room_memory.py"))
        _ROOM_MEMORY = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_ROOM_MEMORY)
    return _ROOM_MEMORY


_ROOM_MEMORY = None


def _on_pre_llm_call(**_):
    """Recent decisions and open blockers/todos of the bound room, for the user message."""
    try:
        room_dir = _room_dir()
        ledger = None if room_dir is None else open_ledger(room_dir, create=False)
        if ledger is None:
            return None
        items = ledger.open_items(limit=INJECT_ENTRIES)
        chosen = [e for e in items if e["kind"] == "blocker"]
        rest = [e for e in items if e["kind"] == "todo"] + ledger.recent(("decision",), limit=INJECT_ENTRIES)
        rest.sort(key=lambda e: (e["ts"], e["id"]), reverse=True)
        chosen = (chosen + rest)[:INJECT_ENTRIES]
        lines, size = [FIXED_LINE], len(FIXED_LINE)
        for entry in chosen:
            line = f"{ledger_ref(entry['id'])} {entry['kind']} {_one_line(entry['text'], LINE_CHARS)}"
            if size + 1 + len(line) > INJECT_CHARS:
                break
            lines.append(line)
            size += 1 + len(line)
        return {"context": "\n".join(lines)} if len(lines) > 1 else None
    except Exception as exc:
        logger.debug("room-ledger: pre_llm_call skipped: %s", exc)
        return None


def _entry_id(value) -> int:
    try:
        return int(str(value).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise ValueError("id must be a ledger entry id such as 12 or #12") from None


def _keyword_list(value, *, required: bool) -> list[str] | None:
    if value is None and not required:
        return None
    if isinstance(value, str):
        value = re.split(r"[,\s]+", value)
    words = [str(v).strip() for v in value or () if str(v).strip()]
    if not 2 <= len(words) <= 5:
        raise ValueError("keywords must be 2-5 words")
    return [_redact(w) for w in words]


def _ref_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    return [_redact(v) for v in value or () if str(v).strip()]


def _brief(ledger, entry: dict) -> dict:
    out = {"id": entry["id"], "ref": ledger_ref(entry["id"]),
           "when": datetime.fromtimestamp(entry["ts"]).strftime("%Y-%m-%d %H:%M"), "kind": entry["kind"],
           "text": entry["text"], "status": entry["status"], "keywords": entry["keywords"], "refs": entry["refs"]}
    if entry["status"] == "superseded":
        out["superseded_by"] = (ledger.get(entry["id"]) or {}).get("superseded_by")
    return out


def _handle_ledger(args: dict, session_id=None, task_id=None, **_) -> str:
    room_dir = _room_dir()
    if room_dir is None:
        return tool_error("No room is bound to this chat, so there is no room ledger.")
    args = args if isinstance(args, dict) else {}
    action = args.get("action")
    try:
        if action == "add":
            kind = args.get("kind") or "note"
            if kind not in TOOL_KINDS:
                raise ValueError(f"kind must be one of {', '.join(TOOL_KINDS)}")
            text = _redact(args.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            keywords = _keyword_list(args.get("keywords"), required=True)
            with _lock:
                entry_id = open_ledger(room_dir).add(text, kind, keywords=keywords, refs=_ref_list(args.get("refs")),
                                                     session_id=session_id, task_id=task_id)
                _last[room_dir] = (kind, text)
            return tool_result(id=entry_id, ref=ledger_ref(entry_id))
        if action == "search":
            q = str(args.get("q") or "").strip()
            if not q:
                raise ValueError("q is required")
            ledger = open_ledger(room_dir, create=False)
            if ledger is None:
                return tool_result(entries=[])
            k = max(1, min(int(args.get("k") or 8), 50))
            hits = ledger.search(q, k=k, include_superseded=bool(args.get("include_superseded")))
            return tool_result(entries=[_brief(ledger, h) for h in hits])
        if action in ("supersede", "done"):
            entry_id = _entry_id(args.get("id"))
            ledger = open_ledger(room_dir, create=False)
            entry = None if ledger is None else ledger.get(entry_id)
            if entry is None:
                raise ValueError(f"no ledger entry {ledger_ref(entry_id)}")
            if action == "done":
                if entry["kind"] not in ("todo", "blocker"):
                    raise ValueError("done closes a todo or blocker only")
                if not ledger.mark_done(entry_id):
                    raise ValueError(f"{ledger_ref(entry_id)} is not open")
                return tool_result(id=entry_id, status="done")
            text = _redact(args.get("text") or "").strip()
            if not text:
                raise ValueError("text is required")
            with _lock:
                new_id = ledger.supersede(entry_id, text, keywords=_keyword_list(args.get("keywords"), required=False),
                                          refs=_ref_list(args.get("refs")), session_id=session_id)
                _last[room_dir] = (entry["kind"], text)
            return tool_result(id=new_id, ref=ledger_ref(new_id), supersedes=entry_id)
        return tool_error("action must be add, search, supersede or done")
    except (KeyError, ValueError) as exc:
        return tool_error(str(exc).strip("'\""))


def register(ctx) -> None:
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("pre_llm_call", _on_pre_llm_call)
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_finalize", _on_session_finalize)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_tool(name="ledger", toolset="todo", schema=LEDGER_SCHEMA, handler=_handle_ledger, emoji="📒")
    logger.debug("room-ledger: registered")

"""The Phase A media worker as an asyncio subprocess speaking JSON lines (see worker/call_worker.py)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import AsyncIterator

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).parent / "worker" / "call_worker.py"


def _env(extra: dict[str, str]) -> dict[str, str]:
    # The gateway's environment carries its Matrix and provider secrets; the worker needs none of them.
    keep = {k: v for k, v in os.environ.items()
            if k in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR") or k.lower().endswith("_proxy")}
    return {**keep, **extra}


class Worker:
    def __init__(self, python: str, env: dict[str, str]):
        self.python, self.env = python, env
        self.proc: asyncio.subprocess.Process | None = None
        self._stderr: asyncio.Task | None = None

    async def start(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            self.python, str(SCRIPT), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, env=_env(self.env), limit=1 << 20)
        self._stderr = asyncio.create_task(self._pump_stderr())

    async def _pump_stderr(self) -> None:
        # Worker logs are already redacted by the worker (keys/JWT never appear).
        while line := await self.proc.stderr.readline():
            text = line.decode(errors="replace").rstrip()
            (logger.warning if (" ERROR " in text or " WARNING " in text) else logger.debug)("worker: %s", text)

    async def send(self, cmd: str, **args) -> None:
        if self.proc is None or self.proc.stdin.is_closing():
            return
        self.proc.stdin.write((json.dumps({"cmd": cmd, **args}, ensure_ascii=False) + "\n").encode())
        try:
            await self.proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            logger.warning("matrix-call: worker stdin closed, %s dropped", cmd)

    async def events(self) -> AsyncIterator[dict]:
        """The worker's events until it exits. A line over the stream limit, not UTF-8 JSON or not an object
        raises (ValueError): the stream is broken and the caller hangs up."""
        while line := await self.proc.stdout.readline():
            ev = json.loads(line)
            if not isinstance(ev, dict):
                raise ValueError("worker output is not a JSON object")
            yield ev

    async def close(self, timeout: float = 5.0) -> None:
        """Leave the room and end the process; a worker that does not exit in time is killed."""
        if self.proc is None:
            return
        await self.send("leave")
        if not self.proc.stdin.is_closing():
            self.proc.stdin.close()  # EOF is the worker's second way to leave
        try:
            await asyncio.wait_for(self.proc.wait(), timeout)
        except asyncio.TimeoutError:
            logger.warning("matrix-call: worker did not exit in %.0f s, killing it", timeout)
            self.proc.kill()
            await self.proc.wait()
        if self._stderr is not None:
            await asyncio.gather(self._stderr, return_exceptions=True)

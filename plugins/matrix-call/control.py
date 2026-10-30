"""The control socket: how the agent places a call (``tools/call.py``). A unix socket in ``$PHI_HOME/run/``, owner
only; one JSON line in, one JSON line out:

    {"cmd": "call", "user": "@alice:example.org"}  → {"ok": true, "status": "ringing", "room_id": "!…", …}
    {"cmd": "status"}                             → the call state (Calls.status)

A call goes to the user's DM room with us, which the plugin picks; the request cannot name a room.

It runs on the gateway loop, and a connection never holds it up: each one is a task of its own with a read deadline."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SOCKET = "matrix-call.sock"
LINE_LIMIT = 4096  # a request is one short line
READ_S = 5  # a client that connects and says nothing is dropped after this


def socket_path() -> Path:
    from phi_constants import get_phi_home
    return Path(get_phi_home()) / "run" / SOCKET


class Server:
    def __init__(self, controller):
        self.controller = controller  # () → the Calls of the wired Matrix client, or None
        self.path = socket_path()
        self.server: asyncio.base_events.Server | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.closed = False

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        loop.create_task(self._start())

    async def _start(self) -> None:
        try:
            # Whoever can connect can make the gateway place a call: the directory and the socket are owner only.
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            self.path.parent.chmod(0o700)
            # A socket file left by a gateway that died is replaced; asyncio removes it when it is a socket.
            server = await asyncio.start_unix_server(self._handle, self.path, limit=LINE_LIMIT, start_serving=False)
            os.chmod(self.path, 0o600)
            if self.closed:  # unloaded meanwhile
                server.close()
                return
            self.server = server
            await server.start_serving()
            logger.info("matrix-call: control socket at %s", self.path)
        except Exception as exc:
            logger.error("matrix-call: no control socket at %s: %s: %s", self.path, type(exc).__name__, exc)

    def close(self) -> None:
        """On the loop. asyncio removes the socket file, unless another server has bound the path since."""
        self.closed = True
        if self.server is not None:
            self.server.close()
            self.server = None

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), READ_S)
            except asyncio.TimeoutError:
                return
            except ValueError:  # longer than LINE_LIMIT
                reply = {"ok": False, "error": "request too long"}
            else:
                try:
                    reply = await self._reply(line)
                except Exception:
                    logger.exception("matrix-call: control request failed")
                    reply = {"ok": False, "error": "internal error"}
            writer.write(json.dumps(reply, ensure_ascii=False).encode() + b"\n")
            await writer.drain()
        except Exception as exc:  # the client went away
            logger.info("matrix-call: control connection dropped: %s: %s", type(exc).__name__, exc)
        finally:
            writer.close()

    async def _reply(self, line: bytes) -> dict:
        try:
            req = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "not a JSON line"}
        cmd = req.get("cmd") if isinstance(req, dict) else None
        if cmd not in ("call", "status"):
            return {"ok": False, "error": "unknown command"}
        calls = self.controller()
        if calls is None:
            return {"ok": False, "error": "Matrix is not connected"}
        if cmd == "status":
            return calls.status()
        if "room_id" in req:  # refused rather than ignored: a caller that names a room expects it to be used
            return {"ok": False, "error": "room_id is not accepted: a call goes to the user's DM room"}
        user = req.get("user")
        if not isinstance(user, str):
            return {"ok": False, "error": "call needs user as a string"}
        return await calls.ring(user)

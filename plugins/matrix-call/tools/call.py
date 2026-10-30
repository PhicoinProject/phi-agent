#!/usr/bin/env python3
"""Ring someone through the gateway's matrix-call plugin, and wait until they join the call.

    python3 <plugin>/tools/call.py --user @alice:example.org

It rings in the user's DM room with the bot, the only room a call goes to. Exit code: 0 the callee joined the call;
2 not answered (no answer within the ring, or declined); 1 error (printed: not allowed, busy, no DM room, the gateway
not reachable…).
Stdlib only, so any python3 runs it."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

SOCKET = "matrix-call.sock"
CALL_S = 60  # the reply comes once it rings: our membership, the LiveKit join and the ring are out
POLL_S = 1
WAIT_S = 100  # the ring lasts 90 s
GAP_S = 30  # a reload of the plugin takes the socket away until the next instance is wired; it keeps the call


def socket_path() -> Path:
    # Where the plugin listens: $PHI_HOME/run/. The plugin is $PHI_HOME/plugins/matrix-call/, for a shell
    # without PHI_HOME.
    home = os.environ.get("PHI_HOME", "").strip()
    return (Path(home) if home else Path(__file__).resolve().parents[3]) / "run" / SOCKET


def request(path: Path, req: dict, timeout: float) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(str(path))
        s.sendall(json.dumps(req).encode() + b"\n")
        line = s.makefile("rb").readline()
    reply = json.loads(line)
    if not isinstance(reply, dict):
        raise ValueError(f"unexpected reply: {line[:200]!r}")
    return reply


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ring a Matrix user (Element X call) through Phi.")
    parser.add_argument("--user", required=True, help="the user to ring, e.g. @alice:example.org")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse exits 2 on a usage error; 2 means "not answered" here
        return 0 if exc.code == 0 else 1
    path = socket_path()
    try:
        reply = request(path, {"cmd": "call", "user": args.user}, CALL_S)
        if not reply.get("ok"):
            print(f"call failed: {reply.get('error')}")
            return 1
        call_id = reply.get("call_id")
        print(f"ringing {args.user} in {reply.get('room_id')} (call {call_id})", flush=True)
        deadline = time.monotonic() + WAIT_S
        reached = time.monotonic()
        while time.monotonic() < deadline:
            time.sleep(POLL_S)
            try:
                placed = request(path, {"cmd": "status"}, CALL_S).get("placed") or {}
            except OSError:
                if time.monotonic() - reached > GAP_S:
                    raise
                continue
            reached = time.monotonic()
            if placed.get("call_id") != call_id:
                print("call failed: the gateway no longer knows this call")
                return 1
            outcome = placed.get("outcome")
            if outcome == "answered":
                print(f"{args.user} answered")
                return 0
            if outcome in ("no_answer", "declined"):
                print(f"not answered: {outcome}")
                return 2
            if outcome == "failed":
                print(f"call failed: {placed.get('reason')}")
                return 1
        print(f"not answered in {WAIT_S} s")
        return 2
    except (OSError, ValueError) as exc:
        print(f"call failed: {path}: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""YAW/2 signaling server (protocol spec §5).

A WebSocket relay that introduces peers within a (hashed) network and forwards
opaque, end-to-end-sealed blobs between them. It authenticates each peer by an
Ed25519 signature over a server nonce, tracks presence, and routes `to`/`from`.
It never sees inside the sealed boxes — no SDP, no candidate IPs, no content.

Run:  SIG_PORT=8077 python3 server.py   (binds 127.0.0.1; nginx WSS-proxies to it)
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets

import websockets
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

VERSION = "yaw/2.0"
MAX_MSG = 1 << 16            # 64 KiB cap on any signaling frame
JOIN_TIMEOUT = 15           # seconds to authenticate after connecting
_HEX = set("0123456789abcdef")

# net (sha256 hex) -> { id (ed25519 pubkey hex) -> websocket }
rooms: dict[str, dict[str, object]] = {}


def _valid_hex(s, n) -> bool:
    return isinstance(s, str) and len(s) == n and all(c in _HEX for c in s.lower())


async def _broadcast(net, obj, exclude=None):
    data = json.dumps(obj)
    for pid, ws in list(rooms.get(net, {}).items()):
        if pid == exclude:
            continue
        try:
            await ws.send(data)
        except Exception:
            pass


async def handler(ws, *_):
    # -- challenge / join --
    nonce = secrets.token_bytes(32)
    await ws.send(json.dumps({"v": VERSION, "type": "challenge", "nonce": nonce.hex()}))

    node_id = net = None
    try:
        raw = await asyncio.wait_for(ws.recv(), timeout=JOIN_TIMEOUT)
        msg = json.loads(raw)
        if msg.get("type") != "join":
            raise ValueError("expected join")
        node_id = str(msg["id"]).lower()
        net = str(msg["net"]).lower()
        sig = bytes.fromhex(msg["sig"])
        if not (_valid_hex(node_id, 64) and _valid_hex(net, 64)):
            raise ValueError("bad id/net")
        # signature is over (nonce_bytes || ascii(net))
        VerifyKey(bytes.fromhex(node_id)).verify(nonce + net.encode(), sig)
    except (asyncio.TimeoutError, BadSignatureError, ValueError, KeyError,
            json.JSONDecodeError, Exception):
        try:
            await ws.close(code=4001, reason="auth failed")
        except Exception:
            pass
        return

    # -- register + presence --
    room = rooms.setdefault(net, {})
    old = room.get(node_id)
    if old is not None and old is not ws:
        try:
            await old.close(code=4002, reason="replaced")
        except Exception:
            pass
    room[node_id] = ws
    await ws.send(json.dumps({"type": "joined",
                              "peers": [p for p in room if p != node_id]}))
    await _broadcast(net, {"type": "peer-join", "id": node_id}, exclude=node_id)

    # -- relay loop --
    try:
        async for raw in ws:
            if isinstance(raw, bytes) or len(raw) > MAX_MSG:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "to":
                to = str(msg.get("to", "")).lower()
                box = msg.get("box")
                if not (_valid_hex(to, 64) and isinstance(box, str) and len(box) <= MAX_MSG):
                    continue
                target = rooms.get(net, {}).get(to)
                if target is not None:
                    await target.send(json.dumps({"type": "from", "from": node_id, "box": box}))
                else:
                    await ws.send(json.dumps({"type": "no-peer", "to": to}))
            # all other types are ignored (forward-compatible)
    except Exception:
        pass
    finally:
        if rooms.get(net, {}).get(node_id) is ws:
            del rooms[net][node_id]
            if not rooms[net]:
                rooms.pop(net, None)
            await _broadcast(net, {"type": "peer-leave", "id": node_id})


async def main():
    host = os.environ.get("SIG_HOST", "127.0.0.1")
    port = int(os.environ.get("SIG_PORT", "8077"))
    async with websockets.serve(handler, host, port, max_size=MAX_MSG,
                                ping_interval=30, ping_timeout=30):
        print(f"[signaling] yaw/2 on ws://{host}:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

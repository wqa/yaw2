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
import time

import websockets
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError

VERSION = "yaw/2.0"
MAX_MSG = 1 << 16            # 64 KiB cap on any signaling frame
JOIN_TIMEOUT = 15           # seconds to authenticate after connecting
_HEX = set("0123456789abcdef")
STATUS_FILE = os.environ.get("SIG_STATUS",
                             os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json"))

# net (sha256 hex) -> { id (ed25519 pubkey hex) -> websocket }
rooms: dict[str, dict[str, object]] = {}
# (net, id) -> { "ip": str, "since": float }  — for the `yawpeers` admin tool
meta: dict = {}

# --- rate limiting (single asyncio loop -> no locks). Conservative: aimed at
# floods, not normal use. A real session makes a handful of connections + frames.
CONN_WINDOW = 60.0          # seconds
CONN_MAX = 30               # new connections per IP per window
CONC_MAX = 40               # concurrent connections per IP
MSG_WINDOW = 10.0           # seconds
MSG_MAX = 300               # relayed frames per connection per window
_conn_hist: dict = {}       # ip -> [recent connect monotonic times]
_conc: dict = {}            # ip -> concurrent connection count


def _allow_connection(ip: str) -> bool:
    now = time.monotonic()
    hist = [t for t in _conn_hist.get(ip, []) if now - t < CONN_WINDOW]
    hist.append(now)
    _conn_hist[ip] = hist
    return len(hist) <= CONN_MAX and _conc.get(ip, 0) < CONC_MAX


def _client_ip(ws) -> str:
    """Real peer IP — via nginx X-Real-IP/X-Forwarded-For, else the socket."""
    try:
        h = ws.request_headers
        xri = h.get("X-Real-IP")
        if xri:
            return xri.strip()
        xff = h.get("X-Forwarded-For")
        if xff:
            return xff.split(",")[0].strip()
    except Exception:
        pass
    ra = getattr(ws, "remote_address", None)
    return ra[0] if ra else "?"


def _write_status():
    """Atomically write a snapshot of current connections for the admin tool."""
    try:
        data = {"updated": time.time(),
                "peers": [{"id": pid, "net": pnet, "ip": m["ip"], "since": m["since"]}
                          for (pnet, pid), m in meta.items()]}
        tmp = STATUS_FILE + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, STATUS_FILE)
    except Exception:
        pass


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
    ip = _client_ip(ws)
    if not _allow_connection(ip):
        try:
            await ws.close(code=4003, reason="rate limited")
        except Exception:
            pass
        return
    _conc[ip] = _conc.get(ip, 0) + 1
    try:
        await _serve(ws, ip)
    finally:
        if _conc.get(ip, 0) <= 1:
            _conc.pop(ip, None)
        else:
            _conc[ip] -= 1


async def _serve(ws, ip):
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
    meta[(net, node_id)] = {"ip": ip, "since": time.time()}
    _write_status()
    await ws.send(json.dumps({"type": "joined",
                              "peers": [p for p in room if p != node_id]}))
    await _broadcast(net, {"type": "peer-join", "id": node_id}, exclude=node_id)

    # -- relay loop --
    msg_times: list = []
    try:
        async for raw in ws:
            now = time.monotonic()
            msg_times = [t for t in msg_times if now - t < MSG_WINDOW]
            msg_times.append(now)
            if len(msg_times) > MSG_MAX:
                continue  # drop frames over the per-connection rate
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
            meta.pop((net, node_id), None)
            if not rooms[net]:
                rooms.pop(net, None)
            await _broadcast(net, {"type": "peer-leave", "id": node_id})
            _write_status()


async def main():
    host = os.environ.get("SIG_HOST", "127.0.0.1")
    port = int(os.environ.get("SIG_PORT", "8077"))
    async with websockets.serve(handler, host, port, max_size=MAX_MSG,
                                ping_interval=30, ping_timeout=30):
        print(f"[signaling] yaw/2 on ws://{host}:{port}")
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())

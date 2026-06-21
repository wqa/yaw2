#!/usr/bin/env python3
"""Local test: spin up the signaling server, run two authenticated clients,
and verify a sealed blob relays from A to B (plus presence)."""

from __future__ import annotations

import asyncio
import hashlib
import json

import websockets
from nacl.signing import SigningKey

import server


def net_hash(name: str) -> str:
    return hashlib.sha256(("yaw2-net:" + name).encode()).hexdigest()


async def join(ws, sk: SigningKey, net: str) -> str:
    challenge = json.loads(await ws.recv())
    assert challenge["type"] == "challenge"
    nonce = bytes.fromhex(challenge["nonce"])
    node_id = sk.verify_key.encode().hex()
    sig = sk.sign(nonce + net.encode()).signature.hex()
    await ws.send(json.dumps({"type": "join", "id": node_id, "net": net, "sig": sig}))
    joined = json.loads(await ws.recv())
    assert joined["type"] == "joined", joined
    return node_id


async def main():
    net = net_hash("test")
    a_sk, b_sk = SigningKey.generate(), SigningKey.generate()

    async with websockets.serve(server.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"

        async with websockets.connect(url) as a, websockets.connect(url) as b:
            a_id = await join(a, a_sk, net)
            b_id = await join(b, b_sk, net)
            print("  both clients authenticated (Ed25519 join) OK")

            # A should observe B joining (presence).
            ev = json.loads(await asyncio.wait_for(a.recv(), timeout=3))
            assert ev["type"] == "peer-join" and ev["id"] == b_id, ev
            print("  presence (peer-join) OK")

            # A relays a sealed blob to B.
            await a.send(json.dumps({"type": "to", "to": b_id, "box": "deadbeefcafe"}))
            got = json.loads(await asyncio.wait_for(b.recv(), timeout=3))
            assert got["type"] == "from" and got["from"] == a_id and got["box"] == "deadbeefcafe", got
            print("  sealed relay A->B OK")

            # Unknown destination -> no-peer.
            await a.send(json.dumps({"type": "to", "to": "f" * 64, "box": "00"}))
            np = json.loads(await asyncio.wait_for(a.recv(), timeout=3))
            assert np["type"] == "no-peer", np
            print("  no-peer for offline target OK")

        # B left -> A gets peer-leave (reconnect A to observe a clean room).
    # Bad signature is rejected.
    async with websockets.serve(server.handler, "127.0.0.1", 0) as srv:
        port = srv.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}") as c:
            challenge = json.loads(await c.recv())
            bad_id = SigningKey.generate().verify_key.encode().hex()
            await c.send(json.dumps({"type": "join", "id": bad_id, "net": net,
                                     "sig": "00" * 64}))
            try:
                await asyncio.wait_for(c.recv(), timeout=3)
                closed = False
            except (websockets.ConnectionClosed, asyncio.TimeoutError):
                closed = True
            assert closed, "bad signature should be rejected"
            print("  bad-signature rejection OK")

    print("[signaling] local test all good ✓")


if __name__ == "__main__":
    asyncio.run(main())

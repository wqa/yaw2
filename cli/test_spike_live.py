#!/usr/bin/env python3
"""Spike: two YAW/2 nodes meet through the LIVE signaling + STUN, form an
authenticated WebRTC DataChannel, chat both ways, and transfer a file —
verifying §5–§9 end to end against production infra.

Both peers run here (same machine), but signaling (wss://<anchor-host>/…) and STUN
(stun:<anchor-host>:3478) are the real deployed services. True cross-NAT validation is
the later multi-device test.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash

from yaw2.config import signal_url
SIGNAL_URL = signal_url()


async def main():
    net = net_hash("spike-" + os.urandom(4).hex())   # fresh net so we're alone
    a_id, b_id = Identity(), Identity()
    events = {"a": [], "b": []}

    def mk(tag):
        def on_event(kind, **kw):
            events[tag].append((kind, kw))
        return on_event

    node_a = Node(SIGNAL_URL, a_id, net, mk("a"))
    node_b = Node(SIGNAL_URL, b_id, net, mk("b"))

    print(f"  net  {net[:16]}…")
    print(f"  A id {a_id.short}")
    print(f"  B id {b_id.short}")

    await node_a.start()
    await node_b.start()   # B sees A present -> the smaller id offers

    async def wait(tag, kind, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for k, kw in events[tag]:
                if k == kind:
                    return kw
            await asyncio.sleep(0.1)
        raise AssertionError(f"[{tag}] event {kind!r} not seen (events={events[tag]})")

    # Both sides confirm an identity-verified DataChannel.
    ca = await wait("a", "connected")
    cb = await wait("b", "connected")
    assert ca["verified"] and cb["verified"], (ca, cb)
    assert ca["peer"] == b_id.id and cb["peer"] == a_id.id
    print("  ICE+DTLS connected & Ed25519-verified BOTH ways ✓")

    # Chat both directions.
    pa = node_a.peers[b_id.id]
    pb = node_b.peers[a_id.id]
    pa.send_chat("hello from A")
    pb.send_chat("hello from B")
    assert (await wait("b", "chat"))["text"] == "hello from A"
    assert (await wait("a", "chat"))["text"] == "hello from B"
    print("  chat both ways over the DataChannel ✓")

    # File A -> B, hash-verified over a dedicated channel.
    blob = os.urandom(200 * 1024)
    pa.send_file("spike.bin", blob)
    fr = await wait("b", "file-recv")
    assert fr["ok"] and fr["size"] == len(blob) and fr["data"] == blob, \
        (fr["ok"], fr["size"], len(blob))
    print(f"  file A->B ({fr['size']} B) received & SHA-256 verified ✓")

    await node_a.sig.close()
    await node_b.sig.close()
    print("[spike] LIVE Python<->Python over production signaling+STUN ✓")


if __name__ == "__main__":
    asyncio.run(main())

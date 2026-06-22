#!/usr/bin/env python3
"""Live test of yaw/2.1 forward-secret signaling (YIP-0001):

  1. two 2.1 nodes exchange `ekey` and seal offer/answer with per-session
     ephemeral X25519 -> the session is forward-secret;
  2. a 2.1 node + a (simulated) 2.0 node fall back to static 2.0 sealing and still
     connect -> non-FS, opportunistic backward-compat (§6.1).

Run over production signaling + STUN. `forward_secret=False` makes a node behave
exactly like a 2.0 peer (no ekey, always static)."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash
from yaw2.config import signal_url

SIGNAL_URL = signal_url()


async def connect_pair(fs_a, fs_b):
    net = net_hash("fs-" + os.urandom(4).hex())
    a, b = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))
    na = Node(SIGNAL_URL, a, net, mk("a"), forward_secret=fs_a)
    nb = Node(SIGNAL_URL, b, net, mk("b"), forward_secret=fs_b)
    await na.start(); await nb.start()

    async def wait(tag, kind, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for k, kw in ev[tag]:
                if k == kind:
                    return kw
            await asyncio.sleep(0.1)
        raise AssertionError(f"[{tag}] {kind!r} not seen")

    ca, cb = await wait("a", "connected"), await wait("b", "connected")
    # prove the link carries data
    na.peers[b.id].send_chat("hi")
    msg = await wait("b", "chat")
    await na.sig.close(); await nb.sig.close()
    return ca, cb, msg["text"]


async def main():
    print("  [1] two 2.1 nodes …")
    ca, cb, txt = await connect_pair(True, True)
    assert ca["verified"] and cb["verified"] and txt == "hi", (ca, cb, txt)
    assert ca["fs"] and cb["fs"], f"expected forward-secret, got fs={ca['fs']}/{cb['fs']}"
    print("      connected, verified, chat ok, and BOTH forward-secret ✓")

    print("  [2] 2.1 node + simulated 2.0 node …")
    ca, cb, txt = await connect_pair(True, False)
    assert ca["verified"] and cb["verified"] and txt == "hi", (ca, cb, txt)
    assert not ca["fs"] and not cb["fs"], f"expected fallback non-FS, got fs={ca['fs']}/{cb['fs']}"
    print("      connected, verified, chat ok, fell back to non-FS (2.0 compat) ✓")

    print("[fs] yaw/2.1 forward-secret signaling + 2.0 fallback verified live ✓")


if __name__ == "__main__":
    asyncio.run(main())

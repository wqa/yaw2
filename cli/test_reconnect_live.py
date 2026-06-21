#!/usr/bin/env python3
"""Live test: signaling auto-reconnect. Two nodes connect; we force-drop one's
signaling socket; it re-handshakes and resyncs, and — because media is P2P — the
existing chat DataChannel keeps working across the blip."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash
from yaw2.config import signal_url

SIGNAL_URL = signal_url()


async def main():
    net = net_hash("reconnect-" + os.urandom(4).hex())
    a, b = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))
    node_a = Node(SIGNAL_URL, a, net, mk("a"))
    node_b = Node(SIGNAL_URL, b, net, mk("b"))
    await node_a.start()
    await node_b.start()

    async def wait(tag, kind, pred=lambda kw: True, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for k, kw in ev[tag]:
                if k == kind and pred(kw):
                    return kw
            await asyncio.sleep(0.1)
        raise AssertionError(f"[{tag}] {kind!r} not seen")

    await wait("b", "connected", lambda kw: kw["verified"])
    await wait("a", "connected", lambda kw: kw["verified"])
    print("  both connected & verified ✓")

    # baseline chat works
    node_a.peers[b.id].send_chat("before blip")
    await wait("b", "chat", lambda kw: kw["text"] == "before blip")
    print("  chat A->B works before the blip ✓")

    # force-drop A's signaling socket
    old_ws = node_a.sig.ws
    await node_a.sig.ws.close()
    print("  dropped A's signaling socket — waiting for auto-reconnect…")
    await wait("a", "signaling", lambda kw: kw["state"] == "reconnected", timeout=20)
    assert node_a.sig.ws is not old_ws, "ws not replaced"
    assert b.id in node_a.sig.peers, "presence not resynced"
    print("  A re-handshaked and resynced presence ✓")

    # the P2P DataChannel survived the signaling outage
    node_a.peers[b.id].send_chat("after blip")
    await wait("b", "chat", lambda kw: kw["text"] == "after blip")
    print("  chat A->B still works after reconnect (P2P link survived) ✓")

    await node_a.sig.close(); await node_b.sig.close()
    print("[reconnect] signaling self-heals; media unaffected ✓")


if __name__ == "__main__":
    asyncio.run(main())

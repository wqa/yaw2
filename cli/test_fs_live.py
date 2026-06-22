#!/usr/bin/env python3
"""Live test of yaw/2.1 forward-secret signaling (YIP-0001) + the 2.0/2.1 mix:

  1. two 2.1 nodes -> forward-secret session;
  2. a 2.1 node + a (simulated) 2.0 node -> static 2.0 fallback, still connects;
  3. the cutover: a require-FS node REFUSES a 2.0 peer but still connects to 2.1.

`forward_secret=False` behaves exactly like a 2.0 peer; `require_fs=True` is the
switch that refuses non-FS sessions once everyone has upgraded (§6.1)."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash
from yaw2.config import signal_url

SIGNAL_URL = signal_url()


async def run_pair(opts_a, opts_b, settle=8):
    net = net_hash("fs-" + os.urandom(4).hex())
    a, b = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))
    na = Node(SIGNAL_URL, a, net, mk("a"), **opts_a)
    nb = Node(SIGNAL_URL, b, net, mk("b"), **opts_b)
    await na.start(); await nb.start()

    def find(tag, kind):
        return next((kw for k, kw in ev[tag] if k == kind), None)

    async def wait(tag, kind, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            if find(tag, kind):
                return find(tag, kind)
            await asyncio.sleep(0.1)
        return None

    # give it time either to connect or to refuse
    ca = await wait("a", "connected", timeout=settle)
    if ca:
        na.peers[b.id].send_chat("hi")
        await wait("b", "chat")
    else:
        await asyncio.sleep(settle)
    result = (find("a", "connected"), find("b", "connected"),
              find("a", "chat") or find("b", "chat"),
              find("a", "fs-refused") or find("b", "fs-refused"))
    await na.sig.close(); await nb.sig.close()
    return result


async def main():
    print("  [1] two 2.1 nodes …")
    ca, cb, _, _ = await run_pair(dict(forward_secret=True), dict(forward_secret=True))
    assert ca and cb and ca["fs"] and cb["fs"], (ca, cb)
    print("      connected + BOTH forward-secret ✓")

    print("  [2] 2.1 node + simulated 2.0 node …")
    ca, cb, chat, _ = await run_pair(dict(forward_secret=True), dict(forward_secret=False))
    assert ca and cb and not ca["fs"] and not cb["fs"] and chat, (ca, cb, chat)
    print("      connected, fell back to non-FS (2.0 compat) ✓")

    print("  [3a] require-FS node + 2.0 node -> must REFUSE …")
    ca, cb, _, refused = await run_pair(dict(forward_secret=True, require_fs=True),
                                        dict(forward_secret=False))
    assert not ca and not cb and refused, (ca, cb, refused)
    print("      no session formed; fs-refused raised ✓")

    print("  [3b] require-FS node + 2.1 node -> still connects (FS) …")
    ca, cb, _, _ = await run_pair(dict(forward_secret=True, require_fs=True),
                                  dict(forward_secret=True))
    assert ca and cb and ca["fs"] and cb["fs"], (ca, cb)
    print("      connected + forward-secret ✓")

    print("[fs] 2.1 forward-secrecy, 2.0 fallback, and the require-FS cutover all verified live ✓")


if __name__ == "__main__":
    asyncio.run(main())

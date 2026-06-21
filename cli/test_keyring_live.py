#!/usr/bin/env python3
"""Live test of the keyring gate: two nodes in the same network do NOT connect
until each has accepted the other's id — then they do, identity-verified.
Runs over the production signaling + STUN."""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Keyring, Node, net_hash

from yaw2.config import signal_url
SIGNAL_URL = signal_url()


async def main():
    net = net_hash("keyring-" + os.urandom(4).hex())
    a, b = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))

    krA, krB = Keyring(), Keyring()      # in-memory, both start empty (trust nobody)
    node_a = Node(SIGNAL_URL, a, net, mk("a"), keyring=krA)
    node_b = Node(SIGNAL_URL, b, net, mk("b"), keyring=krB)
    await node_a.start()
    await node_b.start()

    def seen(tag, kind):
        return [kw for k, kw in ev[tag] if k == kind]

    async def wait(tag, kind, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            if seen(tag, kind):
                return seen(tag, kind)[0]
            await asyncio.sleep(0.1)
        raise AssertionError(f"[{tag}] {kind!r} not seen: {ev[tag]}")

    # Phase 1: present in the same net, but no trust -> no session.
    await asyncio.sleep(6)
    assert not seen("a", "connected") and not seen("b", "connected"), "connected without trust!"
    assert seen("a", "untrusted") or seen("b", "untrusted"), "expected an untrusted nudge"
    print("  no trust -> no session; untrusted nudge raised ✓")

    # Phase 2: mutual accept in the *harder* order — the offerer accepts first and
    # offers into the void (answerer not yet trusting), so the link only comes up
    # via the offerer's stale-retry once the answerer accepts. Exercises both paths.
    offerer, answerer = (a, b) if a.id < b.id else (b, a)
    n_off = node_a if offerer is a else node_b
    n_ans = node_a if answerer is a else node_b
    await n_off.accept(answerer.id)
    await asyncio.sleep(1)
    await n_ans.accept(offerer.id)

    ca = await wait("a", "connected")
    cb = await wait("b", "connected")
    assert ca["verified"] and cb["verified"], (ca, cb)
    print("  after mutual /accept -> connected & identity-verified both ways ✓")

    await node_a.sig.close(); await node_b.sig.close()
    print("[keyring] friend-to-friend trust gate enforced over production infra ✓")


if __name__ == "__main__":
    asyncio.run(main())

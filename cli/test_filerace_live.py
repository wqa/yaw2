#!/usr/bin/env python3
"""Reproduce the multi-file / multi-MB transfer race and confirm the fix.

The bug: `file-done` (control channel) can overtake the bulk bytes (the dedicated
f:<xid> channel) for large files, so the receiver hashed a half-arrived buffer and
every file FAILED. Here A shares several MB-sized files; B browses and pulls them
all at once; every one must arrive hash-verified."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash
from yaw2.config import signal_url

SIGNAL_URL = signal_url()
FILES = {f"img_{i}.bin": os.urandom((2 + i) * 1024 * 1024) for i in range(4)}  # 2..5 MB


async def main():
    net = net_hash("filerace-" + os.urandom(4).hex())
    a, b = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))

    share = tempfile.mkdtemp()
    for name, data in FILES.items():
        with open(os.path.join(share, name), "wb") as fh:
            fh.write(data)

    node_a = Node(SIGNAL_URL, a, net, mk("a"), share_dir=share)
    node_b = Node(SIGNAL_URL, b, net, mk("b"))
    await node_a.start(); await node_b.start()

    async def wait(tag, kind, pred, timeout=60):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for k, kw in ev[tag]:
                if k == kind and pred(kw):
                    return kw
            await asyncio.sleep(0.1)
        return None

    assert await wait("b", "connected", lambda kw: kw["verified"]), "no connection"
    peer_a = node_b.peers[a.id]
    peer_a.request_browse()
    assert await wait("b", "files", lambda kw: len(kw["entries"]) == len(FILES)), "browse failed"
    print(f"  browsing {len(FILES)} files; pulling them all at once…")

    for name in FILES:                      # fire all gets concurrently (the racy case)
        peer_a.request_get(name)

    got = {}
    deadline = asyncio.get_event_loop().time() + 60
    while len(got) < len(FILES) and asyncio.get_event_loop().time() < deadline:
        for k, kw in ev["b"]:
            if k == "file-recv":
                got[kw["name"]] = kw
        await asyncio.sleep(0.2)

    await node_a.sig.close(); await node_b.sig.close()

    assert len(got) == len(FILES), f"only {len(got)}/{len(FILES)} arrived: {list(got)}"
    bad = [n for n, kw in got.items() if not kw["ok"] or kw["data"] != FILES[n]]
    assert not bad, f"hash/content FAILED for: {bad}"
    total = sum(len(d) for d in FILES.values())
    print(f"  all {len(FILES)} files ({total/1e6:.0f} MB) arrived hash-verified ✓")
    print("[filerace] concurrent multi-MB transfers verify (file-done race fixed) ✓")


if __name__ == "__main__":
    asyncio.run(main())

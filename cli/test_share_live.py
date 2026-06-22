#!/usr/bin/env python3
"""Live test of the browse extension: node A shares a folder; node B browses it
and pulls a file, hash-verified — over the production signaling + STUN."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash

from yaw2.config import signal_url
SIGNAL_URL = signal_url()


async def main():
    net = net_hash("share-" + os.urandom(4).hex())
    a_id, b_id = Identity(), Identity()
    ev = {"a": [], "b": []}
    mk = lambda tag: (lambda kind, **kw: ev[tag].append((kind, kw)))

    share = tempfile.mkdtemp()
    blob = os.urandom(150 * 1024)
    with open(os.path.join(share, "doc.bin"), "wb") as fh:
        fh.write(blob)
    nested = os.urandom(80 * 1024)                       # a file one level down
    os.makedirs(os.path.join(share, "photos", "trip"))
    with open(os.path.join(share, "photos", "trip", "view.bin"), "wb") as fh:
        fh.write(nested)

    node_a = Node(SIGNAL_URL, a_id, net, mk("a"), share_dir=share)   # A shares
    node_b = Node(SIGNAL_URL, b_id, net, mk("b"))                    # B browses
    await node_a.start()
    await node_b.start()

    async def wait(tag, kind, pred=None, timeout=25):
        end = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < end:
            for k, kw in ev[tag]:
                if k == kind and (pred is None or pred(kw)):
                    return kw
            await asyncio.sleep(0.1)
        raise AssertionError(f"[{tag}] {kind!r} not seen: {ev[tag]}")

    c = await wait("b", "connected")
    assert c["verified"] and "share" in (c["caps"] or []), c
    print("  connected; A advertises the 'share' capability ✓")

    peer_a = node_b.peers[a_id.id]
    peer_a.request_browse()
    root = await wait("b", "files", lambda kw: kw.get("path", "") == "")
    names = {e["name"]: e for e in root["entries"]}
    assert names.get("doc.bin", {}).get("size") == len(blob), root
    assert names.get("photos", {}).get("dir") is True, root
    print(f"  browse /: B sees {sorted(names)} (photos is a folder) ✓")

    peer_a.request_get("doc.bin")
    fr = await wait("b", "file-recv", lambda kw: kw["name"] == "doc.bin")
    assert fr["ok"] and fr["data"] == blob, (fr["ok"], fr["size"])
    print(f"  get: B pulled doc.bin ({fr['size']} B) hash-verified ✓")

    # descend a subdirectory tree and pull a nested file
    peer_a.request_browse("photos/trip")
    sub = await wait("b", "files", lambda kw: kw.get("path") == "photos/trip")
    assert any(e["name"] == "view.bin" and e["size"] == len(nested) for e in sub["entries"]), sub
    print(f"  browse /photos/trip: B sees {[e['name'] for e in sub['entries']]} ✓")

    peer_a.request_get("photos/trip/view.bin")
    fr2 = await wait("b", "file-recv", lambda kw: kw["name"] == "view.bin")
    assert fr2["ok"] and fr2["data"] == nested, (fr2["ok"], fr2["size"])
    print(f"  get: B pulled photos/trip/view.bin ({fr2['size']} B) hash-verified ✓")

    # path-traversal attempt is refused
    peer_a.request_get("../secret")
    nf = await wait("b", "no-file", lambda kw: kw["name"] == "../secret")
    assert nf["name"] == "../secret"
    print("  security: path-traversal get refused (no-file) ✓")

    await node_a.sig.close(); await node_b.sig.close()
    print("[share] WASTE-style browse + get over production infra ✓")


if __name__ == "__main__":
    asyncio.run(main())

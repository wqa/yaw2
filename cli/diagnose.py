#!/usr/bin/env python3
"""YAW/2 connectivity self-check.

Gathers ICE candidates against the configured STUN server and reports whether you
get a public *server-reflexive* address — a quick "can others reach me?" test
without needing a second person. STUN-only/no-TURN means a peer behind symmetric
NAT or CGNAT may still fail to connect even with a reflexive address, but *no*
reflexive address at all is a strong sign this network will be hard.

  cli/.venv/bin/python cli/diagnose.py
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer
from yaw2.config import stun_url

CAND_RE = re.compile(r"a=candidate:\S+ \d+ \S+ \d+ (\S+) (\d+) typ (\w+)(?:.*raddr (\S+) rport (\d+))?")


async def main():
    stun = stun_url()
    print(f"[diagnose] STUN: {stun}")
    pc = RTCPeerConnection(RTCConfiguration([RTCIceServer(urls=stun)]))
    pc.createDataChannel("diag")
    await pc.setLocalDescription(await pc.createOffer())   # aiortc gathers here (non-trickle)

    cands = {"host": [], "srflx": [], "relay": []}
    for line in pc.localDescription.sdp.splitlines():
        m = CAND_RE.search(line)
        if m:
            addr, port, typ = m.group(1), m.group(2), m.group(3)
            cands.setdefault(typ, []).append(f"{addr}:{port}")

    print(f"  host  candidates: {', '.join(sorted(set(cands['host']))) or '(none)'}")
    print(f"  srflx candidates: {', '.join(sorted(set(cands['srflx']))) or '(none)'}")
    if cands["relay"]:
        print(f"  relay candidates: {', '.join(sorted(set(cands['relay'])))}")

    print()
    if cands["srflx"]:
        pub = sorted(set(cands["srflx"]))[0]
        print(f"  ✓ STUN works — your public (reflexive) address is {pub}")
        print("    You should be reachable on most networks. If a specific peer still")
        print("    can't connect, one of you is likely behind symmetric NAT / CGNAT —")
        print("    try a different network (e.g. not a mobile hotspot) for one side.")
    else:
        print("  ✗ No reflexive candidate. STUN is blocked, or this network won't allow")
        print("    direct peer connections. Try another network. (There is no TURN relay")
        print("    by design, so YAW can't fall back to relaying through the server.)")

    await pc.close()


if __name__ == "__main__":
    asyncio.run(main())

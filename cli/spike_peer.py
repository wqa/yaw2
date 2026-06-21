#!/usr/bin/env python3
"""Interactive YAW/2 CLI peer for the spike — connects to the live signaling and
talks to the web client (or another CLI peer) on the same network.

  cli/.venv/bin/python cli/spike_peer.py [network-name]   # default: spike-room

Type a line to chat it to all peers. Received files land in /tmp/.
"""

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Node, net_hash

SIGNAL_URL = "wss://fnlr.se/4802f621018e1968/signal"


async def main():
    netname = sys.argv[1] if len(sys.argv) > 1 else "spike-room"
    ident = Identity()
    node = None

    def on_event(kind, **kw):
        if kind == "connected":
            print(f"[+] {kw['peer'][:12]}… connected  verified={kw['verified']}")
        elif kind == "peer-leave":
            print(f"[-] {kw['peer'][:12]}… left")
        elif kind == "chat":
            print(f"<{kw['peer'][:8]}> {kw['text']}")
            p = node.peers.get(kw["peer"])
            if p:
                p.send_chat("echo: " + kw["text"])
        elif kind == "file-recv":
            path = os.path.join("/tmp", "yaw2-recv-" + os.path.basename(kw["name"]))
            with open(path, "wb") as fh:
                fh.write(kw["data"])
            print(f"[file] '{kw['name']}' ({kw['size']} B) ok={kw['ok']} -> {path}")

    print(f"[cli peer] id {ident.short}   net '{netname}'")
    node = Node(SIGNAL_URL, ident, net_hash(netname), on_event)
    await node.start()
    print("[cli peer] connected to signaling — open the web client on the same network.")
    print("           type a message + Enter to chat to all peers (Ctrl-C to quit).")

    loop = asyncio.get_event_loop()
    while True:
        text = (await loop.run_in_executor(None, sys.stdin.readline)).strip()
        if text:
            for p in node.peers.values():
                p.send_chat(text)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

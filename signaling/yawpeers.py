#!/usr/bin/env python3
"""yawpeers — show who is connected to the YAW/2 signaling server.

Reads the snapshot the signaling server writes (status.json). Run on the server:

    yawpeers          # table: count, short id, ip, net, connected, uptime
    yawpeers -l       # also print full ids and full network hashes
"""

import datetime
import json
import os
import sys
import time

STATUS = os.environ.get(
    "SIG_STATUS", "/home/fnlr/yaw-signaling/status.json")


def dur(seconds: float) -> str:
    s = int(seconds)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    if d:
        return f"{d}d{h:02d}h"
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def main():
    full = any(a in ("-l", "--full") for a in sys.argv[1:])
    try:
        with open(STATUS) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        print("no status file yet — signaling server not running, or no peers have connected.")
        return
    except Exception as e:
        print(f"could not read status: {e}")
        return

    now = time.time()
    peers = sorted(data.get("peers", []), key=lambda p: p["since"])
    snap_age = now - data.get("updated", now)
    print(f"YAW/2 signaling — {len(peers)} peer(s) connected   "
          f"(snapshot {dur(snap_age)} old)")
    if not peers:
        return

    print()
    print(f"{'#':>2}  {'SHORT ID':<19} {'IP':<16} {'NET':<9} "
          f"{'CONNECTED':<19} {'UPTIME':>7}")
    print("-" * 80)
    for i, p in enumerate(peers, 1):
        sid = " ".join(p["id"][j:j + 4] for j in range(0, 16, 4))
        when = datetime.datetime.fromtimestamp(p["since"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{i:>2}  {sid:<19} {p['ip']:<16} {p['net'][:7] + '…':<9} "
              f"{when:<19} {dur(now - p['since']):>7}")
        if full:
            print(f"      id  {p['id']}")
            print(f"      net {p['net']}")


if __name__ == "__main__":
    main()

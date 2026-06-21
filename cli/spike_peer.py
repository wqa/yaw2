#!/usr/bin/env python3
"""Interactive YAW/2 CLI peer — chat, WASTE-style folder sharing, keyring trust.

  cli/.venv/bin/python cli/spike_peer.py [network] [--share DIR]

Trust is keyring-gated (friend-to-friend): a session forms only with peers whose
id you've /accept-ed and who've accepted you. Defaults: network "spike-room",
share ~/.yaw/share, downloads ~/.yaw/downloads, identity ~/.yaw/identity,
keyring ~/.yaw/keyring. Type a line to chat; /help for commands.
"""

from __future__ import annotations

import asyncio
import getpass
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity, Keyring, Node, net_hash
from yaw2.keybackup import encrypt_seed, decrypt_seed

SIGNAL_URL = "wss://fnlr.se/4802f621018e1968/signal"
HOME = os.path.expanduser("~/.yaw")
DOWNLOADS = os.path.join(HOME, "downloads")
ID_PATH = os.path.join(HOME, "identity")
KEY_PATH = os.path.join(HOME, "keyring")


def load_identity() -> Identity:
    """Stable identity so peers can keep us in their keyring across runs."""
    os.makedirs(HOME, exist_ok=True)
    if os.path.exists(ID_PATH):
        with open(ID_PATH) as fh:
            return Identity.from_seed_hex(fh.read().strip())
    ident = Identity()
    with open(ID_PATH, "w") as fh:
        fh.write(ident.seed_hex)
    os.chmod(ID_PATH, 0o600)
    return ident


def parse_args(argv):
    netname, share = "spike-room", os.path.join(HOME, "share")
    it = iter(argv)
    for a in it:
        if a == "--share":
            share = next(it, share)
        elif not a.startswith("-"):
            netname = a
    return netname, share


async def main():
    netname, share_dir = parse_args(sys.argv[1:])
    os.makedirs(share_dir, exist_ok=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    ident = load_identity()
    kr = Keyring(KEY_PATH)
    node = None
    warned = set()

    def resolve(prefix):
        prefix = prefix.lower()
        hits = [pid for pid in node.peers if pid.startswith(prefix)]
        return hits[0] if len(hits) == 1 else None

    def on_event(kind, **kw):
        if kind == "connected":
            shares = "share" in (kw.get("caps") or [])
            print(f"[+] {kw['peer'][:12]}… connected  verified={kw['verified']}"
                  f"{'  (shares files)' if shares else ''}")
        elif kind == "untrusted":
            if kw["peer"] not in warned:           # one nudge per id
                warned.add(kw["peer"])
                print(f"[trust] {kw['peer'][:16]}… wants to connect — not in your keyring.\n"
                      f"        /accept {kw['peer']}  to allow.")
        elif kind == "peer-leave":
            print(f"[-] {kw['peer'][:12]}… left")
        elif kind == "chat":
            print(f"<{kw['peer'][:8]}> {kw['text']}")
        elif kind == "files":
            entries = kw["entries"]
            print(f"[files] {kw['peer'][:8]}… shares {len(entries)} file(s):")
            for e in entries:
                print(f"    {e['name']:<32} {e['size']:>12,} B")
        elif kind == "no-file":
            print(f"[files] {kw['peer'][:8]}… has no '{kw['name']}'")
        elif kind == "file-recv":
            path = os.path.join(DOWNLOADS, os.path.basename(kw["name"]))
            with open(path, "wb") as fh:
                fh.write(kw["data"])
            print(f"[file] '{kw['name']}' ({kw['size']:,} B) ok={kw['ok']} -> {path}")

    print(f"[cli peer] id {ident.id}")
    print(f"[cli peer] net '{netname}'  sharing {share_dir}  trusting {len(kr.all())} key(s)")
    node = Node(SIGNAL_URL, ident, net_hash(netname), on_event,
                share_dir=share_dir, keyring=kr)
    await node.start()
    print("[cli peer] connected — share /id with friends, /accept their id. /help for more.")

    loop = asyncio.get_event_loop()
    while True:
        line = (await loop.run_in_executor(None, sys.stdin.readline))
        if not line:
            break
        text = line.strip()
        if not text:
            continue
        if not text.startswith("/"):
            for p in node.peers.values():
                p.send_chat(text)
            continue
        parts = text.split()
        cmd = parts[0]
        if cmd == "/help":
            print("  /id                     show your id (give it to friends)\n"
                  "  /accept <id>            trust a peer id (connects if present)\n"
                  "  /keys                   list trusted ids\n"
                  "  /forget <id>            remove a trusted id\n"
                  "  /export <file>          write a passphrase-encrypted key backup\n"
                  "  /import <file>          restore identity from a key backup (then restart)\n"
                  "  /peers                  list connected peers\n"
                  "  /share                  list files you share\n"
                  "  /browse <id-prefix>     list a peer's shared files\n"
                  "  /get <id-prefix> <name> download a file from a peer\n"
                  "  <text>                  chat to all peers")
        elif cmd == "/id":
            print(f"  {ident.id}")
        elif cmd == "/accept" and len(parts) >= 2:
            try:
                added = await node.accept(parts[1])
                warned.discard(parts[1].strip().lower())
                print(f"  {'accepted' if added else 'already trusted'}: {parts[1][:16]}…")
            except ValueError as e:
                print(f"  {e}")
        elif cmd == "/keys":
            ids = kr.all()
            print(f"  trusting {len(ids)} id(s):")
            for i in ids:
                print(f"    {i}")
        elif cmd == "/forget" and len(parts) >= 2:
            print("  removed" if kr.remove(parts[1]) else "  not in keyring")
        elif cmd == "/export" and len(parts) >= 2:
            pw = await loop.run_in_executor(None, getpass.getpass, "  passphrase: ")
            if pw:
                with open(parts[1], "w") as fh:
                    json.dump(encrypt_seed(ident.seed_hex, pw), fh, indent=2)
                os.chmod(parts[1], 0o600)
                print(f"  backup written to {parts[1]} (same file restores you in the web client too)")
        elif cmd == "/import" and len(parts) >= 2:
            pw = await loop.run_in_executor(None, getpass.getpass, "  passphrase: ")
            try:
                seed = decrypt_seed(json.load(open(parts[1])), pw)
                with open(ID_PATH, "w") as fh:
                    fh.write(seed)
                os.chmod(ID_PATH, 0o600)
                print(f"  identity {Identity.from_seed_hex(seed).short} restored — restart to use it")
            except Exception:
                print("  import failed (wrong passphrase or bad file)")
        elif cmd == "/peers":
            if not node.peers:
                print("  (no peers)")
            for pid, p in node.peers.items():
                caps = getattr(p, "peer_caps", [])
                print(f"  {pid[:16]}…  verified={p.verified}  "
                      f"{'shares' if 'share' in caps else ''}")
        elif cmd == "/share":
            if node.share:
                listing = node.share.listing()
                for e in listing:
                    print(f"  {e['name']:<32} {e['size']:>12,} B")
                if not listing:
                    print(f"  (share dir empty: {share_dir})")
        elif cmd == "/browse" and len(parts) >= 2:
            pid = resolve(parts[1])
            (node.peers[pid].request_browse() if pid else print("  no single peer matches"))
        elif cmd == "/get" and len(parts) >= 3:
            pid = resolve(parts[1])
            (node.peers[pid].request_get(parts[2]) if pid else print("  no single peer matches"))
        else:
            print("  ? /help")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

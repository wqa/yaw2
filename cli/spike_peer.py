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

from yaw2 import Identity, Keyring, Node, net_hash, make_card, parse_card
from yaw2.keybackup import encrypt_seed, decrypt_seed
from yaw2.keyring import clean_nick
from yaw2.config import signal_url, default_net

SIGNAL_URL = signal_url()
HOME = os.path.expanduser("~/.yaw")
DOWNLOADS = os.path.join(HOME, "downloads")
ID_PATH = os.path.join(HOME, "identity")
KEY_PATH = os.path.join(HOME, "keyring")
NICK_PATH = os.path.join(HOME, "nick")


def load_nick() -> str:
    if os.path.exists(NICK_PATH):
        with open(NICK_PATH) as fh:
            return clean_nick(fh.read())
    return ""


def save_nick(nick: str):
    os.makedirs(HOME, exist_ok=True)
    with open(NICK_PATH, "w") as fh:
        fh.write(clean_nick(nick))


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
    netname, share, nick = None, os.path.join(HOME, "share"), None
    it = iter(argv)
    for a in it:
        if a == "--share":
            share = next(it, share)
        elif a == "--nick":
            nick = next(it, None)
        elif not a.startswith("-"):
            netname = a
    return netname, share, nick


async def main():
    netname, share_dir, nick_arg = parse_args(sys.argv[1:])
    netname = netname or default_net() or "spike-room"
    os.makedirs(share_dir, exist_ok=True)
    os.makedirs(DOWNLOADS, exist_ok=True)
    ident = load_identity()
    kr = Keyring(KEY_PATH)
    if nick_arg is not None:
        save_nick(nick_arg)
    my_nick = load_nick()
    node = None
    warned = set()

    def label(pid):                         # nickname if we've named them, else short id
        return kr.name(pid) or (pid[:8] + "…")

    def resolve(prefix):
        prefix = prefix.lower()
        hits = [pid for pid in node.peers if pid.startswith(prefix)]
        return hits[0] if len(hits) == 1 else None

    def on_event(kind, **kw):
        if kind == "connected":
            shares = "share" in (kw.get("caps") or [])
            hint = "" if kr.name(kw["peer"]) else (f"  (calls itself '{kw['nick']}')" if kw.get("nick") else "")
            fs = "forward-secret" if kw.get("fs") else "not forward-secret (2.0 peer)"
            print(f"[+] {label(kw['peer'])} connected  verified={kw['verified']}  [{fs}]"
                  f"{'  (shares files)' if shares else ''}{hint}")
        elif kind == "untrusted":
            if kw["peer"] not in warned:           # one nudge per id
                warned.add(kw["peer"])
                print(f"[trust] someone wants to connect — not in your keyring.\n"
                      f"        /accept {kw['peer']} <nickname>   to allow.")
        elif kind == "status":
            st = kw["state"]
            msg = {"connecting": "connecting…",
                   "failed": "could not connect (likely a restrictive NAT — try another network)",
                   "disconnected": "connection dropped"}.get(st)
            if msg:
                print(f"[net] {label(kw['peer'])}: {msg}")
        elif kind == "peer-leave":
            print(f"[-] {label(kw['peer'])} left")
        elif kind == "chat":
            print(f"<{label(kw['peer'])}> {kw['text']}")
        elif kind == "files":
            entries = kw["entries"]
            print(f"[files] {label(kw['peer'])} shares {len(entries)} file(s):")
            for e in entries:
                print(f"    {e['name']:<32} {e['size']:>12,} B")
        elif kind == "no-file":
            print(f"[files] {label(kw['peer'])} has no '{kw['name']}'")
        elif kind == "file-recv":
            path = os.path.join(DOWNLOADS, os.path.basename(kw["name"]))
            with open(path, "wb") as fh:
                fh.write(kw["data"])
            print(f"[file] '{kw['name']}' ({kw['size']:,} B) ok={kw['ok']} -> {path}")

    print(f"[cli peer] you are {my_nick or '(no nick — set one with /nick)'}")
    print(f"[cli peer] your card: {make_card(ident.id, my_nick)}")
    print(f"[cli peer] net '{netname}'  sharing {share_dir}  trusting {len(kr.all())} contact(s)")
    node = Node(SIGNAL_URL, ident, net_hash(netname), on_event,
                share_dir=share_dir, keyring=kr, nick=my_nick)
    await node.start()
    print("[cli peer] connected — share /me with friends, /accept their card. /help for more.")

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
            print("  /me                       show your contact card (give it to friends)\n"
                  "  /id                       show your raw id\n"
                  "  /nick <name>              set your own nickname\n"
                  "  /accept <card|id> [nick]  trust a contact (connects if present)\n"
                  "  /name <id-prefix> <nick>  (re)label a trusted contact\n"
                  "  /keys                     list trusted contacts + nicknames\n"
                  "  /forget <id>              remove a trusted id\n"
                  "  /contacts export <file>   save contacts (ids + nicknames)\n"
                  "  /contacts import <file>   merge contacts from a file\n"
                  "  /export <file>            write a passphrase-encrypted key backup\n"
                  "  /import <file>            restore identity from a key backup (then restart)\n"
                  "  /peers                    list connected peers\n"
                  "  /share                    list files you share\n"
                  "  /browse <id-prefix>       list a peer's shared files\n"
                  "  /get <id-prefix> <name>   download a file from a peer\n"
                  "  <text>                    chat to all peers")
        elif cmd == "/me":
            print(f"  {make_card(ident.id, node.nick)}")
        elif cmd == "/id":
            print(f"  {ident.id}")
        elif cmd == "/nick" and len(parts) >= 2:
            node.nick = clean_nick(" ".join(parts[1:]))
            save_nick(node.nick)
            print(f"  you are now '{node.nick}' (new connections will see this)")
        elif cmd == "/accept" and len(parts) >= 2:
            try:
                pid, card_nick = parse_card(parts[1])
                nick = " ".join(parts[2:]) if len(parts) > 2 else card_nick
                added = await node.accept(pid, nick)
                warned.discard(pid)
                print(f"  {'accepted' if added else 'updated'}: {kr.name(pid) or pid[:16] + '…'}")
            except ValueError as e:
                print(f"  {e}")
        elif cmd == "/name" and len(parts) >= 3:
            cand = [i for i in kr.all() if i.startswith(parts[1].lower())]
            if len(cand) == 1:
                kr.rename(cand[0], " ".join(parts[2:]))
                print(f"  renamed {cand[0][:12]}… to '{kr.name(cand[0])}'")
            else:
                print("  no single trusted id matches that prefix")
        elif cmd == "/keys":
            entries = kr.entries()
            print(f"  trusting {len(entries)} contact(s):")
            for nid, nk in entries:
                print(f"    {nid}  {nk or '(no nick)'}")
        elif cmd == "/forget" and len(parts) >= 2:
            print("  removed" if kr.remove(parts[1]) else "  not in keyring")
        elif cmd == "/contacts" and len(parts) >= 3 and parts[1] == "export":
            with open(parts[2], "w") as fh:
                json.dump(kr.export_contacts(), fh, indent=2)
            print(f"  wrote {len(kr.all())} contact(s) to {parts[2]}")
        elif cmd == "/contacts" and len(parts) >= 3 and parts[1] == "import":
            try:
                n = kr.import_contacts(json.load(open(parts[2])))
                print(f"  imported {n} contact(s) — present ones connect within a few seconds")
            except Exception as e:
                print(f"  import failed: {e}")
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
                print(f"  {label(pid):<16}  {pid[:12]}…  verified={p.verified}  "
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

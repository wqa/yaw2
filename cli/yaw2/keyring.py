#!/usr/bin/env python3
"""Keyring — trusted peer ids, each with an optional local nickname.

Friend-to-friend (spec §6): a session forms only between mutually-accepted ids.
A nickname is a LOCAL label you choose for a contact; it is not authenticated and
never affects trust — the 64-hex id is the only identity. Persisted one per line as
`id<TAB>nick` (nick optional; old id-only keyrings still load).

Contact card — the shareable "here's me" string, format `yaw-contact-1`:

    yaw:<id>?n=<percent-encoded-nick>

The id is self-certifying (it's the Ed25519 public key — nobody can ever connect as
it without the private key). The nick is only a *suggested* label the recipient may
keep or change; treat it as untrusted text.
"""

from __future__ import annotations

import os
from urllib.parse import quote, unquote

_HEX = set("0123456789abcdef")


def valid_id(s: str) -> bool:
    s = s.strip().lower()
    return len(s) == 64 and all(c in _HEX for c in s)


def clean_nick(nick: str) -> str:
    """Untrusted label → safe, short, single-line display string."""
    if not nick:
        return ""
    nick = "".join(ch for ch in nick if ch.isprintable())
    return nick.strip()[:40]


def make_card(node_id: str, nick: str = "") -> str:
    card = "yaw:" + node_id.strip().lower()
    nick = clean_nick(nick)
    return card + ("?n=" + quote(nick, safe="") if nick else "")


def parse_card(text: str):
    """(id, nick) from a contact card or a bare id. Raises ValueError on garbage."""
    text = text.strip()
    if text.startswith("yaw:"):
        text = text[4:]
    nick = ""
    if "?n=" in text:
        text, _, q = text.partition("?n=")
        nick = clean_nick(unquote(q))
    node_id = text.strip().lower()
    if not valid_id(node_id):
        raise ValueError("not a valid id / contact card")
    return node_id, nick


class Keyring:
    def __init__(self, path: str | None = None):
        self.path = path
        self.names: dict[str, str] = {}        # id -> nick ("" if none)
        if path and os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if not line.strip():
                        continue
                    parts = line.split("\t", 1)
                    nid = parts[0].strip().lower()
                    if valid_id(nid):
                        self.names[nid] = clean_nick(parts[1]) if len(parts) > 1 else ""

    def trusts(self, node_id: str) -> bool:
        return node_id.strip().lower() in self.names

    def name(self, node_id: str) -> str:
        return self.names.get(node_id.strip().lower(), "")

    def accept(self, node_id: str, nick: str = "") -> bool:
        node_id = node_id.strip().lower()
        if not valid_id(node_id):
            raise ValueError("not a valid id (need 64 hex chars)")
        existed = node_id in self.names
        self.names[node_id] = clean_nick(nick) or self.names.get(node_id, "")
        self._save()
        return not existed

    def rename(self, node_id: str, nick: str) -> bool:
        node_id = node_id.strip().lower()
        if node_id not in self.names:
            return False
        self.names[node_id] = clean_nick(nick)
        self._save()
        return True

    def remove(self, node_id: str) -> bool:
        node_id = node_id.strip().lower()
        if node_id not in self.names:
            return False
        del self.names[node_id]
        self._save()
        return True

    def all(self) -> list[str]:
        return sorted(self.names)

    def entries(self):
        return sorted(self.names.items())

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            for nid in sorted(self.names):
                nick = self.names[nid]
                fh.write(nid + ("\t" + nick if nick else "") + "\n")
        os.replace(tmp, self.path)


if __name__ == "__main__":
    fid = "a" * 64
    assert parse_card(make_card(fid, "Felix Niklasson")) == (fid, "Felix Niklasson")
    assert parse_card("yaw:" + fid) == (fid, "")
    assert parse_card(fid) == (fid, "")           # bare id still works
    assert make_card(fid, "a/b c?d") == "yaw:" + fid + "?n=a%2Fb%20c%3Fd"
    assert clean_nick("x\ny\t" + "z" * 80) == "xyz" + "z" * 37   # stripped + capped
    kr = Keyring()
    assert kr.accept(fid, "Felix") and not kr.accept(fid)         # add, then dup
    assert kr.name(fid) == "Felix" and kr.rename(fid, "Felix N.")
    print("[keyring] contact-card + nickname round-trip OK ✓")

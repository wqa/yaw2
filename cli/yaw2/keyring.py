"""The keyring — the set of peer ids this node will connect to (trust).

YAW/2 is friend-to-friend: a session forms only if each peer's id is in the
other's keyring (protocol §6). Ids are exchanged out of band. Persisted as one
lowercase-hex id per line.
"""

from __future__ import annotations

import os

_HEX = set("0123456789abcdef")


def valid_id(s: str) -> bool:
    s = s.strip().lower()
    return len(s) == 64 and all(c in _HEX for c in s)


class Keyring:
    def __init__(self, path: str | None = None):
        self.path = path
        self.ids: set[str] = set()
        if path and os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    s = line.strip().lower()
                    if valid_id(s):
                        self.ids.add(s)

    def trusts(self, node_id: str) -> bool:
        return node_id.strip().lower() in self.ids

    def accept(self, node_id: str) -> bool:
        node_id = node_id.strip().lower()
        if not valid_id(node_id):
            raise ValueError("not a valid id (need 64 hex chars)")
        if node_id in self.ids:
            return False
        self.ids.add(node_id)
        self._save()
        return True

    def remove(self, node_id: str) -> bool:
        node_id = node_id.strip().lower()
        if node_id not in self.ids:
            return False
        self.ids.discard(node_id)
        self._save()
        return True

    def all(self) -> list[str]:
        return sorted(self.ids)

    def _save(self):
        if not self.path:
            return
        tmp = self.path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write("".join(i + "\n" for i in sorted(self.ids)))
        os.replace(tmp, self.path)

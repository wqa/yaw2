"""A read-only shared folder for the browse extension (docs/extensions/file-browse.md).

The single choke point that turns an untrusted peer-supplied name into a real path:
a file is served only if `name` is a plain component sitting directly inside the
configured share dir (no separators, no `..`, no dotfiles, no symlink escapes).
"""

from __future__ import annotations

import os


def safe_name(name: str) -> str | None:
    if not name or name in (".", ".."):
        return None
    if os.path.basename(name) != name:      # any separator / parent ref
        return None
    if name.startswith("."):                # no hidden/dotfiles
        return None
    return name


class FileShare:
    def __init__(self, share_dir: str):
        os.makedirs(share_dir, exist_ok=True)
        self.dir = os.path.realpath(share_dir)

    def listing(self) -> list[dict]:
        out = []
        for name in sorted(os.listdir(self.dir)):
            p = self.resolve(name)
            if p:
                out.append({"name": name, "size": os.path.getsize(p)})
        return out

    def resolve(self, name: str) -> str | None:
        safe = safe_name(name)
        if safe is None:
            return None
        real = os.path.realpath(os.path.join(self.dir, safe))
        if os.path.dirname(real) != self.dir or not os.path.isfile(real):
            return None
        return real

    def read(self, name: str) -> bytes | None:
        p = self.resolve(name)
        if p is None:
            return None
        with open(p, "rb") as fh:
            return fh.read()

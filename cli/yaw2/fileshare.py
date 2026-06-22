"""A read-only shared folder *tree* for the browse extension
(docs/extensions/file-browse.md).

Hosts a whole directory recursively; peers navigate it like a filesystem. The one
choke point that turns an untrusted peer-supplied relative path into a real path is
`_resolve`: a path is served only if every component is safe (no separators tricks,
no `..`, no dotfiles) AND the resolved real path stays *inside* the share root
(which also defeats symlink escapes). Symlinks are not listed, to avoid escapes and
loops.
"""

from __future__ import annotations

import os


class FileShare:
    def __init__(self, share_dir: str):
        os.makedirs(share_dir, exist_ok=True)
        self.dir = os.path.realpath(share_dir)

    def _resolve(self, rel: str):
        """Real absolute path for a relative path inside the share, or None."""
        rel = (rel or "").replace("\\", "/").strip()
        if rel.startswith("/"):
            return None                        # refuse absolute paths outright
        rel = rel.strip("/")
        if rel:
            parts = rel.split("/")
            for p in parts:
                if not p or p == ".." or p.startswith("."):
                    return None
            real = os.path.realpath(os.path.join(self.dir, *parts))
        else:
            real = self.dir
        if real == self.dir or real.startswith(self.dir + os.sep):
            return real
        return None

    def listing(self, rel: str = "") -> list[dict]:
        """Immediate children at `rel` (dirs first). [] if invalid or not a dir."""
        base = self._resolve(rel)
        if base is None or not os.path.isdir(base):
            return []
        dirs, files = [], []
        for name in sorted(os.listdir(base)):
            if name.startswith("."):
                continue
            full = os.path.join(base, name)
            if os.path.islink(full):
                continue                       # don't share symlinks (escape/loop safety)
            if os.path.isdir(full):
                dirs.append({"name": name, "dir": True})
            elif os.path.isfile(full):
                files.append({"name": name, "size": os.path.getsize(full)})
        return dirs + files

    def read(self, rel: str):
        real = self._resolve(rel)
        if real is None or os.path.islink(real) or not os.path.isfile(real):
            return None
        with open(real, "rb") as fh:
            return fh.read()

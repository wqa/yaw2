#!/usr/bin/env python3
"""FileShare tree + path-traversal safety. Run: cli/.venv/bin/python cli/test_fileshare.py"""

from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2.fileshare import FileShare


def main():
    with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
        # build a tree:  root/top.txt, root/sub/a.txt, root/sub/deep/b.txt, root/.hidden
        os.makedirs(os.path.join(root, "sub", "deep"))
        open(os.path.join(root, "top.txt"), "w").write("T")
        open(os.path.join(root, "sub", "a.txt"), "w").write("AA")
        open(os.path.join(root, "sub", "deep", "b.txt"), "w").write("BBB")
        open(os.path.join(root, ".hidden"), "w").write("secret")
        secret = os.path.join(outside, "passwd")
        open(secret, "w").write("ROOTPW")
        os.symlink(secret, os.path.join(root, "escape"))          # symlink escaping the share

        fs = FileShare(root)
        ok = True

        def check(label, cond):
            nonlocal ok
            print(("  ok " if cond else "  FAIL ") + label)
            ok = ok and cond

        # listing
        rootnames = [e["name"] for e in fs.listing("")]
        check("root lists sub/ and top.txt", rootnames == ["sub", "top.txt"])
        check("root hides dotfiles", ".hidden" not in rootnames)
        check("root hides escaping symlink", "escape" not in rootnames)
        check("root marks sub as dir", fs.listing("")[0].get("dir") is True)
        check("sub lists deep/ and a.txt", [e["name"] for e in fs.listing("sub")] == ["deep", "a.txt"])
        check("nested listing works", [e["name"] for e in fs.listing("sub/deep")] == ["b.txt"])

        # reads
        check("read top.txt", fs.read("top.txt") == b"T")
        check("read nested b.txt", fs.read("sub/deep/b.txt") == b"BBB")

        # traversal must all be refused
        check("reject ..", fs._resolve("..") is None)
        check("reject ../../etc/passwd", fs._resolve("../../etc/passwd") is None)
        check("reject absolute /etc/passwd", fs._resolve("/etc/passwd") is None)
        check("reject sub/../../x", fs._resolve("sub/../../x") is None)
        check("reject backslash escape", fs._resolve("..\\..\\x") is None)
        check("reject dotfile read", fs.read(".hidden") is None)
        check("reject symlink escape read", fs.read("escape") is None)
        check("listing a file is empty", fs.listing("top.txt") == [])

        print("ALL PASS" if ok else "SOME FAILED")
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

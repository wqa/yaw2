#!/usr/bin/env python3
"""Export the CLI identity (~/.yaw/identity) to a passphrase-encrypted *.yawkey.

Use it to put your EXISTING identity into the web or desktop client (Restore key)
so all your clients are the same person — the one your friends already accepted.

  cli/.venv/bin/python cli/export_key.py [outfile]      # default ~/yaw-identity.yawkey
"""

from __future__ import annotations

import getpass
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2 import Identity
from yaw2.keybackup import encrypt_seed

ID_PATH = os.path.expanduser("~/.yaw/identity")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/yaw-identity.yawkey")
    out = os.path.expanduser(out)
    if not os.path.exists(ID_PATH):
        print(f"no identity at {ID_PATH}")
        return
    seed = open(ID_PATH).read().strip()
    print(f"identity {Identity.from_seed_hex(seed).id}")
    pw = getpass.getpass("passphrase to encrypt the backup: ")
    if not pw:
        print("aborted (empty passphrase)")
        return
    if pw != getpass.getpass("repeat passphrase: "):
        print("aborted (passphrases differ)")
        return
    with open(out, "w") as fh:
        json.dump(encrypt_seed(seed, pw), fh, indent=2)
    os.chmod(out, 0o600)
    print(f"wrote {out}")
    print("-> in the desktop/web app: Restore key, pick this file, enter the same passphrase.")


if __name__ == "__main__":
    main()

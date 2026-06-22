#!/usr/bin/env python3
"""The DTLS-fingerprint extraction that the identity bind (§10) signs over must be
algorithm-agnostic: some WebRTC stacks advertise a cert fingerprint under sha-512 (or
another hash), not sha-256. An sha-256-only matcher returned an EMPTY fingerprint for
those, so the signed bind could never verify (the bug behind a peer stuck UNVERIFIED).

Run: cli/.venv/bin/python cli/test_dtlsfp.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from yaw2.peer import _dtls_fp

FP = "AB:CD:EF:01:23:45:67:89:AB:CD:EF:01:23:45:67:89"
RAW = bytes.fromhex(FP.replace(":", ""))


def main():
    ok = True

    def check(label, cond):
        nonlocal ok
        print(("  ok " if cond else "  FAIL ") + label)
        ok = ok and cond

    check("sha-256 line parses", _dtls_fp(f"a=fingerprint:sha-256 {FP}") == RAW)
    check("sha-512 line parses (old regex gave empty)", _dtls_fp(f"a=fingerprint:sha-512 {FP}") == RAW)
    check("uppercase algo token parses", _dtls_fp(f"a=fingerprint:SHA-256 {FP}") == RAW)
    check("lowercase hex parses", _dtls_fp(f"a=fingerprint:sha-256 {FP.lower()}") == RAW)
    check("first fingerprint wins, both peers agree", len(_dtls_fp(
        f"a=fingerprint:sha-256 {FP}\r\na=fingerprint:sha-256 00:11")) == len(RAW))
    check("no fingerprint -> empty (caught as 'missing')", _dtls_fp("v=0\r\nm=application") == b"")

    print("ALL PASS" if ok else "SOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

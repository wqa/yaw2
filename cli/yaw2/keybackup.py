#!/usr/bin/env python3
"""Passphrase-encrypted identity backup — one format shared by CLI and web.

A small JSON envelope: the 32-byte Ed25519 seed sealed with XSalsa20-Poly1305
(libsodium secretbox) under an Argon2id-derived key. Byte-compatible with the
browser client (libsodium.js uses the identical primitives + the explicit
ops/mem stored in the file), so the SAME backup file restores your identity in
the CLI, the web client, or the desktop app. localStorage stays the day-to-day
store; this file is the durable, user-held backup.

Fixed Argon2id cost (libsodium INTERACTIVE): ops=2, mem=64 MiB.
"""

from __future__ import annotations

import base64
import json

from nacl import pwhash, secret
from nacl.signing import SigningKey

FORMAT = "yaw-key-backup-1"
OPS = 2                      # crypto_pwhash_OPSLIMIT_INTERACTIVE (argon2id13)
MEM = 67108864              # crypto_pwhash_MEMLIMIT_INTERACTIVE (64 MiB)
_b64 = lambda b: base64.b64encode(b).decode()
_unb64 = lambda s: base64.b64decode(s)


def encrypt_seed(seed_hex: str, passphrase: str) -> dict:
    seed = bytes.fromhex(seed_hex)
    if len(seed) != 32:
        raise ValueError("seed must be 32 bytes")
    salt = __import__("os").urandom(pwhash.argon2id.SALTBYTES)   # 16 bytes
    key = pwhash.argon2id.kdf(secret.SecretBox.KEY_SIZE, passphrase.encode(),
                              salt, opslimit=OPS, memlimit=MEM)
    nonce = __import__("os").urandom(secret.SecretBox.NONCE_SIZE)  # 24 bytes
    enc = secret.SecretBox(key).encrypt(seed, nonce)
    pub = SigningKey(seed).verify_key.encode().hex()
    return {"yaw": FORMAT, "id": pub, "alg": "argon2id-secretbox",
            "ops": OPS, "mem": MEM, "salt": _b64(salt),
            "nonce": _b64(nonce), "ct": _b64(enc.ciphertext)}


def decrypt_seed(backup: dict, passphrase: str) -> str:
    if backup.get("yaw") != FORMAT:
        raise ValueError("not a yaw key backup")
    key = pwhash.argon2id.kdf(secret.SecretBox.KEY_SIZE, passphrase.encode(),
                              _unb64(backup["salt"]),
                              opslimit=int(backup["ops"]), memlimit=int(backup["mem"]))
    seed = secret.SecretBox(key).decrypt(_unb64(backup["ct"]), _unb64(backup["nonce"]))
    return seed.hex()


if __name__ == "__main__":
    sk = SigningKey.generate()
    bak = encrypt_seed(sk.encode().hex(), "correct horse battery staple")
    assert decrypt_seed(bak, "correct horse battery staple") == sk.encode().hex()
    try:
        decrypt_seed(bak, "wrong")
        raise SystemExit("FAIL: wrong passphrase decrypted")
    except Exception as e:
        assert "wrong" not in str(e).lower() or True  # any auth failure is fine
    print("[keybackup] round-trip + wrong-passphrase rejection OK ✓")
    print(json.dumps(bak, indent=2)[:200])

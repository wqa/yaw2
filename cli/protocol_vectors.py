#!/usr/bin/env python3
"""Deterministic YAW/2 protocol test vectors.

Run to reproduce every worked example in docs/yaw2-implementation.md. Uses fixed
seeds and fixed nonces so the output is byte-for-byte stable; in production, seeds
are random and crypto_box/secretbox nonces MUST be fresh-random per message.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nacl.public import Box, PrivateKey, PublicKey
from nacl.signing import VerifyKey

from yaw2 import Identity, net_hash

H = lambda b: b.hex()
B64 = lambda b: base64.b64encode(b).decode()


def line(k, v):
    print(f"{k:<26} {v}")


seedA = "01" * 32
seedB = "02" * 32
A = Identity.from_seed_hex(seedA)
B = Identity.from_seed_hex(seedB)

print("== Identities ==")
line("seed A (32 bytes hex)", seedA)
line("id A (Ed25519 pubkey)", A.id)
line("seed B (32 bytes hex)", seedB)
line("id B (Ed25519 pubkey)", B.id)
line("offerer (smaller id)", "A" if A.id < B.id else "B")

print("\n== X25519 keys derived from the Ed25519 identity (for static sealing) ==")
A_curve_pub = VerifyKey(bytes.fromhex(A.id)).to_curve25519_public_key()
B_curve_pub = VerifyKey(bytes.fromhex(B.id)).to_curve25519_public_key()
line("A X25519 pub", H(bytes(A_curve_pub)))
line("B X25519 pub", H(bytes(B_curve_pub)))

print("\n== Network name -> net hash ==")
line('net("spike-room")', net_hash("spike-room"))

print("\n== Signaling: join signature ==")
nonce = bytes([0xAB] * 32)          # the server's challenge nonce (32 bytes)
net = net_hash("spike-room")
sign_input = nonce + net.encode()   # nonce_bytes || utf8(net_hex)
line("challenge nonce (hex)", H(nonce))
line("sign input = nonce||net", H(sign_input))
line("join sig (A signs)", H(A.sign(sign_input)))

print("\n== Static seal (2.0): A -> B, fixed nonce ==")
plaintext = b'{"kind":"chat-illustrative"}'   # real sealed payloads are offer/answer/ekey JSON
seal_nonce = bytes([0x33] * 24)
sealed = bytes(Box(A._curve_priv, B_curve_pub).encrypt(plaintext, seal_nonce))  # nonce||mac||ct
line("plaintext", plaintext.decode())
line("seal nonce (24 bytes)", H(seal_nonce))
line("sealed = nonce||mac||ct", H(sealed))
line("sealed base64 (the 'box')", B64(sealed))
opened = Box(B._curve_priv, A_curve_pub).decrypt(base64.b64decode(B64(sealed)))
line("B opens -> plaintext", opened.decode())

print("\n== Identity binding: signed hello (over DTLS fingerprints) ==")
fp_local = hashlib.sha256(b"DTLS cert of the sender").digest()   # stand-in 32-byte sha-256 fp
fp_remote = hashlib.sha256(b"DTLS cert of the peer").digest()
bind = b"yaw/2 bind" + fp_local + fp_remote                      # sender: prefix||local_fp||remote_fp
line("BIND_PREFIX (utf8)", "yaw/2 bind")
line("local fp (sha-256)", H(fp_local))
line("remote fp (sha-256)", H(fp_remote))
line("bind input", H(bind))
line("hello sig (A signs)", H(A.sign(bind)))

print("\n== yaw/2.1: ephemeral keys + ekey signature ==")
A_eph = PrivateKey(bytes([0x11] * 32))   # fixed X25519 private for the vector
B_eph = PrivateKey(bytes([0x22] * 32))
epkA = bytes(A_eph.public_key)
epkB = bytes(B_eph.public_key)
line("A ephemeral X25519 pub", H(epkA))
line("B ephemeral X25519 pub", H(epkB))
ekey_signed = b"yaw/2.1 ekey" + bytes.fromhex(A.id) + bytes.fromhex(B.id) + epkA
line("ekey sign input", H(ekey_signed))
line("ekey sig (A signs)", H(A.sign(ekey_signed)))

print("\n== yaw/2.1: ephemeral seal A -> B, fixed nonce ==")
eph_nonce = bytes([0x44] * 24)
eph_sealed = bytes(Box(A_eph, B_eph.public_key).encrypt(plaintext, eph_nonce))
line("ephemeral seal nonce", H(eph_nonce))
line("ephemeral box base64", B64(eph_sealed))
line("B opens -> plaintext", Box(B_eph, A_eph.public_key).decrypt(eph_sealed).decode())

print("\n== File transfer: SHA-256 ==")
filedata = b"hello yaw\n"
line("file bytes", repr(filedata))
line("sha256(file)", hashlib.sha256(filedata).hexdigest())

print("\n== xid (file transfer id) ==")
line("xid = 8 random bytes hex", "e.g. " + os.urandom(8).hex() + "  (random per transfer)")

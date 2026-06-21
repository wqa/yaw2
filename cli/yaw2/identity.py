"""YAW/2 identity + signaling-seal (protocol §2, §3).

Ed25519 identity; sealing uses X25519 (derived from the Ed25519 key) + crypto_box,
serialized as base64(nonce(24) || ciphertext) — byte-compatible with libsodium.js
in the web client.
"""

from __future__ import annotations

import base64
import hashlib
import os

from nacl.signing import SigningKey, VerifyKey
from nacl.public import Box


def net_hash(name: str) -> str:
    return hashlib.sha256(("yaw2-net:" + (name or "")).encode()).hexdigest()


class Identity:
    def __init__(self, signing_key: SigningKey | None = None):
        self.sk = signing_key or SigningKey.generate()
        self.vk = self.sk.verify_key
        self.id = self.vk.encode().hex()                       # 64-hex node id
        self._curve_priv = self.sk.to_curve25519_private_key()  # X25519 for sealing

    @classmethod
    def from_seed_hex(cls, seed_hex: str) -> "Identity":
        return cls(SigningKey(bytes.fromhex(seed_hex)))

    @property
    def seed_hex(self) -> str:
        return self.sk.encode().hex()

    @property
    def short(self) -> str:
        h = self.id[:16]
        return " ".join(h[i:i + 4] for i in range(0, 16, 4))

    def sign(self, data: bytes) -> bytes:
        return self.sk.sign(data).signature

    @staticmethod
    def verify(node_id_hex: str, data: bytes, sig: bytes) -> bool:
        try:
            VerifyKey(bytes.fromhex(node_id_hex)).verify(data, sig)
            return True
        except Exception:
            return False

    def seal(self, recipient_id_hex: str, plaintext: bytes) -> str:
        recip = VerifyKey(bytes.fromhex(recipient_id_hex)).to_curve25519_public_key()
        enc = Box(self._curve_priv, recip).encrypt(plaintext, os.urandom(24))  # nonce||ct
        return base64.b64encode(bytes(enc)).decode()

    def open(self, sender_id_hex: str, box_b64: str) -> bytes:
        sender = VerifyKey(bytes.fromhex(sender_id_hex)).to_curve25519_public_key()
        return Box(self._curve_priv, sender).decrypt(base64.b64decode(box_b64))

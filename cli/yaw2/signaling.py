"""YAW/2 signaling client (protocol §5): join, presence, sealed relay."""

from __future__ import annotations

import json

import websockets

from .identity import Identity


class Signaling:
    def __init__(self, url: str, identity: Identity, net: str):
        self.url = url
        self.id = identity
        self.net = net
        self.ws = None
        self.peers: set[str] = set()

    async def connect(self) -> set[str]:
        self.ws = await websockets.connect(self.url, max_size=1 << 16)
        challenge = json.loads(await self.ws.recv())
        assert challenge.get("type") == "challenge", challenge
        nonce = bytes.fromhex(challenge["nonce"])
        sig = self.id.sign(nonce + self.net.encode()).hex()
        await self.ws.send(json.dumps({"type": "join", "id": self.id.id,
                                       "net": self.net, "sig": sig}))
        joined = json.loads(await self.ws.recv())
        assert joined.get("type") == "joined", joined
        self.peers = set(joined.get("peers", []))
        return self.peers

    async def send_to(self, to_id: str, obj: dict):
        box = self.id.seal(to_id, json.dumps(obj).encode())
        await self.ws.send(json.dumps({"type": "to", "to": to_id, "box": box}))

    async def run(self, on_from, on_join, on_leave):
        async for raw in self.ws:
            m = json.loads(raw)
            t = m.get("type")
            if t == "from":
                try:
                    plain = self.id.open(m["from"], m["box"])
                    await on_from(m["from"], json.loads(plain))
                except Exception:
                    pass  # undecryptable / malformed -> ignore
            elif t == "peer-join":
                self.peers.add(m["id"]); await on_join(m["id"])
            elif t == "peer-leave":
                self.peers.discard(m["id"]); await on_leave(m["id"])

    async def close(self):
        if self.ws:
            await self.ws.close()

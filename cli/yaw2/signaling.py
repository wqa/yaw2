"""YAW/2 signaling client (protocol §5): join, presence, sealed relay."""

from __future__ import annotations

import asyncio
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
        self._closed = False

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

    async def send_to(self, to_id: str, box: str):
        # `box` is already a sealed payload (the Node/peer chooses static vs ephemeral
        # keying — yaw/2.1 §5.4'). The server only ever sees this opaque blob.
        await self.ws.send(json.dumps({"type": "to", "to": to_id, "box": box}))

    async def run(self, on_from, on_join, on_leave, on_reconnect=None):
        """Pump signaling; auto-reconnect (re-auth + resync) on a dropped socket.

        Active WebRTC links are peer-to-peer and survive a signaling blip — this
        only restores presence and the ability to form new connections.
        """
        backoff = 1
        while not self._closed:
            try:
                async for raw in self.ws:
                    backoff = 1
                    m = json.loads(raw)
                    t = m.get("type")
                    if t == "from":
                        # deliver the raw sealed box; the Node/peer opens it (it owns
                        # the static + ephemeral keys, yaw/2.1 §5.4')
                        await on_from(m["from"], m["box"])
                    elif t == "peer-join":
                        self.peers.add(m["id"]); await on_join(m["id"])
                    elif t == "peer-leave":
                        self.peers.discard(m["id"]); await on_leave(m["id"])
            except Exception:
                pass
            if self._closed:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
            try:
                present = await self.connect()        # re-handshake (challenge/join)
                backoff = 1
                if on_reconnect:
                    await on_reconnect(present)
            except Exception:
                continue                               # keep retrying

    async def close(self):
        self._closed = True
        if self.ws:
            await self.ws.close()

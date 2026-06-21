"""YAW/2 peer + node over aiortc (protocol §6, §8, §9).

Non-trickle ICE (aiortc embeds candidates in the SDP). The session is bound to
the Ed25519 identity by a signed `hello` over both DTLS fingerprints. Chat rides
the `yaw` control channel; files ride a dedicated `f:<xid>` channel.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re

from aiortc import (RTCPeerConnection, RTCConfiguration, RTCIceServer,
                    RTCSessionDescription)

from .identity import Identity
from .signaling import Signaling

STUN = "stun:fnlr.se:3478"
BIND_PREFIX = b"yaw/2 bind"
CHUNK = 64 * 1024


def _dtls_fp(sdp: str) -> bytes:
    m = re.search(r"a=fingerprint:sha-256 ([0-9A-Fa-f:]+)", sdp or "")
    return bytes.fromhex(m.group(1).replace(":", "")) if m else b""


class YawPeer:
    def __init__(self, identity: Identity, signaling: Signaling, peer_id: str, on_event):
        self.id = identity
        self.sig = signaling
        self.peer_id = peer_id
        self.on_event = on_event
        self.pc = RTCPeerConnection(RTCConfiguration([RTCIceServer(urls=STUN)]))
        self.dc = None
        self.verified = False
        self._recv = {}   # xid -> {name,size,sha,buf}
        self._send = {}   # xid -> bytes

        @self.pc.on("datachannel")
        def _on_dc(channel):
            self._wire(channel)

    # -- offer/answer ----------------------------------------------------------
    async def start_offer(self):
        self.dc = self.pc.createDataChannel("yaw")
        self._wire(self.dc)
        await self.pc.setLocalDescription(await self.pc.createOffer())
        await self.sig.send_to(self.peer_id, {"kind": "offer", "sdp": self.pc.localDescription.sdp})

    async def handle_signal(self, obj: dict):
        kind = obj.get("kind")
        if kind == "offer":
            await self.pc.setRemoteDescription(RTCSessionDescription(obj["sdp"], "offer"))
            await self.pc.setLocalDescription(await self.pc.createAnswer())
            await self.sig.send_to(self.peer_id, {"kind": "answer", "sdp": self.pc.localDescription.sdp})
        elif kind == "answer":
            await self.pc.setRemoteDescription(RTCSessionDescription(obj["sdp"], "answer"))

    # -- channel wiring --------------------------------------------------------
    def _wire(self, channel):
        if channel.label == "yaw":
            self.dc = channel

            @channel.on("open")
            async def _open():
                await self._send_hello()

            @channel.on("message")
            def _msg(message):
                asyncio.ensure_future(self._on_control(message))

            # A received channel can already be "open" when we get it (the open
            # event fired before we attached) — send our hello now in that case.
            if channel.readyState == "open":
                asyncio.ensure_future(self._send_hello())
        elif channel.label.startswith("f:"):
            xid = channel.label[2:]

            @channel.on("message")
            def _data(message):
                st = self._recv.get(xid)
                if st is not None and isinstance(message, (bytes, bytearray)):
                    st["buf"] += message

    async def _send_hello(self):
        if os.environ.get("YAW_DBG"):
            print(f"[dbg {self.id.id[:4]}] dc OPEN -> sending hello (offerer={self.id.id < self.peer_id})")
        bind = BIND_PREFIX + _dtls_fp(self.pc.localDescription.sdp) + _dtls_fp(self.pc.remoteDescription.sdp)
        self.dc.send(json.dumps({"type": "hello", "id": self.id.id, "nick": "py",
                                 "sig": self.id.sign(bind).hex()}))

    async def _on_control(self, message):
        try:
            m = json.loads(message)
        except Exception as e:
            print(f"[dbg {self.id.id[:4]}] bad control msg: {e}"); return
        t = m.get("type")
        if os.environ.get("YAW_DBG"):
            print(f"[dbg {self.id.id[:4]}] got control {t}")
        if t == "hello":
            # verifier reconstructs the sender's bind: prefix || remote_fp || local_fp
            bind = BIND_PREFIX + _dtls_fp(self.pc.remoteDescription.sdp) + _dtls_fp(self.pc.localDescription.sdp)
            ok = (m.get("id") == self.peer_id and
                  Identity.verify(m["id"], bind, bytes.fromhex(m["sig"])))
            self.verified = ok
            self.on_event("connected", peer=self.peer_id, verified=ok, nick=m.get("nick"))
        elif t == "chat":
            self.on_event("chat", peer=self.peer_id, text=m.get("text", ""))
        elif t == "file-offer":
            self._recv[m["xid"]] = {"name": m["name"], "size": m["size"],
                                    "sha": m["sha256"], "buf": bytearray()}
            self.dc.send(json.dumps({"type": "file-accept", "xid": m["xid"]}))
        elif t == "file-accept":
            asyncio.ensure_future(self._stream_file(m["xid"]))
        elif t == "file-done":
            st = self._recv.pop(m["xid"], None)
            if st is not None:
                ok = hashlib.sha256(st["buf"]).hexdigest() == m["sha256"]
                self.on_event("file-recv", peer=self.peer_id, name=st["name"],
                              size=len(st["buf"]), ok=ok, data=bytes(st["buf"]))

    # -- application API -------------------------------------------------------
    def send_chat(self, text: str):
        if self.dc:
            self.dc.send(json.dumps({"type": "chat", "text": text}))

    def send_file(self, name: str, data: bytes):
        xid = os.urandom(8).hex()
        self._send[xid] = data
        self.dc.send(json.dumps({"type": "file-offer", "xid": xid, "name": name,
                                 "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}))

    async def _stream_file(self, xid: str):
        data = self._send.pop(xid, None)
        if data is None:
            return
        ch = self.pc.createDataChannel("f:" + xid)
        opened = asyncio.Event()
        ch.on("open", lambda: opened.set())
        await opened.wait()
        for i in range(0, len(data), CHUNK):
            while ch.bufferedAmount > (1 << 20):
                await asyncio.sleep(0.01)
            ch.send(data[i:i + CHUNK])
        self.dc.send(json.dumps({"type": "file-done", "xid": xid,
                                 "sha256": hashlib.sha256(data).hexdigest()}))


class Node:
    """One signaling connection + a peer per other member of the network."""

    def __init__(self, url: str, identity: Identity, net: str, on_event):
        self.id = identity
        self.net = net
        self.on_event = on_event
        self.sig = Signaling(url, identity, net)
        self.peers: dict[str, YawPeer] = {}

    async def start(self):
        present = await self.sig.connect()
        asyncio.ensure_future(self.sig.run(self._route_from, self._on_join, self._on_leave))
        for pid in present:
            await self._ensure(pid)

    async def _on_join(self, pid, *_):
        # NOTE: spike trusts any id in the network (TOFU). Real client gates on the keyring.
        await self._ensure(pid)

    async def _ensure(self, pid):
        if pid in self.peers or pid == self.id.id:
            return self.peers.get(pid)
        peer = YawPeer(self.id, self.sig, pid, self.on_event)
        self.peers[pid] = peer
        if self.id.id < pid:        # smaller id offers
            await peer.start_offer()
        return peer

    async def _on_leave(self, pid):
        self.peers.pop(pid, None)

    async def _route_from(self, frm, obj):
        peer = await self._ensure(frm)
        await peer.handle_signal(obj)

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
import time

from aiortc import (RTCPeerConnection, RTCConfiguration, RTCIceServer,
                    RTCSessionDescription)

from .identity import Identity
from .signaling import Signaling
from .fileshare import FileShare

STUN = "stun:fnlr.se:3478"
BIND_PREFIX = b"yaw/2 bind"
CHUNK = 64 * 1024


def _dtls_fp(sdp: str) -> bytes:
    m = re.search(r"a=fingerprint:sha-256 ([0-9A-Fa-f:]+)", sdp or "")
    return bytes.fromhex(m.group(1).replace(":", "")) if m else b""


class YawPeer:
    def __init__(self, identity: Identity, signaling: Signaling, peer_id: str, on_event,
                 share=None, nick=""):
        self.id = identity
        self.sig = signaling
        self.peer_id = peer_id
        self.on_event = on_event
        self.share = share          # FileShare or None (we host a browsable folder)
        self.nick = nick            # our self-asserted display nick (informational)
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
        caps = ["share"] if self.share else []
        self.dc.send(json.dumps({"type": "hello", "id": self.id.id, "nick": self.nick,
                                 "caps": caps, "sig": self.id.sign(bind).hex()}))

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
            self.peer_caps = m.get("caps", [])
            self.on_event("connected", peer=self.peer_id, verified=ok,
                          nick=m.get("nick"), caps=self.peer_caps)
        elif t == "chat":
            self.on_event("chat", peer=self.peer_id, text=m.get("text", ""))
        elif t == "browse":
            entries = self.share.listing() if self.share else []
            self.dc.send(json.dumps({"type": "files", "entries": entries}))
        elif t == "files":
            self.on_event("files", peer=self.peer_id, entries=m.get("entries", []))
        elif t == "get":
            data = self.share.read(m.get("name", "")) if self.share else None
            if data is None:
                self.dc.send(json.dumps({"type": "no-file", "name": m.get("name", "")}))
            else:
                self.send_file(m["name"], data)
        elif t == "no-file":
            self.on_event("no-file", peer=self.peer_id, name=m.get("name", ""))
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

    def request_browse(self):
        if self.dc:
            self.dc.send(json.dumps({"type": "browse"}))

    def request_get(self, name: str):
        if self.dc:
            self.dc.send(json.dumps({"type": "get", "name": name}))

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
    """One signaling connection + a peer per *trusted* member of the network.

    Trust gate (protocol §6): a session forms only with peers whose id is in our
    keyring. The smaller id offers; the larger answers. An offerer periodically
    re-offers trusted, present, not-yet-connected peers, so accepting a key at any
    time (even mid-room) brings the link up without a restart. If `keyring` is None
    the node trusts everyone (dev/test only).
    """

    RECONCILE = 4       # seconds between reconcile sweeps
    RETRY_AFTER = 12    # re-offer a link that hasn't verified within this many seconds

    def __init__(self, url: str, identity: Identity, net: str, on_event,
                 share_dir=None, keyring=None, nick=""):
        self.id = identity
        self.net = net
        self.on_event = on_event
        self.sig = Signaling(url, identity, net)
        self.peers: dict[str, YawPeer] = {}
        self.share = FileShare(share_dir) if share_dir else None
        self.keyring = keyring
        self.nick = nick

    def _trusted(self, pid: str) -> bool:
        return self.keyring is None or self.keyring.trusts(pid)

    async def start(self):
        present = await self.sig.connect()
        asyncio.ensure_future(self.sig.run(self._on_from, self._on_join, self._on_leave))
        for pid in present:
            await self._try_connect(pid)
        asyncio.ensure_future(self._reconcile())

    def _new_peer(self, pid: str) -> YawPeer:
        old = self.peers.get(pid)
        if old is not None:
            try:
                asyncio.ensure_future(old.pc.close())
            except Exception:
                pass
        peer = YawPeer(self.id, self.sig, pid, self.on_event, share=self.share, nick=self.nick)
        peer.created = time.monotonic()
        self.peers[pid] = peer
        return peer

    async def _try_connect(self, pid: str):
        """Offerer side: if we trust a present peer with no live session, offer."""
        if pid == self.id.id:
            return
        if not self._trusted(pid):
            self.on_event("untrusted", peer=pid)
            return
        if self.id.id >= pid:
            return  # we are the answerer; we only answer offers
        existing = self.peers.get(pid)
        if existing is not None:
            alive = existing.pc.connectionState not in ("failed", "closed")
            fresh = time.monotonic() - getattr(existing, "created", 0) < self.RETRY_AFTER
            if existing.verified or (alive and fresh):
                return  # connected, or a young attempt still in flight — leave it
        await self._new_peer(pid).start_offer()

    async def _on_join(self, pid, *_):
        await self._try_connect(pid)

    async def _on_leave(self, pid):
        self.peers.pop(pid, None)

    async def _on_from(self, frm, obj):
        if not self._trusted(frm):
            self.on_event("untrusted", peer=frm)
            return
        kind = obj.get("kind")
        if kind == "offer":
            existing = self.peers.get(frm)
            peer = existing if (existing is not None and existing.verified) else self._new_peer(frm)
            await peer.handle_signal(obj)
        elif kind == "answer":
            peer = self.peers.get(frm)
            if peer is not None:
                await peer.handle_signal(obj)

    async def _reconcile(self):
        while True:
            await asyncio.sleep(self.RECONCILE)
            for pid in list(self.sig.peers):
                await self._try_connect(pid)

    async def accept(self, node_id: str, nick: str = "") -> bool:
        """Trust an id (with an optional nickname); connect immediately if present."""
        added = self.keyring.accept(node_id, nick) if self.keyring else False
        node_id = node_id.strip().lower()
        if node_id in self.sig.peers:
            await self._try_connect(node_id)
        return added

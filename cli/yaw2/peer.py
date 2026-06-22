"""YAW/2 peer + node over aiortc (protocol §6, §8, §9).

Non-trickle ICE (aiortc embeds candidates in the SDP). The session is bound to
the Ed25519 identity by a signed `hello` over both DTLS fingerprints. Chat rides
the `yaw` control channel; files ride a dedicated `f:<xid>` channel.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import re
import time

from aiortc import (RTCPeerConnection, RTCConfiguration, RTCIceServer,
                    RTCSessionDescription)
from nacl.public import PrivateKey, PublicKey, Box

from .identity import Identity
from .signaling import Signaling
from .fileshare import FileShare
from .config import stun_url

STUN = stun_url()
BIND_PREFIX = b"yaw/2 bind"
EKEY_PREFIX = b"yaw/2.1 ekey"      # signed context for the ephemeral-key message
FS_TIMEOUT = 2.0                   # wait for peer's ekey before falling back to 2.0
CHUNK = 64 * 1024


def _dtls_fp(sdp: str) -> bytes:
    # algorithm-agnostic (sha-256/sha-512/…): both peers see the same single fingerprint
    # line per description, so binding over its hex stays consistent across WebRTC stacks.
    m = re.search(r"a=fingerprint:\S+\s+([0-9A-Fa-f:]+)", sdp or "", re.I)
    return bytes.fromhex(m.group(1).replace(":", "")) if m else b""


class YawPeer:
    def __init__(self, identity: Identity, signaling: Signaling, peer_id: str, on_event,
                 share=None, nick="", fs=True, require_fs=False):
        self.id = identity
        self.sig = signaling
        self.peer_id = peer_id
        self.on_event = on_event
        self.share = share          # FileShare or None (we host a browsable folder)
        self.nick = nick            # our self-asserted display nick (informational)
        self.pc = RTCPeerConnection(RTCConfiguration([RTCIceServer(urls=STUN)]))
        self.dc = None
        self.verified = False
        self.peer_authed = False    # we've opened an authenticated sealed box from peer_id
        self._recv = {}   # xid -> {name,size,sha,buf}
        self._send = {}   # xid -> bytes

        # yaw/2.1 forward-secret signaling: per-session ephemeral X25519 (§3'/§6').
        self.fs = fs                                  # are we willing to do FS?
        self.require_fs = require_fs                  # refuse non-FS (2.0) sessions (§6.1)
        self._esk = PrivateKey.generate() if fs else None
        self._epk = self._esk.public_key if fs else None
        self.peer_epk = None                          # peer's ephemeral pubkey, once known
        self.session_fs = False                       # did this session end up forward-secret
        self._ekey_sent = False
        self._offer_pending = False
        self._offered = False

        @self.pc.on("datachannel")
        def _on_dc(channel):
            self._wire(channel)

        @self.pc.on("connectionstatechange")
        def _on_conn_state():
            self.on_event("status", peer=self.peer_id, state=self.pc.connectionState)

    # -- signaling seal/open (yaw/2.1 §5.4'/§6') -------------------------------
    def _seal(self, obj, prefer_eph):
        """Seal a signaling payload; ephemeral if we can, else static (2.0)."""
        data = json.dumps(obj).encode()
        if prefer_eph and self.peer_epk is not None and self._esk is not None:
            enc = Box(self._esk, self.peer_epk).encrypt(data, os.urandom(24))
            return base64.b64encode(bytes(enc)).decode(), True
        return self.id.seal(self.peer_id, data), False

    def _open(self, box):
        """Return (plaintext, used_ephemeral). Tries ephemeral then static — a wrong
        key fails the Poly1305 tag cleanly, so try-both is safe (§5.4')."""
        if self.peer_epk is not None and self._esk is not None:
            try:
                return bytes(Box(self._esk, self.peer_epk).decrypt(base64.b64decode(box))), True
            except Exception:
                pass
        try:
            return self.id.open(self.peer_id, box), False
        except Exception:
            return None, False

    async def _send_ekey(self):
        if not self.fs or self._ekey_sent:
            return
        self._ekey_sent = True
        epk_raw = bytes(self._epk)
        sig = self.id.sign(EKEY_PREFIX + bytes.fromhex(self.id.id)
                           + bytes.fromhex(self.peer_id) + epk_raw)
        msg = {"kind": "ekey", "v": "yaw/2.1", "epk": epk_raw.hex(), "sig": sig.hex()}
        box, _ = self._seal(msg, prefer_eph=False)          # ekey is always static
        await self.sig.send_to(self.peer_id, box)

    async def _on_ekey(self, obj):
        if not self.fs or self.peer_epk is not None:
            return
        try:
            epk_raw = bytes.fromhex(obj.get("epk", ""))
            sig = bytes.fromhex(obj.get("sig", ""))
            signed = EKEY_PREFIX + bytes.fromhex(self.peer_id) + bytes.fromhex(self.id.id) + epk_raw
            if len(epk_raw) != 32 or not Identity.verify(self.peer_id, signed, sig):
                return
            self.peer_epk = PublicKey(epk_raw)
        except Exception:
            return
        await self._send_ekey()                              # reciprocate (idempotent)
        if self._offer_pending:                              # offerer was waiting for epk
            await self._do_offer()

    # -- offer/answer ----------------------------------------------------------
    async def start_offer(self):
        if self.fs:
            await self._send_ekey()
            self._offer_pending = True
            asyncio.ensure_future(self._offer_timer())
            if self.peer_epk is not None:                    # peer's ekey already arrived
                await self._do_offer()
        else:
            await self._do_offer()

    async def _offer_timer(self):
        await asyncio.sleep(FS_TIMEOUT)
        if self._offer_pending:                              # no ekey -> 2.0 fallback
            await self._do_offer()

    async def _do_offer(self):
        if self._offered:
            return
        if self.require_fs and self.peer_epk is None:        # peer gave no ekey -> 2.0
            self._offer_pending = False
            self.on_event("fs-refused", peer=self.peer_id)
            asyncio.ensure_future(self.pc.close())
            return
        self._offered = True
        self._offer_pending = False
        self.dc = self.pc.createDataChannel("yaw")
        self._wire(self.dc)
        await self.pc.setLocalDescription(await self.pc.createOffer())
        box, eph = self._seal({"kind": "offer", "sdp": self.pc.localDescription.sdp}, prefer_eph=self.fs)
        self.session_fs = eph
        await self.sig.send_to(self.peer_id, box)

    async def on_box(self, box):
        """Open one relayed box and dispatch (replaces 2.0's handle_signal)."""
        plain, used_eph = self._open(box)
        if plain is None:
            return
        # A box that opens is authenticated to peer_id: ephemeral keys are bound to the
        # identity by the signed `ekey`; the static box uses peer_id's own key. So once we
        # open any box, the peer's identity is proven — and the (authenticated) offer/answer
        # carries the DTLS fingerprint that WebRTC enforces, binding identity to the channel.
        self.peer_authed = True
        try:
            obj = json.loads(plain)
        except Exception:
            return
        kind = obj.get("kind")
        if kind == "ekey":
            await self._on_ekey(obj)
        elif kind == "offer":
            if self.require_fs and not used_eph:             # static offer == 2.0 peer
                self.on_event("fs-refused", peer=self.peer_id)
                asyncio.ensure_future(self.pc.close())
                return
            await self.pc.setRemoteDescription(RTCSessionDescription(obj["sdp"], "offer"))
            await self.pc.setLocalDescription(await self.pc.createAnswer())
            box2, eph = self._seal({"kind": "answer", "sdp": self.pc.localDescription.sdp},
                                   prefer_eph=used_eph)       # answer matches the offer's keying
            self.session_fs = eph
            await self.sig.send_to(self.peer_id, box2)
        elif kind == "answer":
            if self.require_fs and not used_eph:
                self.on_event("fs-refused", peer=self.peer_id)
                asyncio.ensure_future(self.pc.close())
                return
            self.session_fs = used_eph
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
                    self._maybe_finish_file(xid)   # bytes can arrive after file-done

    async def _send_hello(self):
        if os.environ.get("YAW_DBG"):
            print(f"[dbg {self.id.id[:4]}] dc OPEN -> sending hello (offerer={self.id.id < self.peer_id})")
        bind = BIND_PREFIX + _dtls_fp(self.pc.localDescription.sdp) + _dtls_fp(self.pc.remoteDescription.sdp)
        caps = ["share"] if self.share else []
        self._dc({"type": "hello", "id": self.id.id, "nick": self.nick,
                  "caps": caps, "sig": self.id.sign(bind).hex()})

    async def _on_control(self, message):
        try:
            m = json.loads(message)
        except Exception as e:
            print(f"[dbg {self.id.id[:4]}] bad control msg: {e}"); return
        t = m.get("type")
        if os.environ.get("YAW_DBG"):
            print(f"[dbg {self.id.id[:4]}] got control {t}")
        if t == "hello":
            # Identity is bound to this channel by the *authenticated signaling*: the
            # offer/answer that set up this DTLS session arrived in a sealed box that only
            # peer_id could have produced (ephemeral key signed by the identity, or static
            # box to/from the identity), and WebRTC enforces the channel's cert against the
            # fingerprint inside that authenticated SDP. So verification = the box opened
            # (peer_authed) and the hello's claimed id matches. The DTLS-fingerprint text
            # is NOT used: stacks advertise a peer's cert under different hashes (WebKit
            # sha-512 vs aiortc sha-256), so the hex never matches cross-stack.
            ok = (m.get("id") == self.peer_id and self.peer_authed)
            self.verified = ok
            self.peer_caps = m.get("caps", [])
            self.on_event("connected", peer=self.peer_id, verified=ok,
                          nick=m.get("nick"), caps=self.peer_caps, fs=self.session_fs)
        elif t == "chat":
            self.on_event("chat", peer=self.peer_id, text=m.get("text", ""))
        elif t == "browse":
            path = m.get("path", "")
            entries = self.share.listing(path) if self.share else []
            self._dc({"type": "files", "path": path, "entries": entries})
        elif t == "files":
            self.on_event("files", peer=self.peer_id, path=m.get("path", ""),
                          entries=m.get("entries", []))
        elif t == "get":
            name = m.get("name", "")
            data = self.share.read(name) if self.share else None
            if data is None:
                self._dc({"type": "no-file", "name": name})
            else:
                self.send_file(os.path.basename(name), data)  # offer with a clean filename
        elif t == "no-file":
            self.on_event("no-file", peer=self.peer_id, name=m.get("name", ""))
        elif t == "file-offer":
            self._recv[m["xid"]] = {"name": m["name"], "size": m["size"],
                                    "sha": m["sha256"], "buf": bytearray(), "done": False}
            self._dc({"type": "file-accept", "xid": m["xid"]})
        elif t == "file-accept":
            asyncio.ensure_future(self._stream_file(m["xid"]))
        elif t == "file-done":
            st = self._recv.get(m["xid"])
            if st is not None:
                st["done"] = True
                st["sha"] = m["sha256"]
                self._maybe_finish_file(m["xid"])

    def _maybe_finish_file(self, xid):
        st = self._recv.get(xid)
        if st is None or not st["done"] or len(st["buf"]) < st["size"]:
            return                              # need file-done AND all bytes
        self._recv.pop(xid, None)
        ok = hashlib.sha256(st["buf"]).hexdigest() == st["sha"]
        self.on_event("file-recv", peer=self.peer_id, name=st["name"],
                      size=len(st["buf"]), ok=ok, data=bytes(st["buf"]))

    # -- application API -------------------------------------------------------
    def _dc(self, obj):
        # guard: aiortc raises if the channel isn't 'open' (e.g. a failed peer)
        if self.dc is not None and self.dc.readyState == "open":
            self.dc.send(json.dumps(obj))

    def send_chat(self, text: str):
        self._dc({"type": "chat", "text": text})

    def request_browse(self, path: str = ""):
        self._dc({"type": "browse", "path": path})

    def request_get(self, name: str):
        self._dc({"type": "get", "name": name})

    def send_file(self, name: str, data: bytes):
        xid = os.urandom(8).hex()
        self._send[xid] = data
        self._dc({"type": "file-offer", "xid": xid, "name": name,
                  "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})

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
        self._dc({"type": "file-done", "xid": xid,
                  "sha256": hashlib.sha256(data).hexdigest()})


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
                 share_dir=None, keyring=None, nick="", forward_secret=True,
                 require_fs=False):
        self.id = identity
        self.net = net
        self.on_event = on_event
        self.sig = Signaling(url, identity, net)
        self.peers: dict[str, YawPeer] = {}
        self.share = FileShare(share_dir) if share_dir else None
        self.keyring = keyring
        self.nick = nick
        self.fs = forward_secret        # yaw/2.1 forward-secret signaling (opportunistic)
        self.require_fs = require_fs    # the "switch": refuse non-FS (2.0) sessions

    def _trusted(self, pid: str) -> bool:
        return self.keyring is None or self.keyring.trusts(pid)

    async def start(self):
        present = await self.sig.connect()
        asyncio.ensure_future(self.sig.run(self._on_from, self._on_join,
                                           self._on_leave, self._on_reconnect))
        for pid in present:
            await self._try_connect(pid)
        asyncio.ensure_future(self._reconcile())

    async def _on_reconnect(self, present):
        self.on_event("signaling", state="reconnected", peers=len(present))
        for pid in present:                 # offerer re-offers any link that isn't live
            await self._try_connect(pid)

    def _new_peer(self, pid: str) -> YawPeer:
        old = self.peers.get(pid)
        if old is not None:
            try:
                asyncio.ensure_future(old.pc.close())
            except Exception:
                pass
        peer = YawPeer(self.id, self.sig, pid, self.on_event, share=self.share,
                       nick=self.nick, fs=self.fs, require_fs=self.require_fs)
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
            open_ = existing.dc is not None and existing.dc.readyState == "open"
            alive = existing.pc.connectionState not in ("failed", "closed")
            fresh = time.monotonic() - getattr(existing, "created", 0) < self.RETRY_AFTER
            # An OPEN control channel means negotiation succeeded — leave it alone even if
            # unverified: re-offering the same identity/cert pair can't change verification,
            # it only churns the link (and drops in-flight chat). Only re-offer a link that
            # is dead, or still stuck mid-negotiation past RETRY_AFTER.
            if existing.verified or open_ or (alive and fresh):
                return
        await self._new_peer(pid).start_offer()

    async def _on_join(self, pid, *_):
        await self._try_connect(pid)

    async def _on_leave(self, pid):
        self.peers.pop(pid, None)

    async def _on_from(self, frm, box):
        if not self._trusted(frm):
            self.on_event("untrusted", peer=frm)
            return
        peer = self.peers.get(frm)
        if peer is None or peer.pc.connectionState in ("failed", "closed"):
            peer = self._new_peer(frm)     # fresh session for a first/retried connection
        await peer.on_box(box)

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

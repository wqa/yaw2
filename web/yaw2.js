// YAW/2 web client — same protocol as the Python peer (spec §2–§9).
// Crypto via libsodium (vendor/sodium.bundle.js, global YAWSodium.default).
'use strict';

const YAW = (() => {
  let S = null; // libsodium, after ready
  const STUN = 'stun:fnlr.se:3478';
  const BIND_PREFIX = 'yaw/2 bind';
  const CHUNK = 64 * 1024;
  const enc = (s) => new TextEncoder().encode(s);

  async function ready() {
    S = YAWSodium.default;
    await S.ready;
    return S;
  }

  function netHash(name) {
    return S.to_hex(S.crypto_hash_sha256(enc('yaw2-net:' + (name || ''))));
  }
  function dtlsFp(sdp) {
    const m = /a=fingerprint:sha-256 ([0-9A-Fa-f:]+)/.exec(sdp || '');
    return m ? S.from_hex(m[1].replace(/:/g, '').toLowerCase()) : new Uint8Array();
  }
  function concat(...arrs) {
    const n = arrs.reduce((a, b) => a + b.length, 0);
    const out = new Uint8Array(n); let o = 0;
    for (const a of arrs) { out.set(a, o); o += a.length; }
    return out;
  }

  class Identity {
    constructor(kp) {
      this.pub = kp.publicKey; this.priv = kp.privateKey;
      this.id = S.to_hex(this.pub);
      this.curvePriv = S.crypto_sign_ed25519_sk_to_curve25519(this.priv);
    }
    static load() {
      let seedHex = localStorage.getItem('yaw2_seed');
      let kp;
      if (seedHex) kp = S.crypto_sign_seed_keypair(S.from_hex(seedHex));
      else {
        kp = S.crypto_sign_keypair();
        localStorage.setItem('yaw2_seed', S.to_hex(kp.privateKey.slice(0, 32)));
      }
      return new Identity(kp);
    }
    get short() { return this.id.slice(0, 16).replace(/(.{4})/g, '$1 ').trim(); }
    sign(data) { return S.crypto_sign_detached(data, this.priv); }
    static verify(idHex, data, sig) {
      try { return S.crypto_sign_verify_detached(sig, data, S.from_hex(idHex)); }
      catch { return false; }
    }
    seal(recipIdHex, plaintext) {
      const pub = S.crypto_sign_ed25519_pk_to_curve25519(S.from_hex(recipIdHex));
      const nonce = S.randombytes_buf(24);
      const ct = S.crypto_box_easy(plaintext, nonce, pub, this.curvePriv);
      return S.to_base64(concat(nonce, ct), S.base64_variants.ORIGINAL);
    }
    open(senderIdHex, boxB64) {
      const pub = S.crypto_sign_ed25519_pk_to_curve25519(S.from_hex(senderIdHex));
      const box = S.from_base64(boxB64, S.base64_variants.ORIGINAL);
      return S.crypto_box_open_easy(box.slice(24), box.slice(0, 24), pub, this.curvePriv);
    }
  }

  class Signaling {
    constructor(url, identity, net) { this.url = url; this.id = identity; this.net = net; this.ws = null; }
    connect(onFrom, onJoin, onLeave) {
      return new Promise((resolve, reject) => {
        const ws = new WebSocket(this.url); this.ws = ws;
        ws.onerror = () => reject(new Error('signaling connection failed'));
        ws.onmessage = (ev) => {
          const m = JSON.parse(ev.data);
          if (m.type === 'challenge') {
            const nonce = S.from_hex(m.nonce);
            const sig = S.to_hex(this.id.sign(concat(nonce, enc(this.net))));
            ws.send(JSON.stringify({ type: 'join', id: this.id.id, net: this.net, sig }));
          } else if (m.type === 'joined') {
            resolve(m.peers || []);
          } else if (m.type === 'from') {
            try { onFrom(m.from, JSON.parse(S.to_string(this.id.open(m.from, m.box)))); } catch (e) {}
          } else if (m.type === 'peer-join') onJoin(m.id);
          else if (m.type === 'peer-leave') onLeave(m.id);
        };
      });
    }
    sendTo(toId, obj) {
      this.ws.send(JSON.stringify({ type: 'to', to: toId, box: this.id.seal(toId, enc(JSON.stringify(obj))) }));
    }
  }

  function gatherComplete(pc) {
    if (pc.iceGatheringState === 'complete') return Promise.resolve();
    return new Promise((res) => {
      const check = () => { if (pc.iceGatheringState === 'complete') { pc.removeEventListener('icegatheringstatechange', check); res(); } };
      pc.addEventListener('icegatheringstatechange', check);
      setTimeout(res, 6000);
    });
  }

  class Peer {
    constructor(id, sig, peerId, on) {
      this.id = id; this.sig = sig; this.peerId = peerId; this.on = on;
      this.pc = new RTCPeerConnection({ iceServers: [{ urls: STUN }] });
      this.dc = null; this.verified = false;
      this._recv = {}; this._send = {};
      this.pc.ondatachannel = (ev) => this._wire(ev.channel);
    }
    async startOffer() {
      this.dc = this.pc.createDataChannel('yaw');
      this._wire(this.dc);
      await this.pc.setLocalDescription(await this.pc.createOffer());
      await gatherComplete(this.pc);
      this.sig.sendTo(this.peerId, { kind: 'offer', sdp: this.pc.localDescription.sdp });
    }
    async handleSignal(obj) {
      if (obj.kind === 'offer') {
        await this.pc.setRemoteDescription({ type: 'offer', sdp: obj.sdp });
        await this.pc.setLocalDescription(await this.pc.createAnswer());
        await gatherComplete(this.pc);
        this.sig.sendTo(this.peerId, { kind: 'answer', sdp: this.pc.localDescription.sdp });
      } else if (obj.kind === 'answer') {
        await this.pc.setRemoteDescription({ type: 'answer', sdp: obj.sdp });
      }
    }
    _wire(channel) {
      if (channel.label === 'yaw') {
        this.dc = channel;
        channel.onopen = () => this._sendHello();
        channel.onmessage = (ev) => this._onControl(ev.data);
        if (channel.readyState === 'open') this._sendHello();
      } else if (channel.label.startsWith('f:')) {
        const xid = channel.label.slice(2);
        channel.binaryType = 'arraybuffer';
        channel.onmessage = (ev) => { const st = this._recv[xid]; if (st) st.buf.push(new Uint8Array(ev.data)); };
      }
    }
    _sendHello() {
      const bind = concat(enc(BIND_PREFIX), dtlsFp(this.pc.localDescription.sdp), dtlsFp(this.pc.remoteDescription.sdp));
      this.dc.send(JSON.stringify({ type: 'hello', id: this.id.id, nick: 'web', sig: S.to_hex(this.id.sign(bind)) }));
    }
    _onControl(data) {
      const m = JSON.parse(data);
      if (m.type === 'hello') {
        const bind = concat(enc(BIND_PREFIX), dtlsFp(this.pc.remoteDescription.sdp), dtlsFp(this.pc.localDescription.sdp));
        this.verified = m.id === this.peerId && Identity.verify(m.id, bind, S.from_hex(m.sig));
        this.on('connected', { peer: this.peerId, verified: this.verified, nick: m.nick });
      } else if (m.type === 'chat') this.on('chat', { peer: this.peerId, text: m.text });
      else if (m.type === 'file-offer') {
        this._recv[m.xid] = { name: m.name, size: m.size, sha: m.sha256, buf: [] };
        this.dc.send(JSON.stringify({ type: 'file-accept', xid: m.xid }));
        this.on('file-incoming', { peer: this.peerId, name: m.name, size: m.size });
      } else if (m.type === 'file-accept') this._stream(m.xid);
      else if (m.type === 'file-done') {
        const st = this._recv[m.xid]; delete this._recv[m.xid];
        if (st) {
          const blob = new Blob(st.buf);
          blob.arrayBuffer().then((ab) => {
            const ok = S.to_hex(S.crypto_hash_sha256(new Uint8Array(ab))) === m.sha256;
            this.on('file-recv', { peer: this.peerId, name: st.name, size: ab.byteLength, ok, blob });
          });
        }
      }
    }
    sendChat(text) { if (this.dc) this.dc.send(JSON.stringify({ type: 'chat', text })); }
    async sendFile(file) {
      const data = new Uint8Array(await file.arrayBuffer());
      const xid = S.to_hex(S.randombytes_buf(8));
      this._send[xid] = data;
      this.dc.send(JSON.stringify({ type: 'file-offer', xid, name: file.name, size: data.length,
        sha256: S.to_hex(S.crypto_hash_sha256(data)) }));
    }
    async _stream(xid) {
      const data = this._send[xid]; delete this._send[xid]; if (!data) return;
      const ch = this.pc.createDataChannel('f:' + xid);
      await new Promise((res) => { ch.onopen = res; if (ch.readyState === 'open') res(); });
      for (let i = 0; i < data.length; i += CHUNK) {
        while (ch.bufferedAmount > (1 << 20)) await new Promise((r) => setTimeout(r, 10));
        ch.send(data.slice(i, i + CHUNK));
      }
      this.dc.send(JSON.stringify({ type: 'file-done', xid, sha256: S.to_hex(S.crypto_hash_sha256(data)) }));
    }
  }

  class Node {
    constructor(url, identity, net, on) {
      this.id = identity; this.net = net; this.on = on;
      this.sig = new Signaling(url, identity, net); this.peers = {};
    }
    async start() {
      const present = await this.sig.connect(
        (frm, obj) => this._route(frm, obj),
        (pid) => this._ensure(pid),
        (pid) => { delete this.peers[pid]; this.on('peer-leave', { peer: pid }); });
      for (const pid of present) await this._ensure(pid);
    }
    async _ensure(pid) {
      if (this.peers[pid] || pid === this.id.id) return this.peers[pid];
      // SPIKE: trust any id in the network (TOFU). Real client gates on a keyring.
      const p = new Peer(this.id, this.sig, pid, this.on);
      this.peers[pid] = p;
      if (this.id.id < pid) await p.startOffer();
      return p;
    }
    async _route(frm, obj) { const p = await this._ensure(frm); await p.handleSignal(obj); }
  }

  return { ready, netHash, Identity, Node };
})();

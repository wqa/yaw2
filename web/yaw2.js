// YAW/2 web client — same protocol as the Python peer (spec §2–§9).
// Crypto via libsodium (vendor/sodium.bundle.js, global YAWSodium.default).
'use strict';

const YAW = (() => {
  let S = null; // libsodium, after ready
  const STUN = (typeof window !== 'undefined' && window.YAW_CONFIG && window.YAW_CONFIG.stunURL)
    || 'stun:your-anchor.example:3478';   // real value comes from config.js (gitignored)
  const BIND_PREFIX = 'yaw/2 bind';
  const EKEY_PREFIX = 'yaw/2.1 ekey';   // signed context for the ephemeral-key message
  const FS_TIMEOUT = 2000;              // wait for peer's ekey before 2.0 fallback (ms)
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

  // --- passphrase-encrypted identity backup (shared format with the CLI) ------
  const BK_FORMAT = 'yaw-key-backup-1', BK_OPS = 2, BK_MEM = 67108864;
  function exportSeed(seed, passphrase) {
    const b64 = (b) => S.to_base64(b, S.base64_variants.ORIGINAL);
    const salt = S.randombytes_buf(S.crypto_pwhash_SALTBYTES);
    const key = S.crypto_pwhash(S.crypto_secretbox_KEYBYTES, passphrase, salt, BK_OPS, BK_MEM, S.crypto_pwhash_ALG_ARGON2ID13);
    const nonce = S.randombytes_buf(S.crypto_secretbox_NONCEBYTES);
    const ct = S.crypto_secretbox_easy(seed, nonce, key);
    const pub = S.to_hex(S.crypto_sign_seed_keypair(seed).publicKey);
    return { yaw: BK_FORMAT, id: pub, alg: 'argon2id-secretbox', ops: BK_OPS, mem: BK_MEM,
             salt: b64(salt), nonce: b64(nonce), ct: b64(ct) };
  }
  function importSeed(b, passphrase) {
    if (!b || b.yaw !== BK_FORMAT) throw new Error('not a yaw key backup');
    const ub = (s) => S.from_base64(s, S.base64_variants.ORIGINAL);
    const key = S.crypto_pwhash(S.crypto_secretbox_KEYBYTES, passphrase, ub(b.salt), b.ops | 0, b.mem | 0, S.crypto_pwhash_ALG_ARGON2ID13);
    return S.crypto_secretbox_open_easy(ub(b.ct), ub(b.nonce), key);   // throws on wrong passphrase
  }

  // --- nicknames + shareable contact card (format yaw-contact-1) ---------------
  function cleanNick(nick) {
    if (!nick) return '';
    nick = [...String(nick)].filter((ch) => { const c = ch.codePointAt(0); return c >= 0x20 && c !== 0x7f; }).join('');
    return nick.trim().slice(0, 40);
  }
  function makeCard(id, nick) {
    id = (id || '').toLowerCase();
    nick = cleanNick(nick);
    return 'yaw:' + id + (nick ? '?n=' + encodeURIComponent(nick) : '');
  }
  function parseCard(text) {
    text = (text || '').trim();
    if (text.startsWith('yaw:')) text = text.slice(4);
    let nick = '';
    const i = text.indexOf('?n=');
    if (i >= 0) { nick = cleanNick(decodeURIComponent(text.slice(i + 3))); text = text.slice(0, i); }
    const id = text.trim().toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(id)) throw new Error('not a valid id / contact card');
    return { id, nick };
  }

  // Seed storage: the OS keychain when running inside Tauri (survives "clear
  // browsing data", no eviction), else the browser's localStorage. In a plain
  // browser `_invoke` is null, so this is exactly the old localStorage behaviour.
  const _invoke = (typeof window !== 'undefined' && window.__TAURI__ && window.__TAURI__.core)
    ? window.__TAURI__.core.invoke : null;
  const inTauri = !!_invoke;
  async function seedGet() {
    if (_invoke) { try { const s = await _invoke('key_load', { account: 'seed' }); if (s) return s; } catch (e) {} }
    return localStorage.getItem('yaw2_seed');
  }
  async function seedSet(hex) {
    if (_invoke) { try { await _invoke('key_save', { account: 'seed', secret: hex }); return; } catch (e) {} }
    localStorage.setItem('yaw2_seed', hex);
  }

  class Identity {
    constructor(kp) {
      this.pub = kp.publicKey; this.priv = kp.privateKey;
      this.id = S.to_hex(this.pub);
      this.curvePriv = S.crypto_sign_ed25519_sk_to_curve25519(this.priv);
    }
    static async load() {
      let seedHex = await seedGet();
      let kp;
      if (seedHex) kp = S.crypto_sign_seed_keypair(S.from_hex(seedHex));
      else {
        kp = S.crypto_sign_keypair();
        await seedSet(S.to_hex(kp.privateKey.slice(0, 32)));
      }
      return new Identity(kp);
    }
    exportBackup(passphrase) { return exportSeed(this.priv.slice(0, 32), passphrase); }
    static async importBackup(backup, passphrase) {
      const seed = importSeed(backup, passphrase);   // throws on wrong passphrase
      await seedSet(S.to_hex(seed));
      return new Identity(S.crypto_sign_seed_keypair(seed));
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
    constructor(url, identity, net) {
      this.url = url; this.id = identity; this.net = net; this.ws = null;
      this._closed = false; this._backoff = 1000; this._cbs = {};
    }
    // Auto-reconnects (re-auth + resync) on a dropped socket. Active WebRTC links
    // are P2P and survive a signaling blip; this restores presence + new links.
    connect(onFrom, onJoin, onLeave, onReconnect) {
      this._cbs = { onFrom, onJoin, onLeave, onReconnect };
      return this._open(true);
    }
    _open(initial) {
      return new Promise((resolve, reject) => {
        const ws = new WebSocket(this.url); this.ws = ws;
        let joined = false;
        ws.onerror = () => { if (initial && !joined) reject(new Error('signaling connection failed')); };
        ws.onclose = () => { if (!this._closed) this._scheduleReconnect(); };
        ws.onmessage = (ev) => {
          const m = JSON.parse(ev.data);
          if (m.type === 'challenge') {
            const nonce = S.from_hex(m.nonce);
            const sig = S.to_hex(this.id.sign(concat(nonce, enc(this.net))));
            ws.send(JSON.stringify({ type: 'join', id: this.id.id, net: this.net, sig }));
          } else if (m.type === 'joined') {
            joined = true; this._backoff = 1000;
            const peers = m.peers || [];
            if (initial) resolve(peers);
            else if (this._cbs.onReconnect) this._cbs.onReconnect(peers);
          } else if (m.type === 'from') {
            // deliver the raw sealed box; the peer opens it (it owns static + ephemeral keys)
            this._cbs.onFrom(m.from, m.box);
          } else if (m.type === 'peer-join') this._cbs.onJoin(m.id);
          else if (m.type === 'peer-leave') this._cbs.onLeave(m.id);
        };
      });
    }
    _scheduleReconnect() {
      if (this._closed) return;
      const delay = this._backoff;
      this._backoff = Math.min(this._backoff * 2, 30000);
      setTimeout(() => { if (!this._closed) this._open(false).catch(() => {}); }, delay);
    }
    sendTo(toId, box) {
      // `box` is already a sealed payload (the peer picks static vs ephemeral keying)
      try { this.ws.send(JSON.stringify({ type: 'to', to: toId, box })); } catch (e) {}
    }
    close() { this._closed = true; if (this.ws) this.ws.close(); }
  }

  async function diagnose() {
    const pc = new RTCPeerConnection({ iceServers: [{ urls: STUN }] });
    pc.createDataChannel('diag');
    await pc.setLocalDescription(await pc.createOffer());
    await gatherComplete(pc);
    const cands = { host: [], srflx: [], relay: [] };
    const re = /a=candidate:\S+ \d+ \S+ \d+ (\S+) (\d+) typ (\w+)/;
    for (const line of (pc.localDescription.sdp || '').split('\n')) {
      const m = re.exec(line);
      if (m && cands[m[3]]) cands[m[3]].push(`${m[1]}:${m[2]}`);
    }
    pc.close();
    return cands;
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
    constructor(id, sig, peerId, on, share, nick, fs) {
      this.id = id; this.sig = sig; this.peerId = peerId; this.on = on;
      this.share = share || null;   // Map<name, File> we host (optional)
      this.nick = nick || '';       // our self-asserted display nick (informational)
      this.pc = new RTCPeerConnection({ iceServers: [{ urls: STUN }] });
      this.dc = null; this.verified = false; this.caps = [];
      this._recv = {}; this._send = {};
      this.pc.ondatachannel = (ev) => this._wire(ev.channel);
      this.pc.onconnectionstatechange = () => this.on('status', { peer: this.peerId, state: this.pc.connectionState });

      // yaw/2.1 forward-secret signaling: per-session ephemeral X25519 (§3'/§6').
      this.fs = fs !== false;
      const kp = this.fs ? S.crypto_box_keypair() : null;
      this._esk = kp ? kp.privateKey : null;
      this._epk = kp ? kp.publicKey : null;   // Uint8Array(32)
      this.peer_epk = null;                    // peer's ephemeral pubkey once known
      this.sessionFs = false;                  // did this session end up forward-secret
      this._ekeySent = false; this._offerPending = false; this._offered = false;
    }
    // -- signaling seal/open (yaw/2.1 §5.4'/§6') -------------------------------
    _seal(obj, preferEph) {
      const data = enc(JSON.stringify(obj));
      if (preferEph && this.peer_epk && this._esk) {
        const nonce = S.randombytes_buf(24);
        const ct = S.crypto_box_easy(data, nonce, this.peer_epk, this._esk);
        return [S.to_base64(concat(nonce, ct), S.base64_variants.ORIGINAL), true];
      }
      return [this.id.seal(this.peerId, data), false];   // static (2.0)
    }
    _open(box) {                                // -> [plaintext|null, usedEphemeral]
      if (this.peer_epk && this._esk) {
        try {
          const raw = S.from_base64(box, S.base64_variants.ORIGINAL);
          return [S.crypto_box_open_easy(raw.slice(24), raw.slice(0, 24), this.peer_epk, this._esk), true];
        } catch (e) {}
      }
      try { return [this.id.open(this.peerId, box), false]; } catch (e) { return [null, false]; }
    }
    _sendEkey() {
      if (!this.fs || this._ekeySent) return;
      this._ekeySent = true;
      const signed = concat(enc(EKEY_PREFIX), S.from_hex(this.id.id), S.from_hex(this.peerId), this._epk);
      const msg = { kind: 'ekey', v: 'yaw/2.1', epk: S.to_hex(this._epk), sig: S.to_hex(this.id.sign(signed)) };
      const [box] = this._seal(msg, false);     // ekey is always static
      this.sig.sendTo(this.peerId, box);
    }
    async _onEkey(obj) {
      if (!this.fs || this.peer_epk) return;
      try {
        const epkRaw = S.from_hex(obj.epk || '');
        const sig = S.from_hex(obj.sig || '');
        const signed = concat(enc(EKEY_PREFIX), S.from_hex(this.peerId), S.from_hex(this.id.id), epkRaw);
        if (epkRaw.length !== 32 || !Identity.verify(this.peerId, signed, sig)) return;
        this.peer_epk = epkRaw;
      } catch (e) { return; }
      this._sendEkey();                          // reciprocate (idempotent)
      if (this._offerPending) await this._doOffer();
    }
    async startOffer() {
      if (this.fs) {
        this._sendEkey();
        this._offerPending = true;
        setTimeout(() => { if (this._offerPending) this._doOffer(); }, FS_TIMEOUT);
        if (this.peer_epk) await this._doOffer();   // peer's ekey already arrived
      } else {
        await this._doOffer();
      }
    }
    async _doOffer() {
      if (this._offered) return;
      this._offered = true; this._offerPending = false;
      this.dc = this.pc.createDataChannel('yaw');
      this._wire(this.dc);
      await this.pc.setLocalDescription(await this.pc.createOffer());
      await gatherComplete(this.pc);
      const [box, eph] = this._seal({ kind: 'offer', sdp: this.pc.localDescription.sdp }, this.fs);
      this.sessionFs = eph;
      this.sig.sendTo(this.peerId, box);
    }
    async onBox(box) {                            // open one relayed box and dispatch
      const [plain, usedEph] = this._open(box);
      if (!plain) return;
      let obj; try { obj = JSON.parse(S.to_string(plain)); } catch (e) { return; }
      if (obj.kind === 'ekey') {
        await this._onEkey(obj);
      } else if (obj.kind === 'offer') {
        await this.pc.setRemoteDescription({ type: 'offer', sdp: obj.sdp });
        await this.pc.setLocalDescription(await this.pc.createAnswer());
        await gatherComplete(this.pc);
        const [box2, eph] = this._seal({ kind: 'answer', sdp: this.pc.localDescription.sdp }, usedEph);
        this.sessionFs = eph;                     // answer matches the offer's keying
        this.sig.sendTo(this.peerId, box2);
      } else if (obj.kind === 'answer') {
        this.sessionFs = usedEph;
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
      const caps = (this.share && this.share.size) ? ['share'] : [];
      this.dc.send(JSON.stringify({ type: 'hello', id: this.id.id, nick: this.nick, caps, sig: S.to_hex(this.id.sign(bind)) }));
    }
    requestBrowse() { if (this.dc) this.dc.send(JSON.stringify({ type: 'browse' })); }
    requestGet(name) { if (this.dc) this.dc.send(JSON.stringify({ type: 'get', name })); }
    _onControl(data) {
      const m = JSON.parse(data);
      if (m.type === 'hello') {
        const bind = concat(enc(BIND_PREFIX), dtlsFp(this.pc.remoteDescription.sdp), dtlsFp(this.pc.localDescription.sdp));
        this.verified = m.id === this.peerId && Identity.verify(m.id, bind, S.from_hex(m.sig));
        this.caps = m.caps || [];
        this.on('connected', { peer: this.peerId, verified: this.verified, nick: m.nick, caps: this.caps, fs: this.sessionFs });
      } else if (m.type === 'chat') this.on('chat', { peer: this.peerId, text: m.text });
      else if (m.type === 'browse') {
        const entries = this.share ? [...this.share.entries()].map(([name, f]) => ({ name, size: f.size })) : [];
        this.dc.send(JSON.stringify({ type: 'files', entries }));
      } else if (m.type === 'files') this.on('files', { peer: this.peerId, entries: m.entries || [] });
      else if (m.type === 'get') {
        const f = this.share && this.share.get(m.name);
        if (!f) this.dc.send(JSON.stringify({ type: 'no-file', name: m.name }));
        else this.sendFile(f);
      } else if (m.type === 'no-file') this.on('no-file', { peer: this.peerId, name: m.name });
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

  class Keyring {
    // Trusted peer ids + local nicknames, in localStorage. Friend-to-friend (§6).
    constructor() {
      const raw = JSON.parse(localStorage.getItem('yaw2_keyring') || '{}');
      this.names = Array.isArray(raw) ? Object.fromEntries(raw.map((id) => [id, ''])) : (raw || {});
    }
    trusts(id) { return ((id || '').toLowerCase()) in this.names; }
    name(id) { return this.names[(id || '').toLowerCase()] || ''; }
    accept(id, nick) {
      id = (id || '').trim().toLowerCase();
      if (!/^[0-9a-f]{64}$/.test(id)) throw new Error('not a valid id (need 64 hex chars)');
      const existed = id in this.names;
      this.names[id] = cleanNick(nick) || this.names[id] || '';
      this._save(); return !existed;
    }
    rename(id, nick) { id = (id || '').toLowerCase(); if (!(id in this.names)) return false; this.names[id] = cleanNick(nick); this._save(); return true; }
    remove(id) { id = (id || '').toLowerCase(); const had = delete this.names[id]; this._save(); return had; }
    all() { return Object.keys(this.names).sort(); }
    entries() { return Object.entries(this.names).sort((a, b) => (a[0] < b[0] ? -1 : 1)); }
    exportContacts() { return { yaw: 'yaw-contacts-1', contacts: this.entries().map(([id, nick]) => ({ id, nick })) }; }
    importContacts(data) {
      if (!data || data.yaw !== 'yaw-contacts-1') throw new Error('not a yaw contacts file');
      let n = 0;
      for (const c of (data.contacts || [])) {
        const id = (c.id || '').toLowerCase();
        if (/^[0-9a-f]{64}$/.test(id)) { this.names[id] = cleanNick(c.nick || '') || this.names[id] || ''; n++; }
      }
      this._save(); return n;
    }
    _save() { localStorage.setItem('yaw2_keyring', JSON.stringify(this.names)); }
  }

  class Node {
    constructor(url, identity, net, on) {
      this.id = identity; this.net = net; this.on = on;
      this.sig = new Signaling(url, identity, net); this.peers = {};
      this.shared = new Map();        // name -> File, the folder this tab hosts
      this.keyring = new Keyring();
      this.present = new Set();        // ids currently in the network
      this.nick = cleanNick(localStorage.getItem('yaw2_nick') || '');
      this.fs = true;                  // yaw/2.1 forward-secret signaling (opportunistic)
    }
    setNick(nick) { this.nick = cleanNick(nick); localStorage.setItem('yaw2_nick', this.nick); return this.nick; }
    _trusted(pid) { return this.keyring.trusts(pid); }
    async start() {
      const present = await this.sig.connect(
        (frm, obj) => this._onFrom(frm, obj),
        (pid) => { this.present.add(pid); this._tryConnect(pid); },
        (pid) => { this.present.delete(pid); delete this.peers[pid]; this.on('peer-leave', { peer: pid }); },
        (peers) => this._onReconnect(peers));
      for (const pid of present) { this.present.add(pid); await this._tryConnect(pid); }
      setInterval(() => { for (const pid of this.present) this._tryConnect(pid); }, 4000);
    }
    _onReconnect(peers) {
      this.on('signaling', { state: 'reconnected', peers: peers.length });
      this.present = new Set(peers);                 // 'joined' is authoritative after a blip
      for (const pid of peers) this._tryConnect(pid);
    }
    _newPeer(pid) {
      const old = this.peers[pid];
      if (old) { try { old.pc.close(); } catch (e) {} }
      const p = new Peer(this.id, this.sig, pid, this.on, this.shared, this.nick, this.fs);
      p.created = Date.now();
      this.peers[pid] = p; return p;
    }
    async _tryConnect(pid) {           // offerer side
      if (pid === this.id.id) return;
      if (!this._trusted(pid)) { this.on('untrusted', { peer: pid }); return; }
      if (this.id.id >= pid) return;   // we answer; we don't offer
      const e = this.peers[pid];
      if (e) {
        const alive = e.pc.connectionState !== 'failed' && e.pc.connectionState !== 'closed';
        const fresh = Date.now() - (e.created || 0) < 12000;   // RETRY_AFTER
        if (e.verified || (alive && fresh)) return;
      }
      await this._newPeer(pid).startOffer();
    }
    async _onFrom(frm, box) {
      if (!this._trusted(frm)) { this.on('untrusted', { peer: frm }); return; }
      let peer = this.peers[frm];
      if (!peer || peer.pc.connectionState === 'failed' || peer.pc.connectionState === 'closed') peer = this._newPeer(frm);
      await peer.onBox(box);
    }
    async accept(id, nick) {
      const added = this.keyring.accept(id, nick);
      id = id.trim().toLowerCase();
      if (this.present.has(id)) await this._tryConnect(id);
      return added;
    }
    forget(id) { return this.keyring.remove(id); }
  }

  return { ready, netHash, Identity, Keyring, Node, makeCard, parseCard, cleanNick, diagnose, inTauri };
})();

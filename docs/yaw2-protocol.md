# YAW/2 — Protocol Specification

**Version:** `yaw/2.0` · **Status:** draft for implementation · clean break from
WASTE 1.x (no wire-compatibility).

YAW/2 is a small, trusted, peer-to-peer encrypted mesh — chat, presence, and file
transfer — that pierces NAT the way the modern web does (ICE) and rides a modern
encrypted transport (WebRTC DataChannels). A lightweight server (the **anchor**)
helps peers *find* and *introduce* each other but never carries their data.

## 0. Design goals & decisions

- **True peer-to-peer.** Data flows directly between peers. The anchor only does
  signaling + STUN. *No relay (TURN).* Consequence accepted: peers learn each
  other's IP on a direct link, and a minority of peers behind symmetric NAT will
  fail to connect.
- **Modern transport.** WebRTC **DataChannels** — DTLS 1.2/1.3 (PFS, AEAD),
  congestion control, multiplexed reliable streams. File transfer is just a stream.
- **Modern identity.** **Ed25519** identities. Trust is friend-to-friend: you talk
  to a peer only if its public key is in your keyring (exchanged out-of-band).
- **Browser-first.** The reference client is a web app (WebRTC native). A **Tauri**
  shell wraps it for desktop (Electron is dropped); a **Python CLI** (`aiortc`)
  speaks the same protocol.
- **The server learns as little as possible.** Signaling payloads are sealed end
  to end, so the anchor never sees SDP, candidate IPs, chat, or files — only that
  two fingerprints are online in the same (hashed) network and exchanging blobs.

## 1. Terminology

| Term | Meaning |
|------|---------|
| **node / peer** | A participant, identified by its Ed25519 public key. |
| **id** | Lowercase hex of the 32-byte Ed25519 public key (64 chars). The node's identity. |
| **short id** | First 16 hex chars of `id`, grouped in 4s, for human verification. |
| **keyring** | The set of peer `id`s you have accepted (trust). |
| **network** | A named group. Scoped on the server by `net = hex(sha256("yaw2-net:" + name))`, so the server never sees the name. |
| **anchor** | The server: a WebSocket **signaling** endpoint + a **STUN** server. |
| **session** | One established WebRTC PeerConnection between two peers. |

## 2. Identity & trust

- Each node has an **Ed25519** keypair. The 32-byte public key (hex) is its `id`.
- A node connects to another **only if that peer's `id` is in its keyring.** Keys
  are exchanged out of band (paste the hex, a QR code, or `yaw://key/<id>`).
- Human verification: compare **short id**s ("read me yours") before accepting.
- The keyring is the sole trust root. The anchor is *not* trusted to vouch for
  identities; it cannot impersonate a peer (§7).

## 3. Cryptography

| Purpose | Primitive |
|---------|-----------|
| Identity / signatures | **Ed25519** (libsodium `crypto_sign_detached`) |
| Signaling confidentiality + sender auth | **X25519 + crypto_box** (XSalsa20-Poly1305). X25519 keys derived from the Ed25519 identity via `crypto_sign_ed25519_{pk,sk}_to_curve25519`. |
| Transport | **WebRTC DTLS** (ECDHE, AES-GCM/ChaCha20-Poly1305) over SCTP DataChannels. Per-session forward secrecy. |
| Hashes | SHA-256 (network scoping, file integrity) |

> **Why the DTLS cert is *not* your Ed25519 key.** Browsers generate their own
> ephemeral cert for `RTCPeerConnection`; you cannot make it your identity key.
> Instead we **bind** the identity to the session: the SDP (which contains the
> DTLS certificate fingerprint) travels inside an Ed25519-authenticated sealed
> box, and peers re-confirm with a signed `HELLO` over both fingerprints once the
> channel opens (§6). The result is equivalent: the encrypted channel is provably
> to the holder of the trusted Ed25519 key.

All implementations use **libsodium** (PyNaCl, libsodium.js, or a Rust binding) so
the signing and sealing are byte-identical across clients.

## 4. Architecture

```
        ┌──────────────── anchor (server) ────────────────┐
        │  WSS signaling  (relays sealed blobs by id)      │
        │  STUN  udp/3478 (public-address discovery)       │
        └───────▲───────────────────────────▲─────────────┘
                │ sealed offer/answer/cands   │
        ┌───────┴───────┐             ┌───────┴───────┐
        │   peer  A     │◀═══════════▶│   peer  B     │
        │ web / cli /   │  WebRTC      │ web / cli /   │
        │ tauri         │  DataChannel │ tauri         │
        └───────────────┘  (DTLS, P2P) └───────────────┘
                         direct, encrypted, no server in path
```

The anchor has **two** jobs and sees **no** user data:

1. **Signaling (WebSocket, `wss://`)** — authenticates members of a network and
   relays opaque sealed blobs between them by `id`.
2. **STUN (UDP/3478)** — standard STUN (RFC 5389), e.g. `stun:fnlr.se:3478`,
   used as an ICE server so peers learn their public (server-reflexive) address.
   *STUN only — no TURN relay.*

## 5. Signaling protocol (WebSocket, JSON)

One WebSocket per node. All frames are JSON objects with a `type`. Binary blobs
(signatures, sealed boxes) are lowercase hex or base64 as noted.

### 5.1 Join (authentication)

```
server → { "v":"yaw/2.0", "type":"challenge", "nonce":"<32-byte hex>" }
client → { "type":"join",
           "id":   "<ed25519 pubkey hex>",
           "net":  "<sha256 hex of 'yaw2-net:'+name>",
           "sig":  "<ed25519 sig over (nonce_bytes || net_bytes), hex>" }
server → { "type":"joined", "peers":[ "<id>", ... ] }   // current members of net
```

The server verifies `sig` against `id`, then registers the socket under
`(net, id)`. A node may join only one `net` per socket. Bad signature → close.

### 5.2 Presence

```
server → { "type":"peer-join",  "id":"<id>" }
server → { "type":"peer-leave", "id":"<id>" }
```

Pushed to all members of the same `net` as peers come and go.

### 5.3 Sealed relay

```
client → { "type":"to",   "to":"<id>",   "box":"<base64 crypto_box>" }
server → { "type":"from",  "from":"<id>", "box":"<base64 crypto_box>" }
```

The server forwards `box` verbatim to the socket registered for `(net, to)`,
stamping the real `from`. **The server cannot read `box`.** If `to` is offline,
the server replies `{ "type":"no-peer", "to":"<id>" }`.

### 5.4 Sealed payload (inside `box`)

`box = crypto_box(plaintext, nonce, recipient_x25519_pub, sender_x25519_priv)`,
serialized as `base64(nonce(24) || ciphertext)`. The recipient opens it with the
sender's X25519 public key (derived from the `from` id). `plaintext` is JSON:

```
{ "kind": "offer" | "answer" | "candidate" | "bye",
  "sdp":  "<full SDP>",            // for offer/answer
  "cand": "<ICE candidate line>", "mid":"0", "mline":0 }  // for candidate (trickle)
```

Because the box is authenticated by the sender's identity key, a received offer's
SDP — **including the DTLS fingerprint** — is bound to that identity.

## 6. Connection establishment

Both peers are joined to the same `net` and **each has the other's `id` in its
keyring**. (Untrusted `id` → ignore, or hold for manual accept.)

**Who offers:** the peer with the lexicographically **smaller `id`** is the
*offerer* (deterministic; avoids glare).

```
A = offerer (smaller id)                         B = answerer
───────────────────────────────                  ───────────────────────────────
pc = RTCPeerConnection({iceServers:[stun]})
dc = pc.createDataChannel("yaw",                 pc = RTCPeerConnection({iceServers:[stun]})
        {ordered:true})                          pc.ondatachannel = …
offer = pc.createOffer(); setLocalDescription
seal(offer) ─────────────"to B"────────────────▶ verify from∈keyring; setRemoteDescription
                                                  answer = createAnswer(); setLocalDescription
verify; setRemoteDescription ◀──"to A"─seal(answer)
  ⇄  trickle ICE candidates both ways as sealed {kind:"candidate"}  ⇄
        ICE connectivity checks (host + srflx)  →  DTLS handshake
                       "yaw" DataChannel opens on both sides
───────────────── identity confirm (mandatory) ─────────────────
each side, on open, sends on "yaw":
  { "type":"hello", "id":"<self id>", "nick":"…", "caps":[…],
    "sig":"<ed25519 over ('yaw/2 bind'||local_dtls_fp||remote_dtls_fp)>" }
each verifies the peer's sig against its known id AND the actual DTLS
fingerprints (from the SDP). Mismatch → close the connection.
```

After `hello` verification the session is **trusted and live**. `dtls_fp` is the
SHA-256 fingerprint from the SDP `a=fingerprint` line (32 bytes).

ICE config: gather **host + server-reflexive** candidates; **trickle** them as
they arrive. No TURN. If ICE fails (symmetric NAT both sides), the session is
abandoned — peers stay reachable through any other peer only if app-level relay is
enabled (§8.4, optional).

## 7. Why this is safe against a malicious anchor

- The anchor relays only **sealed, sender-authenticated** blobs, so it cannot read
  or forge SDP/candidates, and cannot inject its own DTLS fingerprint (that would
  require an Ed25519 signature it cannot produce).
- The `hello` confirmation re-binds the live channel to both DTLS fingerprints
  under each identity's signature.
- Therefore a hostile anchor can: see who is online in a `net`, see *that* two ids
  exchange blobs, drop/delay messages, and learn timing. It **cannot**: read or
  alter chat/files, MITM the channel, learn candidate IPs, or recover the network
  name (only confirm a guess of it).

## 8. Application protocol (over the `yaw` DataChannel)

The `yaw` channel is reliable + ordered. Each DataChannel message is one
UTF-8 JSON object (DataChannels are message-framed — no length prefix needed).
Unknown `type`s are ignored (forward compatibility). Every message carries `mid`
(a random 16-byte hex message id) for dedup.

| type | fields | meaning |
|------|--------|---------|
| `hello` | `id, nick, caps[], sig` | identity confirm (§6); first message |
| `presence` | `online:bool, nick` | online/away |
| `chat` | `room, text, ts` | group message to a room (default `#main`) |
| `pm` | `text, ts` | private message (this link only) |
| `file-offer` | `xid, name, size, sha256` | offer to send a file |
| `file-accept` | `xid` | accept an offer |
| `file-cancel` | `xid, reason` | decline / abort |
| `file-done` | `xid, sha256` | sender finished; verify hash |
| `bye` | — | graceful close |

`ts` is Unix milliseconds (advisory). `room` names are app-defined strings.

### 8.4 Group delivery (v1 = full mesh)

In v1 each peer connects **directly to every other** peer in the network (full
mesh of sessions). `chat`/`presence` are sent to **all** open sessions; `pm` to one.
Receivers dedup by `mid`.

> *Forward-compatible relay (optional, v1.1):* messages may carry `hops` (int, ≤4).
> A node receiving a message with `hops>0` whose `mid` is new MAY re-send it to its
> other peers with `hops-1`, restoring connectivity across pairs that couldn't form
> a direct session. v1 senders set `hops:0` (no relay).

## 9. File transfer (over a dedicated DataChannel)

Files ride their own channel so a large transfer never blocks chat.

```
sender                                            receiver
file-offer {xid,name,size,sha256} ──"yaw"───────▶ (user accepts)
                              ◀──"yaw"──── file-accept {xid}
open DataChannel label="f:<xid>" (ordered,binary)
stream raw chunks (default 64 KiB), honoring
bufferedAmountLowThreshold for backpressure  ───▶ append to file; running sha256
close "f:<xid>" after last chunk
file-done {xid, sha256} ────────"yaw"───────────▶ verify sha256; success/failure
```

- Chunk size: **64 KiB** default (DataChannel messages must stay < 256 KiB).
- Integrity: SHA-256 over the whole file, sent in the offer and re-asserted in
  `file-done`; the receiver verifies before accepting the file.
- The transport (DTLS) already encrypts; no extra app-layer file encryption.
- Either side may `file-cancel {xid}`; the data channel is closed.

## 10. Reference parameters

| Parameter | Value |
|-----------|-------|
| Protocol version | `yaw/2.0` |
| Signaling | `wss://fnlr.se/4802f621018e1968/signal` (WebSocket) **[deployed & verified]** |
| STUN | `stun:fnlr.se:3478` (coturn, STUN-only, **deployed & verified**) |
| Network scope | `net = hex(sha256("yaw2-net:" + name))` |
| Identity | Ed25519; `id = hex(pubkey)` (64 chars) |
| Signaling seal | libsodium `crypto_box`, `base64(nonce(24)||ct)` |
| Bind string | `"yaw/2 bind" || local_dtls_fp || remote_dtls_fp` |
| DataChannel (control) | label `yaw`, reliable, ordered |
| DataChannel (file) | label `f:<xid>`, reliable, ordered, binary |
| File chunk | 64 KiB |
| Default room | `#main` |

## 11. Security considerations

- **IP exposure (by design).** On a direct session each peer sees the other's host
  (LAN) and server-reflexive (public) addresses. The *anchor* does not (sealed
  signaling). To reduce LAN leakage, a client MAY gather srflx-only candidates at
  some connectivity cost.
- **Symmetric-NAT pairs may not connect** (no TURN). Optional app-relay (§8.4) or a
  future opt-in TURN can recover these.
- **Signaling metadata.** The anchor learns presence and the contact graph within a
  `net`, plus timing. It does not learn names, content, or IPs.
- **Signaling boxes are not forward-secret** (static X25519). They carry only
  short-lived SDP/candidates; the *session* keys are DTLS-ephemeral (PFS). A future
  revision may use ephemeral signaling keys.
- **Trust bootstrapping is out of band.** Compromise of the keyring exchange (e.g.
  accepting a wrong `id`) defeats the system — verify short ids.
- **Replay.** The join `nonce` is single-use; `mid` dedups app messages; DTLS
  prevents transport replay.

## 12. Differences from YAW/1 (WASTE)

| | YAW/1 (WASTE-faithful) | YAW/2 |
|--|--|--|
| Identity | RSA + SHA-1 fingerprint | Ed25519, key = id |
| Transport crypto | Blowfish-PCBC (legacy) | WebRTC DTLS (AEAD, PFS) |
| Handshake | custom 30-step | ICE + DTLS + signed bind |
| NAT traversal | none (needs reachable peer) | ICE/STUN (true P2P) |
| Server role | rendezvous *directory* | signaling + STUN, sealed |
| Topology | flood mesh w/ TTL | direct full mesh (relay optional) |
| Transport library | hand-rolled sockets | WebRTC (browser/aiortc) |

## 13. Open questions / future

- Opt-in **TURN** for symmetric-NAT pairs (breaks "no relay" — explicit choice).
- **Gossip relay** (§8.4 `hops`) for partial-connectivity resilience.
- **Ephemeral signaling keys** for forward-secret signaling.
- **Post-quantum**: hybrid X25519+ML-KEM once WebRTC/libsodium support is routine.
- **Room key distribution** (anchor optionally serves a network's member ids to
  ease group bootstrapping, still keyring-gated).

---

*Implement against §5–§9; everything else is rationale. Clients MUST interoperate
at the signaling JSON, the sealed-payload format, the identity-confirm `hello`, and
the application message types.*

# YAW/2 — Complete Protocol Specification & Implementation Guide

This document specifies the **YAW/2** protocol in enough detail to implement an
interoperable client from scratch, with worked examples and reproducible test
vectors. It consolidates the normative wire — **`yaw/2.0`** (the locked interop
baseline) — and the **`yaw/2.1`** forward-secret-signaling delta on top of it.

- Normative companions: [`yaw2.0-protocol.md`](yaw2.0-protocol.md) (the frozen 2.0
  wire) and [`yaw2.1-protocol.md`](yaw2.1-protocol.md) (the 2.1 delta). Where this
  guide and those disagree, the locked 2.0 doc wins for the 2.0 wire.
- Every hex/base64 value below is **real** and reproducible: run
  `cli/protocol_vectors.py` to regenerate them. Vectors use **fixed seeds and fixed
  nonces** for stability; production uses random seeds and a fresh random nonce per
  sealed message.
- Requirement keywords **MUST / SHOULD / MAY** are per RFC 2119.

---

## 1. Overview & architecture

YAW/2 is a small, friend-to-friend, end-to-end-encrypted mesh: chat, presence, and
file transfer between peers who already trust each other's keys.

```
   peer A  ── WebSocket (sealed) ──►  anchor  ◄── WebSocket (sealed) ──  peer B
      │         signaling only          │ STUN          signaling only        │
      └──────────────  direct WebRTC DataChannel (DTLS/SCTP)  ───────────────┘
                         chat, files — the anchor never sees these
```

Three roles:

1. **Peer** — a client. Has a long-term Ed25519 identity. Talks to other peers
   directly over a WebRTC DataChannel.
2. **Anchor (signaling server)** — a WebSocket relay. It authenticates peers, tracks
   presence within a (hashed) network, and forwards **opaque sealed blobs** between
   them. It has **no long-term key** of its own.
3. **STUN server** — standard RFC 5389 STUN for NAT traversal. **No TURN** (no relay)
   — media is always peer-to-peer.

**What the anchor can see:** that an id is present in a hashed network, when, from
what IP, and the *graph* of who relays to whom. **What it cannot see:** the network
name (only its hash), SDP, ICE candidate IPs, message content, or files — those are
sealed end-to-end (and in 2.1, sealed with keys the server never sees and that are
discarded after the session).

---

## 2. Encoding & wire conventions

| Thing | Rule |
|---|---|
| **Identifiers / keys / hashes** | lowercase **hex**. An id is 64 hex chars (32 bytes). |
| **Sealed boxes** | **standard base64 with padding** (RFC 4648 `+` `/` `=`). In libsodium.js this is `base64_variants.ORIGINAL`. **Not** URL-safe base64. |
| **Signatures** | Ed25519 detached, 64 bytes → 128 hex chars. |
| **JSON** | UTF-8, no BOM. Unknown fields and unknown message `type`/`kind` values **MUST be ignored** (forward compatibility). |
| **Strings** | UTF-8. |
| **Byte order** | All multi-byte concatenations are plain byte concatenation in the order written; there are no integer length prefixes on the wire (JSON framing). |
| **Max signaling frame** | 65536 bytes; larger frames MUST be dropped. |

---

## 3. Cryptographic primitives

All crypto is **libsodium** (PyNaCl, libsodium.js, …). Using the same library family
guarantees byte-identical signing and sealing across implementations.

| Purpose | Primitive (libsodium) |
|---|---|
| Identity & signatures | **Ed25519** — `crypto_sign_seed_keypair`, `crypto_sign_detached`, `crypto_sign_verify_detached` |
| Ed25519 → X25519 | `crypto_sign_ed25519_pk_to_curve25519`, `crypto_sign_ed25519_sk_to_curve25519` |
| Sealing (static & ephemeral) | **`crypto_box`** (X25519 + XSalsa20-Poly1305) — `crypto_box_easy` / `crypto_box_open_easy`; 2.1 ephemeral keypairs via `crypto_box_keypair` |
| Hashing | **SHA-256** — `crypto_hash_sha256` |
| Transport encryption | **WebRTC DTLS 1.2+** (handled by the WebRTC stack; already forward-secret) |

Nonces: every `crypto_box` seal uses a fresh **random 24-byte** nonce, prepended to
the ciphertext (§6). Never reuse a nonce with the same key pair.

---

## 4. Identity

A peer's identity is an **Ed25519 keypair**. The **id** is the hex of the 32-byte
public key. The 32-byte **seed** is the secret (the signing key is derived from it).

**Test vector** (seed A = `01` ×32):

```
seed A   0101010101010101010101010101010101010101010101010101010101010101
id A     8a88e3dd7409f195fd52db2d3cba5d72ca6709bf1d94121bf3748801b40f6f5c
seed B   0202020202020202020202020202020202020202020202020202020202020202
id B     8139770ea87d175f56a35466c34c7ecccb8d8a91b4ee37a25df60f5b8fc9b394
```

To **seal to** a peer (§6) you need X25519 keys derived from the Ed25519 keys:

```
A X25519 public = crypto_sign_ed25519_pk_to_curve25519(id A)
               = 1b1b58dd50ea14b60da17b790cd02754d970c9bab864ebb3c0f3016fe51d3f57
B X25519 public = 60346e7c911a5f6ba154129174cafe75b294ac3bbd5549632f48cec6266f8410
```

A peer's own X25519 **private** key is `crypto_sign_ed25519_sk_to_curve25519(seed-keypair secret key)`.

---

## 5. Network names

A network ("room") is a plaintext name, never sent in the clear. Both peers and the
server only ever use its hash:

```
net = hex( SHA-256( utf8("yaw2-net:" || name) ) )
```

`"yaw2-net:"` is the literal ASCII prefix. **Test vector:**

```
net("spike-room") = 946551fb7e524195ec14d6c6c903031fb8a60ce395635ff25ac6225d252fb1ee
```

Two peers connect only if they used the **same** name. The server isolates traffic by
`net` and never learns the name.

---

## 6. Sealed boxes (`crypto_box`)

A sealed box carries a JSON payload from sender → recipient, opaque to the server.

**Seal** (sender → recipient):

```
nonce  = random 24 bytes
ct     = crypto_box( plaintext, nonce, recipient_X25519_pub, sender_X25519_priv )   // ct = mac(16) || ciphertext
box    = base64_standard( nonce(24) || ct )
```

**Open** (recipient):

```
raw    = base64_decode(box)
nonce  = raw[0:24]
plain  = crypto_box_open( raw[24:], nonce, sender_X25519_pub, recipient_X25519_priv )
```

The serialized layout is always `nonce(24) || mac(16) || ciphertext`, base64-encoded.

**Test vector** (A → B, plaintext `{"kind":"chat-illustrative"}`, fixed nonce `33`×24):

```
seal nonce          333333333333333333333333333333333333333333333333
sealed (raw hex)    33...33 8535272f62f2ac2dc85fe6727cd96b7cf60d8725dcaf13b5ca6a52320318682b2ab9b905bd0dde5705b8399a
box (base64)        MzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzhTUnL2LyrC3IX+ZyfNlrfPYNhyXcrxO1ympSMgMYaCsqubkFvQ3eVwW4OZo=
```

(The `33`×24 nonce is the leading `MzMz…` in the base64; in production it is random.)

---

## 7. Signaling protocol (WebSocket)

The peer opens a WebSocket to the anchor's signaling URL (`wss://…/<path>/signal`).
All frames are single JSON objects. Sequence on connect:

### 7.1 Challenge → join

The server immediately sends a challenge:

```json
{ "v": "yaw/2.0", "type": "challenge", "nonce": "abab…abab" }
```

`nonce` is 32 random bytes (hex). The peer authenticates by signing the nonce bound to
the network, and joins:

```json
{ "type": "join", "id": "8a88…6f5c", "net": "9465…b1ee", "sig": "80e6…cd0d" }
```

where

```
sig = Ed25519_sign( nonce_bytes(32) || utf8(net_hex_string) ,  signing key )
```

**Note the exact signed bytes:** the 32 raw nonce bytes, then the **64-character net
hex string encoded as UTF-8** (i.e. the ASCII of `"9465…b1ee"`, 64 bytes), *not* the
net's raw 32 bytes. **Test vector** (id A, nonce `ab`×32, net = spike-room):

```
sign input (hex)  abab…abab 39343635353166…  (nonce, then ascii of the net hex)
join sig          80e6656606191e6958a660733d0907835c3ab05da2213232320cbca9e52aac58
                  6697fd82d3dd8744130bdfe1068af46ca362e4ce81658e4605e03cb124a8cd0d
```

The server verifies `sig` against `id` over `nonce || net`. On failure it closes with
code **4001**. A peer that does not authenticate within ~15 s is closed. A second
connection with the same `(net, id)` displaces the first (close code **4002**).

### 7.2 Joined + presence

On success the server replies with the currently-present peers (excluding you):

```json
{ "type": "joined", "peers": ["8139…b394", "…"] }
```

and thereafter pushes presence deltas:

```json
{ "type": "peer-join", "id": "8139…b394" }
{ "type": "peer-leave", "id": "8139…b394" }
```

### 7.3 Relay (opaque)

To send a sealed blob to another present peer:

```json
{ "type": "to", "to": "8139…b394", "box": "MzMz…OZo=" }
```

The server forwards it verbatim, tagging the sender:

```json
{ "type": "from", "from": "8a88…6f5c", "box": "MzMz…OZo=" }
```

If the target id is not present:

```json
{ "type": "no-peer", "to": "8139…b394" }
```

The server **never inspects `box`** — it only routes by id within the net. All
`offer`/`answer`/`ekey` payloads (§8, §13) travel as the `box` of `to`/`from`.

### 7.4 Reconnect

Signaling is best-effort. A client SHOULD auto-reconnect on socket close: re-open,
re-do challenge/join, and treat the new `joined` peer list as authoritative. Existing
WebRTC DataChannels are peer-to-peer and survive a signaling outage untouched.

---

## 8. Connection establishment (`yaw/2.0`)

Preconditions: both peers are joined to the same `net`, and **each has the other's id
in its keyring** (trust is established out of band — §15). An untrusted id is ignored.

**Roles:** the peer with the **lexicographically smaller id string** is the
**offerer**; the other **answers**. (For the vectors, id B `8139…` < id A `8a88…`, so
B offers.) The offerer also re-offers a link that has failed, so accepting a key at
any time eventually brings the link up.

**Non-trickle ICE:** candidates are gathered to completion and embedded in the SDP
before it is sent — there are no separate candidate messages.

Flow (sealed payloads in **bold**; each is the `box` of a `to`/`from`):

```
offerer (smaller id)                          answerer
─────────────────────                         ─────────────────────
dc = createDataChannel("yaw")
createOffer; setLocalDescription
gather ICE to completion
seal {kind:"offer", sdp} ──"to"──────────────► setRemoteDescription(offer)
                                               createAnswer; setLocalDescription
                                               gather ICE to completion
setRemoteDescription(answer) ◄──"to"── seal {kind:"answer", sdp}
        ICE connectivity checks → DTLS handshake → SCTP "yaw" channel opens
        signed `hello` exchange over the channel (§9)
```

Sealed payloads (§6) for 2.0:

```json
{ "kind": "offer",  "sdp": "v=0\r\no=- … a=candidate:… typ srflx …\r\n…" }
{ "kind": "answer", "sdp": "v=0\r\n… (with the answerer's candidates) …" }
```

`sdp` is the full WebRTC SDP string (with `\r\n` line endings) after ICE gathering.

**DataChannel:** the offerer creates a channel **labeled exactly `yaw`**. Gotcha: a
received channel may already be in `open` state when your `ondatachannel` handler
fires — send your `hello` if `readyState === "open"`, don't rely solely on the `open`
event.

---

## 9. Identity binding — the signed `hello`

WebRTC authenticates the *channel* (DTLS), not the *identity*. A browser can't pin the
DTLS cert to the Ed25519 key, so YAW binds them at the application layer: as soon as
the `yaw` channel opens, each side sends a `hello` signing **both DTLS fingerprints**.

```json
{ "type": "hello", "id": "8a88…6f5c", "nick": "magnus", "caps": ["share"], "sig": "fa51…d904" }
```

```
bind = utf8("yaw/2 bind") || local_fp(32) || remote_fp(32)
sig  = Ed25519_sign(bind, signing key)
```

- `local_fp` = **your** DTLS fingerprint; `remote_fp` = the **peer's**. Each side signs
  `prefix || own_fp || peer_fp`. The **verifier** reconstructs `prefix || sender_fp ||
  own_fp` (i.e. swaps the two, since the sender's `local` is the verifier's `remote`)
  and checks it against the sender's id.
- The **DTLS fingerprint** is the value of the SDP line
  `a=fingerprint:<algo> F8:BF:28:…` — strip colons, lowercase, hex-decode to bytes.
  Match the line **algorithm-agnostically** (`sha-256` is typical, but a stack MAY
  advertise its cert under `sha-512` or another hash): there is exactly one fingerprint
  line per description, so both peers extract the same value regardless of the hash. An
  implementation MUST NOT hard-match `sha-256` only — doing so yields an empty local
  fingerprint against such a stack and the bind can then never verify.
- A peer MUST treat a session whose `hello` fails verification, or whose `id` ≠ the
  expected peer id, as **unauthenticated** (don't display it as verified).
- `nick` (optional, §10) is a display label; `caps` (optional) advertises capabilities
  (e.g. `"share"`, §12).

**Test vector** (signer id A; example 32-byte fingerprints):

```
BIND_PREFIX        "yaw/2 bind"  (10 bytes)
local fp           f8bf28cbaf432cf859f350667d228387dbf965f6230df002c7979c98c2891673
remote fp          c90a985afb96d4085ab5fec69fa7a3dcd0de74792b3cf2c532c038e8676099a2
bind (hex)         7961772f322062696e64 f8bf…1673 c90a…99a2
hello sig          fa5185a99142fa22251e2788e314d2c44a0b5eb7b2a3723918d10fa9a9fb0e19
                   6b211057f97f3639cc40b00d2defc7dae01c09f8878b7a80e1d1c4420b8ad904
```

---

## 10. Application protocol (over the `yaw` DataChannel)

After the channel opens, all application messages are **plaintext JSON over the DTLS
channel** (the channel itself is encrypted; these are not separately sealed). Dispatch
on `type`; ignore unknown types.

| `type` | Fields | Meaning |
|---|---|---|
| `hello` | `id, nick?, caps?, sig` | identity binding (§9), sent once on open |
| `chat` | `text` | a chat message |
| `file-offer` | `xid, name, size, sha256` | offer to send a file (§11) |
| `file-accept` | `xid` | accept an offered file |
| `file-done` | `xid, sha256` | end of a file stream + its hash |
| `browse` | `path` | request a folder listing at `path` (§12) |
| `files` | `path, entries:[{name,dir?,size?}]` | one directory level |
| `get` | `name` | request a shared file by relative path |
| `no-file` | `name` | requested path unknown/refused |

```json
{ "type": "chat", "text": "hi there" }
```

---

## 11. File transfer

A file rides a **dedicated binary DataChannel** so it doesn't block the control
channel; control messages go over `yaw`.

```
sender                                         receiver
──────                                         ────────
file-offer {xid, name, size, sha256} ─────────► (verify name; auto-accept or prompt)
                              ◄──────────────── file-accept {xid}
open DataChannel "f:<xid>" (binary)
send file bytes in 65536-byte frames
   (pause while bufferedAmount > 1 MiB)
file-done {xid, sha256} ──────────────────────► reassemble; verify SHA-256
```

- `xid` = 8 random bytes, hex (16 chars), unique per transfer. e.g. `bd4f18ac27a9956f`.
- `sha256` = hex SHA-256 of the **whole file**. **Test vector:** `sha256("hello yaw\n")
  = 9a060d65a4649aedc3156ab556da46144538563c9b8a5a389f8a66f520517ac1`.
- The dedicated channel's label is **exactly** `f:` + `xid`. Binary frames are the raw
  file bytes in order; the receiver concatenates them. Chunk size is **65536** bytes;
  the sender SHOULD throttle on `bufferedAmount`.
- **Cross-channel ordering (critical):** the bulk bytes ride `f:<xid>` while `file-done`
  rides the `yaw` control channel — **two independent SCTP streams with no ordering
  between them**. For a large file, the small `file-done` can arrive *before* the last
  bytes. The receiver therefore MUST finalize (hash-check) only once it has **both**
  received `file-done` **and** accumulated the full `size` bytes from `file-offer` —
  never hash immediately on `file-done`. (Finalizing on `file-done` alone makes large
  transfers fail the hash check while small ones pass.)

---

## 12. Shared-folder browse (capability extension)

Optional, additive, capability-gated. A peer that hosts a **directory tree**
advertises `caps:["share"]` in its `hello`. Others may then `browse` it like a
filesystem and `get` files (read-only). `browse.path`/`files.path` are relative to
the share root (`""` = root); `files.entries` is one directory level, where a folder
has `"dir": true` and a file has a `size`.

```json
{ "type": "browse", "path": "" }
{ "type": "files",  "path": "",
  "entries": [ { "name": "photos", "dir": true }, { "name": "report.pdf", "size": 12345 } ] }
{ "type": "browse", "path": "photos/trip" }     // descend
{ "type": "get", "name": "photos/trip/view.jpg" }  →  triggers a normal §11 file-offer
{ "type": "no-file", "name": "photos/trip/view.jpg" } // unknown or refused
```

**Security (mandatory):** the host MUST treat `browse.path` and `get.name` as
untrusted — serve a path only if it resolves **inside** the share root: reject
absolute paths and any component that is empty, `..`, or starts with `.`; then join
onto the root, resolve the **real** path (following symlinks), and require it to stay
within the root (defeats symlink escapes); `get` must land on a regular file. Else
reply `no-file`. See [`extensions/file-browse.md`](extensions/file-browse.md).

---

## 13. Forward-secret signaling (`yaw/2.1`)

2.1 is a **client-side-only** delta: it changes which keys seal the
`offer`/`answer`/`candidate` payloads — from the **static** identity-derived X25519
keys (2.0) to **per-session ephemeral** X25519 keys, introduced by a signed **`ekey`**
message. This makes recorded signaling unreadable even if a long-term key later leaks
(forward secrecy). The anchor is unchanged — it still relays opaque boxes.

### 13.1 The `ekey` message (sealed **static**, as in 2.0)

```json
{ "kind": "ekey", "v": "yaw/2.1", "epk": "7b4e…3f13", "sig": "53a6…8705" }
```

- `epk` = a fresh per-session **X25519 public key** (`crypto_box_keypair`), hex (32 bytes).
- `sig = Ed25519_sign( utf8("yaw/2.1 ekey") || my_id_raw(32) || peer_id_raw(32) || epk_raw(32) )`.
  Binding both ids stops an `ekey` being replayed to a third party.
- The recipient verifies `sig` against the **sender's** id, reconstructing
  `utf8("yaw/2.1 ekey") || sender_id_raw || my_id_raw || epk_raw`, and checks that the
  bound peer id is itself.

**Test vector** (A's ekey for B; A ephemeral private = `11`×32):

```
A ephemeral X25519 pub (epk)   7b4e909bbe7ffe44c465a220037d608ee35897d31ef972f07f74892cb0f73f13
ekey sign input (hex)          7961772f322e3120656b6579 8a88…6f5c 8139…b394 7b4e…3f13
ekey sig                       53a6a701dd9c65ca08f75fe85f4645e8da55e8fe4b634db3a9b87685a26f0e99
                               b5b22f3c190847b35e9bfd1550d57f6aaaed31cfafc02dddb1d13a65b4a58705
```

### 13.2 Ephemeral seal

Once both peers hold each other's `epk`, `offer`/`answer` are sealed with the
**ephemeral** box — identical serialization to §6, but the keys are
`crypto_box(plaintext, nonce, peer_epk, my_esk)`. **Test vector** (A→B, ephemeral
keys, nonce `44`×24, plaintext `{"kind":"chat-illustrative"}`):

```
ephemeral box (base64)  REREREREREREREREREREREREREREREREO3NNFFPoeKzsr4Opo7KfwuPFclRX6oCWT75db2ArLRg/tbhiPbK1ykfgHnk=
```

### 13.3 Which key opens a box?

Determined by **ordering**, not a plaintext tag (so the server learns nothing): a peer
always sends its `ekey` *before* any ephemeral box, and the WebSocket preserves
per-sender order. So:

- `kind:"ekey"` → open with **static** keys.
- any other kind → if you hold the sender's `epk`, open with **ephemeral**; else the
  sender is a 2.0 peer → open with **static**. Implementations SHOULD **try-both** (a
  wrong key fails the Poly1305 tag cleanly): try ephemeral first if you have `epk`,
  else static.

### 13.4 Establishment with ekey

```
offerer (smaller id, 2.1)                      answerer (2.1)
esk_A,epk_A = crypto_box_keypair()             esk_B,epk_B = crypto_box_keypair()
sealStatic(ekey{epk_A,sig}) ──"to"───────────► verify ekey; store epk_A
store epk_B ◄────"to"── sealStatic(ekey{epk_B,sig})  (answerer reciprocates on receiving ekey)
createOffer; gather
sealEph(offer) ──"to"────────────────────────► sealEph(answer)  ◄── answer matches the offer's keying
        … then DTLS, "yaw" channel, signed hello — exactly as 2.0 (§8–§9) …
        on session close: wipe esk
```

### 13.5 Opportunistic fallback & the cutover (interop with 2.0)

A 2.1 client interoperates with 2.0 automatically:

1. The 2.1 client sends its `ekey`, then starts a **2 s** timer.
2. **Offerer:** if `epk_B` arrives before the timer → send the `offer` with `sealEph`.
   If the timer fires first (no `ekey` — the peer is 2.0) → send the `offer` with
   `sealStatic`, mark the session **non-FS**.
3. **Answerer:** reply with the **same keying that opened the offer** — `sealEph` if
   the offer opened with ephemeral keys, `sealStatic` if it opened static (2.0 peer).
4. A 2.0 peer ignores the unknown `ekey` kind and behaves exactly as 2.0.

A client MAY enforce **require-FS** (refuse / close non-FS sessions for the final
cutover once everyone has upgraded); otherwise it MUST surface FS status to the user.

---

## 14. Reference constants

| Constant | Value |
|---|---|
| Protocol versions | `yaw/2.0` (challenge `v`), `yaw/2.1` (ekey `v`) |
| Net-hash prefix | `"yaw2-net:"` (ASCII), then SHA-256, hex |
| Sign-bind prefix (hello) | `"yaw/2 bind"` (10 bytes) |
| Sign prefix (ekey) | `"yaw/2.1 ekey"` (12 bytes) |
| Sealed-box base64 | standard, padded (libsodium `ORIGINAL`) |
| Sealed-box layout | `nonce(24) || mac(16) || ciphertext` |
| Offerer | peer with the lexicographically smaller id string |
| ICE | non-trickle (candidates embedded in SDP) |
| Control DataChannel label | `yaw` |
| File DataChannel label | `f:` + `xid` (xid = 8 random bytes hex) |
| File chunk size | 65536 bytes |
| File backpressure | pause while `bufferedAmount` > 1 MiB |
| Max signaling frame | 65536 bytes |
| Join timeout (server) | ~15 s |
| FS negotiation timeout (2.1) | 2 s, then fall back to 2.0 |
| Auth-fail / replaced / rate-limit close codes | 4001 / 4002 / 4003 |

---

## 15. Security considerations

- **Trust = the keyring.** A session forms only between peers who have each accepted
  the other's id, exchanged **out of band** (e.g. a contact card `yaw:<id>?n=<nick>`).
  Verify a peer's short id out of band before accepting. The anchor cannot vouch for
  or impersonate anyone.
- **Content** (chat/files) is protected by WebRTC **DTLS** with per-session forward
  secrecy; the anchor never sees it.
- **Signaling** is sealed end-to-end. In **2.0** the sealing keys are static (derived
  from long-term identity keys), so recorded signaling could be decrypted if those
  keys later leak. **2.1** closes this with ephemeral keys wiped after the session.
- **Identity binding** (§9) prevents a malicious anchor from man-in-the-middling: it
  would have to forge an Ed25519 signature over the real DTLS fingerprints.
- **Metadata the anchor learns:** presence, timing, peer IPs (at signaling time via
  the relayed candidates in 2.0 — sealed, but the endpoints are the peers'), and the
  contact graph within a hashed net. It does **not** learn the network name or content.
- **No TURN by design:** peers behind symmetric NAT / CGNAT may be unable to connect;
  there is no relay fallback. This is an accepted trade-off for true P2P.

---

## 16. Interop checklist & common pitfalls

1. **Base64 variant** — sealed boxes are **standard padded** base64, not URL-safe.
2. **Net hashing** — `SHA-256("yaw2-net:" + name)`, hex; sign join over
   `nonce_bytes || utf8(net_hex_string)` (the hex *string*, not raw bytes).
3. **`hello` bind byte order** — sign `prefix || own_fp || peer_fp`; the verifier swaps.
4. **DataChannel open-race** — a received channel can already be `open`; send `hello`
   on a `readyState === "open"` check too.
5. **Non-trickle** — gather ICE to completion before sending SDP; no candidate messages.
6. **Offerer rule** — smaller id offers; this also decides who re-offers on failure.
7. **2.1 try-both open** — a wrong key fails cleanly; try ephemeral (if you have `epk`)
   then static. Send `ekey` *before* any ephemeral box.
8. **Answer keying (2.1)** — answer with whichever key opened the offer.

A minimal interop test: stand up a peer against the live STUN + signaling, connect to
the reference CLI (`cli/`) or web (`web/`) client on the same net, exchange a chat and
a hash-verified file. Reproduce every vector here with `cli/protocol_vectors.py`.

---

## 17. Worked end-to-end trace (2.1, abridged)

Peers A (`8a88…`) and B (`8139…`) on `spike-room`; B is the offerer (smaller id). All
`to`/`from` boxes are sealed; `[static]`/`[eph]` notes the keying.

```
A→server  {"type":"join","id":"8a88…","net":"9465…","sig":"80e6…"}
B→server  {"type":"join","id":"8139…","net":"9465…","sig":"…"}
server→A  {"type":"joined","peers":["8139…"]}
server→B  {"type":"joined","peers":["8a88…"]}

B→A  to{ box=[static] {"kind":"ekey","v":"yaw/2.1","epk":"<epkB>","sig":"…"} }
A→B  to{ box=[static] {"kind":"ekey","v":"yaw/2.1","epk":"7b4e…3f13","sig":"53a6…8705"} }
B→A  to{ box=[eph]    {"kind":"offer","sdp":"v=0…"} }          # B holds epkA → ephemeral
A→B  to{ box=[eph]    {"kind":"answer","sdp":"v=0…"} }         # answer matches offer keying
        ICE checks → DTLS → "yaw" DataChannel opens
A→B  (dc) {"type":"hello","id":"8a88…","nick":"magnus","caps":[],"sig":"fa51…d904"}
B→A  (dc) {"type":"hello","id":"8139…","nick":"felix","sig":"…"}
        both verify hello → connected, forward-secret
A→B  (dc) {"type":"chat","text":"hi"}
```

---

## 18. Reproducing the vectors

```sh
cli/.venv/bin/python cli/protocol_vectors.py
```

prints every value in this document (fixed seeds/nonces). Match your implementation's
output against it to confirm wire compatibility before testing against a live peer.

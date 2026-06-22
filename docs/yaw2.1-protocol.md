# YAW/2.1 — Protocol Specification (forward-secret signaling)

**Version:** `yaw/2.1` · **Status:** 📝 **DRAFT** (proposed) · motivated by
[YIP-0001](proposals/yip-0001-forward-secret-signaling.md).

> **Implemented & deployed across all reference clients** — Python CLI (`cli/`),
> web (`web/`), and the Tauri desktop app — opportunistic, with a `require_fs`
> cutover switch. The CLI is verified live (`cli/test_fs_live.py`: 2.1↔2.1
> forward-secret, 2.1↔2.0 fallback, require-FS refusing a 2.0 peer), and the web's
> ekey signature + ephemeral box are verified **byte-identical to the CLI** across
> libsodium.js and PyNaCl. The deployed **server is untouched** — 2.1 is purely
> client-side (§5.4'), so the anchor just relays the opaque boxes as before.

> **2.1 = [2.0](yaw2.0-protocol.md) + forward-secret signaling.** This document is a
> **delta**: everything in [yaw2.0-protocol.md](yaw2.0-protocol.md) still applies
> *except* the sections replaced below (§3, §5.4, §6). Identity, signaling
> transport (§5.1–§5.3), the application protocol (§8), and file transfer (§9) are
> **unchanged**. 2.1 peers **interoperate with 2.0** by falling back (§6.1).

## What changes vs 2.0

The only change is the key material used to seal `offer`/`answer`/`candidate`
signaling payloads: 2.0 uses **static** X25519 keys (from the long-term Ed25519
identity); 2.1 uses **per-session ephemeral** X25519 keys, wiped after the session,
introduced by a new signed **`ekey`** message. This makes the signaling
forward-secret (see the YIP for the threat it closes). Nothing else changes.

---

## §3′ Cryptography (replaces 2.0 §3)

Unchanged from 2.0 **except** the "Signaling confidentiality" row:

| Purpose | Primitive |
|---------|-----------|
| Identity / signatures | **Ed25519** (unchanged) |
| **Signaling — `ekey` exchange** | sealed with **static** X25519 (`crypto_box`, keys derived from Ed25519 as in 2.0). Carries only ephemeral *public* keys. |
| **Signaling — offer/answer/candidate** | sealed with **ephemeral** X25519: `crypto_box(plaintext, nonce, peer_epk, my_esk)`, where `(esk, epk)` is a fresh per-session X25519 keypair. |
| Transport | **WebRTC DTLS** (unchanged; already PFS) |
| Hashes | SHA-256 (unchanged) |

Each peer generates `(esk, epk) = crypto_box_keypair()` **per session** and
**securely wipes `esk`** when the session ends or is abandoned. `epk` is exchanged
and authenticated via the `ekey` message (§5.4′).

All seal serialization (`base64_ORIGINAL(nonce(24)||mac(16)||ct)`) is exactly as in
2.0 — only the *keys* differ.

## §5.4′ Sealed payloads (replaces 2.0 §5.4)

The relay envelope (`{type:"to"/"from", box}`) is unchanged. Two keying schemes now
exist for the inner `box`:

**(a) `ekey` — sealed under STATIC keys** (as in 2.0):

```
{ "kind":"ekey",
  "v":   "yaw/2.1",
  "epk": "<x25519 ephemeral public key, hex (32 bytes)>",
  "sig": "<ed25519 sig, hex>" }
```

`sig` is over the exact bytes
`utf8("yaw/2.1 ekey") || my_id_raw(32) || peer_id_raw(32) || epk_raw(32)`
(`*_raw = hex_decode`). Binding both ids prevents an `ekey` from being replayed to
a third party. The recipient verifies `sig` against the sender id and that the
embedded `peer_id` is *itself*.

**(b) `offer` / `answer` / `candidate` / `bye` — sealed under EPHEMERAL keys:**
identical JSON to 2.0 §5.4, but the `box` is `crypto_box(…, peer_epk, my_esk)`.

**Which key opens an incoming box?** Determined by ordering, not a plaintext tag
(so the server learns nothing extra): a peer always sends its `ekey` *before* any
ephemeral box, and the WebSocket preserves per-sender order. Therefore:

- `kind:"ekey"` → open with **static** keys.
- any other kind → if you already hold the sender's `epk`, open with **ephemeral**
  keys; if you do not (sender sent no `ekey`), the sender is a 2.0 peer → open with
  **static** keys (§6.1). Implementations MAY also try-both (a wrong key fails the
  Poly1305 tag cleanly) for robustness.

## §6′ Connection establishment (replaces 2.0 §6)

Preconditions as in 2.0 (same `net`, peer id in keyring). Offerer = smaller id.

```
A = offerer (smaller id)                         B = answerer
──────────────────────────────                   ──────────────────────────────
esk_A, epk_A = box_keypair()                     esk_B, epk_B = box_keypair()
sealStatic(ekey{epk_A,sig}) ──"to B"───────────▶ verify ekey; store epk_A
store epk_B ◀──────"to A"── sealStatic(ekey{epk_B,sig})
createOffer; setLocalDescription; gather-complete
sealEph(offer.sdp) ───"to B"───────────────────▶ verify from∈keyring; setRemoteDescription
                                                 createAnswer; setLocalDescription; gather-complete
verify; setRemoteDescription ◀──"to A"── sealEph(answer.sdp)
        ICE checks (host + srflx) → DTLS → "yaw" DataChannel opens
        identity-confirm `hello` exactly as in 2.0 §6
        ── on session close/abandon: WIPE esk ──
```

- `sealStatic(...)` = 2.0 static-key box; `sealEph(...)` = ephemeral-key box.
- Both peers send `ekey` first (no offerer/answerer distinction for `ekey`).
- The offerer sends the `offer` only after it holds `epk_B`; the answerer sends the
  `answer` only after it has both sent its `ekey` and received the `offer`. Because
  a sender's `ekey` precedes its ephemeral boxes and the channel is ordered, the
  recipient always holds the peer's `epk` before any ephemeral box arrives.
- Everything after the DataChannel opens (the signed `hello`, §8, §9) is **identical
  to 2.0**.

### §6.1 Backward compatibility (opportunistic FS)

2.1 ↔ 2.0 must interoperate. Rules:

1. A 2.1 peer sends its `ekey`, then starts a short timer (recommended **2 s**).
2. **2.1 offerer:** if `epk_B` arrives before the timer, send the `offer` with
   `sealEph`. If the timer fires first (no `ekey` — peer is 2.0), send the `offer`
   with `sealStatic` and mark the session **non-FS**.
3. **2.1 answerer:** if an `offer` arrives and you hold `epk_A`, reply `sealEph`.
   If an `offer` arrives and you do **not** hold `epk_A` (2.0 offerer), reply
   `sealStatic` and mark the session **non-FS**.
4. A 2.0 peer ignores the unknown `ekey` kind (2.0 §8: "unknown types ignored") and
   behaves exactly as 2.0.

A client MAY enforce a **require-FS** policy (refuse / close non-FS sessions);
otherwise it MUST surface the non-FS status to the user.

## §10′ Reference parameters (additions to 2.0 §10)

| Parameter | Value |
|-----------|-------|
| Protocol version | `yaw/2.1` (advertised in the `ekey` `v` field) |
| Ephemeral key | X25519, `crypto_box_keypair()`, per session, `esk` wiped on close |
| `ekey` sign input | `utf8("yaw/2.1 ekey") \|\| my_id_raw \|\| peer_id_raw \|\| epk_raw` |
| `ekey` seal | static keys (2.0 scheme) |
| offer/answer/candidate seal | ephemeral keys `crypto_box(·, peer_epk, my_esk)` |
| FS-negotiation timeout | 2 s (then fall back to 2.0) |

## Security & compatibility notes

See [YIP-0001 §6](proposals/yip-0001-forward-secret-signaling.md) for the full
analysis. In short: pure-2.1 sessions are forward-secret (recorded signaling
unrecoverable after `esk` is wiped, even if long-term keys leak later); mixed 2.1/2.0
sessions fall back to 2.0 security and are flagged; authentication and the
malicious-server analysis (2.0 §7) are unchanged.

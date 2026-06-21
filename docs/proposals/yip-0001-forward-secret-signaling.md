# YIP-0001 — Forward-Secret Signaling

| | |
|---|---|
| **Status** | Proposed (target wire: `yaw/2.1`) |
| **Created** | 2026-06-21 |
| **Affects** | Signaling seal crypto — §3, §5.4, §6 |
| **Wire-breaking** | Yes (adds an `ekey` exchange) — but **opportunistic**: 2.1 peers downgrade to 2.0 with 2.0 peers, so the network keeps interoperating |
| **Spec** | [yaw2.1-protocol.md](../yaw2.1-protocol.md) |
| **Supersedes weakness in** | [yaw2.0-protocol.md](../yaw2.0-protocol.md) §11 |

## 1. Summary

In YAW/2.0 the WebSocket signaling payloads (SDP offers/answers and ICE
candidates) are sealed with **static** X25519 keys derived from each peer's
long-term Ed25519 identity. Because the keys never change, recorded signaling can
be decrypted *retroactively* if either peer's long-term key is later compromised.

This proposal makes the signaling **forward-secret**: each session uses fresh
**ephemeral** X25519 keys that are wiped afterward, so a future key compromise
cannot decrypt past signaling. The change is small (one extra signed round-trip)
and backward-compatible (2.1 peers fall back to 2.0 sealing with 2.0 peers).

## 2. Motivation & threat model

**What YAW exists to protect:** YAW is a darknet. Its core promise is hiding *who
talks to whom, and from where.* Chat and file **content** is already well
protected — it rides WebRTC DTLS, which negotiates fresh ephemeral keys per
session (perfect forward secrecy). That part is fine.

**Where the long-term risk is:** the **signaling** carries the single most
deanonymizing data in the whole system — the ICE candidates, which contain each
peer's **LAN IP (host candidate)** and **public IP (server-reflexive candidate)**,
plus the SDP. In 2.0 those blobs are sealed under static, identity-derived keys.

**The attack (harvest-now, decrypt-later):**

1. A passive adversary records the (encrypted) signaling traffic to/from the
   server over weeks or months. This is cheap and undetectable — the server, an
   ISP, or anyone on-path can do it.
2. Later, the adversary obtains **one** endpoint's long-term Ed25519 private key —
   by device seizure, theft, malware, coercion, or simply compelling the operator.
3. From that one key they derive its static X25519 key and **decrypt the entire
   recorded history** of that node's signaling: every peer id it connected to, and
   the **IP addresses both ends used, with timestamps.**

For a darknet this is a catastrophic, *retroactive* deanonymization — it reverses
the system's central guarantee, after the fact, from a single key compromise. And
because content is already PFS, the *signaling metadata is the most valuable thing
left to attack*. A well-resourced adversary plausibly already operates this way.

**Why fix it now:** the cost is tiny and the property is foundational. Doing it
before a wider rollout means we never accumulate a corpus of recorded,
retroactively-decryptable signaling.

## 3. Non-goals

- **Hiding the contact graph or timing from the signaling server.** The server
  still routes by `from`/`to` id and sees presence; that is inherent to a
  relay-based rendezvous and is out of scope here (a future YIP could explore
  mixing / cover traffic).
- **Changing the transport crypto.** DTLS already provides PFS for content.
- **Authentication changes.** Identity, trust, and the signed-DTLS-fingerprint
  binding are unchanged. FS adds confidentiality-over-time, not new auth.

## 4. Proposed change (overview)

Per session, each peer generates an **ephemeral X25519 keypair** `(esk, epk)`:

1. On deciding to connect, each peer sends a signed **`ekey`** message carrying its
   `epk` (still sealed under static keys, and signed by its Ed25519 identity so it
   is authenticated and bound to the session).
2. Once a peer holds the other's `epk`, all `offer` / `answer` / `candidate` boxes
   are sealed with **`crypto_box(my_esk, peer_epk)`** — ephemeral-to-ephemeral.
3. When the session ends (or is abandoned), `esk` is **wiped**. The recorded boxes
   are then unrecoverable even with both long-term keys.

A future compromise of the static identity keys can decrypt only the `ekey`
messages — which contain just ephemeral *public* keys, revealing nothing.

Full wire detail, ordering, and fallback are in
[yaw2.1-protocol.md](../yaw2.1-protocol.md).

## 5. Backward compatibility (opportunistic FS)

2.1 is a **superset**; it degrades gracefully to 2.0:

- A 2.1 peer sends its `ekey`, then waits briefly for the other's `ekey`.
- If the other side never sends one (it's a 2.0 client, which ignores the unknown
  `ekey` kind), the 2.1 peer **falls back** to 2.0 static sealing and proceeds.
- Such a session is **flagged non-forward-secret** so a UI can show it, and a
  client MAY adopt a **"require FS"** policy that refuses to downgrade.

So 2.0 and 2.1 clients always interoperate; mixed pairs get 2.0 security, pure-2.1
pairs get forward secrecy.

## 6. Security analysis

- **Gained:** past signaling (SDP, candidate IPs) is unrecoverable after a session
  ends, even if long-term keys later leak. Key seizure exposes at most *future*
  sessions, and only until the next rotation/session.
- **Unchanged:** sender authentication (Ed25519 signs the `ekey`; the identity
  binding via the signed DTLS fingerprint is as in 2.0). A malicious server still
  cannot read or forge boxes or MITM the channel.
- **Residual:** the server still learns presence + the contact graph + timing
  (non-goal §3). The `ekey` is static-sealed, so a future static-key compromise
  reveals the ephemeral *public* keys — harmless (the ephemeral *private* keys are
  wiped).
- **Downgrade attack:** an active MITM/server could drop `ekey`s to force the 2.0
  fallback. Mitigation: the downgrade is **detectable** (no FS established) and
  surfaced to the user; a "require FS" policy eliminates it for pure-2.1 groups.

## 7. Alternatives considered

- **Ephemeral-static (half FS).** Seal with `crypto_box(my_esk, peer_static_pub)` —
  no extra round-trip, but does **not** protect against compromise of the
  *recipient's* static key. *Rejected:* incomplete forward secrecy.
- **Server-stored prekeys (X3DH-style).** The answerer publishes ephemeral prekeys
  to the server so the offerer can seal the first message with FS, removing the
  round-trip. *Rejected:* adds server state and trust; we keep the server a dumb,
  stateless relay.
- **Adopt the Noise framework for signaling.** Heavier and redundant — `crypto_box`
  with ephemeral keys already gives the property with libsodium-only primitives we
  already ship.

## 8. Cost

- **Latency:** one extra signaling round-trip (`ekey`) before the offer — ~1 RTT
  through the server. Negligible for human-initiated connections.
- **Code:** generate + securely wipe an ephemeral keypair per session; one new
  message kind; pick ephemeral-vs-static key by "do I have the peer's `epk`?".

## 9. Migration plan

1. **Lock 2.0** (done) so the current interop baseline is stable.
2. Implement 2.1 in the reference clients behind a capability; **default
   opportunistic** (FS when both support it, 2.0 fallback otherwise).
3. Once the reference clients and partner implementations all speak 2.1, optionally
   flip a **network-policy** flag to *require* FS (refuse downgrade) for sensitive
   groups.

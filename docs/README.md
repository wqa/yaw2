# YAW protocol documents

YAW/2 is a small, trusted, peer-to-peer encrypted mesh (chat, presence, files)
using WebRTC DataChannels for transport, ICE/STUN for NAT traversal, and Ed25519
identities. A lightweight server (the **anchor**) does signaling + STUN and never
carries user data.

## Wire versions

| Doc | Version | Status | What it is |
|-----|---------|--------|------------|
| [yaw2.0-protocol.md](yaw2.0-protocol.md) | `yaw/2.0` | 🔒 **LOCKED** | The frozen interop baseline. Implement against this exact wire + the live server. Do not change it. |
| [yaw2.1-protocol.md](yaw2.1-protocol.md) | `yaw/2.1` | 📝 Draft | A **delta** over 2.0 adding forward-secret signaling. Backward-compatible (2.1 peers fall back to 2.0). |

**If you are implementing a client or testing interop: start with 2.0.** It is
locked and matches the deployed server. 2.1 is additive and opportunistic.

## Extensions (optional, capability-gated, no wire break)

| Doc | Applies to | Summary |
|-----|-----------|---------|
| [extensions/file-browse.md](extensions/file-browse.md) | `yaw/2.0`+ | WASTE-style **shared folder**: a peer shares a configured directory; others `browse` it and `get` files on demand. Additive app-layer messages (`browse`/`files`/`get`); 2.0 clients ignore them. |

## Proposals (YIPs — YAW Improvement Proposals)

| Doc | Status | Summary |
|-----|--------|---------|
| [proposals/yip-0001-forward-secret-signaling.md](proposals/yip-0001-forward-secret-signaling.md) | Proposed → `yaw/2.1` | Make signaling forward-secret with per-session ephemeral X25519 keys, so a future long-term-key compromise can't retroactively decrypt recorded signaling (which carries peer IPs). |

## Live reference infrastructure

| Service | Endpoint | Status |
|---------|----------|--------|
| STUN | `stun:fnlr.se:3478` (coturn, STUN-only) | live |
| Signaling | `wss://fnlr.se/4802f621018e1968/signal` | live |

Reference clients: `signaling/` (server), `cli/` (Python/aiortc), `web/`
(browser). See 2.0 §14 for an interop test recipe.

## Connectivity & NAT (by design: STUN-only, no TURN)

YAW is **true peer-to-peer**: media flows directly between peers over WebRTC, and
the anchor only signals + provides STUN. There is **deliberately no TURN relay**, so
the anchor never carries or sees user traffic.

The tradeoff: peers behind **symmetric NAT or CGNAT** (common on some mobile
carriers and corporate networks) may be **unable to connect to each other** — STUN
cannot punch through those. Most home/office networks work; a hotspot or carrier-grade
NAT may not. This is an accepted limitation, not a bug. If a pair won't link, try a
different network for one side. (Adding an encrypted-DTLS TURN relay remains a future
option, but it would mean the server relays ciphertext — a step away from "the anchor
only signals" — so it stays off until measured demand justifies it.)

## Identity & backup

An identity is an Ed25519 keypair; losing it means every friend must re-accept your
new id. Clients keep the key locally (browser `localStorage`, CLI `~/.yaw/identity`),
which is **not a backup** — clearing browser data or losing the device loses it.
Export a **passphrase-encrypted key backup** (`*.yawkey`) and store it safely; the
same file restores your identity in the web client *and* the CLI (one format, verified
byte-identical across libsodium.js and PyNaCl). Full how-to:
[KEYHANDLING.md](../KEYHANDLING.md).

### Contact card (`yaw-contact-1`)

To add each other, friends swap a **contact card** — a single shareable string that
bundles an id with a *suggested* nickname:

```
yaw:<id>?n=<percent-encoded-nick>      e.g.  yaw:7f27…d16b?n=Felix
```

The `id` is self-certifying (it's the Ed25519 public key — nobody can connect as it
without the private key). The nickname is only a **local label** the recipient may
keep or change; it is **not authenticated** and never affects trust. Clients show
nicknames in place of raw ids. Bare ids (no `yaw:`/`?n=`) are still accepted.

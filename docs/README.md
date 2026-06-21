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

# YAW/2

A small, trusted, **peer-to-peer encrypted mesh** — chat, presence, and file
transfer — that pierces NAT the modern way (WebRTC + ICE/STUN) and rides a modern
encrypted transport (DTLS DataChannels). A lightweight server (the **anchor**)
helps peers *find and introduce* each other and **never carries their data**.

YAW/2 is a clean break from the original WASTE protocol — the faithful Blowfish/RSA
implementation has been retired (see [`attic/`](#repository-layout)).

> **Specs are the source of truth:** [`docs/`](docs/README.md) — the protocol is
> **[`yaw/2.0`](docs/yaw2.0-protocol.md) (LOCKED)** with a drafted
> **[`yaw/2.1`](docs/yaw2.1-protocol.md)** for forward-secret signaling.

## Design policy

These are the rules the codebase upholds. Changing any of them is a protocol-level
decision (open a [YIP](docs/proposals/)).

1. **The anchor is *only* a rendezvous.** It does **signaling (WebSocket) + STUN**,
   and relays only **end-to-end-sealed** blobs. It MUST NOT carry mesh data — **no
   relay, no TURN**. It learns presence + the contact graph within a *hashed*
   network, and nothing else: not message content, not files, not peer IPs, not the
   network name.
2. **True peer-to-peer.** Sessions are direct WebRTC DataChannels (DTLS, per-session
   forward secrecy). The accepted trade-off: peers learn each other's IP on a direct
   link, and a minority behind symmetric NAT won't connect (no relay to fall back
   to).
3. **Identity = Ed25519; trust = keyring.** A node is its public key. You talk to a
   peer only if its `id` is in your keyring, exchanged **out of band**
   (friend-to-friend). The anchor cannot vouch for or impersonate anyone.
4. **Secrets stay on the client.** Private keys live in client storage (browser
   `localStorage`, CLI `~/.yaw`). Nothing secret is uploaded; the server is stateless
   beyond presence.
5. **The wire is versioned and disciplined.** **`yaw/2.0` is LOCKED** as the interop
   baseline — independent implementations build against it and the live server.
   Changes go through **YIPs**; breaking changes require agreement and a version bump
   (e.g. `yaw/2.1`), and ship **backward-compatibly** where possible.
6. **One protocol, many clients, one crypto.** Browser, Python CLI, (planned) Tauri —
   all speak the same wire. **libsodium everywhere** (PyNaCl / libsodium.js) so
   signing and sealing are byte-identical across implementations.

## Repository layout

```
docs/         protocol specs + proposals (START HERE — docs/README.md)
                yaw2.0-protocol.md   🔒 LOCKED interop baseline
                yaw2.1-protocol.md   📝 draft: forward-secret signaling
                proposals/yip-0001-*  the motivated change proposal
signaling/    the anchor's WebSocket signaling server (Python, asyncio + PyNaCl)
cli/          YAW/2 Python client — yaw2/ (identity, signaling, aiortc peer)
                + spike_peer.py (interactive) + test_spike_live.py
web/          browser client — index.html, yaw2.js, vendored libsodium
deploy/       server config (nginx, systemd, coturn); secrets are gitignored
attic/        archived YAW/1 (WASTE) — frozen, gitignored, NOT part of v2
```

## Status

**Live infrastructure** (on `fnlr.se`):

| Service | What |
|---------|------|
| STUN | `stun:fnlr.se:3478` (coturn, STUN-only) |
| Signaling | WebSocket relay (secret path), sealed blobs only |
| Web client | hosted behind a secret path + basic auth — open in a browser, no install |

**Proven:** an authenticated, identity-bound DataChannel between the Python CLI and
the browser/another CLI — over the *production* signaling + STUN — exchanging chat
both ways and a hash-verified file (see `cli/test_spike_live.py`). JS ↔ Python
crypto is verified byte-identical.

**Spike caveats (next to harden):** the current clients **trust any id on the
network (TOFU)** — the keyring gate (policy #3) is the first thing to add. True
cross-NAT traversal needs peers on *different* networks to validate. Tauri shell and
`yaw/2.1` are not built yet.

## For users

- **[USERGUIDE.md](USERGUIDE.md)** — non-technical quick start: open the client, pick a
  nickname, swap contact cards, accept, chat, share, back up your key.
- **[KEYHANDLING.md](KEYHANDLING.md)** — how your identity is stored, backed up, and
  moved between the CLI and the web client.

## Quick start

A YAW/2 network is just a shared **name** (hashed for the server). Two peers on the
same name find each other.

**Python CLI peer:**

```sh
cd cli && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python spike_peer.py my-network        # chat to all peers; files land in /tmp
```

**Browser:** open the hosted web client (URL + login are in `deploy/` — gitignored),
or serve it locally for development:

```sh
cd web && python3 -m http.server 8090            # then open http://localhost:8090
```

Pick the same network name on both, and they connect. The CLI peer interoperates
with the browser for a mixed browser↔CLI test.

## Implementing another client / testing interop

Build against **[`docs/yaw2.0-protocol.md`](docs/yaw2.0-protocol.md)** (§5–§9) and
point at the live STUN + signaling. Section §14 lists the endpoints, an interop test
recipe, and the three gotchas that trip up naïve implementations (base64 variant,
identity-bind byte order, the DataChannel open-race).

## Security posture (summary)

- **Content** (chat/files) is end-to-end encrypted with per-session forward secrecy
  (DTLS). The server never sees it.
- **Signaling** is sealed end-to-end; the server can't read SDP, candidate IPs, or
  content — only presence/timing within a hashed network. In `2.0` the sealing keys
  are static (not forward-secret); `2.1` (drafted) fixes this. See
  [`docs/yaw2.0-protocol.md` §11](docs/yaw2.0-protocol.md) and
  [YIP-0001](docs/proposals/yip-0001-forward-secret-signaling.md).
- **Trust** is the keyring; verify a contact's short id out of band before accepting.

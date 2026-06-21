# Changelog

All notable changes to YAW (Yet Another WASTE) are recorded here.

## [Unreleased]

### 2026-06-21 — One key file, everywhere (and a candid word on NAT)
On this day in 1948 the first stored program ran; on this day in 1990 a magnitude-7.4
quake in Iran reminded everyone that the ground you build on matters. So we made
identity portable and wrote down where our ground is soft:

- **Passphrase-encrypted key backup.** Export your identity to a `*.yawkey` file
  (Argon2id + secretbox) and store it safely; the *same file* restores you in the
  web client and the CLI. Verified **byte-identical across libsodium.js and PyNaCl**
  in both directions, so a key minted in the browser unlocks in Python and vice
  versa. New: `cli/yaw2/keybackup.py`, CLI `/export` `/import`, web Back-up/Restore
  buttons. localStorage stays the day-to-day store — the file is the durable backup
  it never was.
- **Documented the STUN-only / no-TURN tradeoff.** True P2P means the anchor never
  relays traffic — and means symmetric-NAT / CGNAT pairs may simply fail to connect.
  Written down plainly in the docs rather than discovered the hard way.
- A progressive roadmap toward real users: durable identity → onboarding → measured
  connectivity → hardening → desktop comfort.

### 2026-06-21 — The keyring decides who gets in
On this day in 1788 New Hampshire became the ninth state to ratify the
Constitution — the vote that finally made it binding, proof that a network springs
to life only once enough parties agree to trust the same rules. And on this day in
1948 the Manchester "Baby" ran the first stored program ever executed, fifty-odd
minutes of arithmetic that opened the software age. We add rules of trust, and a
folder to share:

- **Keyring trust gate (YAW/2).** A session now forms only between peers who have
  each accepted the other's id — friend-to-friend, both directions. Untrusted ids
  are refused (with a one-time nudge so you can `/accept` them). Persistent identity
  + keyring on disk (CLI: `~/.yaw/identity`, `~/.yaw/keyring`) and in localStorage
  (web). The smaller id offers and re-offers only a *dead* link, so accepting a key
  brings the connection up without tearing down healthy ones.
- **WASTE-style folder sharing (YAW/2).** Share a configured directory; friends
  `browse` it and `get` files on demand, path-traversal-safe and read-only.
  Additive, capability-gated (`caps:["share"]`) — no change to the locked 2.0 wire.
- Live-tested end to end over the production signaling + STUN: no trust → no link;
  mutual accept → identity-verified session both ways; browse + SHA-256-verified
  pull; a `../escape` attempt politely refused.
- New on the server: a `yawpeers` CLI showing who is connected (id, real IP via the
  proxy's `X-Real-IP`, connect time, uptime).

### 2026-06-20 — Project genesis
On this day in 1837, a teenaged Victoria was woken before dawn to learn she was
queen of a realm she'd hold for 63 years; on this day in 1819 the *SS Savannah*
limped into Liverpool as the first steamship to cross the Atlantic, proving a
network can stay alive even when the wind dies. In that spirit we lay the keel of
a mesh that keeps talking while its nodes wander.

- Scaffolding: project layout, `requirements.txt`, `Makefile`, `.venv` bootstrap.
- Crypto primitives: RSA identity (+ sign/verify), accepted-key keyring, and a
  hand-rolled Blowfish-PCBC session cipher — the three things every link needs
  before it can whisper a single byte in the clear-of-eavesdroppers sense.
- The link handshake: challenge → key-hash identify → RSA session-key exchange →
  derive PCBC → signature confirm, network-name scoped, deadlock-free and
  symmetric. (On this day in 1840 Samuel Morse patented a way to make distant
  machines agree on a code; ours just needs four phases and a pair of primes.)
- Framing with per-message MD5 integrity, message types (chat/PM/presence/
  host-info/search), and a TTL+GUID flood router so messages reach everyone once.
- `WasteNode`: listens, dials, gossips endpoints, and keeps the mesh chatting.
- The Flask **anchor**: a signed, network-scoped rendezvous directory on :5055
  that keeps members reachable as they wander — verified by an end-to-end test
  where a node hops ports and its peer re-finds it and resumes chatting.
- Interactive line client (`client.cli`) and a 12-case test suite, all green.

### 2026-06-21 — Native macOS app: networking, live interop, signed `.app`
Fitting work for the solstice — the longest day earned the longest build. YawCore
grew the rest of the stack in Swift: a `Keyring`, an async **handshake + node over
Network.framework**, and a URLSession **anchor client** — and a **Swift node now
handshakes and chats with a real Python node** over a socket (an XCTest spawns the
Python peer and checks chat flows both ways). On top sits a chat-first **SwiftUI**
window (identity, peers, dial/anchor, hex key exchange, chat), bundled into a
`YAW.app` and **code-signed with the Developer ID** (hardened runtime, secure
timestamp, full Apple chain) via `macos-client/scripts/bundle.sh`. It launches,
mints its identity, and starts the node. Six Swift tests green. Still to come:
notarization (awaiting a `notarytool` credential) and UI parity (files, search,
privacy/settings). Electron-mac remains the published download until then.

### 2026-06-21 — Fix: CLI `/accept` takes hex keys (cross-client key exchange)
A key shared from the desktop client's "Show my key" is hex text, but the CLI's
`/accept` only read raw blob bytes — and the generic error handler mislabelled the
failure as "bad arguments". Now `/accept` takes a **file or pasted hex, raw or
hex-encoded**, with a clear message on a genuinely bad key. The CLI also exports
its own public key as hex and shows it under `/id`, so keys flow freely between the
CLI and desktop clients. Republished the CLI source bundle.

### 2026-06-21 — Python CLI bundle + native macOS core (Swift) begins
On this day in 1948 the Manchester "Baby" ran the world's first stored program —
fitting, since today brought two new ways to run YAW. The **Python REPL client**
became a downloadable source bundle: production directory + network baked in, a
`from __future__ import annotations` sweep so the source runs on Python 3.8+, and
a one-command `./yaw` launcher that builds its own venv. It's live behind the
secret download link as a third option, verified from a clean extraction. And the
**native macOS client** broke ground: a Swift `YawCore` package whose crypto and
codecs are **byte-identical to the Python core** — Blowfish (via CommonCrypto,
matching the Eric-Young vectors), PCBC, key derivation, framing, every message
encoder, the flood envelope, netname obfuscation, and — across languages — the RSA
`YAWK1` blob, fingerprint, and PKCS1v15-SHA256 signatures (Swift imports a Python
key and verifies a Python signature). `swift test` green. The async handshake,
networking, and SwiftUI window come next; Electron-mac stays the macOS download
until the native app is approved.

### 2026-06-20 — Client trust: transparency, settings, key-at-rest passphrase
On this day in 1975 *Jaws* taught a generation to wonder what's moving under the
surface — a healthy instinct for anyone running a privacy tool. So the client now
shows its hand. The mystery input boxes got **labels**. A **Privacy & connections**
panel spells out exactly what the directory sees (*your fingerprint + IP*) and
never sees (*messages, contacts, your key*), lists the only hosts the app talks
to, shows what's stored on disk, and states plainly: no telemetry. A **Settings**
panel exposes nick / network / port / directory / auto-anchor / auto-accept
(clearly flagged unsafe). And the private key can now be **passphrase-encrypted at
rest** (AES-256), with an unlock screen on launch — wrong passphrase rejected,
right one boots the node. Eight headless JS suites green, including a new
`lock_flow` that drives the whole lock→unlock path. Rebuilt and re-published the
macOS + Windows bundles behind the secret link so the live download carries it all.

### 2026-06-20 — Distribution: live anchor at fnlr.se + downloadable client
On this day in 1840 Samuel Morse was granted the telegraph patent — a network is
only as useful as the people who can quietly find their way onto it. The anchor
now runs in production at **https://fnlr.se** (gunicorn + systemd, behind nginx
with the existing Let's Encrypt cert), wearing a plain cover page that says
nothing of meshes; the directory API hides under an unguessable path prefix and
the client downloads from a second secret path. Made the anchor **Python 3.8**-
friendly (`from __future__ import annotations`) since that's what the box runs,
and added `ProxyFix` so a node's real IP — not nginx's — gets recorded. Built
signed-free, double-click **macOS (Apple Silicon)** and **Windows** bundles of the
Electron client (no native deps, so a clean cross-build), zipped with start notes,
and served them behind the secret link. Verified end-to-end over real TLS: a
client signs a nonce in JS, the server verifies it in Python, and the registration
lands with the caller's true public address. Ops runbook + one-shot `redeploy.sh`
in `deploy/`.

### 2026-06-20 — JS client: file transfer + mesh search
On this day in 1793 Eli Whitney filed for the cotton gin — a machine for pulling
the wanted bits out of a tangled mass at speed, which is roughly what a file
search does. The Electron client gained **file browse/transfer** (chunked,
SHA-256-verified, path-traversal-hardened, with backpressure so a big file won't
balloon memory) and **mesh search with results**: `/search` floods, peers with
matching files answer with a new `SEARCHHIT` frame, and hits show up with one-click
Get buttons. The `SEARCHHIT` reply path was added to the **Python** node as well,
so searches return results across JS and Python clients alike. Verified by two new
interop suites (`file_interop`, `search_interop`) plus JS↔JS coverage — JS suites
now seven, Python still 14, all green.

### 2026-06-20 — JavaScript/Electron client port
On this day in 1782 Congress adopted the Great Seal, binding thirteen prickly
independent states into one design that still had to agree byte-for-byte on every
reprint; porting a wire protocol is much the same. Added `electron-client/` — a
desktop client whose **Node main process runs the whole mesh core** (re-ported
from `wasteproto`) and whose Chromium renderer is the chat UI, bridged by an
`contextIsolation` preload. Because the protocol is defined by bytes, not by
language, a JS node and a Python node now handshake and chat on the **same mesh**,
and the JS client registers with the **same Python anchor**. Every parity-
sensitive primitive is asserted byte-identical to the Python core; Node's OpenSSL
3 having dropped Blowfish, we generate our own from the digits of pi and check it
against the canonical vectors. Five headless suites, all green (the GUI itself
needs a desktop to show its face). File transfer remains Python-only for now.

### 2026-06-20 — File transfer (M4)
On this day in 1948 the variety show *Toast of the Town* first aired, built
entirely on the then-novel idea of piping content to strangers who'd tuned in;
ours is more discerning about who it serves. Added WASTE-style **1:1 file
browse and transfer**: a peer lists a share, requests a name, and receives it in
32 KiB chunks closed by a SHA-256 the receiver checks before the `.part` file is
promoted. The share is a hardened choke point — peer-supplied names are refused
unless they're a plain file sitting directly in the shared folder (no separators,
no `..`, no symlink escapes). Suite now 14 cases, including an end-to-end
transfer and a turned-away path-traversal attempt.

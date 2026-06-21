# YAW — Yet Another WASTE

A clean-room Python implementation of the [WASTE](https://en.wikipedia.org/wiki/WASTE)
darknet mesh: a small (10–50 node) trusted group that exchanges **encrypted chat,
private messages, presence, and searches** with no central server. Plus an
always-on **anchor** that keeps the mesh reachable while members change IP.

## What's here

```
wasteproto/   the protocol library (one self-testable class per file)
  rsa_identity   RSA keypair + public-key fingerprints (the web of trust)
  keyring        the set of peer keys you've accepted
  blowfish_pcbc  the WASTE session cipher (Blowfish in PCBC, hand-rolled)
  handshake      the link negotiation: challenge → identify → session key → confirm
  framing        per-message framing with MD5 integrity
  messages       chat / PM / presence / host-info / search payloads
  router         broadcast flood with TTL + GUID de-duplication
  filetransfer   1:1 file browse + chunked, hash-verified transfer
  peer           one link: socket + session + receive loop
  node           a mesh member: listen, dial, flood, stay alive
client/        the interactive line client (client.cli) + anchor helper
anchor/        the Flask rendezvous directory (app + SQLite store)
tests/         module self-tests + an end-to-end mobility test
electron-client/  a desktop (Electron) client — same wire protocol, see its README
```

A JavaScript/Electron desktop client lives in [electron-client/](electron-client/).
It re-implements the mesh core in Node and is **wire-compatible** — a JS node and a
Python node chat on the same mesh, sharing the same anchor.

## Trust model

Every node has an RSA identity; you're known by the **fingerprint** (SHA-1 of your
public key). A link forms only if each side has *accepted the other's public key*.
Swap key files out-of-band, then `/accept` them. An optional case-sensitive
**network name** further scopes who can connect.

## Quick start

```sh
make run-anchor                 # rendezvous directory on http://127.0.0.1:5055
make run-client                 # interactive client (NODE_PORT defaults to 1337)
```

In the client:

```
/id                             # your fingerprint + exported key file
/accept friend.pub              # trust a peer's exported public key
/connect 10.0.0.42 1337         # dial a peer directly …
/anchor http://host:5055        # … or register and auto-find peers as they move
hello everyone                  # bare text → current room (#general)
/pm 1a2b3c hi there             # private message by fingerprint prefix
/shared                         # list files you share (drop them in yawdata/share)
/browse 1a2b3c                  # see a peer's shared files
/get 1a2b3c report.pdf          # download one (saved to yawdata/downloads)
```

Run any module's self-test directly against the venv:

```sh
.venv/bin/python -m wasteproto.handshake
make test                       # the whole suite
```

## Crypto note

The faithful path uses **RSA + Blowfish-PCBC** for wire-fidelity with the original
WASTE client. PCBC has known weaknesses, so two YAW nodes additionally advertise a
capability flag and can negotiate a modern session on top — while a stock WASTE
peer falls back to the faithful mode. Byte-exact interop with the original client
is validated separately against the reference source (see the project plan, M6).

## Deploy

We develop on macOS and deploy on Linux. `make deploy REMOTE=user@host` rsyncs the
code (never with `--delete`), rebuilds the **remote** `.venv`, and restarts the
service. Private keys, the venv, and the local database are excluded.

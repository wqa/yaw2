# YAW/2 — deployment (`<anchor-host>`)

The anchor is a **signaling + STUN** rendezvous only — it never carries mesh data
(chat/files are peer-to-peer over WebRTC). It runs on **`<server-host>`** (Ubuntu,
Python 3.8) as the `fnlr` user, behind nginx with the existing Let's Encrypt cert that
covers `<anchor-host>`. The public site shows only an innocuous cover page; everything
else lives under unguessable paths behind basic auth.

> Secrets (host, secret path segments, basic-auth) are **not in this repo** — see the
> placeholders below and **[ROTATING_KEYS.md](../ROTATING_KEYS.md)** for where the real
> values live and how to rotate them.

## Services

| Service | What | Where |
|---------|------|-------|
| `yaw-signaling` (systemd) | async WebSocket signaling (`websockets` + PyNaCl); challenge/join, presence, opaque sealed relay; per-IP/-conn **rate-limited**; writes `status.json` | `/home/fnlr/yaw-signaling/`, `127.0.0.1:8077` |
| `coturn` | **STUN-only** (relay disabled — not an open relay), UDP+TCP 3478 | `/etc/turnserver.conf` |
| `nginx` | TLS; serves the cover page + web client (static), WSS-proxies the signaling path | vhost below |
| ~~`yaw-anchor`~~ | **RETIRED** — the old YAW/1 Flask directory (gunicorn `:8055`); `systemctl disable --now`d | — |

The signaling server has **no long-term key** (it verifies each node's Ed25519
signature over a per-connection nonce), so there's nothing server-side to rotate.

## nginx locations (real vhost is gitignored)

The live vhost is `deploy/anchor.nginx` (gitignored); a sanitized template is
[`anchor.nginx.example`](anchor.nginx.example). Locations:

- `/` → static cover page (`/home/fnlr/cover/`)
- `/<app-path>/` → web client (`alias /home/fnlr/yaw-web/`), **basic auth**
  (`/etc/nginx/.htpasswd-yaw`)
- `/<signal-path>/signal` → WSS proxy to `127.0.0.1:8077` (`X-Real-IP` set, so the
  server logs the true peer IP)
- `/<download-path>/` → static download area (`alias .../dist/`, `download.html`)

Client endpoints come from config, never the repo: web `web/config.js` (gitignored,
template `web/config.example.js`), CLI `~/.yaw/config` (see `cli/yaw2/config.py`).

## Operations

```sh
# status / logs / restart  (magnus has passwordless sudo)
ssh magnus@<server-host> 'systemctl is-active yaw-signaling coturn nginx'
ssh magnus@<server-host> 'sudo journalctl -u yaw-signaling -n 50 --no-pager'
ssh magnus@<server-host> 'sudo systemctl restart yaw-signaling'

# who is connected right now (id, real IP, connect time, uptime)
ssh magnus@<server-host> 'yawpeers'           # -l for full ids

# deploy: rsync the relevant tree (NEVER --delete), then restart if code changed
rsync -az signaling/  fnlr@<server-host>:/home/fnlr/yaw-signaling/
rsync -az web/        fnlr@<server-host>:/home/fnlr/yaw-web/
```

- **TLS:** Let's Encrypt via Certbot (auto-renews).
- **Rotating the secret paths / basic-auth / network name:** [ROTATING_KEYS.md](../ROTATING_KEYS.md).
- **Clients to hand out:** the web client (no install) + `desktop/` (Tauri) + `cli/`.
  The download page is `download.html` (served at the secret download path).

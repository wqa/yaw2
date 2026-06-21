# Rotating keys & secrets

How to change every secret YAW relies on, and where each one lives. None of the real
values appear in this repo — they live on the server and in gitignored local config
(`web/config.js`, `~/.yaw/config`, the real nginx vhost). Templates: `web/config.example.js`,
`deploy/anchor.nginx.example`.

## Secret inventory

| Secret | Lives on the server | Lives in client/config | In the repo? |
|---|---|---|---|
| **Signaling path** (`/<signal-path>/signal`) | nginx vhost `location` | web `config.js` `signalURL`, CLI `~/.yaw/config` `signal_url` | no (placeholder) |
| **Web-app path** (`/<app-path>/`) | nginx vhost `location` | the URL you hand out | no (placeholder) |
| **Download path** (`/<download-path>/`) | nginx vhost `location` | the URL you hand out | no (placeholder) |
| **Basic-auth users** | `/etc/nginx/.htpasswd-yaw` | given out of band | no |
| **Anchor / STUN host** | the box itself | `config.js` `stunURL`, `~/.yaw/config` `stun_url` | no (placeholder) |
| **Network name** (the room) | — (hashed before it reaches the server) | `config.js` `defaultNet`, `~/.yaw/config` `default_net` | no |
| **Per-user identity** (Ed25519) | — | browser `localStorage`, CLI `~/.yaw/identity` (+ `*.yawkey` backup) | no |
| **TLS certificate** | `/etc/letsencrypt/...` (Certbot) | — | no |

> The **signaling server has no long-term key** of its own — it only issues challenge
> nonces and verifies each node's signature with that node's public id. So there is no
> server keypair to rotate.

## Rotate when

- You suspect a secret leaked (see **git-history caveat** below — the host and old
  paths are in this repo's *past* commits; treat them as known if it was ever public).
- A member leaves the group (rotate basic-auth, consider a new network name).
- Periodically, as hygiene.

## How to rotate each

### Secret URL paths (signaling / web-app / download)

1. Mint new unguessable segments: `openssl rand -hex 8`.
2. Edit the `location` blocks in the real nginx vhost on the server, then:
   `sudo nginx -t && sudo systemctl reload nginx`.
3. Update **`web/config.js`** on the server (`signalURL`) and rsync it; update any CLI
   users' **`~/.yaw/config`** (`signal_url`). Re-share the new web-app / download URLs.
4. The old paths now 404. Done.

### Basic-auth users (the web-client gate)

- Add/change: `sudo htpasswd /etc/nginx/.htpasswd-yaw <user>` (no reload needed —
  `auth_basic` reads the file per request).
- Revoke: delete that user's line. Share new credentials out of band.

### Network name (the room)

- Agree a new name; update `defaultNet` (web `config.js`) and `default_net`
  (`~/.yaw/config`). It's SHA-256-hashed before it reaches the server, so changing it
  re-partitions the group — **everyone must switch together**.

### Your identity key (Ed25519) — heaviest, avoid unless compromised

- Mint a new identity (clear the browser key / remove `~/.yaw/identity`, or import a
  fresh key), then share your **new contact card** so friends `/accept` it again. Your
  old id is dead once you stop using it.
- **Back up the new key immediately** (see [KEYHANDLING.md](KEYHANDLING.md)).

### STUN / anchor host

- Just `host:port`, no secret inside. If you move infrastructure, update `stunURL`
  (web) and `stun_url` (CLI). Rotate the host only if the box itself is compromised.

### TLS certificate

- Auto-renewed by Certbot. Nothing to do unless you change hostnames.

## ⚠️ The git-history caveat

Scrubbing the working tree does **not** remove secrets from **past commits**. The
deployment host and the earlier secret paths were committed before this scrub, so if
the repo is (or ever was) public, treat those specific values as **known**:

- The real fix is to **rotate the paths** (above) — old values become dead ends.
- To also purge them from history, rewrite it (`git filter-repo` / BFG), force-push,
  and have every clone re-clone. This is destructive — coordinate before doing it.
- Basic-auth credentials and private keys were **never** committed, so those are safe
  as long as you didn't paste them somewhere tracked.

## Post-rotation checklist

- [ ] `sudo nginx -t` clean, nginx reloaded
- [ ] server `web/config.js` updated, verified: `curl -u <user>:<pass> https://<host>/<app-path>/config.js`
- [ ] CLI users' `~/.yaw/config` updated
- [ ] old path returns 404
- [ ] (if creds rotated) new `.htpasswd-yaw`, old login rejected
- [ ] (if identity rotated) new contact card shared, friends re-accepted, key backed up

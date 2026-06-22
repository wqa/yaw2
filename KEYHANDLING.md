# Key handling

How your YAW identity is stored, backed up, and moved between the CLI and the web
client. **Short answer to "can I restore my CLI key in the web client?": yes** — see
[Move your identity: CLI → web](#move-your-identity-cli--web).

## What your key actually is

Your identity is an **Ed25519 keypair**:

- The **public key** is your **id** (64 hex chars). It is also what you hand out, as a
  *contact card* (`yaw:<id>?n=<nickname>`). Sharing it is safe — it is public.
- The **private key** (a 32-byte *seed*) is the secret. Whoever holds it **is you** on
  the network. Never share it. It never leaves your device except as an encrypted
  backup file that *you* choose to move.

Trust is mutual: a friend accepting your card only lets *them* reach *you*; a session
forms only once you have each accepted the other's id.

## Where it lives

| | CLI peer | Web client (browser) | Desktop app (Tauri) |
|---|---|---|---|
| Identity (secret seed) | `~/.yaw/identity` — file, mode `0600`, **plaintext** | `localStorage` `yaw2_seed`, **plaintext** | **OS keychain** (service `yaw`, account `seed`) |
| Your nickname | `~/.yaw/nick` | `localStorage` `yaw2_nick` | `localStorage` `yaw2_nick` |
| Keyring (trusted ids + nicknames) | `~/.yaw/keyring` | `localStorage` `yaw2_keyring` | `localStorage` `yaw2_keyring` |

**Each store is separate** — a fresh client mints its *own* new identity unless you
restore one. There is no auto-import between them; the `*.yawkey` backup is the bridge.

Warnings:

- **`localStorage` is not a backup.** Clearing site data, a private window, browser
  eviction, or losing the device erases it — with no copy anywhere.
- The CLI `~/.yaw/identity` is on disk but **unencrypted** (only protected by file
  permissions). Anyone who can read that file has your key.
- The **desktop app's keychain** entry is the most durable store (survives clearing
  the app's data), but it's still tied to that one machine — back it up too.

So: **export an encrypted backup and keep it safe.** That is the durable copy.

## The backup file (`*.yawkey`, format `yaw-key-backup-1`)

A small JSON file containing only your **seed**, encrypted with a passphrase
(Argon2id key derivation + XSalsa20-Poly1305 secretbox). It is:

- **Passphrase-protected** — useless to anyone without your passphrase.
- **Portable** — the *same file* restores your identity in the CLI, the web client,
  and any future YAW client. The two implementations were verified to produce and
  read byte-identical files.

It contains your identity **only**. It does **not** contain your keyring (your trusted
contacts / nicknames) — see [What moves and what doesn't](#what-moves-and-what-doesnt).

## Back up your key

**From the CLI** — either start the peer and run `/export ~/Desktop/magnus.yawkey`,
or, without connecting, one command:

```sh
cli/.venv/bin/python cli/export_key.py ~/Desktop/magnus.yawkey
```

It prints your id, asks for a passphrase twice, and writes the `0600` file. Choose a
strong passphrase — it is the only thing protecting the key inside.

**From the web / desktop client** — click **Back up key**, enter a passphrase, and a
`yaw-identity-<id8>.yawkey` file downloads. Store it somewhere safe (password
manager, encrypted drive).

## Move your identity: CLI → web

This makes the browser use your existing CLI identity, so friends who already
accepted your card reach you in the web client too.

1. **CLI:** `/export ~/Desktop/magnus.yawkey` (set a passphrase).
2. Get that file onto the machine with the browser (copy it across however you like —
   it is encrypted, but still treat it as sensitive).
3. **Web:** open the client. *Before clicking Connect*, click **Restore key**, choose
   the `.yawkey` file, and enter the **same passphrase**.
4. The web client now shows the same id as your CLI. Click **Connect**.
   (If you were already connected under a different identity, reload the page first.)

> **Desktop app:** identical — **Restore key** in the Tauri app writes the seed into
> the **OS keychain**, then reload the window. (The desktop app mints its own fresh
> identity on first run, so restore is how you make it *you*.)

## Move your identity: web → CLI

1. **Web:** **Back up key** → save the `.yawkey` file.
2. **CLI:** `/import ~/Downloads/yaw-identity-XXXX.yawkey`, enter the passphrase, then
   **restart** the peer. It now runs as that identity.

## What moves and what doesn't

| Thing | Moves with the `.yawkey`? |
|---|---|
| Your identity (id + ability to be you) | **Yes** |
| Your **keyring** (who you trust + their nicknames) | **No** — separate per client |
| Your own nickname | **No** — set it again (`/nick`, or the web *You* panel) |

After restoring on a new client you **are** the same person (friends recognize your
id), but you start with an empty keyring there — re-accept your friends' cards. Since
they already trust your id, each connection comes up as soon as you accept them back.

## Security notes (be careful)

- **The card is public; the seed is secret.** Share `yaw:<id>?n=...` freely. Never
  share `~/.yaw/identity`, `localStorage.yaw2_seed`, or an *un*-encrypted seed.
- **Passphrase = the lock on your backup.** A weak passphrase means a weak backup.
  There is no recovery if you forget it — the seed inside is unrecoverable.
- **No backup + wiped storage = lost identity.** You can make a new key, but every
  friend must accept your new card. Back up *before* you need it.
- **Nicknames are not identity.** A nickname (yours or on a contact card) is an
  unauthenticated label. Trust is the **id** and the signed handshake, never the name.
- **Same identity in two places at once** (CLI and web on the same network) is allowed
  but can be confusing — the newer connection replaces the older one per peer.

## Reference

- Backup format + parity test: `cli/yaw2/keybackup.py` (CLI) and `exportSeed`/
  `importSeed` in `web/yaw2.js`.
- Contact card format `yaw-contact-1`: see `docs/README.md` and `cli/yaw2/keyring.py`.

# YAW — quick start

YAW is a small, private, encrypted network for chatting and sharing files with people
you trust. It's **peer-to-peer**: your messages and files go *directly* between you and
your friend. The server only helps you find each other — it never sees your messages,
your files, or who's talking to whom.

You don't install anything: it runs in your web browser.

---

## 1. Open the client

Use the **link** and the **username / password** your host gave you. It opens in any
modern browser (Chrome, Edge, Firefox, Safari).

## 2. Pick a nickname

In the **You** box, type a name and click **Set nickname**. This is just the label your
friends will see.

## 3. Copy your contact card

Click your **card** — the line that looks like `yaw:....?n=yourname` — to copy it. Send
it to your friends however you like (chat, email, etc.).

> A contact card is **safe to share**. It's your public address, not a password.

## 4. Add your friends

- Ask each friend for *their* card.
- Paste it into the **Accept** box (you can give them a nickname), then click **Accept**.
- Trust is **mutual**: your friend must accept your card too. You'll connect only once
  you've **both** accepted each other.

## 5. Join the room

- Type the **network name** your group agreed on into the *network name* box. (Everyone
  must use the exact same name — it's what keeps your group separate and private.)
- Click **Connect**.
- Friends who are online and have accepted you appear under **Peers**.

## 6. Talk and share

- **Chat:** type in the box at the bottom.
- **Send a file now:** choose file(s), then **Send now to all**.
- **Share a folder to browse:** choose files, then **Add to my share**. Friends click
  **browse** next to your name, then **get** to download what they want.

## 7. Back up your key — do this once, now

Click **Back up key**, choose a passphrase, and save the file somewhere safe (a password
manager or encrypted drive).

> **Why it matters:** your identity lives only in this browser. If you clear your
> browser data or lose the device, it's gone — and every friend would have to add you
> again as a new person. The backup file restores you anywhere (another computer, or the
> command-line client). Keep the passphrase safe too; there's no recovery without it.
> Details: [KEYHANDLING.md](KEYHANDLING.md).

---

## If someone won't connect

- Check that you've **both accepted each other's card**, and you're **both online**
  (Connected, same network name).
- Click **Test my connectivity**. If it says STUN works and shows your public address,
  your network is fine. If it finds no reflexive address, this network is blocking
  direct connections.
- Some networks — especially **mobile/carrier** connections — block direct peer
  connections. Try a normal Wi-Fi network for one side. (By design, the server never
  relays your traffic, so it can't paper over this.)

## What stays private

The server only introduces peers. Your messages and files travel **directly and
encrypted** between you and your friend. Nicknames are just labels you choose locally —
the thing that actually proves identity is the card's address and the encrypted
handshake, never the name.

---

**Other clients** — same network, same contact cards and key backups: a **command-line
client** (`cli/`) for the terminal, and a **desktop app** (a native window that keeps
your key in the OS keychain) — ask your host for a build. You can move your identity
between any of them with a key backup (see KEYHANDLING.md).

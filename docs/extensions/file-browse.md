# Extension: shared-folder browse (WASTE-style)

**Status:** stable extension · **Wire impact:** none (additive app-layer messages
over the existing `yaw` DataChannel) · **Applies to:** `yaw/2.0`+

A peer MAY **share a configured directory**; other peers can **list** it and
**pull** files from it on demand — the persistent "browse my folder" model from
WASTE, as opposed to the active "send this file now" of [§9](../yaw2.0-protocol.md).

This is **not** a protocol version change. It adds three application messages on the
`yaw` control channel; a peer that doesn't implement them ignores them (2.0 §8:
"unknown types ignored"). Capability is advertised in `hello`:

```
hello: { …, "caps": ["share"] }     // "I host a browsable folder"
```

## Messages (over the `yaw` control channel, JSON)

| type | fields | direction | meaning |
|------|--------|-----------|---------|
| `browse` | *(optional `path`)* | requester → sharer | "list your shared folder" |
| `files` | `entries:[{name,size}]` | sharer → requester | the listing (a flat list of files) |
| `get` | `name` | requester → sharer | "send me this file" |
| `no-file` | `name` | sharer → requester | requested name is unknown/refused |

- `browse` requests a listing. `path` is reserved for future subfolders; v1 shares a
  **flat** directory (files only, no recursion) and ignores `path`.
- `files.entries` is `[{ "name": "report.pdf", "size": 12345 }, …]`. `sha256` MAY be
  included per entry but is optional (it's verified on transfer anyway).
- `get` asks for one file **by name**. The sharer responds by starting a normal
  [§9](../yaw2.0-protocol.md) transfer of that file (`file-offer` → dedicated
  `f:<xid>` channel → `file-done`). No new transfer mechanism — `get` just triggers
  the existing one. If the name is unknown or refused, the sharer sends `no-file`.

## Security (mandatory)

The sharer MUST treat `get.name` as **untrusted**. It serves a file only if `name`
is a **single safe path component inside the configured share directory**:

- reject any `name` containing a path separator (`/`, `\`) or `..`,
- reject names starting with `.` (no dotfiles),
- the resolved real path MUST live **directly inside** the share dir (defeat symlink
  escapes — resolve and check the parent), and it MUST be a regular file.

Otherwise → `no-file`. (This is the same path-traversal defence the WASTE client
used.) The share is **read-only** and never serves anything outside the configured
directory.

## Notes

- Browsing/pulling is **peer-to-peer** over the DTLS DataChannel — the anchor is not
  involved, exactly as for chat and `send`.
- A **CLI / Tauri** peer is the natural host (a persistent on-disk folder). A pure
  **browser** tab can browse + pull freely, and can *host* a folder only via
  `showDirectoryPicker()` (Chromium) or by sharing session-picked files — it cannot
  serve an arbitrary disk path without a grant.
- Listing a huge directory: keep `files` under the 64 KiB control-message cap; if a
  folder is very large, paginate via `path`/future fields. v1 assumes modest folders.

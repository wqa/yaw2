# Extension: shared-folder browse (WASTE-style)

**Status:** stable extension · **Wire impact:** none (additive app-layer messages
over the existing `yaw` DataChannel) · **Applies to:** `yaw/2.0`+

A peer MAY **share a directory tree**; other peers can **navigate** it like a
filesystem — listing folders, descending into subfolders, and **pulling** files on
demand — the persistent "browse my folder" model from WASTE, as opposed to the
active "send this file now" of [§9](../yaw2.0-protocol.md).

This is **not** a protocol version change. It adds four application messages on the
`yaw` control channel; a peer that doesn't implement them ignores them (2.0 §8:
"unknown types ignored"). Capability is advertised in `hello`:

```
hello: { …, "caps": ["share"] }     // "I host a browsable folder tree"
```

## Messages (over the `yaw` control channel, JSON)

| type | fields | direction | meaning |
|------|--------|-----------|---------|
| `browse` | `path` (string, default `""`) | requester → sharer | "list this folder" |
| `files` | `path`, `entries:[…]` | sharer → requester | the listing at `path` |
| `get` | `name` (relative path) | requester → sharer | "send me this file" |
| `no-file` | `name` | sharer → requester | path is unknown/refused |

- **`browse`** requests the listing of one directory level. `path` is a relative
  path within the share using `/` separators (`""` = the share root,
  `"photos/trip"` = a subfolder). To walk a tree, the requester sends successive
  `browse` messages with deeper `path`s.
- **`files`** echoes the `path` it describes and carries `entries`, the **immediate
  children** at that level (not recursive):
  ```json
  { "type": "files", "path": "photos",
    "entries": [ { "name": "trip", "dir": true },
                 { "name": "cover.jpg", "size": 48213 } ] }
  ```
  A **folder** entry has `"dir": true` (no `size`); a **file** entry has a `size`
  (no `dir`). Folders are conventionally listed first. `sha256` MAY be included per
  file but is optional (it's verified on transfer anyway). Entries with a name
  starting with `.` and symlinks are omitted.
- **`get`** asks for one file **by its path relative to the share root**
  (e.g. `"photos/trip/view.bin"`). The sharer responds by starting a normal
  [§9](../yaw2.0-protocol.md) transfer (`file-offer` → dedicated `f:<xid>` channel →
  `file-done`). The `file-offer.name` SHOULD be the **basename** only, so the
  receiver saves a clean filename. No new transfer mechanism — `get` just triggers
  the existing one. Unknown/refused path → `no-file`.

## Security (mandatory)

The sharer MUST treat `browse.path` and `get.name` as **untrusted**. A path is
served only if it resolves to a real path **inside** the configured share root:

- reject **absolute** paths (leading `/`),
- split on `/` and reject any component that is empty, `..`, or starts with `.`
  (no parent escapes, no dotfiles),
- join onto the share root, **resolve the real path** (following symlinks), and
  require it to be the share root itself or to start with `shareRoot + separator`
  — this is what actually defeats symlink escapes,
- for `get`, the resolved target MUST be a **regular file** (not a symlink, not a
  directory); for `browse`, a **directory**.

Otherwise → `no-file` (for `get`) or an empty `entries` (for `browse`). The share is
**read-only** and never serves, lists, or follows anything outside the share root.

> This is stricter than v1 (which allowed only a single flat component). The
> reference implementation centralises all of this in one `_resolve(path)` choke
> point; everything else (listing, reading) goes through it.

## Notes

- Browsing/pulling is **peer-to-peer** over the DTLS DataChannel — the anchor is not
  involved, exactly as for chat and `send`.
- A **CLI / Tauri** peer is the natural host: point it at any on-disk directory
  (`--share DIR`) and the whole tree becomes browsable, traversal-safe.
- A pure **browser** tab can browse + pull freely, and can also *host* a tree by
  picking a folder (`<input webkitdirectory>` / `showDirectoryPicker()`); it keys its
  in-memory share by each file's **relative path** (`webkitRelativePath`), so the
  same `browse`/`files`/`get` messages reconstruct the tree for visitors.
- Listing a huge directory: each `files` message is one directory level, so it stays
  well under the 64 KiB control-message cap unless a single folder holds tens of
  thousands of entries; split such folders into subfolders if needed.

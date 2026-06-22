# YAW desktop (Tauri)

A native desktop wrapper around the **web client** (`../web`), so YAW is a real app
window instead of a browser tab — and so the identity can live in the **OS keychain**
instead of browser `localStorage` (survives "clear browsing data", no eviction).

This is **scaffolding** — it is not built here (the build needs Rust, which isn't
installed in this environment). The files are ready; follow the steps below to build.

## What's here

```
desktop/
  README.md                 (this file)
  src-tauri/
    Cargo.toml              Rust deps: tauri 2, keyring 3 (OS keychain)
    tauri.conf.json         app config; frontend = ../../web (the static web client)
    build.rs
    src/main.rs             Tauri entry + key_save / key_load / key_delete commands
    capabilities/default.json
    icons/                  generate with `cargo tauri icon` (see icons/README.md)
```

The frontend is the **existing web client served as-is** — `index.html`, `yaw2.js`,
the vendored libsodium, and `web/config.js` (the gitignored deployment config; it must
be present for the app to know the signaling URL). All YAW logic stays in the shared
web/CLI code; this is just a shell.

## Prerequisites

- **Rust** — `curl https://sh.rustup.rs -sSf | sh`
- **Tauri CLI** — `cargo install tauri-cli --version "^2"` (or `npm i -g @tauri-apps/cli`)
- **Platform webview** — macOS: WKWebView (built-in). Windows: WebView2. Linux:
  `webkit2gtk` + `libsoup`.

## Build / run

```sh
cd desktop/src-tauri
cargo tauri icon ../../path/to/logo.png   # once, to create icons (optional for dev)
cargo tauri dev                           # run a dev window
cargo tauri build                         # produce a signed-able app bundle
```

Because `frontendDist` points straight at `../../web` (static files), there's no JS
build step — the app loads the same client friends use in the browser.

## Next step: store the identity in the OS keychain

`src/main.rs` exposes three commands the frontend can call:

| Command | Effect |
|---|---|
| `key_save(account, secret)` | write `secret` to the OS keychain under service `yaw` |
| `key_load(account)` | read it back (`null` if absent) |
| `key_delete(account)` | remove it |

To use them, the web client should prefer the keychain when running inside Tauri.
Sketch (in `web/yaw2.js`, guarded so the browser is unaffected):

```js
const inTauri = typeof window !== 'undefined' && !!window.__TAURI__;
const invoke  = inTauri ? window.__TAURI__.core.invoke : null;

// load: try keychain, else localStorage
async function loadSeedHex() {
  if (inTauri) { const s = await invoke('key_load', { account: 'seed' }); if (s) return s; }
  return localStorage.getItem('yaw2_seed');
}
// save: keychain in Tauri, localStorage in the browser
async function saveSeedHex(hex) {
  if (inTauri) return invoke('key_save', { account: 'seed', secret: hex });
  localStorage.setItem('yaw2_seed', hex);
}
```

This requires making `Identity.load()` async (keychain access is async) and awaiting it
at startup — a small but real refactor that should be browser-tested. The
passphrase-encrypted `*.yawkey` backup ([../KEYHANDLING.md](../KEYHANDLING.md)) still
works regardless and remains the portable, cross-client copy.

## Notes

- `org.yaw.client` is the bundle identifier (no deployment host in it).
- Tauri v2 generates `src-tauri/gen/` and `target/` on first build — both gitignored.
- The same `web/config.js` rules apply: keep real signaling URLs out of the repo.

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
cargo tauri icon ../app-icon.png   # once — generates icons/ (REQUIRED; the build
                                   # embeds them). Replace app-icon.png with your own.
cargo tauri dev                    # run a dev window
cargo tauri build                  # produce a signed-able app bundle
```

> The repo ships a placeholder `desktop/app-icon.png`; the generated `icons/` set is
> gitignored, so run `cargo tauri icon` once after cloning (or whenever you change the
> logo).

Because `frontendDist` points straight at `../../web` (static files), there's no JS
build step — the app loads the same client friends use in the browser.

## Identity in the OS keychain (wired up)

`src/lib.rs` exposes three commands the frontend calls:

| Command | Effect |
|---|---|
| `key_save(account, secret)` | write `secret` to the OS keychain under service `yaw` |
| `key_load(account)` | read it back (`null` if absent) |
| `key_delete(account)` | remove it |

The web client (`web/yaw2.js`) already uses them: a small seed-store abstraction
(`seedGet`/`seedSet`) reads/writes the identity seed via the keychain when
`window.__TAURI__` is present, and falls back to `localStorage` in a plain browser —
so `Identity.load()`/`importBackup()` are async, and the browser behaviour is
unchanged. `withGlobalTauri: true` (in `tauri.conf.json`) exposes `window.__TAURI__`
to the bundler-less frontend. Inside the desktop app the key therefore survives
"clear browsing data" and webview eviction.

The passphrase-encrypted `*.yawkey` backup ([../KEYHANDLING.md](../KEYHANDLING.md))
still works regardless and remains the portable, cross-client copy. `key_delete` is
available for a future "forget this device" action.

## Notes

- `org.yaw.client` is the bundle identifier (no deployment host in it).
- Tauri v2 generates `src-tauri/gen/` and `target/` on first build — both gitignored.
- The same `web/config.js` rules apply: keep real signaling URLs out of the repo.

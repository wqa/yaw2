# Icons

Tauri bundles need app icons (referenced in `../tauri.conf.json` → `bundle.icon`).
Generate them all from one square PNG (≥512×512):

```sh
cargo tauri icon path/to/logo.png
```

That writes `32x32.png`, `128x128.png`, `icon.icns` (macOS), `icon.ico` (Windows),
etc. into this folder. `cargo tauri dev` runs without them; a bundle build needs them.

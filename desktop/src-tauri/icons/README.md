# Icons

Tauri bundles need app icons (referenced in `../tauri.conf.json` → `bundle.icon`).
Generate them all from one square PNG (≥512×512):

```sh
cargo tauri icon path/to/logo.png
```

That writes `32x32.png`, `128x128.png`, `icon.icns` (macOS), `icon.ico` (Windows),
etc. into this folder. **These are required to compile** — `tauri::generate_context!`
embeds them — so run the command once before `cargo tauri dev`/`build`. A placeholder
source lives at `../../app-icon.png`.

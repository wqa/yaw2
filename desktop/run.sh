#!/usr/bin/env bash
# Launch the YAW desktop app (Tauri). Sources Cargo so it works from any terminal
# — rustup's PATH line isn't reliably picked up by every shell.
#
#   ./run.sh          # dev window   (cargo tauri dev)
#   ./run.sh build    # release bundle (cargo tauri build)
set -e

# Put cargo/rustc on PATH no matter how the shell is configured.
[ -f "$HOME/.cargo/env" ] && . "$HOME/.cargo/env"
command -v cargo >/dev/null 2>&1 || export PATH="$HOME/.cargo/bin:$PATH"
if ! command -v cargo >/dev/null 2>&1; then
  echo "cargo not found — install Rust:  curl https://sh.rustup.rs -sSf | sh" >&2
  exit 1
fi

cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/src-tauri"
exec cargo tauri "${1:-dev}" "${@:2}"

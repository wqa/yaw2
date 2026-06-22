#!/usr/bin/env bash
# Sign + notarize + staple the YAW desktop app and produce a distributable zip.
#
# RUN THIS MANUALLY in your own terminal — not via an automation agent — so
# corporate EDR/anti-virus sees normal developer activity (signing a binary and
# uploading it to Apple's notary service looks suspicious when an unknown agent
# process does it). Each step is deliberate; read before running.
#
#   ./desktop/sign-and-notarize.sh
#
# Prereqs: a "Developer ID Application" cert in your keychain, and a notarytool
# credential stored as a keychain profile (Step 0, once).
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"   # repo root

APP="desktop/src-tauri/target/release/bundle/macos/YAW.app"
OUT="/tmp/yaw-desktop-macos-arm64.zip"
NOTARY_PROFILE="${NOTARY_PROFILE:-yaw-notary}"   # set to your stored profile name

# Auto-detect the Developer ID identity (no personal IDs hardcoded in the repo).
IDENTITY="${SIGN_IDENTITY:-$(security find-identity -v -p codesigning \
  | awk -F'"' '/Developer ID Application/{print $2; exit}')}"

# ── Step 0 (ONCE) — store your notary credential, if you haven't already ──────
# Create an app-specific password at appleid.apple.com (Sign-In & Security →
# App-Specific Passwords), then run ONCE:
#   xcrun notarytool store-credentials "$NOTARY_PROFILE" \
#     --apple-id "you@example.com" --team-id "<YOUR_TEAM_ID>" --password "<app-specific-password>"
# (Your team id is the (XXXXXXXXXX) in the identity below.)

[ -n "$IDENTITY" ] || { echo "No 'Developer ID Application' cert found."; exit 1; }
[ -d "$APP" ] || { echo "Build first: ./desktop/run.sh build"; exit 1; }
echo "Signing identity : $IDENTITY"
echo "Notary profile   : $NOTARY_PROFILE"
echo

echo "[1/6] codesign (Developer ID + hardened runtime)…"
codesign --force --options runtime --timestamp --sign "$IDENTITY" "$APP"
codesign --verify --strict --verbose=2 "$APP"

echo "[2/6] zip for notarization…"
rm -f /tmp/yaw-notarize.zip
ditto -c -k --keepParent "$APP" /tmp/yaw-notarize.zip

echo "[3/6] submit to Apple notary (waits for the result)…"
xcrun notarytool submit /tmp/yaw-notarize.zip --keychain-profile "$NOTARY_PROFILE" --wait

echo "[4/6] staple the ticket onto the app…"
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"

echo "[5/6] gatekeeper check (want: accepted / source=Notarized Developer ID)…"
spctl -a -vvv "$APP" || true

echo "[6/6] produce the distributable zip…"
rm -f "$OUT"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$OUT"
echo
echo "Done → $OUT"
echo "Next: upload it to the secret download area (your host/path), e.g.:"
echo "  rsync -az \"$OUT\" <deploy-user>@<server>:/home/<deploy-user>/yaw-anchor/dist/"
echo "Then it replaces the unsigned zip and friends can just double-click."

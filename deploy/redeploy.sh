#!/usr/bin/env bash
# Redeploy the YAW anchor code to fnlr.se and restart the service.
# Syncs only the anchor app code (not the client bundles — see deploy/README.md).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="$(mktemp -d)"
SYNC_USER="fnlr@emop.se"
SUDO_USER="magnus@emop.se"
DEST="/home/fnlr/yaw-anchor"

# Stage exactly the files the anchor needs on the server.
mkdir -p "$STAGE/anchor/templates" "$STAGE/wasteproto"
cp "$REPO"/anchor/{__init__.py,app.py,directory.py} "$STAGE/anchor/"
cp "$REPO"/anchor/templates/{cover.html,status.html} "$STAGE/anchor/templates/"
cp "$REPO"/wasteproto/{__init__.py,rsa_identity.py} "$STAGE/wasteproto/"
cp "$REPO"/deploy/anchor.env "$STAGE/anchor.env"
cp "$REPO"/deploy/anchor-requirements.txt "$STAGE/requirements.txt"

# rsync (never --delete, per project convention) and refresh the venv.
rsync -az -e "ssh -o BatchMode=yes" "$STAGE/" "$SYNC_USER:$DEST/"
ssh -o BatchMode=yes "$SYNC_USER" "chmod 600 $DEST/anchor.env && \
  $DEST/.venv/bin/pip install -q -r $DEST/requirements.txt"

# Restart and report.
ssh -o BatchMode=yes "$SUDO_USER" "sudo systemctl restart yaw-anchor && \
  sleep 1 && sudo systemctl is-active yaw-anchor"

rm -rf "$STAGE"
echo "redeploy complete."

#!/usr/bin/env bash
# deploy/install.sh — Install Sandy as a systemd user service.
#
# Installs sandy.service to ~/.config/systemd/user/ and enables it
# to start on boot (via loginctl enable-linger).
#
# Usage (run from repo root):
#   bash deploy/install.sh
#
# Requirements:
#   - uv installed: ~/.local/bin/uv (or on PATH)
#   - loginctl available (standard on systemd Linux)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
SERVICE_NAME="sandy"
SERVICE_SRC="$SCRIPT_DIR/sandy.service"
SERVICE_DEST="$HOME/.config/systemd/user/${SERVICE_NAME}.service"

echo "Sandy homelab installer"
echo "  Repo: $REPO_ROOT"
echo "  Service: $SERVICE_DEST"
echo ""

# Ensure systemd user directory exists
mkdir -p "$HOME/.config/systemd/user"

# Copy service file
cp "$SERVICE_SRC" "$SERVICE_DEST"
echo "  ✓ Installed $SERVICE_DEST"

# Reload systemd user daemon
systemctl --user daemon-reload
echo "  ✓ Reloaded systemd user daemon"

# Enable service (start on boot)
systemctl --user enable "$SERVICE_NAME"
echo "  ✓ Enabled $SERVICE_NAME on boot"

# Enable linger so user services start without login
# Check first — if already enabled, skip (avoids polkit/pkttyagent on headless systems)
_user="$(whoami)"
if loginctl show-user "$_user" 2>/dev/null | grep -q "^Linger=yes"; then
    echo "  ✓ Linger already enabled (service starts without login)"
elif loginctl enable-linger "$_user" 2>/dev/null; then
    echo "  ✓ Enabled linger (service starts without login)"
else
    echo "  ⚠ Could not enable linger — run: sudo loginctl enable-linger $_user"
fi

echo ""
echo "Start now with: systemctl --user start $SERVICE_NAME"
echo "View logs with: journalctl --user -u $SERVICE_NAME -f"

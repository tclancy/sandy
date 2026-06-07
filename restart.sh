#!/usr/bin/env bash
# restart.sh — sync deps and restart the Sandy systemd user service.
#
# Used by itguy git-pull post-deploy and for manual restarts.
# Safe to run multiple times.
#
# Usage:
#   ./restart.sh
#
# Requirements:
#   - uv installed at ~/.local/bin/uv
#   - sandy.service installed: ~/.config/systemd/user/sandy.service
#   - loginctl enable-linger has been run for the current user

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Syncing dependencies..."
cd "$SCRIPT_DIR"
# --frozen: install from uv.lock as-is; do NOT re-resolve/rewrite the lock.
# Without it, floor-pinned deps (e.g. aiohttp >=x) get upgraded on every run,
# dirtying the tracked uv.lock — which breaks idempotency for the Ansible
# native-apps deploy (its git clone reverts the lock, flapping every run).
# Deploys should run the locked versions; bump deps by re-locking + committing.
uv sync --frozen --quiet

echo "Installing sibling entry-point packages..."
uv pip install -e ../itguy -e ../irs --quiet 2>/dev/null || true

echo "Restarting sandy service..."
systemctl --user restart sandy

echo "Done. Check status with: journalctl --user -u sandy -f"

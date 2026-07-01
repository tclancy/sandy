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

# Non-interactive SSH shells (e.g. `ssh host 'cd ~/sources/sandy && ./restart.sh'`,
# or itguy's git-pull post-deploy) don't source the login profile, so uv's
# install dir (~/.local/bin) may be missing from PATH. Prepend the usual
# locations ourselves so remote/automated runs find uv (used by both
# `uv sync` and `uv pip install` below). Mirrors itguy's restart.sh (#123).
for bin_dir in "$HOME/.local/bin" "$HOME/.cargo/bin" /opt/homebrew/bin /usr/local/bin; do
    case ":$PATH:" in
        *":$bin_dir:"*) ;;                       # already present — skip
        *) [ -d "$bin_dir" ] && PATH="$bin_dir:$PATH" ;;
    esac
done
export PATH

if ! command -v uv >/dev/null 2>&1; then
    echo "error: 'uv' not found on PATH (looked in ~/.local/bin, ~/.cargo/bin, /opt/homebrew/bin, /usr/local/bin)." >&2
    echo "Install it: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

echo "Syncing dependencies..."
cd "$SCRIPT_DIR"
# --frozen: install from uv.lock as-is; do NOT re-resolve/rewrite the lock.
# Without it, floor-pinned deps (e.g. aiohttp >=x) get upgraded on every run,
# dirtying the tracked uv.lock — which breaks idempotency for the Ansible
# native-apps deploy (its git clone reverts the lock, flapping every run).
# Deploys should run the locked versions; bump deps by re-locking + committing.
uv sync --frozen --quiet

echo "Installing sibling entry-point plugins..."
# itguy/estimatedtaxes are homelab-only plugins that live outside sandy's
# lockfile, so `uv sync --frozen` prunes them every run — reinstall explicitly.
# Fail LOUDLY: a silent skip ships Sandy without the tax/itguy commands (the
# old `|| true 2>/dev/null` hid exactly that). Siblings are absent in CI / dev
# checkouts that don't have them — skip those cleanly. `set -e` aborts the
# deploy before the restart if a present sibling won't install, and the daemon's
# SANDY_REQUIRED_PLUGINS startup check reports any miss to Sentry on restart.
sibling_specs=()
for sib in ../itguy ../irs; do
    if [ -d "$sib" ]; then
        sibling_specs+=(-e "$sib")
    else
        echo "  (skipping $sib — not present)"
    fi
done
if [ ${#sibling_specs[@]} -gt 0 ]; then
    uv pip install "${sibling_specs[@]}"
fi

echo "Restarting sandy service..."
systemctl --user restart sandy

echo "Done. Check status with: journalctl --user -u sandy -f"

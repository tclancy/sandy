#!/usr/bin/env bash
# Wrapper script for Sandy CLI.
# Symlink this somewhere on your PATH:
#   ln -s /path/to/sandy/sandy.sh /usr/local/bin/sandy
set -euo pipefail

SANDY_DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
exec uv run --directory "$SANDY_DIR" sandy "$@"

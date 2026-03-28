#!/usr/bin/env bash
# Deploy Sandy to homelab via Ansible (in the rpi repo)
set -euo pipefail

RPI_DIR="$(cd "$(dirname "$0")/../rpi" && pwd)"

cd "$RPI_DIR"
uv run ansible-playbook -i ansible/inventory/hosts ansible/playbook.yml --tags sandy

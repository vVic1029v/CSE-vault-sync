#!/usr/bin/env bash
# Sync Brightspace -> Obsidian vault (pure read-only clone).
# Full run: login (if needed) -> sync -> vault -> selftest.
# The vault output (-o) is the Brightspace/ subfolder of your Obsidian vault;
# --read-only chmods everything a-w, no exceptions. Personal notes live in
# the vault-side Courses/ hub notes, never here. Re-runs wipe and rebuild.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="${1:-$HOME/Documents/OBSIDIAN/holanda/Brightspace}"
python3 "$SCRIPT_DIR/main.py" -o "$VAULT_DIR" --read-only "$@"

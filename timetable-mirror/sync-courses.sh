#!/usr/bin/env bash
# Regenerate vault-side Courses/ hub notes (AUTO block only; user space kept).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="${1:-$HOME/Documents/OBSIDIAN/holanda}"
python3 "$SCRIPT_DIR/courses.py" --vault "$VAULT_DIR" "$@"

#!/usr/bin/env bash
# Mirror MyTimetable ICS -> Obsidian Timetable/ notes (read-only).
# Needs TIMETABLE_ICS_URL (personal subscription URL — never commit it).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="${1:-$HOME/Documents/OBSIDIAN/holanda/Timetable}"
if [ -z "${TIMETABLE_ICS_URL:-}" ]; then
  echo "error: set TIMETABLE_ICS_URL to your MyTimetable subscription URL" >&2
  exit 1
fi
python3 "$SCRIPT_DIR/mirror.py" -o "$VAULT_DIR" "$@"

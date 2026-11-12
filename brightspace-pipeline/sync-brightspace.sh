#!/usr/bin/env bash
# Sync Brightspace -> Obsidian vault (pure read-only clone).
# Full run: login (if needed) -> sync -> vault -> selftest.
# The vault output (-o) is the Brightspace/ subfolder of your Obsidian vault;
# --read-only chmods everything a-w, no exceptions. Personal notes live in
# the vault-side Courses/ hub notes, never here. Re-runs wipe and rebuild.
#
# Cache is keyed per Brightspace user (mirrors sync.sh: incident 2026-10-08
# — a shared cache merged two users' courses into both vaults). The owner
# is taken from --netid/--as, else $BS_NETID, else an interactive prompt.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_DIR="$HOME/Documents/OBSIDIAN/holanda/Brightspace"
if [[ $# -gt 0 && "$1" != -* ]]; then
    VAULT_DIR="$1"; shift
fi

NETID=""; HAVE_CACHE_DIR=0; HAVE_COOKIES=0
FILTERED=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --netid) NETID="$2"; FILTERED+=("$1" "$2"); shift 2 ;;
        --as) NETID="$2"; FILTERED+=(--netid "$2"); shift 2 ;;
        --cache-dir) HAVE_CACHE_DIR=1; FILTERED+=("$1" "$2"); shift 2 ;;
        --cookies) HAVE_COOKIES=1; FILTERED+=("$1" "$2"); shift 2 ;;
        *) FILTERED+=("$1"); shift ;;
    esac
done
if [[ -z "$NETID" ]]; then NETID="${BS_NETID:-}"; fi
if [[ -z "$NETID" ]]; then
    read -rp "Cache owner NetID (--as to skip this): " NETID || true
    [[ -z "$NETID" ]] && { echo "error: need a NetID: pass --as NETID" >&2; exit 1; }
fi
export BS_NETID="$NETID"   # pipeline login guard checks against this
NS_SAN="$(printf '%s' "$NETID" | tr '[:upper:]' '[:lower:]' \
    | tr -c '[:alnum:]._-' '_')"
NS_DIR="$SCRIPT_DIR/_state/cache/by-user/$NS_SAN"
if [[ "$HAVE_CACHE_DIR" -eq 0 ]]; then
    FILTERED+=(--cache-dir "$NS_DIR")
fi
if [[ "$HAVE_COOKIES" -eq 0 ]]; then
    FILTERED+=(--cookies "$NS_DIR/cookies.json")
fi
python3 "$SCRIPT_DIR/main.py" -o "$VAULT_DIR" --read-only "${FILTERED[@]}"

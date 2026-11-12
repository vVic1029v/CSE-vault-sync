#!/usr/bin/env bash
# scripts/vault-sync.sh - SUPER+CTRL+S menu wrapper around the CSE vault sync.
# All logic stays in ~/Projects/CSE-vault-sync/sync.sh; this only builds the
# flag list. Credentials and the timetable URL stay sync.sh's own prompts.
# The terminal remains attached because sync.sh asks for those and for review
# confirmation.
set -euo pipefail

. /home/donkw/.config/hypr/scripts/lib.sh

SYNC=/home/donkw/Projects/CSE-vault-sync/sync.sh
DEFAULT_VAULT="$HOME/Documents/OBSIDIAN/holanda"

if [ ! -f "$SYNC" ]; then
    echo "vault-sync: missing $SYNC" >&2
    exit 1
fi

header_on "CSE VAULT SYNC"
trap 'header_off' EXIT

# Toggleable sync.sh flags. Order here is the order shown in the menu.
FLAG_ARGS=(--cached --skip-brightspace --skip-timetable --skip-courses
           --skip-summary --no-sanitize --yes --no-commit)
FLAG_LABELS=(
    "Rebuild from cache, offline (--cached)"
    "Skip Brightspace (--skip-brightspace)"
    "Skip Timetable (--skip-timetable)"
    "Skip Courses (--skip-courses)"
    "Skip dashboard (--skip-summary)"
    "Do not sanitize links (--no-sanitize)"
    "Auto-confirm review (--yes)"
    "Leave changes uncommitted (--no-commit)"
)
FLAG_ON=(0 0 0 0 0 0 0 0)

VAULT_PATH="$DEFAULT_VAULT"
DAYS_PAST=""
DAYS_FUTURE=""
EXCLUDES=()

menu() {
    local i
    for i in "${!FLAG_ARGS[@]}"; do
        if [ "${FLAG_ON[$i]}" -eq 1 ]; then
            printf '%s\t[x] %s\n' "$i" "${FLAG_LABELS[$i]}"
        else
            printf '%s\t[ ] %s\n' "$i" "${FLAG_LABELS[$i]}"
        fi
    done
    printf -- '---\t────────────────────────────────────────\n'
    printf 'vault\tVault path:        %s\n' "$VAULT_PATH"
    printf 'past\tDays past:         %s\n' "${DAYS_PAST:-default (14)}"
    printf 'future\tDays future:       %s\n' "${DAYS_FUTURE:-default (120)}"
    printf 'exclude\tExclude regexes:   %s\n' "${EXCLUDES[*]:-none}"
    printf -- '---\t────────────────────────────────────────\n'
    printf 'run\t>>> Run sync <<<\n'
    printf 'cancel\tCancel\n'
}

pause_msg() {
    printf '\n%s\n' "$1" >&2
    read -rp "Press Enter to continue..." _ || true
}

edit_number() { # edit_number <label>
    local ans
    read -rp "$1 (blank resets to default): " ans || true
    if [ -z "$ans" ]; then
        printf ''
        return 0
    fi
    if [[ ! "$ans" =~ ^[0-9]+$ ]]; then
        pause_msg "Not a number: $ans"
        return 1
    fi
    printf '%s' "$ans"
}

while true; do
    if ! choice=$(menu | fzf --height=80% --reverse --no-sort \
            --delimiter='\t' --with-nth=2 --prompt='sync> ' \
            --header='Enter toggles or edits · Esc cancels'); then
        printf 'Cancelled.\n'
        exit 0
    fi
    key=${choice%%$'\t'*}

    case "$key" in
        [0-7])
            FLAG_ON[$key]=$((1 - FLAG_ON[$key]))
            ;;
        vault)
            read -rp "Vault path [$DEFAULT_VAULT]: " ans || true
            VAULT_PATH=${ans:-$DEFAULT_VAULT}
            ;;
        past)
            if out=$(edit_number "Days past"); then
                DAYS_PAST="$out"
            fi
            ;;
        future)
            if out=$(edit_number "Days future"); then
                DAYS_FUTURE="$out"
            fi
            ;;
        exclude)
            read -rp "Exclude RAW codes, space-separated (blank clears): " ans || true
            read -ra EXCLUDES <<< "$ans"
            ;;
        run)
            break
            ;;
        cancel)
            printf 'Cancelled.\n'
            exit 0
            ;;
    esac
done

ARGS=()
for i in "${!FLAG_ARGS[@]}"; do
    [ "${FLAG_ON[$i]}" -eq 1 ] && ARGS+=("${FLAG_ARGS[$i]}")
done
ARGS+=(--vault "$VAULT_PATH")
[ -n "$DAYS_PAST" ] && ARGS+=(--days-past "$DAYS_PAST")
[ -n "$DAYS_FUTURE" ] && ARGS+=(--days-future "$DAYS_FUTURE")
for rx in "${EXCLUDES[@]}"; do
    ARGS+=(--exclude "$rx")
done

printf '\n%s %q' "Running:" "$SYNC"
printf ' %q' "${ARGS[@]}"
printf '\n\n'

set +e
/bin/bash "$SYNC" "${ARGS[@]}" "$@"
rc=$?
set -e
exit "$rc"

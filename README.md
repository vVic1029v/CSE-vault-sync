# CSE-vault-sync

Sync TU Delft sources → Obsidian vault (`~/Documents/OBSIDIAN/holanda`).

## Entry point: `./sync.sh`

One transactional wrapper around all three generators: git checkpoint
(commit + `pre-sync-*` tag) → run → review → confirm or rollback.

```bash
./sync.sh                                  # from source: prompts for NetID/password + ICS URL
./sync.sh --cached                         # offline rebuild from cache, no prompts
./sync.sh --exclude 'CSE000' --days-future 60
./sync.sh --skip-timetable                 # Brightspace + Courses only
```

- Default mode syncs **from source** (interactive prompts; env vars
  `BS_NETID` / `BS_PASSWORD` / `TIMETABLE_ICS_URL` pre-fill). `--cached`
  rebuilds Brightspace from the RAW cache (`--stage vault`, no network),
  skips Timetable (no offline cache exists for it), and always runs Courses.
- Secrets are exported only to the child generator processes, never logged.
- `--exclude REGEX` matches RAW cache codes (`CSE000+2026+1`), so use
  `--exclude 'CSE000'`, not a display name. Repeatable.
- `--yes` takes the review default without asking (for destructive
  changes the default is *decline* — forcing one requires an interactive
  `y`). `--no-commit` applies everything and leaves it uncommitted.

## Review model

- `Timetable/` + `Courses/` are git-tracked: reviewed via `git diff`.
- `Brightspace/` is git-ignored by policy (never commit downloaded course
  material): reviewed via sha256 manifests against a pre-sync backup.
  Verbatim moves collapse to `old -> new`; changed text notes show real
  unified diffs (full copy: `$WORK/review.diff` path printed at review).
- **Destructive** (prompt defaults to NO): tracked prunes, Brightspace
  removals / verbatim moves / non-whitespace overwrites, or any change to
  a file hand-edited inside `Brightspace/`. Whitespace-only and
  `Synced DATE`-stamp churn is noise. Everything else (new files, tracked
  edits) is safe and defaults to yes.
- Output is color-coded on a terminal (cyan stages, yellow review, red
  destructive/errors, green safe/done); piped output stays plain, and
  `NO_COLOR=1` disables colors.

## Tools

- `brightspace-pipeline/` — Brightspace LMS → read-only `Brightspace/`
  clone (login → sync RAW cache → vault → selftest). `--stage vault`
  rebuilds from cache with no network.
- `timetable-mirror/` — MyTimetable ICS → `Timetable/` instance notes,
  plus `courses.py` vault-side `Courses/` hubs (AUTO block regenerates,
  user space preserved).
- `vaultlib/autolib.py` — shared stdlib-only helpers both tools import:
  AUTO markers, file banner, user-section reader, YAML quoting,
  read-only chmod, tag helpers.
- `_state/` (inside `brightspace-pipeline/`) holds cookies, sync cache,
  and logs. **Never commit it.**

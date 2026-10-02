# brightspace-pipeline

Brightspace (TU Delft) → Obsidian vault. One note per content item
(`## Contents` holds its text, `## MOC` links its children), files copied
alongside. Pure read-only clone: no user content lives here — personal
notes go in the vault-side `Courses/` hub notes. Re-runs wipe and rebuild.

Prefer the transactional wrapper `../sync.sh` (checkpoint → run all three
mirrors → review → confirm/rollback); the commands below are for
single-mirror work.

## Install

```bash
pip install -r requirements.txt
python -m playwright install chromium   # only for the first SSO login
```

## Use

```bash
python3 main.py -o ~/MyVault                     # prompts for NetID/password
BS_NETID=... BS_PASSWORD=... python3 main.py -o ~/MyVault
python3 main.py -o ~/MyVault --exclude 'Mentoring' --exclude '^B.+TI$'
python3 main.py -o ~/MyVault --list              # just list courses
python3 main.py -o ~/MyVault --selftest          # sync + build + validate
python3 main.py --selftest                       # validate ./vault only (offline)
python3 main.py -o ~/MyVault --stage login|sync|vault
```

`--stage vault` rebuilds from the RAW cache with no network (used by
`../sync.sh --cached`); the other stages log in and re-fetch.

`-o` names the vault folder itself: the vault is the ONLY output. Sync
cache (raw files, manifest, logs) lives with the script in `_state/`
unless `--cache-dir` is given. Extra output toggles:

- `--read-only`: chmod the output read-only after building — for targeting
  a subfolder inside your Obsidian vault.
- `--virt-folder`: emit VirtFolder `Folders:` parent links (mirroring
  `up:`) so notes nest in the VirtFolder tree. Omit for plain output.
- `--virt-root NOTE`: with `--virt-folder`, nest the top note (named
  `! <folder>`, e.g. `! Brightspace.md`) under this vault-side note
  (e.g. `--virt-root '! Index'`) for a single tree root.

## Credentials (read this)

- Preferred: `BS_NETID` / `BS_PASSWORD` env vars, or the interactive
  prompt. `--password` still works but prints a warning — it leaks into
  shell history and process lists.
- After the first login the session lives in `_state/cookies.json` and is
  reused until Brightspace rejects it. **Never commit `_state/`**
  (see `.gitignore`): it holds a live session for your account.
- Never paste secrets into chats, tickets, or shared docs — same rule as
  anywhere else.

## How it works

```
login (auth.py: playwright SSO, cookies on disk)
  ▼
sync  (client.py: Valence reads · sync.py: tree walk -> RAW cache + manifest
       snapshots.py: dropbox / news / grades)
  ▼
vault (notes.py: one note per item · extras.py: grades/assignments tables
       vault.py: wipe + copy + home notes + prune orphans)
  ▼
selftest (selftest.py: 5 read-only checks — junk files, filenames,
          wikilinks, frontmatter, PDFs; editor dirs like
          `.obsidian/` are not flagged as junk)
```

`bsvault/pipeline.py` wires the stages; `bsvault/cli.py` only parses
flags. Supporting rules:

- `config.Paths` carries all directories explicitly — no mutated globals.
- Content order is always Brightspace order, never sorted.
- `vault_filter.py` decides what never leaves the cache (internal
  quicklinks, `javascript:` targets become locked notes, never downloads).

## Layout

```
main.py                 thin shim (keeps `python3 main.py ...` working)
bsvault/
  cli.py                flags + stage wiring
  pipeline.py           login -> sync -> vault -> selftest composition
  config.py             API versions, ext sets, Paths
  utils.py              sanitize, hashes, log, labels
  htmlmd.py             HTML -> Markdown (inline/block)
  auth.py               cookies, session check, headless SSO login
  client.py             Valence GET / whoami / enrollments
  sync.py               Syncer: incremental course walk + manifest
  snapshots.py          dropbox / news / grades snapshots
  vault_filter.py       what stays out of the vault
  notes.py              emit_* : cache entries -> notes + MOC
  extras.py             grades / assignments tables
  vault.py              build_vault: preserve, copy, emit, home notes, prune
   selftest.py           read-only vault health checks
                        (junk, filenames, wikilinks, frontmatter, PDFs)
```

## Limits

- Personal tooling against an internal LMS: scraping automation may
  violate your institution's acceptable-use policy. Personal, low-rate,
  cached use is the safe shape — run rarely, keep the cache, don't share
  downloaded course materials.
- Valence has no stable "everything changed since X" feed, so sync walks
  the whole tree and skips unchanged items by hash.

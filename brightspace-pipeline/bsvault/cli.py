"""CLI: flags in, stages out. Parsing here, work in pipeline.*.

Stages (run in order unless --stage narrows it):
  login -> sync -> vault, then the read-only selftest.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from . import auth
from .client import BrightspaceClient
from .config import STATE, build_paths
from .pipeline import (ensure_login, fetch_courses, report_selftest, run_sync,
                       run_vault)
from .selftest import selftest
from .utils import log


def build_parser():
    """Define every flag (kept identical to the original single-file CLI)."""
    ap = argparse.ArgumentParser(
        description="Brightspace -> Obsidian vault. -o names the vault folder "
                    "itself; that folder is the only output. Sync cache lives "
                    "with the script.")
    ap.add_argument("--netid")
    ap.add_argument("--password")
    ap.add_argument("--cookies", default=str(STATE / "cookies.json"))
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--update", action="store_true",
                    help="sync is always incremental; flag kept for readability")
    ap.add_argument("--stage", default="all",
                    choices=["all", "login", "sync", "vault"])
    ap.add_argument("-o", "--output", default=str(Path.cwd() / "vault"),
                    help="the Obsidian vault folder to create/update "
                         "(default: ./vault)")
    ap.add_argument("--cache-dir", default=None,
                    help="sync cache dir (default: <script>/_state/cache)")
    ap.add_argument("--exclude", action="append", default=[],
                    help="skip courses whose code matches this regex (repeatable)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--read-only", action="store_true",
                    help="chmod the vault output read-only after building; "
                         "use when targeting a subfolder inside your "
                         "Obsidian vault")
    ap.add_argument("--virt-folder", action="store_true",
                    help="emit VirtFolder `Folders:` parent links (mirroring "
                         "`up:`) so generated notes nest in the VirtFolder "
                         "tree; omit for plain output without the metadata")
    ap.add_argument("--virt-root", default=None, metavar="NOTE",
                    help="with --virt-folder, nest the top note (named after "
                         "the output folder) under this vault-side note "
                         "(e.g. '! Index') so the whole "
                         "tree has a single root")
    return ap


def selftest_only(paths):
    """Validate the vault and exit (no login, no network). Returns exit code."""
    errors, warnings = selftest(paths.vault)
    print(f"SELFTEST: {len(errors)} errors, {len(warnings)} warnings")
    for err in errors:
        print("ERROR:", err)
    for warn in warnings[:10]:
        print("WARN:", warn)
    return 1 if errors else 0


def main(argv=None):
    """Entry point: parse flags, run stages, selftest, done."""
    args = build_parser().parse_args(argv)
    paths = build_paths(args.output, args.cache_dir, args.cookies)
    meta = paths.raw / "_meta"
    meta.mkdir(parents=True, exist_ok=True)
    logfile = meta / "pipeline-log.txt"
    paths.state.mkdir(parents=True, exist_ok=True)

    if args.selftest and args.stage == "all" \
            and not args.netid and not os.environ.get("BS_NETID"):
        sys.exit(selftest_only(paths))

    cookies = None
    if args.stage in ("all", "login"):
        cookies = ensure_login(paths, args.netid, args.password, logfile)
        if args.stage == "login":
            return
    elif args.stage in ("all", "sync"):
        # offline stages reuse the jar on disk as-is (no revalidation)
        cookies = auth.load_cookies(paths.cookies)

    if args.stage in ("all", "sync") or args.list:
        # --stage vault rebuilds from the RAW cache and needs no network
        with auth.build_client(cookies) as client:
            api = BrightspaceClient(client, logfile)
            _, courses = fetch_courses(api, meta, logfile)
            if args.list:
                for course in courses:
                    print(f"{course['id']} | {course['code']} | {course['name']}")
                return
            if args.stage in ("all", "sync"):
                manifest_path = meta / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8")) \
                    if manifest_path.exists() else {}
                run_sync(api, paths, courses, manifest, manifest_path, logfile)

    if args.stage in ("all", "vault"):
        run_vault(paths, logfile, exclude=args.exclude,
                  read_only=args.read_only, virt_folder=args.virt_folder,
                  virt_root=args.virt_root)
    if args.selftest or args.stage == "all":
        if not report_selftest(paths.vault):
            sys.exit(1)
    log("PIPELINE DONE", logfile)

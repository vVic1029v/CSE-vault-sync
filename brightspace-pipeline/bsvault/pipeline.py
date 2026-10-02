"""Composition: login -> sync -> vault -> selftest.

Each run_* does one stage; cli.main wires them in order. Nothing here knows
Valence endpoints or note layouts — those live in client/sync/vault.
"""

import getpass
import json
import os
import sys
from datetime import datetime, timezone

from . import auth, vault as vault_mod
from .client import BrightspaceClient
from .config import LP_VER
from .selftest import selftest
from .sync import Syncer
from .utils import log, sanitize


def ensure_login(paths, netid, password, logfile):
    """Return a working cookie jar, logging in through the browser if needed."""
    cookies = auth.load_cookies(paths.cookies)
    if auth.session_ok(cookies, LP_VER):
        log("LOGIN: existing session still valid, skipping browser login", logfile)
        return cookies
    netid = netid or os.environ.get("BS_NETID") or input("NetID: ").strip()
    secret = (password or os.environ.get("BS_PASSWORD")
              or getpass.getpass("Password: "))
    if password:
        print("WARN: --password exposes your secret in shell history and "
              "process lists; prefer BS_PASSWORD env or the prompt.",
              file=sys.stderr)
    log("LOGIN: starting local SSO login…", logfile)
    cookies = auth.playwright_login(netid, secret, paths.state, logfile)
    auth.save_cookies(cookies, paths.cookies)
    del secret
    log(f"LOGIN: ok, {len(cookies)} cookies", logfile)
    return cookies


def fetch_courses(api, meta_dir, logfile):
    """whoami + enrollments; persist courses.json. Returns (me, courses)."""
    me = api.whoami()
    log(f"Logged in as: {me.get('FirstName')} {me.get('LastName')} "
        f"({me.get('UniqueName')})", logfile)
    courses = api.enrollments()
    log(f"Found {len(courses)} course offerings", logfile)
    (meta_dir / "courses.json").write_text(json.dumps(courses, indent=2),
                                           encoding="utf-8")
    return me, courses


def run_sync(api, paths, courses, manifest, manifest_path, logfile):
    """Sync every course into the RAW cache. Returns (new, skipped)."""
    syncer = Syncer(api, logfile)
    total_new, total_skipped = 0, 0
    for course in courses:
        cdir = paths.raw / sanitize(course["code"] or f"course-{course['id']}", 80)
        try:
            new, skipped = syncer.sync_course(course, cdir, manifest)
            total_new += new
            total_skipped += skipped
        except Exception as ex:
            log(f"!! course failed {course.get('code')}: {ex}", logfile)
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (paths.raw / "_meta" / "last-sync.txt").write_text(
        datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    log(f"SYNC COMPLETE: {total_new} new/changed, {total_skipped} unchanged",
        logfile)
    return total_new, total_skipped


def run_vault(paths, logfile, exclude=(), read_only=False, virt_folder=False,
              virt_root=None):
    """Build the vault. Returns [(code, vname, entries, files)]."""
    return vault_mod.build_vault(paths, logfile, exclude, read_only,
                                 virt_folder, virt_root)


def report_selftest(vault_dir):
    """Run the read-only selftest, print it, return True when clean."""
    errors, warnings = selftest(vault_dir)
    print(f"SELFTEST: {len(errors)} errors, {len(warnings)} warnings")
    for err in errors:
        print("ERROR:", err)
    for warn in warnings[:10]:
        print("WARN:", warn)
    return not errors

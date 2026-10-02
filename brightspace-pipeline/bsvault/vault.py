"""Sync cache -> Obsidian vault. The vault dir (-o) is the ONLY output.

One note per item (# Contents holds its text, # MOC links children).
Pure read-only clone: no user content lives here (that's what the
vault-side Courses/ hub notes are for).
"""

import json
import re
import shutil

from .config import AUTO_TAG  # noqa: F401  (also installs vaultlib sys.path)
from autolib import (AUTO_END, AUTO_START, make_readonly, make_writable,
                     tags_line)
from .notes import (EmitCtx, course_vault_name, emit_level, label,
                    write_moc_note)
from .utils import log, sanitize, utcnow


def course_codes_in_order(raw):
    """Course codes: manifest order first, then any new cache dirs."""
    order, seen = [], set()

    def _remember(code):
        if code not in seen:
            seen.add(code)
            order.append(code)

    courses_path = raw / "_meta" / "courses.json"
    if courses_path.exists():
        try:
            for course in json.loads(courses_path.read_text(encoding="utf-8")):
                if isinstance(course, dict) and course.get("code"):
                    _remember(sanitize(course["code"], 80))
        except Exception:
            pass
    for cdir in sorted(raw.iterdir()):
        if cdir.is_dir() and not cdir.name.startswith(("_", ".")):
            _remember(cdir.name)
    return order


def reset_vault(vault, logfile=None):
    """Wipe the vault and return it fresh and empty."""
    if vault.exists():
        make_writable(vault)  # a previous --read-only run left it a-w
        shutil.rmtree(vault)
    vault.mkdir(parents=True, exist_ok=True)


def copy_course_files(root, cdir, vcourse, used):
    """Copy file topics into the vault; seed note-name sets. Returns count."""
    copied = [0]

    def _copy(nodes, vdir):
        for topic in nodes:
            if topic.get("kind") == "file" and topic.get("path"):
                src = cdir / topic["path"]
                if src.exists():
                    dest = vcourse / topic["path"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    copied[0] += 1
                    used.setdefault(dest.parent.as_posix(), set()).add(
                        dest.name.lower())
            elif topic.get("kind") == "module":
                _copy(topic.get("children", []), vdir / topic["name"])

    _copy(root, vcourse)
    return copied[0]


def frontmatter_for(vcourse_name, code, virt_folder=False):
    """Frontmatter block shared by the Assignments/Grades extras.

    Starts at byte 0 (Obsidian only recognizes leading frontmatter);
    callers prepend it before AUTO_TAG.
    """
    home = f"{vcourse_name}/{vcourse_name}"
    vf = (f"Folders:\n  - \"[[{home}]]\"\n" if virt_folder else "")
    return (f"---\nup: [[{home}]]\n{vf}"
            f"{tags_line(['brightspace'])}\n"
            f"course_code: {code}\n---\n")


def _prepend_frontmatter(body, fm):
    """fm (a --- block) lands at byte 0; generated table wrapped in markers."""
    from .config import AUTO_TAG
    content = body.replace(AUTO_TAG, "", 1).strip()
    return fm + AUTO_TAG + "\n".join([AUTO_START, content, AUTO_END]) + "\n"


def emit_extras(vcourse, vname, code, cdir, kids, virt_folder=False):
    """Write Assignments/Grades/Announcements extras; extend MOC kids."""
    from .extras import assignments_md, grades_md
    body = assignments_md(cdir / "_assignments")
    if body:
        body = body.replace("# Assignments", f"# Assignments — {label(code)}", 1)
        body = _prepend_frontmatter(
            body, frontmatter_for(vcourse.name, code, virt_folder))
        (vcourse / "Assignments.md").write_text(body, encoding="utf-8")
        kids.append(("note", f"{vname}/Assignments", "Assignments"))
    body = grades_md(cdir / "_grades.json")
    if body:
        body = body.replace("# Grades", f"# Grades — {label(code)}", 1)
        body = _prepend_frontmatter(
            body, frontmatter_for(vcourse.name, code, virt_folder))
        (vcourse / "Grades.md").write_text(body, encoding="utf-8")
        kids.append(("note", f"{vname}/Grades", "Grades"))
    ann_raw = cdir / "_announcements.md"
    if ann_raw.exists():
        ann = ann_raw.read_text(encoding="utf-8")
        home = f"{vname}/{vname}"
        vf = (f"Folders:\n  - \"[[{home}]]\"\n" if virt_folder else "")
        ann = ann.replace(
            f"# Announcements - {code}",
            f"---\nup: [[{home}]]\n{vf}"
            f"{tags_line(['brightspace', 'announcements'])}\n"
            f"course_code: {code}\n---\n"
            f"{AUTO_TAG.strip()}\n{AUTO_START}\n"
            f"# Announcements — {label(code)}", 1)
        ann = ann.rstrip() + f"\n{AUTO_END}\n"
        (vcourse / "Announcements.md").write_text(ann, encoding="utf-8")
        kids.append(("note", f"{vname}/Announcements", "Announcements"))
    return kids


def emit_course(raw, vault, code, used, logfile=None, virt_folder=False):
    """Build one course folder. Returns (code, vname, entries, files) or None."""
    from .notes import EmitCtx
    cdir = raw / code
    tree_path = cdir / "moc.json"
    if not tree_path.exists():
        log(f"VAULT: no moc for {code}, skipping (re-run sync)", logfile)
        return None
    try:
        root = json.loads(tree_path.read_text(encoding="utf-8")).get("root", [])
    except Exception as ex:
        log(f"VAULT: bad moc for {code}: {ex}", logfile)
        return None
    info = {}
    info_path = cdir / "course-info.json"
    if info_path.exists():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    cid = info.get("id", "")
    vcourse = vault / course_vault_name(raw, code)
    vcourse.mkdir(parents=True, exist_ok=True)
    # Course home note carries the course dir name (never a bare "Home",
    # which is ambiguous in search, tabs and the tree).
    course_home = f"{vcourse.name}/{vcourse.name}"
    top_stem = course_vault_link(vault.name)
    kept = copy_course_files(root, cdir, vcourse, used)
    ctx = EmitCtx(vault=vault, vcourse=vcourse, raw_cdir=cdir,
                  code=code, cid=cid, used=used, virt_folder=virt_folder)
    kids = emit_level(ctx, vcourse, course_home, root)
    kids = emit_extras(vcourse, vcourse.name, code, cdir, kids, virt_folder)
    if not kids:
        log(f"VAULT: skipped empty {code}", logfile)
        shutil.rmtree(vcourse, ignore_errors=True)
        return None
    # Course hub link (vault-side middleman note): only in virt mode, since
    # it points outside the generated dir at Courses/<vname>.
    hub = (f"Course hub: [[Courses/{vcourse.name}]]\n\n"
           if virt_folder else "")
    write_moc_note(vcourse / f"{vcourse.name}.md",
                   info.get("name", code) or code,
                   top_stem, cid, code, hub, kids, virt_folder)
    n_files = sum(1 for _ in vcourse.rglob("*")
                  if _.is_file() and _.suffix != ".md")
    return code, vcourse.name, len(kids), n_files, kept


def course_vault_link(vault_name):
    """Top-note link: the folder is `Brightspace`, the note is `! Brightspace`."""
    return f"{vault_name}/! {vault_name}"


def write_vault_home(vault, course_homes, logfile=None, virt_root=None):
    """Write the top-level home note listing every course.

    The note is named `! <folder>` (e.g. `! Brightspace.md`) — it is a MOC
    (grouping note with no own Notes section), never a bare "Home". With
    virt_root (e.g. '! Index', requires --virt-folder), it nests under that
    vault-side note for a single root. Frontmatter starts at byte 0 for
    Obsidian to recognize it.
    """
    name = f"! {vault.name}"
    top = vault / f"{name}.md"
    fm = ["---", tags_line(["brightspace", "moc"])]
    if virt_root:
        fm += [f"up: [[{virt_root}]]", "Folders:", f"  - \"[[{virt_root}]]\""]
    fm += ["---"]
    body = [f"# ! {vault.name} Vault", "",
            f"Synced {utcnow()[:10]}. One note per item: "
            "`## Contents` holds the item's own text, `## MOC` links its children. "
            "Your own notes live in the vault-side `Courses/` hub notes.", "",
            "## Courses", ""]
    for code, vname, nmod, nfiles in course_homes:
        from .notes import wl
        body.append(f"- {wl(vname + '/' + vname, code)} — {nmod} entries, {nfiles} files")
    lines = fm + [AUTO_TAG.strip(), AUTO_START, *body, AUTO_END]
    top.write_text("\n".join(lines) + "\n", encoding="utf-8")


def prune_orphans(vault, logfile=None):
    """Delete stale leftovers: empty dirs or dirs without a course-home note
    and without real content. Anything with files is always kept.
    """
    removed = []
    for child in [p for p in vault.iterdir() if p.is_dir()]:
        if (child / f"{child.name}.md").exists():
            continue
        files = [p for p in child.rglob("*") if p.is_file()]
        if not files:
            try:
                shutil.rmtree(child)
                removed.append(child.name)
            except Exception:
                pass
    if removed:
        log(f"VAULT: pruned {len(removed)} stale folders: {removed}", logfile)


def build_vault(paths, logfile, exclude=(), read_only=False,
                virt_folder=False, virt_root=None):
    """Compose the full vault build; return [(code, vname, entries, files)]."""
    from pathlib import Path
    raw, vault = paths.raw, paths.vault
    assert raw.exists(), f"sync cache missing: {raw} (run sync first)"
    reset_vault(vault, logfile)
    excluded = [re.compile(p) for p in (exclude or [])]
    used, course_homes, kept_files = {}, [], 0
    for code in course_codes_in_order(raw):
        if any(rx.search(code) for rx in excluded):
            log(f"VAULT: excluded {code}", logfile)
            continue
        if not (raw / code).is_dir():
            continue
        result = emit_course(raw, vault, code, used, logfile, virt_folder)
        if result is None:
            continue
        code, vname, entries, files, kept = result
        kept_files += kept
        course_homes.append((code, vname, entries, files))
    write_vault_home(vault, course_homes, logfile,
                     virt_root if virt_folder else None)
    total_md = sum(1 for _ in vault.rglob("*.md"))
    total_files = sum(1 for _ in vault.rglob("*") if _.is_file())
    log(f"VAULT: {len(course_homes)} courses, {total_md} notes, "
        f"{total_files} files ({kept_files} files copied)", logfile)
    prune_orphans(vault, logfile)
    if read_only:
        make_readonly(vault)
        log("VAULT: set read-only (pure clone, no exceptions)", logfile)
    return course_homes

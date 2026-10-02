#!/usr/bin/env python3
"""MyTimetable (TU Delft, TimeEdit ICS) -> Obsidian Timetable/ notes.

One note per class instance inside a rolling window. Notes carry
Full-Calendar-compatible frontmatter (title/date/startTime/endTime) so the
week view renders them and clicking opens the note, plus Dataview-friendly
fields (course/room/kind) and smart links (vault-side Courses/ hub,
same-date lecture note) so the Now/Today dashboards can list lectures.

Regeneration is idempotent: the output dir is rebuilt in place and only
the `## Notes` section of each note is preserved (matched per occurrence,
so notes survive time/title shifts). Everything else regenerates —
hand-made study sessions still live in `Sessions/` instead.

Usage:
  TIMETABLE_ICS_URL='https://...' python3 mirror.py -o ~/vault/Timetable
  python3 mirror.py -o ~/vault/Timetable --days-past 14 --days-future 120
"""

import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vaultlib"))
from autolib import (AUTO_END, AUTO_START, banner, make_writable,
                     read_section, split_markers, tags_line, yq)

LOCAL_TZ = ZoneInfo("Europe/Amsterdam")
AUTO_TAG = banner("timetable-mirror")


def sanitize(name, limit=100):
    """Filesystem- and wikilink-safe stem (spaces kept).

    Local on purpose: the Brightspace scraper replaces unsafe chars with
    `-`, here they are deleted — unifying would rename every file.
    """
    name = re.sub(r"[][\[^|#<>:/\\?*]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:limit] or "untitled"


def unfold(text):
    """Unfold ICS line continuations."""
    return re.sub(r"\r?\n[ \t]", "", text)


def extract_field(desc, label):
    """TimeEdit DESCRIPTION sections look like 'Label: value' runs."""
    m = re.search(rf"^{re.escape(label)}:\s*(.+?)(?=\n[A-Z][^:\n]*:|\Z)",
                  desc, re.M | re.S)
    return m.group(1).strip().replace("\n", " ") if m else ""


def course_code(summary, desc):
    """DESCRIPTION 'Course code:' first, else SUMMARY prefix like CSE11A."""
    code = extract_field(desc, "Course code").split()[0] if \
        extract_field(desc, "Course code") else ""
    if code:
        return code
    m = re.match(r"^([A-Z]{1,4}\d{2,4}[A-Z]*)(\s|-|$)", summary)
    return m.group(1) if m else ""


def kind_of(desc):
    """Activity type, e.g. Lecture / Mentor meeting / Introduction."""
    return extract_field(desc, "Type")


def has_parent(note, parent_stem):
    """True when the note's VirtFolder Folders: points at parent."""
    try:
        text = note.read_text(encoding="utf-8")
    except OSError:
        return False
    if not text.startswith("---"):
        return False
    fm = text.split("---", 2)[1]
    return f"[[{parent_stem}]]" in fm.split("tags:", 1)[0] if "tags:" in fm \
        else f"[[{parent_stem}]]" in fm


def course_targets(vault, code):
    """Vault-side Courses/ hub links, one per '/'-separated code part.

    Returns [(link_target, lecture_scan_note_or_None)]: the hub link always
    points at Courses/<Brightspace-dir>; the scan note is the user's own
    (OLD) course note when one exists, used only to find same-date lecture
    notes — never linked.
    """
    targets = []
    bs = vault / "Brightspace"
    for part in [c.strip() for c in re.split(r"[/,]", code or "") if c.strip()]:
        d = None
        if bs.is_dir():
            d = next((x for x in sorted(bs.iterdir())
                      if x.is_dir() and x.name.startswith(part + " ")), None)
        if d is None:
            continue
        link = f"Courses/{d.name}"
        scan = next((p for p in sorted(vault.glob("*.md"))
                     if p.name.startswith(part + " ")
                     and has_parent(p, "! Index")), None)
        if link not in [t[0] for t in targets]:
            targets.append((link, scan))
    return targets


def children_of(vault, parent_stem):
    """Notes whose VirtFolder Folders: points at parent (one level)."""
    kids = []
    cands = list(vault.glob("*.md"))
    ex = vault / "Excalidraw"
    if ex.is_dir():
        cands += list(ex.glob("*.md"))
    target = f"[[{parent_stem}]]"
    for p in cands:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]
        m = re.search(r"^Folders:\s*(.*)$", fm, re.M)
        if not m:
            continue
        rest = m.group(1).strip()
        if rest:  # single-line form: Folders: "[[X]]"
            if target in rest:
                kids.append(p)
        else:  # list form: following '  - "[...]"' lines
            for line in fm.split("Folders:", 1)[1].split("\n")[1:]:
                if re.match(r"^\s+-\s+", line):
                    if target in line:
                        kids.append(p)
                        break
                elif line.strip() == "" or line.startswith(" "):
                    continue
                else:
                    break
    return kids


def lecture_note_for(vault, course_notes, day):
    """First course child ending ' - YYYY-MM-DD.md' matching day."""
    for note in course_notes:
        if note is None:
            continue
        for kid in children_of(vault, note.stem):
            m = re.search(r" - (\d{4}-\d{2}-\d{2})\.md$", kid.name)
            if m and m.group(1) == day:
                return kid
    return None


def emit(out_dir, vault, start, end, summary, code, kind, room, uid,
         written):
    """Surgical write of one instance note. Returns (course?, lecture?).

    Markers are absolute: existing files keep everything outside them
    (frontmatter, static headers, user prose) verbatim; only the marked
    region regenerates, plus the single derived `annotated:` line.
    """
    day = start.strftime("%Y-%m-%d")
    targets = course_targets(vault, code)
    course_notes = [n for _, n in targets if n is not None]
    lecture = lecture_note_for(vault, course_notes, day)
    core = sanitize(summary, 60)
    prefix = "" if (code and core.startswith(sanitize(code))) else \
        (sanitize(code + " ", 24) if code else "")
    stem = (f"{day} {start.strftime('%H%M')}-{end.strftime('%H%M')} "
            f"{prefix}{core}")
    path = out_dir / f"{stem}.md"
    i = 2
    while path in written:
        # Same stem twice in one run (shouldn't happen): disambiguate.
        # Files from previous runs are updated in place below.
        path = out_dir / f"{stem} ({i}).md"
        i += 1
    title = summary
    fm = ["---", f"title: {yq(title)}", f"date: {day}",
          f'startTime: "{start.strftime("%H:%M")}"',
          f'endTime: "{end.strftime("%H:%M")}"']
    if code:
        fm.append(f"course: {code}")
        parts = [c.strip() for c in re.split(r"[/,]", code) if c.strip()]
        fm.append("codes: [" + ", ".join(f'"{p}"' for p in parts) + "]")
    if kind:
        fm.append(f"kind: {kind}")
    if room and room != "No Room (No Room)":
        fm.append(f"room: {yq(room)}")
    if targets:
        fm.append("course_notes: [" + ", ".join(
            f"\"[[{t}]]\"" for t, _ in targets) + "]")
    if lecture:
        fm.append(f"lecture: \"[[{lecture.stem}]]\"")
    fm += [tags_line(["timetable"], partial=True),
           f"uid: {yq(uid)}", "---"]
    when = f"{day} · {start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
    auto = [f"# {title}", "",
            "> [!info]- 🕐 When & where",
            f"> **{when}**"]
    if room and room != "No Room (No Room)":
        auto.append(f"> {room}")
    if kind:
        auto.append(f"> **Type:** {kind}")
    auto += ["",
             "> [!warning]- ⛔ Auto-generated section",
             "> Everything outside the AUTO markers is yours and is kept. "
             "Dragging on the calendar is reverted. Hand-made sessions go "
             "in `Sessions/`.",
             ""]
    if targets or lecture:
        auto.append("> [!note]- 🔗 Links")
        if targets:
            auto.append("> - Course: " + " · ".join(f"[[{t}]]"
                                                    for t, _ in targets))
        if lecture:
            auto.append(f"> - Lecture notes: [[{lecture.stem}]]")
        elif targets:
            auto.append("> - _No dated lecture note for this day yet._")
        auto.append("")
    new_auto = "\n".join(auto)
    if path.exists():
        old = path.read_text(encoding="utf-8")
        head, _, tail = split_markers(old)
        # Surgical: keep head (incl. frontmatter) + tail verbatim.
        text = head + AUTO_START + "\n" + new_auto + "\n" + \
            AUTO_END + "\n" + tail
        text = maintain_annotated(text)
    else:
        text = "\n".join(fm + [AUTO_TAG.strip(), "", AUTO_START,
                               new_auto, AUTO_END, "", "## Notes", ""])
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    written.add(path)
    return bool(targets), bool(lecture)


def maintain_annotated(text):
    """Sync the derived `annotated:` frontmatter line with Notes content."""
    has_notes = bool(read_section(text))
    lines = text.split("\n")
    try:
        end = lines.index("---", 1)
    except ValueError:
        return text
    fm = [l for l in lines[1:end] if not l.startswith("annotated:")]
    if has_notes:
        try:
            at = next(i for i, l in enumerate(fm) if l.startswith("tags:"))
        except StopIteration:
            at = len(fm)
        fm.insert(at, "annotated: true")
    return "\n".join(["---", *fm, *lines[end:]])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--output", required=True,
                    help="Timetable/ folder inside the Obsidian vault")
    ap.add_argument("--url", default=os.environ.get("TIMETABLE_ICS_URL"),
                    help="ICS subscription URL (or TIMETABLE_ICS_URL env)")
    ap.add_argument("--days-past", type=int, default=14)
    ap.add_argument("--days-future", type=int, default=120)
    args = ap.parse_args(argv)
    if not args.url:
        sys.exit("error: provide --url or TIMETABLE_ICS_URL")
    out = Path(args.output).expanduser()
    vault = out.parent

    import urllib.request
    req = urllib.request.Request(args.url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")

    import icalendar
    import recurring_ical_events
    cal = icalendar.Calendar.from_ical(raw)
    start = datetime.now(LOCAL_TZ) - timedelta(days=args.days_past)
    end = datetime.now(LOCAL_TZ) + timedelta(days=args.days_future)
    events = recurring_ical_events.of(cal).between(start, end)

    make_writable(out)
    out.mkdir(parents=True, exist_ok=True)

    n, matched_course, matched_lecture, skipped = 0, 0, 0, 0
    written = set()
    for ev in events:
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            skipped += 1
            continue
        ds, de = ev.get("DTSTART"), ev.get("DTEND")
        if ds is None or de is None:
            skipped += 1
            continue
        s = ds.dt
        e = de.dt
        if not isinstance(s, datetime) or not isinstance(e, datetime):
            skipped += 1  # all-day / date-only entries
            continue
        if s.tzinfo is None:
            s = s.replace(tzinfo=LOCAL_TZ)
        else:
            s = s.astimezone(LOCAL_TZ)
        if e.tzinfo is None:
            e = e.replace(tzinfo=LOCAL_TZ)
        else:
            e = e.astimezone(LOCAL_TZ)
        summary = str(ev.get("SUMMARY", "Untitled")).strip()
        desc = str(ev.get("DESCRIPTION", ""))
        code = course_code(summary, desc)
        kind = kind_of(desc)
        room = str(ev.get("LOCATION", "")).strip()
        uid = str(ev.get("UID", ""))
        mc, ml = emit(out, vault, s, e, summary, code, kind, room, uid,
                      written)
        n += 1
        matched_course += mc
        matched_lecture += ml
    kept, dropped = sweep_stale(out, written)
    for p in kept:
        print(f"  kept stale annotated note: {p.name}")
    print(f"TIMETABLE: {n} instances "
          f"({matched_course} course-linked, {matched_lecture} lecture-linked, "
          f"{len(kept)} kept stale, {dropped} pruned, "
          f"{skipped} skipped)")


def sweep_stale(out, written):
    """Prune instances gone from the feed. Files with user content outside
    the markers are KEPT (never delete user writing) and reported."""
    kept, dropped = [], 0
    for p in sorted(out.glob("*.md")):
        if p in written:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        _, _, tail = split_markers(text)
        if tail.strip():
            kept.append(p)
        else:
            try:
                p.unlink()
                dropped += 1
            except OSError:
                pass
    return kept, dropped


if __name__ == "__main__":
    main()

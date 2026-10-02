#!/usr/bin/env python3
"""Vault -> AGENT-SUMMARY.md agent dashboard. Stdlib only, <1s.

Reads Daily/ checkboxes (same format contract as the Dataview dashboards),
Timetable/ frontmatter, and Courses/ hubs, and writes a compact,
pre-rendered dashboard for fetch-agents next to the query dashboards it
mirrors (Now/Today/Weekly View). Rewrites the file ONLY when the body
changed (ignoring the generated:/source-commit: stamp lines), so routine
runs don't dirty the git tree.

Usage:
  python3 agent-summary.py [--vault ~/Documents/OBSIDIAN/holanda] [--days 14]
"""

import argparse
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

CORE_TAGS = {"study", "project", "exam"}
TASK_RE = re.compile(r"^-\s+\[([ xX])\]\s*(.*)$")
TAG_RE = re.compile(r"#([A-Za-z][\w-]*)")
DUE_RE = re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})")
EST_RE = re.compile(r"\[est::\s*([^\]]+)\]")
NOTES_RE = re.compile(r"^## Notes\s*$", re.M)
FAR_FUTURE = date(2999, 1, 1)
HABIT_TAG = "study"
HABIT_WEEKS = 12


def parse_tasks(daily_dir):
    """(open_tasks, done_today_count). Each task: dict(text, tags, due, est, src)."""
    open_tasks, done = [], 0
    if not daily_dir.is_dir():
        return open_tasks, done
    for p in sorted(daily_dir.glob("*.md")):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            m = TASK_RE.match(line.strip())
            if not m or not m.group(2).strip():
                continue  # template placeholder / empty
            done_mark, body = m.group(1), m.group(2).strip()
            if done_mark.lower() == "x":
                done += 1
                continue
            due_m = DUE_RE.search(body)
            open_tasks.append({
                "text": body,
                "tags": set(TAG_RE.findall(body)),
                "due": datetime.strptime(due_m.group(1), "%Y-%m-%d").date()
                if due_m else None,
                "est": EST_RE.search(body).group(1)
                if EST_RE.search(body) else None,
                "src": p.stem,
            })
    return open_tasks, done


def fmt_task(t):
    return f"- [ ] {t['text']} — in [[Daily/{t['src']}]]"


def read_offset(vault):
    """uni_week_offset from Settings.md frontmatter (0 when absent)."""
    try:
        fm = (vault / "Settings.md").read_text(encoding="utf-8").split("---")[1]
        m = re.search(r"uni_week_offset:\s*(-?\d+)", fm)
        return int(m.group(1)) if m else 0
    except (OSError, IndexError, ValueError):
        return 0


def weekkey(d):
    iso = d.isocalendar()
    return (iso[0], iso[1])


def parse_timetable(tt_dir):
    """List of dicts: date, start, end, title, room, kind, codes, lecture, path."""
    out = []
    if not tt_dir.is_dir():
        return out
    for p in sorted(tt_dir.glob("*.md"), key=lambda p: p.name):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]
        get = lambda k: (re.search(rf"^{k}:\s*\"?([^\"\n]+)\"?", fm, re.M).group(1).strip()
                         if re.search(rf"^{k}:", fm, re.M) else "")
        try:
            day = datetime.strptime(get("date"), "%Y-%m-%d").date()
        except ValueError:
            continue
        codes = re.findall(r'"([^"]+)"', re.search(
            r"^codes:\s*\[(.*)\]", fm, re.M).group(1)) if re.search(
            r"^codes:", fm, re.M) else []
        out.append({"date": day, "start": get("startTime"),
                    "end": get("endTime"), "title": get("title") or p.stem,
                    "room": get("room"), "kind": get("kind"), "codes": codes,
                    "lecture": get("lecture"), "path": p.stem})
    return out


def notes_body(text):
    """Last ## Notes section body ('' when absent/empty)."""
    idx = [m.start() for m in NOTES_RE.finditer(text)]
    if not idx:
        return ""
    rest = text[idx[-1]:].split("\n", 1)[1] if "\n" in text[idx[-1]:] else ""
    lines = rest.splitlines()
    end = next((i for i, ln in enumerate(lines) if ln.startswith("# ")), -1)
    body = "\n".join(lines[:end] if end >= 0 else lines).strip()
    return "" if body in ("", "-") else body


def annotated_counts(tt_dir):
    """code -> number of Timetable notes with non-empty ## Notes."""
    counts = {}
    if not tt_dir.is_dir():
        return counts
    for p in tt_dir.glob("*.md"):
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---") or not notes_body(text):
            continue
        fm = text.split("---", 2)[1]
        m = re.search(r"^codes:\s*\[(.*)\]", fm, re.M)
        for code in re.findall(r'"([^"]+)"', m.group(1)) if m else []:
            counts[code] = counts.get(code, 0) + 1
    return counts


def git_head(vault):
    try:
        head = subprocess.run(["git", "-C", str(vault), "rev-parse", "--short",
                               "HEAD"], capture_output=True, text=True,
                              timeout=10)
        dirty = subprocess.run(["git", "-C", str(vault), "status",
                                "--porcelain"], capture_output=True, text=True,
                               timeout=10)
        if head.returncode != 0:
            return "unavailable"
        h = head.stdout.strip()
        return h + "+dirty" if dirty.stdout.strip() else h
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def section(lines, title, items, cap=15):
    lines.append(f"## {title}")
    lines.append("")
    if not items:
        lines.append("_None._")
    else:
        lines.extend(items[:cap])
        if len(items) > cap:
            lines.append(f"_…and {len(items) - cap} more._")
    lines.append("")


def habit_counts(daily_dir, tag=HABIT_TAG):
    """date -> checkbox lines carrying #tag (open or done — no distinction)."""
    counts = {}
    if not daily_dir.is_dir():
        return counts
    for p in daily_dir.glob("*.md"):
        try:
            day = datetime.strptime(p.stem, "%Y-%m-%d").date()
            text = p.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        n = 0
        for line in text.splitlines():
            m = TASK_RE.match(line.strip())
            if not m or not m.group(2).strip():
                continue
            if tag in TAG_RE.findall(m.group(2)):
                n += 1
        if n:
            counts[day] = counts.get(day, 0) + n
    return counts


def habit_grid(vault, today, weeks=HABIT_WEEKS, tag=HABIT_TAG):
    """GitHub-style grid: rows Mon–Sun, one column per week. Cells link
    their daily note (clicking an empty day creates it).

    The alias pipe MUST be escaped (`\\|`) — a bare `|` inside a table
    cell splits the row and destroys the grid. Emoji use VS16
    (black/white squares plus a VS16 suffix) so every cell renders at
    uniform emoji size.
    """
    counts = habit_counts(vault / "Daily", tag)
    monday = today - timedelta(days=today.weekday())
    first = monday - timedelta(weeks=weeks - 1)
    lines = ["---", 'Folders:\n  - "[[Now]]"',
             "tags: [agent-dashboard, autogenerated]",
             "cssclasses:", "  - habits-heatmap", "---", "",
             f"# Habits — #{tag} heatmap", "",
             "> Generated file — do not hand-edit. Regenerate with "
             "`python3 ~/Projects/CSE-vault-sync/agent-summary.py`.", "",
             f"Last {weeks} weeks. ⬜️ future · ⬛️ none · 🟨 1 · "
             f"🟩 2+ (open or done — overdue is on you).", "",
             "|  | " + " | ".join(
                 f"W{(first + timedelta(weeks=w)).isocalendar()[1]:02d}"
                 for w in range(weeks)) + " |",
             "|" + "---|" * (weeks + 1)]
    names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    for d in range(7):
        cells = []
        for w in range(weeks):
            day = first + timedelta(weeks=w, days=d)
            if day > today:
                cells.append("⬜️")
                continue
            n = counts.get(day, 0)
            emoji = "🟩" if n >= 2 else "🟨" if n == 1 else "⬛️"
            cells.append(f"[[Daily/{day.isoformat()}\\|{emoji}]]")
        lines.append(f"| {names[d]} | " + " | ".join(cells) + " |")
    lines.append("")
    return lines


def emit(path, lines, stamp):
    """Append stamp, compare-and-write ignoring stamp lines. Returns wrote?"""
    strip = lambda s: "\n".join(
        ln for ln in s.splitlines()
        if not (ln.startswith("generated:") or ln.startswith("source-commit:")))
    out = "\n".join(lines).rstrip() + "\n\n" + stamp
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    if strip(old) == strip(out):
        return False
    path.write_text(out, encoding="utf-8")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--vault", default=str(Path.home() / "Documents/OBSIDIAN/holanda"))
    ap.add_argument("--days", type=int, default=14,
                    help="upcoming-classes window in days (default 14)")
    args = ap.parse_args(argv)
    vault = Path(args.vault).expanduser()
    today = date.today()
    now_hm = datetime.now().strftime("%H:%M")

    tasks, done_n = parse_tasks(vault / "Daily")
    open_t = [t for t in tasks]
    is_core = lambda t: bool(t["tags"] & CORE_TAGS)

    def due_le(t, days):
        return t["due"] is not None and t["due"] <= today + timedelta(days=days)

    study = sorted([t for t in open_t if "study" in t["tags"] and due_le(t, 3)],
                   key=lambda t: t["due"])
    exams = sorted([t for t in open_t if "exam" in t["tags"] and due_le(t, 7)],
                   key=lambda t: t["due"])
    project = sorted([t for t in open_t if "project" in t["tags"]],
                     key=lambda t: t["due"] or FAR_FUTURE)[:3]
    life = sorted([t for t in open_t if not is_core(t) and due_le(t, 1)],
                  key=lambda t: t["due"])
    overdue = sorted([t for t in open_t if t["due"] and t["due"] < today],
                     key=lambda t: t["due"])
    due_today = sorted([t for t in open_t if t["due"] == today],
                       key=lambda t: (sorted(t["tags"])[0] if t["tags"] else "", t["text"]))
    nodate = [t for t in open_t if t["due"] is None]
    offset = read_offset(vault)
    ref_week = weekkey(today + timedelta(days=offset))
    week = sorted([t for t in open_t
                   if t["due"] and weekkey(t["due"] + timedelta(days=offset)) == ref_week],
                  key=lambda t: t["due"])

    classes = [c for c in parse_timetable(vault / "Timetable")
               if c["date"] >= today and c["date"] <= today + timedelta(days=args.days)]
    classes.sort(key=lambda c: (c["date"], c["start"]))
    today_cl = [c for c in classes if c["date"] == today]
    upcoming = [c for c in classes if c["date"] > today]

    def fmt_class(c):
        room = f" @{c['room']}" if c["room"] else ""
        codes = f" ({'/'.join(c['codes'])})" if c["codes"] else ""
        return (f"- {c['date'].isoformat()} {c['start']}–{c['end']} "
                f"{c['title']}{codes}{room} — [[Timetable/{c['path']}]]")

    hubs = sorted((vault / "Courses").glob("*.md")) if (vault / "Courses").is_dir() else []
    hubs = [h for h in hubs if not h.stem.endswith(" Notebook")]
    ann = annotated_counts(vault / "Timetable")
    course_lines = []
    for h in hubs:
        try:
            text = h.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = text.split("---", 2)[1] if text.startswith("---") else ""
        m = re.search(r"^code:\s*(\S+)", fm, re.M)
        code = m.group(1).strip() if m else ""
        week_n = sum(1 for c in classes
                     if c["date"] <= today + timedelta(days=7)
                     and code and code in c["codes"])
        own = "hub notes yes" if notes_body(text) else "hub notes empty"
        nb = f" · [[Courses/{h.stem} Notebook|📓]]" if (
            h.parent / f"{h.stem} Notebook.md").exists() else ""
        course_lines.append(
            f"- {code or h.stem} — {week_n} upcoming (7d) · "
            f"{ann.get(code, 0) if code else 0} annotated · {own} — "
            f"[[Courses/{h.stem}]]{nb}")

    L = []
    L.append("---")
    L.append('Folders:\n  - "[[Now]]"')
    L.append("tags: [agent-dashboard, autogenerated]")
    L.append("---")
    L.append("")
    L.append("# AGENT-SUMMARY — agent dashboard")
    L.append("")
    L.append("> Generated file — do not hand-edit. Regenerate with "
             "`python3 ~/Projects/CSE-vault-sync/agent-summary.py`.")
    L.append("")
    section(L, "📚 STUDY — urgent (due ≤ 72h)", [fmt_task(t) for t in study])
    section(L, "🎓 EXAMS — ≤ 7 days", [fmt_task(t) for t in exams])
    section(L, "🛠️ PROJECT — next", [fmt_task(t) for t in project])
    section(L, "🏠 LIFE — urgent (due ≤ 24h)", [fmt_task(t) for t in life])
    section(L, "🔴 Overdue", [fmt_task(t) for t in overdue])
    section(L, "📅 Due today", [fmt_task(t) for t in due_today])
    section(L, "📥 No due date", [fmt_task(t) for t in nodate])
    section(L, "🗓️ Due this week", [fmt_task(t) for t in week])
    section(L, "🏫 Today's classes", [fmt_class(c) for c in today_cl])
    section(L, f"⏭️ Upcoming classes (next {args.days}d)",
            [fmt_class(c) for c in upcoming], cap=25)
    section(L, "🎒 Courses", course_lines, cap=30)
    L.append(f"_Open tasks: {len(open_t)} · done checkboxes (all Daily files): "
             f"{done_n} · classes in window: {len(classes)}._")
    L.append("")

    stamp = (f"generated: {datetime.now().astimezone().isoformat(timespec='seconds')} "
             f"· as-of: {today.isoformat()} · source-commit: {git_head(vault)}\n")
    wrote = [name for name, ok in
             (("AGENT-SUMMARY.md", emit(vault / "AGENT-SUMMARY.md", L, stamp)),
              ("Habits.md", emit(vault / "Habits.md",
                                 habit_grid(vault, today), stamp))) if ok]
    detail = f"{len(open_t)} open tasks, {len(classes)} classes"
    if wrote:
        print(f"wrote {' + '.join(wrote)} ({detail})")
    else:
        print(f"up to date ({detail})")


if __name__ == "__main__":
    main()

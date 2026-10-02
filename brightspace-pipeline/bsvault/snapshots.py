"""Course snapshots: dropbox folders, news, personal grades.

Each fetch writes raw JSON (or a markdown digest for news) into the course
cache dir and never raises: a failed snapshot is logged and skipped so one
flaky endpoint can't sink the whole course sync.
"""

import json

from .config import LE_VER
from .htmlmd import html_to_md
from .utils import log, sanitize


def fetch_dropbox(api, cid, code, cdir, logfile=None):
    """Save dropbox folders + one JSON per folder into _assignments/."""
    try:
        boxes = api.get(f"/d2l/api/le/{LE_VER}/{cid}/dropbox/folders/")
        adir = cdir / "_assignments"
        adir.mkdir(exist_ok=True)
        if not boxes:
            return
        (adir / "dropbox.json").write_text(json.dumps(boxes, indent=2),
                                           encoding="utf-8")
        for box in boxes if isinstance(boxes, list) else []:
            (adir / f"{sanitize(box.get('Name', f'folder-{box.get('Id')}'))}.json"
             ).write_text(json.dumps(box, indent=2), encoding="utf-8")
    except Exception as ex:
        log(f"  assignments skipped {code}: {ex}", logfile)


def fetch_news(api, cid, code, course_name, cdir, logfile=None):
    """Save announcements as a markdown digest (_announcements.md)."""
    try:
        news = api.get(f"/d2l/api/le/{LE_VER}/{cid}/news/")
        if not news:
            return
        items = news if isinstance(news, list) else news.get("Items", [])
        lines = [f"# Announcements - {code} {course_name}"]
        for item in items if isinstance(items, list) else []:
            body = item.get("Body", {})
            text = body.get("Text", "") if isinstance(body, dict) else str(body)
            lines.append(
                f"\n## {item.get('Title', '')}\n*{item.get('StartDate', '')}*\n\n"
                f"{html_to_md(text)[:4000]}\n")
        (cdir / "_announcements.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception as ex:
        log(f"  news skipped {code}: {ex}", logfile)


def fetch_grades(api, cid, code, cdir, logfile=None):
    """Save personal grade values (_grades.json)."""
    try:
        grades = api.get(f"/d2l/api/le/{LE_VER}/{cid}/grades/values/myGradeValues/")
        if grades:
            (cdir / "_grades.json").write_text(json.dumps(grades, indent=2),
                                               encoding="utf-8")
    except Exception as ex:
        log(f"  grades skipped {code}: {ex}", logfile)

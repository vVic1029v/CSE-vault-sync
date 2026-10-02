"""Cache JSON -> vault markdown tables: grades and dropbox assignments.

Pure readers: '' when the snapshot is missing or empty, so callers can
simply skip that extra.
"""

import json
import re

from .config import AUTO_TAG
from .htmlmd import html_to_md
from .utils import label, short_date


def _grade_rows(data):
    items = data if isinstance(data, list) else data.get("Items", data.get("Values", []))
    if not isinstance(items, list):
        return []
    rows = []
    for grade in items:
        if not isinstance(grade, dict):
            continue
        name = grade.get("GradeObjectName") or grade.get("Name") or ""
        num = grade.get("PointsNumerator", grade.get("Points", ""))
        den = grade.get("PointsDenominator", grade.get("MaxPoints", ""))
        score = f"{num} / {den}" if den not in ("", None) else str(num)
        feedback = grade.get("Feedback", grade.get("Comments", ""))
        if isinstance(feedback, dict):
            feedback = feedback.get("Text", "")
        feedback = re.sub(r"\s+", " ",
                          html_to_md(feedback) if "<" in str(feedback)
                          else str(feedback))[:300]
        rows.append((str(name), str(score), feedback))
    return rows


def grades_md(path):
    """Render _grades.json as a markdown table ('' when empty)."""
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    rows = _grade_rows(data)
    if not rows:
        return ""
    out = [f"{AUTO_TAG}# Grades\n", "| Item | Score | Feedback |",
           "| --- | --- | --- |"]
    out += [f"| {label(n)} | {label(s)} | {label(f)} |" for n, s, f in rows]
    return "\n".join(out) + "\n"


def _dropbox_list(adir):
    if not adir.is_dir():
        return []
    boxes = []
    for f in sorted(adir.glob("*.json")):
        if f.name == "dropbox.json":
            continue
        try:
            boxes.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            continue
    if not boxes and (adir / "dropbox.json").exists():
        try:
            raw = json.loads((adir / "dropbox.json").read_text(encoding="utf-8"))
            boxes = raw if isinstance(raw, list) else []
        except Exception:
            pass
    return boxes


def assignments_md(adir):
    """Render _assignments/ as a markdown table ('' when empty)."""
    boxes = _dropbox_list(adir)
    if not boxes:
        return ""
    out = [f"{AUTO_TAG}# Assignments\n", "| Name | Due | Details |",
           "| --- | --- | --- |"]
    for box in boxes:
        if not isinstance(box, dict):
            continue
        name = box.get("Name", "")
        due = box.get("DueDate") or box.get("DueDateTime") or box.get("EndDate") or ""
        instr = box.get("CustomInstructions") or box.get("Instructions") or ""
        if isinstance(instr, dict):
            instr = instr.get("Text", "")
        instr = re.sub(r"\s+", " ",
                       html_to_md(instr) if "<" in str(instr)
                       else str(instr))[:400]
        out.append(f"| {label(name)} | {short_date(due)} | {label(instr)} |")
    return "\n".join(out) + "\n"

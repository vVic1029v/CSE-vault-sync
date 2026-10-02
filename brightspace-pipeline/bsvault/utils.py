"""Small pure utils: filenames, hashes, logging, labels.

No network, no Brightspace knowledge. Each function does one thing.
"""

import hashlib
import html as ihtml
import re
from datetime import datetime, timezone


def utcnow():
    """Current UTC time as `YYYY-MM-DDTHH:MM:SSZ`."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg, logfile=None):
    """Print a timestamped line; also append to logfile when given."""
    line = f"[{utcnow()}] {msg}"
    print(line, flush=True)
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def sanitize(name, maxlen=110):
    """Make a string safe as a filename (and wikilink target)."""
    name = ihtml.unescape(name or "untitled").strip()
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", name)
    name = re.sub(r"[\[\]^#|]", "-", name)  # wikilink-breakers
    name = re.sub(r"\s+", " ", name).strip(" .")
    # strip AGAIN after truncation: a cut mid-word must not leave trailing space/dot
    return (name[:maxlen].strip(" .") or "untitled")


def sha256_file(path):
    """Hex SHA-256 of a file, streamed in 1MB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def short_date(iso):
    """Trim an ISO timestamp to `YYYY-MM-DD`; '' on anything odd."""
    if not iso:
        return ""
    try:
        return str(iso)[:10]
    except Exception:
        return ""


def vrel(path, root):
    """Path relative to root, always with forward slashes."""
    return path.relative_to(root).as_posix()


def label(text):
    """Make a string safe inside a markdown table cell or link label."""
    s = re.sub(r"\s+", " ", (text or "").replace("|", "-")).strip()
    return s.replace("[", "(").replace("]", ")")

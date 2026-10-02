"""Decide what never leaves the sync cache.

Internal Brightspace quicklinks (/d2l/...) and javascript: links only work
inside Brightspace itself, so topics pointing at them become locked notes
instead of downloads.
"""


def is_dead_url_target(url):
    """True for empty, internal (/d2l/) or javascript: link targets."""
    u = (url or "").strip()
    return (not u) or u.startswith("/d2l/") or u.startswith("javascript:")

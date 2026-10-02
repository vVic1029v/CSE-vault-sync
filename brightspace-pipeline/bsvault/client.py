"""Thin wrapper over the Brightspace Valence API (read-only calls).

Session expiry surfaces as AuthExpiredError so the pipeline can fail fast
instead of syncing garbage.
"""

from .config import BASE, LP_VER
from .utils import log


class AuthExpiredError(RuntimeError):
    """The cookie jar no longer authenticates (HTTP 401/403)."""


class BrightspaceClient:
    """GET helper plus the two calls every run needs: whoami, enrollments."""

    def __init__(self, http_client, logfile=None):
        self.http = http_client
        self.logfile = logfile

    def log(self, msg):
        log(msg, self.logfile)

    def get(self, path, params=None, expect_json=True):
        """GET a Valence path; 404 -> None, 401/403 -> AuthExpiredError."""
        response = self.http.get(BASE + path, params=params,
                                 follow_redirects=True, timeout=60)
        self.log(f"GET {path} -> {response.status_code} ({len(response.content)}b)")
        if response.status_code in (401, 403):
            raise AuthExpiredError(f"auth expired on {path} ({response.status_code})")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        if not expect_json:
            return response
        try:
            return response.json()
        except Exception:
            return response

    def whoami(self):
        """Return the logged-in user's profile."""
        return self.get(f"/d2l/api/lp/{LP_VER}/users/whoami")

    def enrollments(self):
        """Return [{id, code, name, start, end}] for course offerings only."""
        data = self.get(f"/d2l/api/lp/{LP_VER}/enrollments/myenrollments/")
        items = data.get("Items", data) if isinstance(data, dict) else data
        courses = []
        for entry in items if isinstance(items, list) else []:
            org = entry.get("OrgUnit", {})
            if org.get("Type", {}).get("Name") == "Course Offering":
                courses.append({"id": org.get("Id"), "code": org.get("Code", ""),
                                "name": org.get("Name", ""),
                                "start": org.get("StartDate"),
                                "end": org.get("EndDate")})
        return courses

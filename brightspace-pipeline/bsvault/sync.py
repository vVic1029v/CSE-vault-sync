"""Sync one course: Valence content tree -> RAW cache + manifest (incremental).

Manifest-backed stable names + hash compare make re-runs cheap: unchanged
topics are skipped, renames/deletes don't reshuffle names. Children always
stay in API (= Brightspace) order — never sorted.
"""

import json
import os
from pathlib import Path

from . import snapshots
from .config import BASE, LE_VER
from .vault_filter import is_dead_url_target
from .htmlmd import html_to_md
from .utils import log, sanitize, sha256_file, vrel


class Syncer:
    """Per-run course syncer. new/skipped count fresh vs reused items."""

    def __init__(self, api, logfile=None):
        self.api = api
        self.logfile = logfile
        self.new = 0
        self.skipped = 0

    def log(self, msg):
        log(msg, self.logfile)

    # -- single-object helpers -------------------------------------------

    def structure(self, cid, mid):
        """Children of a module; [] on failure (logged, never fatal)."""
        try:
            data = self.api.get(
                f"/d2l/api/le/{LE_VER}/{cid}/content/modules/{mid}/structure/")
            return data if isinstance(data, list) else []
        except Exception as ex:
            self.log(f"  ! structure {mid} failed: {ex}")
            return []

    def full(self, cid, kind, oid):
        """Single-object GET (carries Description); None on failure."""
        try:
            return self.api.get(
                f"/d2l/api/le/{LE_VER}/{cid}/content/{kind}/{oid}")
        except Exception as ex:
            self.log(f"  ! full {kind}/{oid}: {ex}")
            return None

    def desc_of(self, obj):
        """Best readable text of a Description block (HTML preferred)."""
        desc = (obj or {}).get("Description") or {}
        html = desc.get("Html") or ""
        if html and "<" in html:
            try:
                return html_to_md(html).strip()
            except Exception:
                pass
        return (desc.get("Text") or "").strip()

    def claim(self, parent, stem, suffix, owner, manifest, taken=()):
        """Stable unique basename within parent for an owner key.

        Manifest-backed: a known owner reuses its previous name when the
        file still exists, so renames/deletes don't reshuffle names later.
        When the manifest entry was lost, an existing unclaimed directory
        is reclaimed instead of suffixed — but never one already taken by
        a sibling earlier in this walk (genuine duplicates still dedup).
        """
        taken = set(taken or ())
        prev = manifest.get(owner, {}).get("name")
        if prev and (parent / prev).exists() and prev not in taken:
            return prev
        cand, i = f"{stem}{suffix}", 2
        if (parent / cand).exists() and cand not in taken:
            return cand
        while (parent / cand).exists() or cand in taken:
            cand = f"{stem} ({i}){suffix}"
            i += 1
        return cand

    # -- file download ---------------------------------------------------

    def download_file(self, cid, tid, dest, entry):
        """Fetch a file topic; (ok, sha-or-status, content-type).

        Unchanged files (hash matches manifest) are left alone.
        """
        response = self.api.http.get(
            f"{BASE}/d2l/api/le/{LE_VER}/{cid}/content/topics/{tid}/file",
            params={"stream": "false"}, follow_redirects=True, timeout=120)
        ctype = response.headers.get("content-type", "")
        self.log(f"GET file topic {tid} -> {response.status_code} "
                 f"({len(response.content)}b) -> {dest.name}")
        if response.status_code in (401, 403, 404):
            return False, f"http-{response.status_code}", ctype
        response.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(response.content)
        digest = sha256_file(tmp)
        if dest.exists() and entry.get("sha256") == digest:
            tmp.unlink()
            return True, "unchanged", ctype
        tmp.rename(dest)
        return True, digest, ctype

    @staticmethod
    def looks_html(path):
        """True when a downloaded file smells like an HTML page."""
        try:
            head = path.read_bytes()[:2048].lower()
            return b"<html" in head or b"<!doctype html" in head or \
                (b"<p" in head and b"</p>" in head)
        except Exception:
            return False

    @staticmethod
    def size_str(path):
        """Human size for MOC file entries ('' when unreadable)."""
        try:
            size = path.stat().st_size
            return f"{size / 1048576:.1f} MB" if size > 1048576 \
                else f"{size // 1024} KB"
        except Exception:
            return ""

    # -- tree walk -------------------------------------------------------

    def sync_course(self, course, cdir, manifest):
        """Sync one course; return (new, skipped) counts."""
        cid, code = course["id"], course["code"]
        cdir.mkdir(parents=True, exist_ok=True)
        (cdir / "course-info.json").write_text(
            json.dumps(course, indent=2), encoding="utf-8")
        root = self.api.get(
            f"/d2l/api/le/{LE_VER}/{cid}/content/root/") or []
        (cdir / "_toc.json").write_text(
            json.dumps(root, indent=2)[:2000000], encoding="utf-8")
        self.new, self.skipped = 0, 0
        tree = []
        self._walk(cid, code, cdir, manifest, root, cdir, tree)
        (cdir / "moc.json").write_text(
            json.dumps({"root": tree}, indent=1)[:12000000], encoding="utf-8")
        self._prune_orphans(cdir, tree)
        snapshots.fetch_dropbox(self.api, cid, code, cdir, self.logfile)
        snapshots.fetch_news(self.api, cid, code, course.get("name", ""),
                             cdir, self.logfile)
        snapshots.fetch_grades(self.api, cid, code, cdir, self.logfile)
        self.log(f"Course done: {code} (+{self.new} new, {self.skipped} unchanged)")
        return self.new, self.skipped

    def _walk(self, cid, code, cdir, manifest, nodes, parent, out):
        # NOTE: nodes stay in API order == Brightspace order. Never sort.
        for node in nodes:
            raw_title = node.get("Title", "untitled") or "untitled"
            title = sanitize(raw_title)
            mid = node.get("Id")
            kids = node.get("Modules") or node.get("Topics")
            is_mod = (node.get("Type") == 0 and node.get("TopicType") is None) \
                or isinstance(kids, list)
            if is_mod and mid and node.get("TopicType") is None and not node.get("Url"):
                self._walk_module(cid, code, cdir, manifest, node, title,
                                  raw_title, parent, out)
                continue
            self._walk_topic(cid, cdir, manifest, node, title, raw_title, parent, out)

    def _walk_module(self, cid, code, cdir, manifest, node, title,
                     raw_title, parent, out):
        mid = node.get("Id")
        mkey = f"{cid}:mod:{mid}"
        mprev = manifest.get(mkey, {})
        last_modified = str(node.get("LastModifiedDate") or "")
        emb = node.get("Description") or {}
        if emb.get("Html") or emb.get("Text"):
            desc = self.desc_of(node)
            fresh = mprev.get("lastModified") == last_modified
        elif mprev.get("lastModified") == last_modified and mprev.get("desc") is not None:
            desc, fresh = mprev["desc"], True
            self.skipped += 1
        else:
            desc, fresh = self.desc_of(self.full(cid, "modules", mid)), False
        if not fresh or not mprev.get("desc"):
            manifest[mkey] = {"title": raw_title, "lastModified": last_modified,
                              "desc": desc, "name": mprev.get("name")}
        dirname = self.claim(parent, title, "", mkey, manifest,
                             taken=[e.get("name") for e in out])
        manifest[mkey]["name"] = dirname
        mdir = parent / dirname
        mdir.mkdir(parents=True, exist_ok=True)
        sub = []
        # structure() holds the children; embedded kids are fallback only
        self._walk(cid, code, cdir, manifest,
                   self.structure(cid, mid) or node.get("Modules")
                   or node.get("Topics") or [], mdir, sub)
        out.append({"kind": "module", "id": mid, "title": raw_title,
                    "name": dirname, "desc": desc, "children": sub})

    def _walk_topic(self, cid, cdir, manifest, node, title, raw_title, parent, out):
        tid = node.get("Id")
        if tid is None:
            self.log("  ! topic without id skipped")
            return
        url = node.get("Url", "") or ""
        if url and not url.startswith("/content/") and node.get("TopicType") != 1:
            self._walk_link_topic(cid, manifest, node, title, raw_title, url, out)
            return
        self._walk_file_topic(cid, cdir, manifest, node, title, raw_title,
                              parent, url, out)

    def _walk_link_topic(self, cid, manifest, node, title, raw_title, url, out):
        """Link topic: never downloaded; the note points at the URL."""
        tid = node.get("Id")
        mkey = f"{cid}:{tid}"
        entry = manifest.get(mkey, {})
        last_modified = str(node.get("LastModifiedDate") or "")
        # internal quicklinks only work inside Brightspace itself
        if is_dead_url_target(url):
            if entry.get("type") != "locked" or entry.get("lastModified") != last_modified:
                manifest[mkey] = {"title": raw_title, "type": "locked",
                                  "lastModified": last_modified,
                                  "reason": "internal Brightspace link",
                                  "desc": entry.get("desc", "")}
                self.new += 1
            else:
                self.skipped += 1
            out.append({"kind": "locked", "id": tid, "title": raw_title,
                        "desc": manifest[mkey].get("desc", ""),
                        "reason": "Only opens inside Brightspace."})
            return
        if entry.get("type") == "link" and entry.get("url") == url \
                and entry.get("lastModified") == last_modified \
                and entry.get("desc") is not None:
            self.skipped += 1
            desc = entry["desc"]
        else:
            desc = self.desc_of(self.full(cid, "topics", tid))
            manifest[mkey] = {"title": raw_title, "url": url, "type": "link",
                              "lastModified": last_modified, "desc": desc}
            self.new += 1
        out.append({"kind": "link", "id": tid, "title": raw_title,
                    "url": url, "desc": desc})

    def _walk_file_topic(self, cid, cdir, manifest, node, title, raw_title,
                         parent, url, out):
        tid = node.get("Id")
        mkey = f"{cid}:{tid}"
        entry = manifest.get(mkey, {})
        last_modified = str(node.get("LastModifiedDate") or "")
        if entry.get("lastModified") == last_modified and entry.get("sha256") \
                and entry.get("name") and (parent / entry["name"]).exists():
            self.skipped += 1
            desc = entry.get("desc")
            if desc is None:
                desc = self.desc_of(self.full(cid, "topics", tid))
                entry["desc"] = desc
                manifest[mkey] = entry
            dest = parent / entry["name"]
            is_html = entry.get("is_html")
            if is_html is None:
                is_html = dest.suffix.lower() == ".html" or self.looks_html(dest)
                entry["is_html"] = is_html
                manifest[mkey] = entry
        else:
            ext = os.path.splitext(url.split("?")[0])[1]
            if len(ext) > 6 or "/" in ext:
                ext = ""
            dest = parent / self.claim(parent, title, ext, mkey, manifest,
                                          taken=[e.get("name") for e in out
                                                 if "name" in e])
            try:
                ok, digest, ctype = self.download_file(cid, tid, dest, entry)
            except Exception as ex:
                self.log(f"  ! download {tid} {title}: {ex}")
                out.append({"kind": "locked", "id": tid, "title": raw_title,
                            "desc": "", "reason": f"Download failed ({ex})."})
                manifest[mkey] = {"title": raw_title, "type": "locked",
                                  "lastModified": last_modified,
                                  "reason": "download failed", "desc": ""}
                self.new += 1
                return
            if not ok:
                self.log(f"  ! topic {tid} {title}: {digest}")
                out.append({"kind": "locked", "id": tid, "title": raw_title,
                            "desc": "", "reason": f"Download failed ({digest})."})
                manifest[mkey] = {"title": raw_title, "type": "locked",
                                  "lastModified": last_modified,
                                  "reason": "download failed", "desc": ""}
                self.new += 1
                return
            if not ext and "text/html" in (ctype or ""):
                fixed = dest.with_name(dest.name + ".html")
                if dest.exists() and fixed.name != dest.name and not fixed.exists():
                    dest.rename(fixed)
                    dest = fixed
                elif fixed.exists() and fixed.name != dest.name:
                    dest.unlink(missing_ok=True)
                    dest = fixed
            if ok and digest == "unchanged":
                self.skipped += 1
                desc = entry.get("desc")
                if desc is None:
                    desc = self.desc_of(self.full(cid, "topics", tid))
            else:
                self.new += 1
                desc = self.desc_of(self.full(cid, "topics", tid))
            is_html = dest.suffix.lower() == ".html" or (
                not dest.suffix and self.looks_html(dest))
            manifest[mkey] = {"title": raw_title, "name": dest.name,
                              "path": vrel(dest, cdir),
                              "sha256": digest if digest != "unchanged"
                              else entry.get("sha256"),
                              "lastModified": last_modified, "url": url,
                              "desc": desc, "is_html": is_html,
                              "ctype": ctype if digest != "unchanged"
                              else entry.get("ctype", "")}
        rel = vrel(dest, cdir)
        if is_html:
            out.append({"kind": "page", "id": tid, "title": raw_title,
                        "name": dest.name, "path": rel, "desc": desc})
        else:
            out.append({"kind": "file", "id": tid, "title": raw_title,
                        "name": dest.name, "path": rel, "desc": desc,
                        "size": self.size_str(dest)})

    def _prune_orphans(self, cdir, tree):
        """Delete cache files no topic references anymore (renames/deletes)."""
        ref = set()

        def _collect(nodes):
            for t in nodes:
                if t.get("path"):
                    ref.add(t["path"])
                _collect(t.get("children", []))
        _collect(tree)
        for f in sorted(cdir.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(cdir)
            if rel.parts[0].startswith("_") or "_assignments" in rel.parts:
                continue
            if rel.name in ("course-info.json", "moc.json"):
                continue
            if rel.as_posix() in ref:
                continue
            try:
                f.unlink()
                self.log(f"  pruned orphan {rel}")
            except Exception:
                pass
        for d in sorted([p for p in cdir.rglob("*") if p.is_dir()], reverse=True):
            if d == cdir:
                continue
            try:
                if not any(d.iterdir()):
                    d.rmdir()
                    self.log(f"  pruned empty dir {d.relative_to(cdir)}")
            except Exception:
                pass

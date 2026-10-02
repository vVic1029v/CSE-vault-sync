"""Vault selftest: read-only health checks for a generated vault.

Five checks: no JSON/URL junk, wikilink-safe filenames, resolving
wikilinks, sane frontmatter, real PDFs. Returns (errors, warnings);
never writes anything.
"""

import re


def _readable_notes(vault):
    """Yield (path, text) for every note; record unreadable ones as errors."""
    notes, errors = [], []
    for note in vault.rglob("*.md"):
        try:
            notes.append((note, note.read_text(encoding="utf-8")))
        except Exception:
            errors.append(f"unreadable note: {note.relative_to(vault)}")
    return notes, errors


def check_no_junk(vault):
    """No .json/.url sidecars leaked into the vault.

    Hidden dirs (e.g. Obsidian's own .obsidian/) are skipped: they hold
    editor config, never pipeline output.
    """
    errors = []
    for bad in ("*.json", "*.url"):
        found = [p for p in vault.rglob(bad)
                 if not any(part.startswith(".") for part in p.parts)]
        if found:
            errors.append(f"{len(found)} {bad} files leaked into vault "
                          f"(e.g. {found[0].relative_to(vault)})")
    return errors


def check_filenames(vault):
    """Every filename must be wikilink-safe (no []^|#)."""
    return [f"wikilink-unsafe filename: {p.relative_to(vault)}"
            for p in vault.rglob("*")
            if any(ch in p.name for ch in "[]^|#")]


def _folders_targets(text):
    """[[targets]] of VirtFolder `Folders:` lines (list and string forms)."""
    targets = []
    in_list = False
    for line in text.split("\n"):
        stripped = line.strip()
        if re.match(r"^Folders:\s*$", stripped):
            in_list = True
            continue
        m = (re.match(r"^Folders:\s*\"?\[\[([^\]|#^]+)", stripped)
             or (in_list and re.match(r"^-\s*\"?\[\[([^\]|#^]+)", stripped)))
        if m:
            targets.append(m.group(1).strip())
            if not in_list or not stripped.startswith("-"):
                in_list = False
            continue
        in_list = False
    return targets


def check_wikilinks(notes, vault):
    """Every [[target]] resolves to a file; generated notes carry an up: link.

    `Folders:` parents that don't resolve locally are warnings (external
    parents are legal when this dir is embedded in a bigger vault, e.g.
    `--virt-root '! Index'`). An `up:` line mirroring such an external
    parent warns too. Links into vault-side `Courses/` hubs warn too (they
    resolve once embedded). Everything else errors.
    """
    errors, warnings = [], []
    link_re = re.compile(r"!?\[\[([^\]|#^]+)")
    broken = []
    for note, text in notes:
        rel = note.relative_to(vault).as_posix()
        if "auto-generated" in text[:600] and "up:" not in text[:600] \
                and rel != f"! {vault.name}.md":
            warnings.append(f"generated note without up: {rel}")
        folders = set(_folders_targets(text))
        in_folders = False
        for line in text.split("\n"):
            s = line.strip()
            if re.match(r"^Folders:\s*$", s):
                in_folders = True
                continue
            if in_folders and not re.match(r"^-\s*\"?\[\[", s):
                in_folders = False
            if in_folders or re.match(r"^Folders:\s*\"?\[\[", s):
                continue  # checked leniently below
            for match in link_re.finditer(line):
                target = match.group(1).strip()
                if not target or target.startswith(("http", "mailto:")):
                    continue
                candidates = [vault / target, vault / (target + ".md"),
                              note.parent / target,
                              note.parent / (target + ".md")]
                if any(c.exists() for c in candidates):
                    continue
                raw = target.split("|")[0].split("#")[0].strip()
                if (re.match(r"^up:\s*\[\[", s) and raw in folders) \
                        or raw.startswith("Courses/"):
                    warnings.append(f"external link: {rel} -> [[{target}]]")
                else:
                    broken.append(f"{rel} -> [[{target}]]")
        for target in sorted(folders):
            if not target or target.startswith(("http", "mailto:")):
                continue
            candidates = [vault / target, vault / (target + ".md"),
                          note.parent / target, note.parent / (target + ".md")]
            if not any(c.exists() for c in candidates):
                warnings.append(f"external VirtFolder parent: {rel} -> "
                                f"[[{target}]]")
    if broken:
        errors.append(f"{len(broken)} broken wikilinks:\n  "
                      + "\n  ".join(broken[:20]))
    return errors, warnings


def check_frontmatter(notes):
    """Frontmatter blocks must terminate."""
    errors = []
    for note, text in notes:
        if text.startswith("---") and "\n---" not in text[:1200]:
            errors.append(f"unterminated frontmatter: {note}")
    return errors


def check_pdfs(vault):
    """A sample of PDFs must start with %PDF- (or warn when there are none)."""
    errors, warnings = [], []
    pdfs = list(vault.rglob("*.pdf"))[:8]
    for pdf in pdfs:
        try:
            with open(pdf, "rb") as f:
                if f.read(5) != b"%PDF-":
                    errors.append(f"not a PDF: {pdf.relative_to(vault)}")
        except Exception as ex:
            errors.append(f"unreadable pdf {pdf.relative_to(vault)}: {ex}")
    if not pdfs:
        warnings.append("no PDFs in vault at all")
    return errors, warnings


def selftest(vault):
    """Compose all five checks. Returns (errors, warnings)."""
    from pathlib import Path
    vault = Path(vault)
    if not vault.exists():
        return ["vault dir missing"], []
    notes, errors = _readable_notes(vault)
    errors = list(errors)
    top = f"! {vault.name}.md"
    if not (vault / top).exists():
        errors.append(f"{top} missing")
    stale = vault / f"{vault.name}.md"
    if stale.exists():
        errors.append(f"legacy {stale.name} still present (rename to {top})")
    errors += check_no_junk(vault)
    errors += check_filenames(vault)
    link_errors, link_warnings = check_wikilinks(notes, vault)
    errors += link_errors
    errors += check_frontmatter(notes)
    pdf_errors, pdf_warnings = check_pdfs(vault)
    errors += pdf_errors
    return errors, link_warnings + pdf_warnings

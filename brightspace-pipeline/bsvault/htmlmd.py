"""HTML -> Markdown (BeautifulSoup only).

Two mutually recursive functions: inline() for in-flow content, block()
for structure. html_to_md() composes them over the document body.
"""

import re


def _inline_children(el):
    """Yield child nodes of el (or el itself when it has no children)."""
    return getattr(el, "children", [el])


def inline(el):
    """Render an element's inline content (links, bold, code, images...)."""
    from bs4 import NavigableString, Tag
    parts = []
    for node in _inline_children(el):
        if isinstance(node, NavigableString):
            parts.append(re.sub(r"\s+", " ", str(node)))
        elif isinstance(node, Tag):
            parts.append(_inline_tag(node))
    return "".join(parts)


def _inline_tag(node):
    """Render one inline tag."""
    name = node.name
    if name == "a":
        href = (node.get("href") or "").strip()
        text = inline(node).strip().replace("[", "(").replace("]", ")")
        return f"[{text}]({href})" if href and text else text or href
    if name in ("b", "strong"):
        return f"**{inline(node).strip()}**"
    if name in ("i", "em"):
        return f"_{inline(node).strip()}_"
    if name == "code":
        return f"`{inline(node).strip()}`"
    if name == "br":
        return "\n"
    if name == "img":
        return f"![{node.get('alt', '')}]({node.get('src', '')})"
    return inline(node)


def block(el, out):
    """Append one block-level element's markdown to out (list of lines)."""
    from bs4 import NavigableString, Tag
    if isinstance(el, NavigableString):
        text = re.sub(r"\s+", " ", str(el)).strip()
        if text:
            out.append(text)
        return
    if not isinstance(el, Tag):
        return
    name = el.name
    if name in ("h1", "h2", "h3", "h4"):
        out.append(f"{'#' * (int(name[1]) + 1)} {inline(el).strip()}")
    elif name == "p":
        text = inline(el).strip()
        if text:
            out.append(text)
    elif name in ("ul", "ol"):
        _block_list(el, out)
    elif name == "pre":
        out.append("```\n" + el.get_text() + "\n```")
    elif name == "table":
        _block_table(el, out)
    elif name == "blockquote":
        text = inline(el).strip()
        if text:
            out.extend("> " + line for line in text.splitlines())
    elif name == "hr":
        out.append("---")
    elif name in ("div", "section", "article", "body", "html", "span",
                  "header", "footer", "main", "li", "td", "th", "font"):
        for child in el.children:
            block(child, out)
    elif name == "a":
        text, href = inline(el).strip(), (el.get("href") or "").strip()
        if text or href:
            out.append(f"[{text}]({href})" if href and text else text or href)
    elif name == "img":
        out.append(f"![{el.get('alt', '')}]({el.get('src', '')})")
    elif name == "iframe":
        # ignore players/embeds as content, but keep a link to them
        src = (el.get("src") or "").strip()
        if src:
            out.append(f"[embedded content]({src})")
    # ignore: script/style (removed up front), buttons, inputs


def _block_list(el, out):
    """Render a ul/ol, recursing into nested lists with indentation."""
    for i, li in enumerate(el.find_all("li", recursive=False), 1):
        bullet = "-" if el.name == "ul" else f"{i}."
        chunks, nested = [], []
        for child in li.children:
            from bs4 import Tag
            (nested if isinstance(child, Tag) and child.name in ("ul", "ol")
             else chunks).append(child)
        out.append(f"{bullet} {inline(_wrap(chunks)).strip()}")
        for sub in nested:
            lines = []
            block(sub, lines)
            out.extend("  " + line for line in lines)


def _wrap(nodes):
    """Wrap loose nodes in a span so inline() can render them."""
    from bs4 import BeautifulSoup
    wrapper = BeautifulSoup("", "lxml").new_tag("span")
    for node in nodes:
        wrapper.append(node)
    return wrapper


def _block_table(el, out):
    """Render a table as a pipe table, padding short rows."""
    rows = []
    for tr in el.find_all("tr"):
        cells = [inline(td).strip() for td in tr.find_all(["th", "td"])]
        if any(cells):
            rows.append(cells)
    if not rows:
        return
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out.append("| " + " | ".join(rows[0]) + " |")
    out.append("| " + " | ".join(["---"] * width) + " |")
    for row in rows[1:]:
        out.append("| " + " | ".join(row) + " |")


def html_to_md(html_text):
    """Convert an HTML fragment to Markdown (scripts/styles dropped)."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text or "", "lxml")
    for tag in soup.find_all(["script", "style"]):
        tag.decompose()
    out = []
    for child in (soup.body or soup).children:
        block(child, out)
    md = "\n\n".join(line for line in (line.rstrip() for line in out) if line)
    return re.sub(r"\n{3,}", "\n\n", md).strip()

#!/usr/bin/env python3
"""Stamp a BUILT site directory with a deploy version, so every deploy fetches
a fresh set of files.

GitHub Pages serves everything with `cache-control: max-age=600`. After a
deploy a browser could pair a cached old js/materials.js with the new
index.html and crash. Appending `?v=VERSION` to every relative script,
stylesheet, module import and data fetch makes each deploy a new set of URLs.

Run in CI on the Pages artifact only; the committed sources stay unstamped.
Idempotent, and re-stampable with another version.

    python3 tools/stamp_site.py SITE_DIR VERSION
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

VERSION_OK = re.compile(r"[0-9a-zA-Z._-]+")
OLD = r"(?:\?v=[0-9a-zA-Z._-]*)?"
# src="js/app.js" / href="../css/site.css": relative .js/.css only
HTML_URL = re.compile(r"""((?:src|href)=["'](?![a-zA-Z][a-zA-Z0-9+.-]*:|//|/)[^"'?#]+\.(?:js|css))""" + OLD)
# import x from "./a.js", import "./a.js", export ... from "../a.js", import("./a.js")
JS_URL = re.compile(r"""(\b(?:from|import)\s*\(?\s*(["'])\.{1,2}/[^"'?]+\.js)""" + OLD + r"""\2""")
V_LINE = re.compile(r'^const V = "(?:\?v=[0-9a-zA-Z._-]*)?";$', re.M)


def stamp(site: Path, version: str) -> int:
    """Rewrite the files under `site`; returns the number of files changed."""
    if not VERSION_OK.fullmatch(version):
        raise ValueError(f"bad version {version!r}: use [0-9a-zA-Z._-]+")
    q = f"?v={version}"
    changed = 0

    def write(p: Path, old: str, new: str) -> None:
        nonlocal changed
        if new != old:
            p.write_text(new, encoding="utf-8")
            changed += 1

    for p in sorted(site.rglob("*.html")):
        if "vendor" in p.relative_to(site).parts:
            continue
        t = p.read_text(encoding="utf-8")
        write(p, t, HTML_URL.sub(lambda m: m.group(1) + q, t))
    for p in sorted(site.rglob("*.js")):
        rel = p.relative_to(site).parts
        if rel[0] not in ("js", "vendor") or "tests" in rel:
            continue
        t = p.read_text(encoding="utf-8")
        new = JS_URL.sub(lambda m: m.group(1) + q + m.group(2), t)
        if rel == ("js", "app.js"):
            if not V_LINE.search(new):
                raise LookupError('js/app.js has no `const V = "";` line to stamp')
            new = V_LINE.sub(f'const V = "{q}";', new)
        write(p, t, new)
    if not (site / "js" / "app.js").exists():
        raise LookupError(f"{site}/js/app.js not found")
    return changed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        n = stamp(Path(argv[1]), argv[2])
    except (ValueError, LookupError) as e:
        print(f"stamp_site: {e}", file=sys.stderr)
        return 1
    print(f"stamp_site: {n} files stamped with ?v={argv[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

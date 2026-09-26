"""Render the static pages the showcase serves from committed JSON.

    python3 tools/render_site.py [--data site/data] [--out site]

No tables, no network: everything this reads was produced by
tools/build_problems.py and committed. That is why `make site` runs it on
every build and the output is git-ignored -- it is derived, deterministic and
cheap, so checking it in would swamp diffs with generated markup.

Three kinds of page:

  site/material/<MAT>.html   one per material, 302 of them, including the 68
                             markers -- material in which no helpmate exists
  site/themes.html           every theme, linked to each problem showing it
  (index.html)               untouched; it keeps the SPA and its animated
                             front board, and only gains links into the above

Boards are drawn by the vendored cm-chessboard, and solutions step through the
{san, uci, fen} triples the JSON already carries, so these pages need no chess
logic of their own -- the same contract the SPA relies on.
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


# The statement lives in the repository rather than on the site: it is
# prose that belongs with the code and the data, not a generated page.
REPO = "https://github.com/osick/helpmate-tablebase"


def esc(value) -> str:
    """Every value that reaches HTML goes through here. `None` is empty."""
    return "" if value is None else html.escape(str(value), quote=True)


def page(title: str, body: str, depth: int = 0,
         description: str = "") -> str:
    """A complete document. `depth` is how many directories down it sits, so
    a material page can reach the shared css and the front page."""
    up = "../" * depth
    meta = (f'\n<meta name="description" content="{esc(description)}">'
            if description else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · Helpmate tablebases</title>{meta}
<link rel="stylesheet" href="{up}vendor/cm-chessboard/assets/chessboard.css">
<link rel="stylesheet" href="{up}css/site.css">
</head>
<body>
<header>
  <div class="brand">
    <a href="{up}index.html" class="title">Helpmate tablebases</a>
    <span class="tagline">Every solution to every position, precomputed.</span>
  </div>
  <nav aria-label="Screens">
    <a href="{up}index.html#/">About</a>
    <a href="{up}index.html#/deepest">Deepest</a>
    <a href="{up}index.html#/puzzles">Puzzles</a>
    <a href="{up}index.html#/materials">Materials</a>
    <a href="{up}themes.html">Themes</a>
  </nav>
</header>
<main>
{body}
</main>
<footer>
  <p class="disclaimer">These positions were enumerated, not composed. No
  authorship is claimed over them and a generated database anticipates
  nobody — a composer who independently arrives at one of these positions is
  unaffected. Where a position is an already published composition it is
  credited to its author; corrections are welcome.
  <a href="{REPO}/blob/main/docs/AUTHORSHIP.md">Authorship and what this
  corpus is for →</a></p>
</footer>
</body>
</html>
"""


def _quality_note(q: Optional[Dict]) -> str:
    """What is wrong with a problem, in words.

    Deliberately mirrors tools/published_problems.quality_note rather than
    importing it. That module does `import chess` at module scope, and the
    Pages workflow builds this site with node only -- no pip step, so
    python-chess is absent in CI. Importing it here would break the deploy.
    Keep the two wordings in step.

    Two other stdlib clones of this exact wording exist: tools/render_deepest.py
    (quality_note, around line 52) and tools/deepest_booklet.py (quality_note,
    around line 406). Update all three together."""
    if not q:
        return ""
    if not q.get("legal", True):
        return ("the diagram has no legal last move, so it cannot arise in "
                "a game")
    parts = []
    if q.get("check"):
        parts.append("the side to move is in check in the diagram")
    if q.get("capture_first"):
        parts.append("the solution begins with a capture")
    return "; ".join(parts)


def attribution_html(p: Dict) -> str:
    """Who published this problem, if anyone. Most problems are new positions
    with nothing to show here."""
    if not p.get("published"):
        return ""
    rows = []
    for rec in p["published"]:
        sources = "; ".join(esc(s) for s in rec.get("sources", []))
        rows.append(
            f"<li><strong>{esc(rec.get('author'))}</strong> — {sources}</li>")
    return (f'<div class="attribution"><p>Published as '
            f'{esc(p.get("published_by"))}</p><ul>{"".join(rows)}</ul></div>')


def problem_html(p: Dict, n: int) -> str:
    """One problem: a board, its solutions, its themes, its caveats.

    The plies ride along as JSON so the page's script can step the board
    without any chess logic -- it sets FENs it was handed."""
    themes = " ".join(
        f'<a class="theme" href="../themes.html#{esc(t)}">{esc(t)}</a>'
        for t in p.get("themes", []))
    solutions = "".join(
        f'<li class="solution">{" ".join(esc(ply["san"]) for ply in line)}</li>'
        for line in p.get("solutions", []))
    note = _quality_note(p.get("quality"))
    caveat = f'<p class="caveat">Note: {esc(note)}.</p>' if note else ""
    plies = json.dumps(p.get("solutions", []))
    duals = ("" if p.get("count", 1) == 1 else
             f'<p class="duals">Two solutions, with different first and last '
             f'moves ({esc(p.get("starts"))} starts, {esc(p.get("ends"))} '
             f'ends).</p>')
    return f"""<article class="problem" id="problem-{n}">
  <div class="board" data-fen="{esc(p["fen"])}" data-plies='{esc(plies)}'></div>
  <div class="detail">
    <h3>{esc(p["stipulation"])}</h3>
    <p class="fen mono">{esc(p["fen"])}</p>
    {duals}
    <ol class="solutions">{solutions}</ol>
    <p class="themes">{themes}</p>
    {caveat}
    {attribution_html(p)}
  </div>
</article>"""


def stipulation(dtm: Optional[int]) -> str:
    """`h#n` from a ply distance. Odd dtm means White to move: the .5 case."""
    if dtm is None:
        return "—"
    return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"


def _num(n) -> str:
    return "—" if n is None else f"{n:,}"


def stats_html(doc: Dict) -> str:
    s = doc["stats"]
    rows = [
        ("longest mate", stipulation(s["max_dtm"])),
        ("deepest unique", stipulation(s["deepest_unique_dtm"])),
        ("positions at that depth", _num(s["unique_at_depth"])),
        ("deepest dual", stipulation(s["deepest_dual_dtm"])),
        ("deepest strict dual", stipulation(s["strict_dual_dtm"])),
        ("positions with a helpmate", _num(s["solvable"])),
        ("with a unique solution", _num(s["unique"])),
        ("cells in the plane", _num(s["plane_size"])),
        ("on disk", _num(s["size_bytes"]) + " bytes"),
    ]
    cells = "".join(f"<div><dd>{esc(v)}</dd><dt>{esc(k)}</dt></div>" for k, v in
                    rows)
    return f'<dl class="numbers">{cells}</dl>'


def _section(title: str, problems: List[Dict], empty: str,
             offset: int = 0, note: str = "", depth_note: str = "") -> str:
    # `depth_note` frames the whole section (which depth these came from and
    # why), so it precedes the picker's note about how many were found. Both
    # belong under the heading: rendered above it they read as a trailing
    # remark on the previous section.
    note_html = "".join(f'<p class="note">{esc(n)}</p>'
                        for n in (depth_note, note) if n)
    if not problems:
        return (f"<section><h2>{esc(title)}</h2>{note_html}<p class=\"empty\">"
                f"{esc(empty)}</p></section>")
    # The articles need a wrapper of their own: the grid that lays them two
    # per row cannot sit on <section>, whose first child is the heading.
    body = "".join(problem_html(p, i + offset) for i, p in enumerate(problems,
                                                                      1))
    return (f"<section><h2>{esc(title)}</h2>{note_html}"
            f'<div class="problems">{body}</div></section>')


def _attribute_notes(doc: Dict):
    """Where each of `doc["notes"]` belongs.

    `pick()` (tools/problem_picker.py) emits at most one note per call, and
    only when it returned fewer than 3 problems -- so for a non-marker
    material the attribution is deterministic: the first note belongs to the
    unique section iff `len(doc["unique"]) < 3`, and the last belongs to the
    dual section iff `len(doc["duals"]) < 3`. Verified against all 302
    committed documents with zero violations.

    Returns (unique_note, dual_note, floating_notes) -- exactly one of the
    first two is non-empty, or `floating_notes` carries everything, never
    both. A marker material (no helpmate at all: `deepest_unique_dtm is
    None`) has exactly one note and no sections, so it always floats. A
    mismatch between the note count and the invariant above also falls back
    to floating everything together -- a wrong label is worse than an
    unlabelled one."""
    notes = doc.get("notes", [])
    if doc["stats"]["deepest_unique_dtm"] is None:
        return "", "", notes

    unique_short = len(doc["unique"]) < 3
    dual_short = len(doc["duals"]) < 3
    expected = int(unique_short) + int(dual_short)
    if len(notes) != expected:
        return "", "", notes

    idx = 0
    unique_note = ""
    dual_note = ""
    if unique_short:
        unique_note = notes[idx]
        idx += 1
    if dual_short:
        dual_note = notes[idx]
        idx += 1
    return unique_note, dual_note, []


def material_page(doc: Dict) -> str:
    s = doc["stats"]
    unique_note, dual_section_note, floating = _attribute_notes(doc)
    notes = "".join(f'<p class="note">{esc(n)}</p>' for n in floating)

    dual_title = "Deepest dual problems"
    if (s["strict_dual_dtm"] is not None and
            s["deepest_dual_dtm"] != s["strict_dual_dtm"]):
        dual_note = (f'Deepest dual with different first and last moves: '
                     f'{stipulation(s["strict_dual_dtm"])}. The deepest dual '
                     f'overall is {stipulation(s["deepest_dual_dtm"])}, where '
                     f'the two solutions share a first or a last move.')
    else:
        dual_note = ""

    considered = ""
    if doc.get("candidates_total", 0) > doc.get("candidates_considered", 0):
        considered = (f'<p class="note">Chosen from the first '
                      f'{_num(doc["candidates_considered"])} of '
                      f'{_num(doc["candidates_total"])} positions at this '
                      f'depth.</p>')

    body = f"""<div class="material">
  <p class="crumb"><a href="../index.html#/materials">← all materials</a></p>
  <h1>{esc(doc["material"])}</h1>
  <p class="lede">{esc(doc["pieces"])} pieces.</p>
  {stats_html(doc)}
  {notes}
  {_section("Deepest unique problems", doc["unique"],
            "No unique solution exists at any depth in this material.",
            note=unique_note)}
  {considered}
  {_section(dual_title, doc["duals"],
            "No position in this material has exactly two solutions "
            "differing in both their first and last move.", offset=10,
            note=dual_section_note, depth_note=dual_note)}
</div>
<script type="module" src="../js/static-board.js"></script>"""
    return page(doc["material"], body, depth=1,
                description=(f'The deepest helpmate problems in '
                             f'{doc["material"]}, with their solutions and '
                             f'themes.'))


ENGINE_THEME_ENTRIES = 33      # registry entries, including colour-specific
                               # variants -- see docs/USAGE.md ("Thirty-three
                               # registry entries cover twenty-eight themes")
ENGINE_THEMES = 28             # distinct theme names the engine can detect
GLOSSARY_THEMES = 295          # named in the Helpmate Analyzer glossary


def themes_page(themes: Dict[str, Dict], index: List[Dict]) -> str:
    """Every theme, and every problem showing it, across the whole corpus."""
    blocks = []
    for name in sorted(themes):
        entry = themes[name]
        n = len(entry["problems"])
        items = "".join(
            f'<li><a href="material/{esc(p["material"])}.html">'
            f'{esc(p["material"])}</a> · {esc(p["stipulation"])} '
            f'<span class="kind">{esc(p["kind"])}</span></li>'
            for p in entry["problems"])
        # Collapsed by default. Open, this page runs to tens of thousands of
        # pixels -- `pure` alone carries several hundred problems -- and the
        # theme names, which are what a reader is scanning for, are lost in
        # it. `theme-open.js` opens the right one when a problem page links
        # to `#<theme>`, and offers an "open all" so find-in-page still
        # reaches every entry.
        blocks.append(
            f'<details class="theme-block" id="{esc(name)}">'
            f'<summary><span class="theme-name">{esc(name)}</span>'
            f'<span class="count">{n} '
            f'{"problem" if n == 1 else "problems"}</span></summary>'
            f'<ul class="theme-problems">{items}</ul></details>')

    with_helpmate = sum(1 for r in index if r["has_helpmate"])
    # Three different numbers, deliberately not conflated: how many themes
    # this site's problems happen to exhibit, how many the engine's registry
    # can detect at all, and how many the glossary names in total.
    lede = (f'<p class="lede">The {len(themes)} themes below are the ones '
            f'that appear on the problems selected for this site, drawn from '
            f'{len(index)} materials ({with_helpmate} of which hold a '
            f'helpmate). The engine can detect {ENGINE_THEMES} themes '
            f'({ENGINE_THEME_ENTRIES} registry entries, some colour-specific) '
            f'directly from the tables; the Helpmate Analyzer glossary names '
            f'{GLOSSARY_THEMES} in all, so this list is short by design '
            f'rather than incomplete.</p>')

    # `theme-index`, not `themes`: a problem's own theme list is already
    # `<p class="themes">`, and one class meaning two different things is a
    # specificity trap waiting for whoever styles this next.
    toc = " ".join(f'<a href="#{esc(t)}">{esc(t)}</a>' for t in sorted(themes))
    body = (f'<div class="theme-index"><h1>Themes</h1>{lede}'
            f'<nav class="toc">{toc}</nav>'
            f'<p class="toggle-all"><button type="button" id="open-all">'
            f'Open all themes</button></p>'
            f'<div class="theme-blocks">{"".join(blocks)}</div></div>'
            f'<script type="module" src="js/theme-open.js"></script>')
    return page("Themes", body, depth=0,
                description=("Every theme the helpmate tablebases detect, and "
                             "the deepest problems showing each one."))


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser("render_site")
    ap.add_argument("--data", default="site/data")
    ap.add_argument("--out", default="site")
    a = ap.parse_args(argv)

    data, out = Path(a.data), Path(a.out)
    themes_file, index_file = data / "themes.json", data / "index.json"
    if not themes_file.exists() or not index_file.exists():
        print(f"error: {data} has no themes.json/index.json -- run "
              f"tools/build_problems.py first", file=sys.stderr)
        return 1

    (out / "material").mkdir(parents=True, exist_ok=True)
    written = 0
    for doc_path in sorted((data / "material").glob("*.json")):
        doc = json.loads(doc_path.read_text())
        (out / "material" / f'{doc["material"]}.html').write_text(material_page(doc))
        written += 1

    (out / "themes.html").write_text(
        themes_page(json.loads(themes_file.read_text()),
                    json.loads(index_file.read_text())))
    print(f"rendered {written} material pages and the theme index", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

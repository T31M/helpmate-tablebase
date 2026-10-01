"""Render docs/DEEPEST.json as a LaTeX booklet: docs/DEEPEST.tex.

A print companion to docs/DEEPEST.md. Same data, same diagrams, but laid out
as an A5 booklet with real chess diagrams (the `chessboard` package) and a
statistics chapter up front.

The booklet is scoped to every 3--6 man material class in which a mate can
exist, which is 875 of them. The corpus does not hold all 875 yet, so this is a
draft: the coverage table in the statistics chapter says exactly how much of
the target is in and what is still missing. Re-running it against a fuller
corpus is the only thing needed to grow the booklet.

    python3 tools/deepest_booklet.py --data docs/DEEPEST.json
    pdflatex -output-directory=... docs/DEEPEST.tex   (twice: index page refs)

Needs `chessboard.sty` -- TeX Live ships it in `texlive-games`.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations_with_replacement
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))

from deepest_lib import (  # noqa: E402
    helpman_url, hn, numbered, numbers, ordered, piece_counts, tex_escape,
)

CHAPTERS = {
    3: "Three men",
    4: "Four men",
    5: "Five men",
    6: "Six men",
}

OFFICERS = "QRBNP"


def multisets(n: int) -> int:
    """How many unordered selections of n officers there are, repeats allowed."""
    return len(list(combinations_with_replacement(OFFICERS, n)))


def possible_classes(pieces: int) -> int:
    """How many material classes exist with this many men on the board.

    Two kings are compulsory; the remaining men are split between the sides,
    each side's share an unordered multiset drawn from Q, R, B, N, P. White
    versus Black is *not* a symmetry here -- White mates, so KRPvkb and
    KBvkrp are different problems -- which is why both orders are counted.
    """
    spare = pieces - 2
    if spare < 0:
        return 0
    total = 0
    for w in range(spare + 1):
        b = spare - w
        total += multisets(w) * multisets(b)
    return total


def mateable_classes(pieces: int) -> int:
    """Of those, the ones that can hold a mate at all.

    A bare white king cannot deliver mate, so every class where White has
    nothing but the king is empty by construction -- there is no problem in
    it to show. Subtracting them turns the raw 715 six-man classes into the
    645 that can hold a problem. (README.md counts progress over all 715: the
    bare-king classes are published as marker tables and count as done there.)
    """
    if pieces < 3:
        return 0
    return possible_classes(pieces) - multisets(pieces - 2)


def statistics(rows: list[dict]) -> dict:
    gaps = [r["max_dtm"] - r["dtm"] for r in rows]
    by_pieces = Counter(r["pieces"] for r in rows)
    covered = {n: by_pieces.get(n, 0) for n in sorted(CHAPTERS)}
    return {
        "classes": len(rows),
        "covered": covered,
        "possible": sum(mateable_classes(n) for n in CHAPTERS),
        "combinatorial": sum(possible_classes(n) for n in CHAPTERS),
        "indexed": sum(r["plane_size"] or 0 for r in rows),
        "deepest": max(rows, key=lambda r: r["dtm"]),
        "widest": max(rows, key=lambda r: r["max_dtm"] - r["dtm"]),
        "gap_mean": mean(gaps),
        "gap_median": median(gaps),
        "gap_max": max(gaps),
        "saturated": sum(1 for r in rows if r["saturated_at_max"]),
        "singletons": sorted((r for r in rows if r["unique_at_depth"] == 1),
                             key=lambda r: (-r["dtm"], r["material"])),
        "few": sum(1 for r in rows if r["unique_at_depth"] <= 10),
        "depth_hist": Counter(r["dtm"] for r in rows),
        "gap_hist": Counter(gaps),
    }


def num(n: int) -> str:
    """A thousands-separated number LaTeX will not break across a line."""
    return f"{n:,}".replace(",", "\\,")


def bar_chart(hist: Counter, xlabel: str, ylabel: str, key) -> list[str]:
    coords = " ".join(f"({key(k)},{v})" for k, v in sorted(hist.items()))
    top = max(hist.values())
    return [
        r"\begin{center}",
        r"\begin{tikzpicture}",
        r"\begin{axis}[",
        r"  width=0.95\linewidth, height=45mm,",
        r"  ybar, bar width=5pt,",
        rf"  xlabel={{{xlabel}}}, ylabel={{{ylabel}}},",
        r"  ylabel near ticks, xlabel near ticks,",
        rf"  ymin=0, ymax={int(top * 1.15) + 1},",
        r"  tick label style={font=\scriptsize},",
        r"  label style={font=\scriptsize},",
        r"  axis lines=left, enlarge x limits=0.06,",
        r"]",
        rf"\addplot[fill=black!62,draw=none] coordinates {{{coords}}};",
        r"\end{axis}",
        r"\end{tikzpicture}",
        r"\end{center}",
    ]


PREAMBLE = r"""\documentclass[10pt,twoside,openany]{book}

\usepackage[a5paper,inner=18mm,outer=14mm,top=16mm,bottom=18mm]{geometry}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage{microtype}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{xcolor}
\usepackage{pgfplots}
\pgfplotsset{compat=1.16}
\usepackage{chessboard}
\usepackage[explicit]{titlesec}
\usepackage{fancyhdr}
\usepackage[hidelinks]{hyperref}

\setchessboard{
  boardfontsize=12pt,
  labelfontsize=5pt,
  showmover=false,
  borderwidth=0.15em,
}

\titleformat{\chapter}[display]{\normalfont\huge\bfseries}{}{0pt}{#1}
\titlespacing*{\chapter}{0pt}{0pt}{1.2\baselineskip}
\titleformat{\section}{\normalfont\large\bfseries}{}{0pt}{#1}
\titlespacing*{\section}{0pt}{1.4\baselineskip}{0.3\baselineskip}

\raggedbottom
\setlength{\parindent}{0pt}
\setlength{\parskip}{0.5\baselineskip}
\setcounter{tocdepth}{0}
\setcounter{secnumdepth}{0}

\pagestyle{fancy}
\fancyhf{}
\fancyhead[LE]{\footnotesize\itshape\leftmark}
\fancyhead[RO]{\footnotesize\itshape The deepest sound helpmates}
\fancyfoot[C]{\footnotesize\thepage}
\renewcommand{\headrulewidth}{0.2pt}

% One showcased position: diagram left, facts right, solution underneath.
% The whole entry sits in one minipage, so a board never splits away from its
% caption across a page break.
%   #1 material   #2 anchor    #3 FEN           #4 stipulation
%   #5 facts      #6 solution  #7 analyser URL  #8 material count
\newsavebox{\hmboard}
\newlength{\hmfactswidth}
\newcommand{\hmentry}[9]{%
  \par\addvspace{1.2\baselineskip}%
  \phantomsection\label{hm:#2}%
  % Set the board first and measure it, so the stipulation and material count
  % align with the board's own edges rather than with an arbitrary column, and
  % so the facts take whatever width is left over at any board font size.
  \sbox{\hmboard}{\chessboard[setfen={#3}]}%
  \setlength{\hmfactswidth}{\linewidth}%
  \addtolength{\hmfactswidth}{-\wd\hmboard}%
  \addtolength{\hmfactswidth}{-2em}%
  \noindent\begin{minipage}{\linewidth}%
    {\large\bfseries #1}\hfill{\small\href{#7}{solve\,$\nearrow$}}\par\addvspace{0.4\baselineskip}%
    % \vspace{0pt} makes [t] align on the minipage's top rather than on the
    % board's baseline, which chessboard puts under the bottom rank.
    \begin{minipage}[t]{\wd\hmboard}%
      \vspace{0pt}%
      \usebox{\hmboard}%
      \par\addvspace{0.2\baselineskip}%
      {\footnotesize\textbf{#4}\hfill #8}%
    \end{minipage}\hfill
    \begin{minipage}[t]{\hmfactswidth}%
      \vspace{0pt}%
      \footnotesize\raggedright #5%
    \end{minipage}%
    \par\addvspace{0.5\baselineskip}%
    {\footnotesize\raggedright\textit{Solution:}\ #6\par}%
    \addvspace{0.15\baselineskip}%
    {\footnotesize\raggedright\textit{Themes:}\ #9\par}%
  \end{minipage}%
  \par
}
"""


def front_matter(s: dict) -> list[str]:
    return [
        r"\begin{document}",
        r"\frontmatter",
        r"\begin{titlepage}",
        r"\centering",
        r"\vspace*{2cm}",
        r"{\Huge\bfseries The Deepest\\[0.3em] Sound Helpmates\par}",
        r"\vspace{1.2cm}",
        r"{\large One position per material class:\\",
        r"the longest helpmate that still has a single solution\par}",
        r"\vspace{2cm}",
        rf"{{\large\itshape Draft --- {s['classes']} of {num(s['possible'])} "
        r"material classes\par}",
        r"\vspace{0.4cm}",
        r"{\large All 3 to 6 man endings\par}",
        r"\vfill",
        r"{\small Generated from the helpmate tablebase corpus.\\",
        r"Every diagram, depth and solution in this booklet is machine-derived;",
        r"nothing is hand-written.\par}",
        r"\vspace{1cm}",
        r"\end{titlepage}",
        "",
        r"\chapter*{How to read this booklet}",
        r"\markboth{How to read this booklet}{}",
        r"\addcontentsline{toc}{chapter}{How to read this booklet}",
        "",
        r"A \emph{helpmate} is a chess problem in which both sides cooperate:",
        r"Black moves first and helps White deliver mate. \textbf{h\#n} means",
        r"mate on White's \(n\)th move. \textbf{h\#n.5} is the half-move case:",
        r"White is to move, so the solution opens \(1\ldots\) and needs one",
        r"extra half-move.",
        "",
        r"Under every diagram stands the stipulation and the material count,",
        r"\emph{white men} + \emph{black men}, in the usual problemist's form.",
        r"The line below the solution is the position's FEN, and it is a link:",
        r"it opens the position in the Helpmate Analyzer at",
        r"\texttt{helpman.komtera.lt}, already set to the right stipulation,",
        r"ready to solve and to analyse for thematic content.",
        "",
        r"\section*{Why the deepest problem is not the longest one}",
        "",
        r"In problem chess, uniqueness is the quality criterion. A second",
        r"solution is a \emph{dual}, and a composition with a dual is unsound.",
        r"So the position worth showing in a material class is not its longest",
        r"helpmate --- it is the longest one that still has exactly one",
        r"solution.",
        "",
        r"Those are never the same position. In all",
        rf"{s['classes']} classes collected here the deepest sound problem is",
        r"shallower than the class maximum, on average",
        rf"{s['gap_mean']:.1f} plies shallower and at worst {s['gap_max']}.",
        rf"The reason is in the data: in {s['saturated']} of {s['classes']}",
        r"classes \emph{every} position at maximum depth has a saturated",
        r"solution count of 255 or more. The longest helpmates have hundreds",
        r"of ways to reach mate, which is exactly what disqualifies them as",
        r"compositions.",
        "",
        r"\section*{Where the numbers come from}",
        "",
        r"Depths and position counts are exact. They are read from each",
        r"table's \texttt{uniqueness} histogram, which maps depth to solution",
        r"count to number of positions, so ``the deepest depth holding a",
        r"unique solution'' and ``how many such positions exist'' are both",
        r"lookups, not samples. Each FEN is verified by probing the table",
        r"before it is used, and each solution is the solver's own output.",
        "",
        r"\tableofcontents",
        r"\mainmatter",
        "",
    ]


def stats_chapter(rows: list[dict], s: dict) -> list[str]:
    L = [
        r"\chapter{The corpus in numbers}",
        r"\markboth{The corpus in numbers}{}",
        "",
        rf"This draft covers {s['classes']} material classes holding",
        rf"{num(s['indexed'])} indexed positions. The deepest sound problem in",
        rf"the whole corpus is \textbf{{{tex_escape(hn(s['deepest']['dtm']))}}}",
        rf"in {s['deepest']['material']}",
        rf"(page~\pageref{{hm:{s['deepest']['material']}}}).",
        "",
        r"\section{Coverage}",
        "",
        r"The target is every material class from three to six men in which a",
        r"mate can exist at all. Both orders count separately --- White mates,",
        r"so KRPvkb and KBvkrp are different problems --- which gives",
        rf"{num(s['combinatorial'])} classes on paper. Of those,",
        rf"{num(s['combinatorial'] - s['possible'])} have White with nothing but",
        r"a bare king and cannot hold a mate under any circumstances, leaving",
        rf"the {num(s['possible'])} counted here.",
        "",
        r"\begin{center}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"men & in this draft & possible & coverage \\",
        r"\midrule",
    ]
    for n in sorted(CHAPTERS):
        have, poss = s["covered"].get(n, 0), mateable_classes(n)
        L.append(rf"{n} & {have} & {num(poss)} & {100 * have / poss:.1f}\% \\")
    L += [
        r"\midrule",
        rf"total & {s['classes']} & {num(s['possible'])} & "
        rf"{100 * s['classes'] / s['possible']:.1f}\% \\",
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{center}",
        "",
        r"The six-man row is what makes this a draft: those tables are the",
        r"expensive ones and only a handful have been generated so far.",
        r"The three-, four- and five-man rows fall a little short of their own",
        r"totals for a different reason. A class can have a complete table and",
        r"still contribute nothing here --- either no mate exists in it at all,",
        r"or no depth in it holds a position with a single solution. Such a",
        r"class has no sound problem to show, so it has no page.",
        "",
        r"\section{How deep a sound problem gets}",
        "",
        rf"Distribution of the deepest sound depth across all {s['classes']}",
        r"classes.",
    ]
    L += bar_chart(s["depth_hist"], "deepest sound depth (h\\#n)",
                   "classes", lambda d: d / 2)
    L += [
        "",
        r"\section{The gap to the class maximum}",
        "",
        r"How much depth uniqueness costs: the class's longest helpmate minus",
        r"its deepest sound one, in plies. It is never zero.",
    ]
    L += bar_chart(s["gap_hist"], "gap (plies)", "classes", lambda g: g)
    L += [
        "",
        rf"Mean {s['gap_mean']:.1f} plies, median {s['gap_median']:.0f},",
        rf"worst {s['gap_max']} --- {s['widest']['material']}, which runs to",
        rf"{tex_escape(hn(s['widest']['max_dtm']))} but whose deepest sound",
        rf"problem is only {tex_escape(hn(s['widest']['dtm']))}",
        rf"(page~\pageref{{hm:{s['widest']['material']}}}).",
        "",
        r"\section{The ten deepest}",
        "",
        r"\begin{center}",
        r"\begin{tabular}{lrrrr}",
        r"\toprule",
        r"material & sound & class max & gap & positions \\",
        r"\midrule",
    ]
    for r in sorted(rows, key=lambda r: (-r["dtm"], r["material"]))[:10]:
        L.append(
            rf"{r['material']} & {tex_escape(hn(r['dtm']))} & "
            rf"{tex_escape(hn(r['max_dtm']))} & "
            rf"{r['max_dtm'] - r['dtm']} & {num(r['unique_at_depth'])} \\"
        )
    L += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{center}",
        "",
        r"\section{Rarity}",
        "",
        r"At its deepest sound depth a class may hold a single position and",
        rf"nothing else. {len(s['singletons'])} classes are like that, and",
        rf"{s['few']} hold ten or fewer. Those are the positions with no",
        r"margin at all: change one man and the problem is gone.",
        "",
        r"\begin{center}",
        r"\begin{tabular}{llll}",
        r"\toprule",
        r"\multicolumn{4}{c}{classes with exactly one position at their "
        r"deepest sound depth} \\",
        r"\midrule",
    ]
    names = [rf"{r['material']}~{tex_escape(hn(r['dtm']))}"
             for r in s["singletons"]]
    for i in range(0, len(names), 4):
        row = names[i:i + 4] + [""] * (4 - len(names[i:i + 4]))
        L.append(" & ".join(row) + r" \\")
    L += [
        r"\bottomrule",
        r"\end{tabular}",
        r"\end{center}",
        "",
    ]
    return L


def quality_note(q: dict | None) -> str:
    """What is wrong with a position as a problem, or empty.

    Two other stdlib clones of this exact wording exist: tools/render_site.py
    (_quality_note) and tools/render_deepest.py (quality_note, around line
    52). Update all three together."""
    if not q:
        return ""
    if not q.get("legal", True):
        return "the diagram has no legal last move, so it cannot arise in a game"
    parts = []
    if q.get("check"):
        parts.append("the side to move is in check in the diagram")
    if q.get("capture_first"):
        parts.append("the solution begins with a capture")
    return "; ".join(parts)


def note_tex(q: dict | None) -> str:
    n = quality_note(q)
    return rf"\\[0.3em]\textit{{Note:}} {tex_escape(n)}." if n else ""


def published_tex(pubs: list[dict]) -> str:
    parts = []
    for p in pubs:
        src = "; ".join(p.get("sources") or []) or "source unknown"
        stip = f", as {p['stipulation']}" if p.get("stipulation") else ""
        parts.append(tex_escape(f"{p['author']} -- {src}{stip} ({p['id']})"))
    return r"\\[0.3em]\textit{Published:} " + "; ".join(parts)


def facts(r: dict) -> str:
    """The right-hand column of an entry: what the numbers say about it."""
    g = r["max_dtm"] - r["dtm"]
    sat = (" Every position at that depth has a saturated solution count "
           "(255 or more)." if r["saturated_at_max"] else "")
    plural = "s" if r["unique_at_depth"] != 1 else ""
    of_total = (rf" of the {num(r['plane_size'])} indexed"
                if r.get("plane_size") else "")
    return (
        rf"\textbf{{{tex_escape(hn(r['dtm']))}}}, unique solution.\\[0.3em]"
        rf"The class runs to {tex_escape(hn(r['max_dtm']))}, so the deepest "
        rf"sound problem is {g}~pl{'y' if g == 1 else 'ies'} shallower.{sat}"
        rf"\\[0.3em]"
        rf"{num(r['unique_at_depth'])} position{plural}{of_total} "
        rf"{'have' if plural else 'has'} a unique solution at "
        rf"{tex_escape(hn(r['dtm']))}."
        + (published_tex(r["published"]) if r.get("published") else "")
        + note_tex(r.get("quality"))
    )


def alternative_entry(r: dict, n: int) -> str:
    """The unpublished sibling of a published problem, as its own entry."""
    a = r["alternative"]
    w, b = piece_counts(a["fen"])
    themes = a.get("themes") or []
    facts_b = (rf"\textbf{{{tex_escape(hn(r['dtm']))}}}, unique solution.\\[0.3em]"
               rf"Same material and stipulation as No.~{n}, which is published; "
               rf"this position is not in the published database, under any mirroring."
               + note_tex(a.get("quality")))
    return "\\hmentry{%s}{%s}{%s}{%s}{%s}{%s}{%s}{%s}{%s}" % (
        rf"No.~{n}b\quad {tex_escape(r['material'])}",
        f"{r['material']}-b",
        a["fen"],
        tex_escape(hn(r["dtm"])),
        facts_b,
        tex_escape(numbered(a["solution"], r["dtm"])),
        helpman_url(a["fen"], r["dtm"]),
        f"{w} + {b}",
        tex_escape(", ".join(themes)) if themes else r"\textit{none detected}",
    )


def entry(r: dict, n: int) -> str:
    w, b = piece_counts(r["fen"])
    themes = r.get("themes") or []
    return "\\hmentry{%s}{%s}{%s}{%s}{%s}{%s}{%s}{%s}{%s}" % (
        rf"No.~{n}\quad {tex_escape(r['material'])}",
        r["material"],
        r["fen"],
        tex_escape(hn(r["dtm"])),
        facts(r),
        tex_escape(numbered(r["solution"], r["dtm"])),
        helpman_url(r["fen"], r["dtm"]),
        f"{w} + {b}",
        tex_escape(", ".join(themes)) if themes else r"\textit{none detected}",
    )


def index_appendix(rows: list[dict]) -> list[str]:
    L = [
        r"\appendix",
        r"\chapter{Index of material classes}",
        r"\markboth{Index of material classes}{}",
        "",
        r"Sorted by how deep a sound problem gets. \emph{class max} is the",
        r"longest helpmate in that material at any solution count.",
        "",
        r"{\footnotesize",
        r"\begin{longtable}{lrrrrlr}",
        r"\toprule",
        r"material & men & sound & class max & gap & published by & page \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"material & men & sound & class max & gap & published by & page \\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]
    for r in sorted(rows, key=lambda r: (-r["dtm"], r["material"])):
        L.append(
            rf"{r['material']} & {r['pieces']} & "
            rf"\textbf{{{tex_escape(hn(r['dtm']))}}} & "
            rf"{tex_escape(hn(r['max_dtm']))} & {r['max_dtm'] - r['dtm']} & "
            rf"{tex_escape(r.get('published_by', ''))} & "
            rf"\pageref{{hm:{r['material']}}} \\"
        )
    L += [r"\end{longtable}", r"}", ""]
    return L


def build(rows: list[dict]) -> str:
    s = statistics(rows)
    L = [
        "% docs/DEEPEST.tex -- generated by tools/deepest_booklet.py.",
        "% Do not edit: regenerate from docs/DEEPEST.json instead.",
        "% Build: pdflatex DEEPEST.tex (twice -- the index carries page refs).",
        "% Needs chessboard.sty; TeX Live ships it in texlive-games.",
        "",
        PREAMBLE,
    ]
    L += front_matter(s)
    L += stats_chapter(rows, s)
    nums = numbers(rows)

    for n in sorted(CHAPTERS):
        group = [r for r in ordered(rows) if r["pieces"] == n]
        if not group:
            continue
        L += [
            rf"\chapter{{{CHAPTERS[n]}}}",
            rf"\markboth{{{CHAPTERS[n]}}}{{}}",
            "",
            rf"{len(group)} of the {num(mateable_classes(n))} material classes",
            rf"with {n} men that can hold a mate, deepest sound problem first.",
            "",
        ]
        for r in group:
            L.append(entry(r, nums[r["material"]]))
            if r.get("alternative"):
                L.append(alternative_entry(r, nums[r["material"]]))
        L.append("")

    L += index_appendix(rows)
    L.append(r"\end{document}")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", default="docs/DEEPEST.json")
    ap.add_argument("--out", default="docs/DEEPEST.tex")
    a = ap.parse_args()
    rows = json.loads(Path(a.data).read_text())
    Path(a.out).write_text(build(rows))
    print(f"wrote {a.out}: {len(rows)} entries")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

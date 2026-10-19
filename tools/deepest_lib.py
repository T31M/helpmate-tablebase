"""Shared presentation for the DEEPEST showcase: diagrams, links, notation.

Both renderers -- `render_deepest.py` (markdown) and `deepest_booklet.py`
(LaTeX) -- read the same `docs/DEEPEST.json` and must present the same
position the same way, so everything that turns a row into something a reader
sees lives here.
"""
from __future__ import annotations

from pathlib import Path

# Popeye's diagram is 37 columns: a rank digit, eight four-column cells, and
# the rank digit again. Every line of a diagram is padded to this.
BOARD_WIDTH = 37

# Problem-chess piece letters. The knight is S (Springer) -- N is the German
# Nachtreiter, and the whole helpmate literature, Popeye included, writes S.
LETTER = {"K": "K", "Q": "Q", "R": "R", "B": "B", "N": "S", "P": "P"}

FILES = "abcdefgh"


def hn(dtm: int) -> str:
    """`h#n` from a ply distance. Odd dtm means White to move: the .5 case."""
    return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"


def plies(stipulation: str) -> int:
    """Inverse of `hn`: `h#8.5` -> 17."""
    body = stipulation[2:]
    whole, _, half = body.partition(".")
    return int(whole) * 2 + (1 if half else 0)


def moves_param(dtm: int) -> str:
    """The move count as a stipulation writes it: `13`, or `8.5`."""
    return str(dtm // 2) if dtm % 2 == 0 else f"{dtm // 2}.5"


def squares(fen: str):
    """Yield (rank_index_from_top, file_index, piece_char) for every man."""
    for r, rank in enumerate(fen.split()[0].split("/")):
        f = 0
        for ch in rank:
            if ch.isdigit():
                f += int(ch)
            else:
                yield r, f, ch
                f += 1


def piece_counts(fen: str) -> tuple[int, int]:
    """(white men, black men) -- the `2 + 3` under a diagram."""
    men = [p for _, _, p in squares(fen)]
    return sum(p.isupper() for p in men), sum(p.islower() for p in men)


def board(fen: str) -> str:
    """The board alone, in Popeye's ASCII diagram format.

    Black men carry a leading `-`, which is how Popeye distinguishes colour
    without relying on case -- it survives being read aloud, quoted in plain
    text, or pasted into a mail client that helpfully capitalises things.
    """
    grid = [[" ."] * 8 for _ in range(8)]
    for r, f, ch in squares(fen):
        letter = LETTER[ch.upper()]
        grid[r][f] = f" {letter}" if ch.isupper() else f"-{letter}"

    border = "+" + "".join(f"---{f}" for f in FILES) + "---+"
    inner = "|" + " " * (BOARD_WIDTH - 2) + "|"

    out = [border]
    for r in range(8):
        rank = 8 - r
        out.append(inner)
        out.append(f"{rank}" + "".join(f"  {c}" for c in grid[r]) + f"   {rank}")
    out.append(inner)
    out.append(border)
    return "\n".join(out)


def diagram(fen: str, dtm: int) -> str:
    """The board plus the caption line problemists expect under it.

    Stipulation on the left, material count on the right, aligned with the
    board's own right edge.
    """
    w, b = piece_counts(fen)
    left = f"  {hn(dtm)}"
    right = f"{w} + {b}"
    pad = BOARD_WIDTH - len(left) - len(right)
    return f"{board(fen)}\n{left}{' ' * pad}{right}"


def helpman_url(fen: str, dtm: int) -> str:
    """A Helpmate Analyzer deep link: helpman.komtera.lt.

    Only the board field goes in `fen`. Two reasons, both load-bearing:

    * the site parses its own query string in `transformToAssocArray()` by
      splitting on `&` and `=` -- there is no `decodeURIComponent` anywhere on
      that path, so a percent-encoded space arrives as a literal `%20` and the
      FEN fails to parse. The board field is `[A-Za-z0-9/]` only, which needs
      no encoding at all;
    * side to move is not carried by the FEN there. It is implied by the
      stipulation: `moves=13` is Black to play (the helpmate default),
      `moves=8.5` is White. That is exactly our dtm parity.
    """
    return (f"https://helpman.komtera.lt/?fen={fen.split()[0]}"
            f"&moves={moves_param(dtm)}")


def numbered(solution: str, dtm: int) -> str:
    """Helpmate notation, in which Black moves first.

    `1.Kb7 d5 2...` for a black-to-move problem; an odd depth is White to
    move, so it opens `1...` with White's move and Black's first reply starts
    move two.
    """
    moves = solution.split()
    if not moves:
        return ""
    out: list[str] = []
    if dtm % 2:                                  # White to move: 1...
        out.append(f"1...{moves[0]}")
        moves = moves[1:]
        n = 2
    else:
        n = 1
    for i in range(0, len(moves), 2):
        pair = " ".join(moves[i:i + 2])
        out.append(f"{n}.{pair}")
        n += 1
    return " ".join(out)


_TEX = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
        "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
        "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}


def tex_escape(text: str) -> str:
    """Escape a literal string for LaTeX. `h#13` is the case that matters."""
    return "".join(_TEX.get(c, c) for c in text)


# --------------------------------------------------------------------------
# one order, one numbering, shared by DEEPEST.md and the booklet


def ordered(rows: list[dict]) -> list[dict]:
    """Presentation order: by men, then deepest sound problem first, then name.

    DEEPEST.md and the booklet both iterate this, so `No. 117` is the same
    problem in both.
    """
    return sorted(rows, key=lambda r: (r["pieces"], -r["dtm"], r["material"]))


def numbers(rows: list[dict]) -> dict[str, int]:
    """material -> problem number, 1-based, in `ordered` order."""
    return {r["material"]: i + 1 for i, r in enumerate(ordered(rows))}


# --------------------------------------------------------------------------
# SVG diagrams, for DEEPEST.md (GitHub renders an <img> of an .svg file)

# The piece drawings are Cburnett's Wikimedia pieces (CC BY-SA 3.0), taken
# from the cm-chessboard sprite the dashboard vendors, so the site, the
# dashboard and the markdown all draw the same men. The tracked copy is the
# dashboard's; site/vendor/ is a git-ignored copy that `make site` creates.
PIECE_SPRITE = Path(__file__).resolve().parent.parent / (
    "src/packages/web/helpmate_web/static/vendor/cm-chessboard/assets/pieces/standard.svg")
PIECE_IDS = ("wk", "wq", "wr", "wb", "wn", "wp", "bk", "bq", "br", "bb", "bn", "bp")
SPRITE_CELL = 40  # the sprite draws each man in a 40x40 box
_piece_defs: dict[str, str] | None = None


def piece_defs(only: tuple[str, ...] | None = None) -> str:
    """The piece groups of the sprite, verbatim, for an SVG <defs> -- all
    twelve, or just `only` (a diagram embeds only the men it shows, which
    keeps 234 files at a few KB each instead of 23)."""
    global _piece_defs
    if _piece_defs is None:
        import xml.etree.ElementTree as ET
        ET.register_namespace("", "http://www.w3.org/2000/svg")
        root = ET.parse(PIECE_SPRITE).getroot()
        groups = {g.get("id"): g for g in root if g.get("id") in PIECE_IDS}
        missing = [i for i in PIECE_IDS if i not in groups]
        if missing:
            raise RuntimeError(f"{PIECE_SPRITE}: sprite lacks {missing}")
        _piece_defs = {i: ET.tostring(groups[i], encoding="unicode") for i in PIECE_IDS}
    return "".join(_piece_defs[i] for i in (only or PIECE_IDS))


def svg_diagram(fen: str, width: int = 200, hatched: bool = False) -> str:
    """A self-contained SVG diagram of `fen`: light/dark squares, a frame,
    and one <use> of a sprite piece per man. No text, no fonts, so it renders
    the same everywhere, GitHub's image proxy included. `hatched` draws the
    dark squares as diagonal hatching, the way printed problem diagrams do."""
    c = SPRITE_CELL
    size = 8 * c
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
        f'viewBox="-1 -1 {size + 2} {size + 2}" width="{width}" height="{width}">',
        "<!-- pieces: Cburnett, Wikimedia Commons, CC BY-SA 3.0, via cm-chessboard -->",
        f"<defs>{piece_defs(tuple(dict.fromkeys(('w' if ch.isupper() else 'b') + ch.lower() for _, _, ch in squares(fen))))}</defs>",
        f'<rect x="0" y="0" width="{size}" height="{size}" fill="#ffffff"/>',
    ]
    dark = "#d2d2d2"
    if hatched:
        out.insert(3, '<defs><pattern id="hatch" patternUnits="userSpaceOnUse" width="4" height="4" '
                      'patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" '
                      'stroke="#000" stroke-width="1.1"/></pattern></defs>')
        dark = "url(#hatch)"
    for r in range(8):
        for f in range(8):
            if (r + f) % 2:
                out.append(f'<rect x="{f * c}" y="{r * c}" width="{c}" height="{c}" fill="{dark}"/>')
    for r, f, ch in squares(fen):
        pid = ("w" if ch.isupper() else "b") + ch.lower()
        out.append(f'<use xlink:href="#{pid}" href="#{pid}" x="{f * c}" y="{r * c}"/>')
    out.append(f'<rect x="-0.5" y="-0.5" width="{size + 1}" height="{size + 1}" fill="none" stroke="#000" stroke-width="1.5"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"

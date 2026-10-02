"""Build the JSON the static showcase (site/) reads.

    python3 tools/build_site_data.py --tables ~/tb [--binary helpmate] [--out site/data]

Run by hand against a corpus, like tools/deepest_showcase.py; the output is
committed, because the GitHub Pages workflow has no tables. Four files:

  deepest.json    docs/DEEPEST.json with every solution expanded ply by ply
  puzzles.json    the dashboard's puzzles.epd, each with its one solution and
                  the themes it shows (`helpmate probe --themes`, one call per puzzle)
  materials.json  one row per material (1000 + corpus extras such as Kvk), see
                  helpmate_server/contrib/site_data.py
  corpus.json     the totals the front page states

Every solution ply carries its SAN, its from/to squares (UCI, promotion piece
appended) and the FEN after the move. The browser therefore needs no chess
logic at all: stepping through a line is setting positions, and grading a
puzzle move is comparing two UCI strings. python-chess does the SAN parsing
here, once.

`helpmate line` is called once per puzzle. A puzzle was mined with count = 1,
so the one line it prints is the solution; a puzzle for which the binary
prints anything else is dropped with a note rather than shipped wrong.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
try:
    from helpmate_server.contrib.site_data import corpus_summary, write_site_data
    from helpmate_server.contrib.site_data import stats_row as material_row
except ImportError:  # running from a checkout without helpmate-api installed
    sys.path.insert(0, str(ROOT / "src" / "packages" / "api"))
    from helpmate_server.contrib.site_data import corpus_summary, write_site_data
    from helpmate_server.contrib.site_data import stats_row as material_row

__all__ = ["corpus_summary", "material_row"]
PUZZLES_EPD = ROOT / "src/packages/web/helpmate_web/static/puzzles.epd"
DEEPEST_JSON = ROOT / "docs/DEEPEST.json"


def piece_count(material: str) -> int:
    """Same rule as helpmate_server.storage._piece_count: every letter but the separator."""
    return sum(1 for c in material if c != "v")


def expand_solution(fen: str, san_line: str) -> list[dict]:
    """[{san, uci, fen}] for each ply of `san_line` played from `fen`.

    Raises ValueError on an illegal or ambiguous SAN, which would mean the
    line and the position disagree -- never something to ship silently."""
    import chess

    board = chess.Board(fen)
    plies = []
    for san in san_line.split():
        try:
            move = board.parse_san(san)
        except ValueError as exc:
            raise ValueError(f"{fen}: cannot play {san!r} at ply {len(plies) + 1}: {exc}") from exc
        board.push(move)
        plies.append({"san": san, "uci": move.uci(), "fen": board.fen()})
    if not board.is_checkmate():
        raise ValueError(f"{fen}: line {san_line!r} does not end in checkmate")
    return plies


def helpmate_themes(binary: str, fen: str, tables: str) -> list[str]:
    """The theme names `helpmate probe --themes` prints for `fen`, in registry order.

    Its stdout is `dtm=... count=...` then one `themes:` line: `(none)` for a
    position showing nothing, `(unavailable: ...)` when detection could not run
    (a colour-flipped probe, a missing sub-table); both give an empty list
    here rather than a fake tag."""
    out = subprocess.run(
        [binary, "probe", fen, "--themes", "--tables", tables],
        capture_output=True, text=True, check=True,
    ).stdout
    for line in out.splitlines():
        if line.startswith("themes:"):
            rest = line[len("themes:"):].strip()
            if not rest or rest.startswith("("):
                return []
            return rest.split()
    raise RuntimeError(f"{fen}: probe --themes printed no themes line:\n{out}")


def parse_epd(text: str) -> list[dict]:
    """Mirror of site/js/lib and the dashboard's parseEpd: fen, dtm (plies), id."""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        head, *ops = line.split(";")
        fields = head.split()
        if len(fields) < 4:
            continue
        p = {"fen": " ".join(fields[:4]) + " 0 1", "dtm": None, "id": None}
        for op in ops:
            t = op.strip()
            if not t:
                continue
            key, _, val = t.partition(" ")
            val = val.strip().strip('"')
            if key == "hm":
                try:
                    p["dtm"] = int(val)
                except ValueError:
                    p["dtm"] = None
            elif key == "id":
                p["id"] = val
        if p["dtm"] and p["dtm"] > 0:
            out.append(p)
    return out


def material_of(fen: str) -> str:
    """Canonical material name of a FEN: White's men then 'v' then Black's, K first, then Q R B N P."""
    order = "KQRBNP"
    placement = fen.split()[0]
    white = sorted((c for c in placement if c.isupper()), key=order.index)
    black = sorted((c.upper() for c in placement if c.islower()), key=order.index)
    return "".join(white) + "v" + "".join(black).lower()


def helpmate_line(binary: str, fen: str, tables: str) -> str:
    p = subprocess.run([binary, "line", fen, "--tables", tables], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:200])
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"expected one line, got {len(lines)}")
    return lines[0]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tables", required=True)
    ap.add_argument("--binary", default="helpmate")
    ap.add_argument("--out", default=str(ROOT / "site/data"))
    ap.add_argument("--deepest", default=str(DEEPEST_JSON))
    ap.add_argument("--puzzles", default=str(PUZZLES_EPD))
    a = ap.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tables = Path(a.tables).expanduser()

    # deepest
    deepest = []
    for e in json.load(open(a.deepest)):
        deepest.append(
            {
                "material": e["material"],
                "pieces": e["pieces"],
                "fen": e["fen"],
                "dtm": e["dtm"],
                "max_dtm": e["max_dtm"],
                "unique_at_depth": e["unique_at_depth"],
                "plies": expand_solution(e["fen"], e["solution"]),
            }
        )
    (out / "deepest.json").write_text(json.dumps(deepest, separators=(",", ":")))
    print(f"deepest.json: {len(deepest)} positions", file=sys.stderr)

    # puzzles
    puzzles, dropped = [], 0
    for p in parse_epd(Path(a.puzzles).read_text()):
        try:
            plies = expand_solution(p["fen"], helpmate_line(a.binary, p["fen"], str(tables)))
        except (RuntimeError, ValueError) as exc:
            dropped += 1
            print(f"  drop {p['id']}: {exc}", file=sys.stderr)
            continue
        if len(plies) != p["dtm"]:
            dropped += 1
            print(
                f"  drop {p['id']}: epd says {p['dtm']} plies, line has {len(plies)}",
                file=sys.stderr,
            )
            continue
        mat = material_of(p["fen"])
        puzzles.append(
            {
                "id": p["id"],
                "fen": p["fen"],
                "dtm": p["dtm"],
                "material": mat,
                "pieces": piece_count(mat),
                "plies": plies,
                "themes": helpmate_themes(a.binary, p["fen"], str(tables)),
            }
        )
    (out / "puzzles.json").write_text(json.dumps(puzzles, separators=(",", ":")))
    print(f"puzzles.json: {len(puzzles)} puzzles, {dropped} dropped", file=sys.stderr)

    # materials + corpus: the same rows `helpmate-tables sync` writes
    written = write_site_data(out, tables)
    for p in written:
        print(f"wrote {p.name}", file=sys.stderr)
    if not written:
        print("materials.json, corpus.json unchanged", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""V6: sampled positions must satisfy the recurrence the generator solves.

A position's stored (dtm, count) is recomputed from its successors' stored
values -- successors after captures and promotions come from the published
sub-tables -- so a wrong table has to be wrong consistently with its
neighbours AND with independently published tables to pass.
"""
from __future__ import annotations

import random
from pathlib import Path

from .checks import Check
from .materials import Material

MAX_LISTED = 10


class MissingSubtable(Exception):
    pass


def random_position(material: Material, rng: random.Random) -> str | None:
    import chess

    symbols = ["K", *material.white, "k", *material.black]
    board = chess.Board(None)
    for sym, sq in zip(symbols, rng.sample(range(64), len(symbols))):
        if sym in "Pp" and chess.square_rank(sq) in (0, 7):
            return None
        board.set_piece_at(sq, chess.Piece.from_symbol(sym))
    board.turn = rng.choice([chess.WHITE, chess.BLACK])
    return board.fen() if board.is_valid() else None


def check_position(tb, fen: str) -> str | None:
    import chess

    board = chess.Board(fen)
    moves = tb.moves(fen)
    legal = sorted(m.uci() for m in board.legal_moves)
    if sorted(m["uci"] for m in moves) != legal:
        return f"{fen}: move list differs from python-chess"
    want: tuple[int, int] | None
    if not legal:
        want = (0, 1) if board.turn == chess.BLACK and board.is_check() else None
    else:
        # moves() reports a successor whose sub-table is absent as merely
        # unsolvable; probe() raises MissingTableError, so probe those.
        for m in moves:
            if not m["solvable"] and tb.probe(m["fen"]) is not None:
                return f"{fen}: {m['uci']} listed unsolvable but its successor probes solvable"
        solvable = [m for m in moves if m["solvable"]]
        if not solvable:
            want = None
        else:
            best = min(m["dtm"] for m in solvable)
            want = (best + 1, min(255, sum(m["count"] for m in solvable if m["dtm"] == best)))
    p = tb.probe(fen)
    got = None if p is None else (p[0], p[1])
    return None if got == want else f"{fen}: table {got}, successors imply {want}"


def check_consistency(material: str, tables: Path, samples: int, seed: int,
                      extra_fens: list[str]) -> tuple[Check, list[str]]:
    import helpmate

    title = "local consistency with successors and sub-tables"
    rng = random.Random(seed)
    mat = Material(material)
    per = {" w ": 0, " b ": 0}
    fens: list[str] = []
    attempts = 0
    while min(per.values()) < samples and attempts < samples * 200:
        attempts += 1
        fen = random_position(mat, rng)
        if fen is None:
            continue
        side = " w " if " w " in fen else " b "
        if per[side] >= samples:
            continue
        per[side] += 1
        fens.append(fen)
    tb = helpmate.Tablebase(str(tables))
    bad: list[str] = []
    for fen in list(extra_fens) + fens:
        try:
            msg = check_position(tb, fen)
        except helpmate.MissingTableError as exc:
            raise MissingSubtable(f"{exc} -- pull the published corpus into the tables "
                                  "directory first") from exc
        if msg:
            bad.append(msg)
    n = len(extra_fens) + len(fens)
    detail = f"{n:,} positions (seed {seed}), {len(bad)} inconsistent"
    if bad:
        return Check("V6", title, "fail", detail + ": " + "; ".join(bad[:MAX_LISTED])), fens
    if min(per.values()) < samples:
        return Check("V6", title, "warn",
                     detail + f"; only {min(per.values())} legal positions found per side"), fens
    return Check("V6", title, "pass", detail), fens

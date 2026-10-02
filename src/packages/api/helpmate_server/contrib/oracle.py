"""V7: an independent helpmate solver on python-chess.

It shares no code with the generator (not even the move generator), so it
catches errors V6 cannot: a table and its sub-tables that are wrong in the
same way. Exponential, so only shallow positions (default <= 3 plies).
"""
from __future__ import annotations

import random
from pathlib import Path

from .checks import Check

CAP = 255


def _lines(board, depth: int) -> int:
    import chess

    if depth == 0:
        return 1 if board.turn == chess.BLACK and board.is_checkmate() else 0
    total = 0
    for mv in list(board.legal_moves):
        board.push(mv)
        total += _lines(board, depth - 1)
        board.pop()
        if total >= CAP:
            return CAP
    return total


def solve(fen: str, max_plies: int) -> tuple[int, int] | None:
    """(dtm, count) as the table stores them, or None if no helpmate within
    max_plies. count = optimal lines, saturating at 255: the number of lines
    of exactly dtm plies, because a shorter mate would make dtm smaller."""
    import chess

    board = chess.Board(fen)
    for d in range(max_plies + 1):
        if (board.turn == chess.BLACK) != (d % 2 == 0):
            continue  # the mated side is always Black: parity fixes d
        n = _lines(board, d)
        if n:
            return d, min(n, CAP)
    return None


def check_oracle(material: str, tables: Path, *, samples: int, max_plies: int,
                 seed: int, others: list[str]) -> Check:
    import helpmate

    title = f"independent python-chess solver (≤ {max_plies} plies)"
    rng = random.Random(seed)
    tb = helpmate.Tablebase(str(tables))
    chosen: list[str] = []
    for d in range(max_plies + 1):
        found = tb.mine(material, dtm=d, max=500)
        chosen += rng.sample(found, min(samples, len(found)))
    chosen += others[:samples]
    bad: list[str] = []
    for fen in chosen:
        p = tb.probe(fen)
        table = None if p is None or p[0] > max_plies else (p[0], p[1])
        want = solve(fen, max_plies)
        if table != want:
            bad.append(f"{fen}: table {None if p is None else p[:2]}, solver {want}")
    detail = f"{len(chosen)} positions (seed {seed}), {len(bad)} disagree"
    if bad:
        return Check("V7", title, "fail", detail + ": " + "; ".join(bad[:10]))
    return Check("V7", title, "pass", detail)

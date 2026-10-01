"""The material universe: every 3-6-man material the project can hold.

Names are White then 'v' then Black, each side in Q R B N P order
("KRBvkqq"). Kvk (two men) is outside the universe on purpose: the claim
list and the site's Materials page start at three.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations_with_replacement

ORDER = "QRBNP"
_RANK = {c: i for i, c in enumerate(ORDER)}
_SHAPE = re.compile(r"^K([QRBNP?]*)vk([qrbnp?]*)$")
KK_PAWNLESS, KK_PAWNS = 462, 1806
# RAM tier by pawn count, from docs/CONTRIBUTING-TABLES.md "What is missing".
_RAM_TIER_GIB = {0: 32, 1: 96, 2: 96, 3: 64, 4: 64}


def _side(pieces: str) -> str:
    return "".join(sorted(pieces, key=lambda c: _RANK[c.upper()]))


@dataclass(frozen=True)
class Material:
    name: str

    @property
    def white(self) -> str:
        return self.name.split("v")[0][1:]

    @property
    def black(self) -> str:
        return self.name.split("v")[1][1:]

    @property
    def pieces(self) -> int:
        return 2 + len(self.white) + len(self.black)

    @property
    def pawns(self) -> int:
        return self.white.count("P") + self.black.count("p")

    @property
    def bare_king(self) -> bool:
        """White has only the king: no helpmate can exist, no table is needed."""
        return self.white == ""

    @property
    def plane_size(self) -> int:
        n = self.pieces - 2
        if self.pawns == 0:
            return KK_PAWNLESS * 64 ** n
        return KK_PAWNS * 48 ** self.pawns * 64 ** (n - self.pawns)

    @property
    def ram_tier_gib(self) -> int:
        return _RAM_TIER_GIB[self.pawns]


def canonical(text: str) -> str | None:
    m = _SHAPE.match(text)
    if not m or "?" in text:
        return None
    white, black = m.group(1), m.group(2)
    if not 3 <= 2 + len(white) + len(black) <= 6:
        return None
    return f"K{_side(white)}vk{_side(black)}"


@lru_cache(maxsize=1)
def _universe() -> tuple[Material, ...]:
    out = []
    for n in range(1, 5):
        for w in range(n, -1, -1):
            for ws in combinations_with_replacement(ORDER, w):
                for bs in combinations_with_replacement(ORDER, n - w):
                    out.append(Material(f"K{''.join(ws)}vk{''.join(bs).lower()}"))
    return tuple(out)


def universe() -> list[Material]:
    return list(_universe())


def expand(pattern: str) -> list[str]:
    """Names matching a pattern where '?' is one non-king piece of that side's
    colour, in universe order. A plain name expands to itself if canonical."""
    m = _SHAPE.match(pattern)
    if not m:
        return []
    white, black = m.group(1), m.group(2)
    if 2 + len(white) + len(black) > 6:
        return []
    fixed_w, wild_w = white.replace("?", ""), white.count("?")
    fixed_b, wild_b = black.replace("?", ""), black.count("?")
    want = set()
    for ws in combinations_with_replacement(ORDER, wild_w):
        for bs in combinations_with_replacement(ORDER.lower(), wild_b):
            name = canonical(f"K{fixed_w}{''.join(ws)}vk{fixed_b}{''.join(bs)}")
            if name:
                want.add(name)
    return [mat.name for mat in _universe() if mat.name in want]

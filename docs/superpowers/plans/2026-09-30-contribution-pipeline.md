# Table Contribution Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take a contributed tablebase from GitHub claim to credited, merged
table with the maintainer doing two things: reading a verification report and
running `helpmate-tables accept`.

**Architecture:** Every command is a subcommand of the existing
`helpmate-tables` CLI (`src/packages/api/helpmate_server/tables_cli.py`); the
logic lives in a new subpackage `helpmate_server/contrib/`, one module per
responsibility. `verify` runs checks V1–V7 against a table in a directory (a
contributor's own, or a staging overlay of the maintainer's corpus plus a
downloaded HF PR). `claims` runs in a GitHub Action with no C++ build.
`accept` merges on HF, regenerates the manifest and docs, and lands a docs PR
on GitHub. `data/contributions.json` is the one hand-owned record; everything
else is generated from it plus live HF/GitHub metadata.

**Tech Stack:** Python ≥ 3.9 (`from __future__ import annotations`),
argparse, `huggingface_hub` ≥ 0.23 (already a dependency), optional extra
`[verify]`: `zstandard`, `numpy`, `chess` (python-chess); the `helpmate`
pybind11 bindings (`Tablebase.probe/moves/mine`); GitHub REST via `urllib`;
`git` and `gh` via `subprocess`; pytest.

**Spec:** `docs/superpowers/specs/2026-09-30-contribution-pipeline-design.md`

## Global Constraints

- All new code under `src/packages/api/helpmate_server/contrib/`; tests under
  `src/packages/api/tests/test_contrib_*.py`. No new scripts in `tools/`.
- `tables_cli.py` and everything it imports at module level must import
  neither `helpmate` (the C++ bindings), `numpy`, `zstandard`, `chess` nor
  `huggingface_hub`. Heavy imports go inside functions. (The `claims` job runs
  from a bare checkout with only `huggingface_hub` installed.)
- Material names: White pieces then `v` then Black, each side in order
  `Q R B N P`; the universe is 3–6 pieces including both kings: 10 + 55 + 220 +
  715 = **1000** materials.
- Index size (`plane_size`): `462 · 64^n` pawnless, `1806 · 48^p · 64^(n−p)`
  with `p ≥ 1` pawns, where `n` = non-king pieces. (Verified against all 317
  corpus headers.)
- DTM bytes: 0–252 plies, 253 `DTM_UNSET`, 254 `DTM_INVALID`, 255
  `DTM_UNSOLVABLE`; count saturates at 255. Payload = 4 planes of
  `plane_size` bytes, in order `dtm_wtm, dtm_btm, cnt_wtm, cnt_btm`,
  block-compressed as one logical stream.
- Header (64 bytes, little-endian, packed): `magic[4]="HM8P"` @0,
  `version u32` @4, `encoding u8` @8, `symmetry u8` @9 (1 pawnless, 0 pawns),
  `material char[26]` @10, `plane_size u64` @36, `max_dtm u8` @44, `flags u8`
  @45 (bit 0 = marker), `block_size u32` @46, `codec u8` @50, `json_len u32`
  @60. Then `json_len` bytes of metadata JSON (identical to the sidecar), then
  for encoding 2: `nblocks u64`, `(nblocks+1)` u64 offsets, zstd frames.
  Compressed tables are version 3 / encoding 2 / codec 1; markers version 2 /
  encoding 1 / flags bit 0.
- Merge on HF happens only in `accept`, never on a passing `verify`.
- No large download without confirmation: `verify --pr` prints the size and
  asks unless `--yes`; `--plan-only` exits after printing.
- Data additions do not bump `VERSION`; `accept` writes a `### Data` entry under
  `## [Unreleased]` in `CHANGELOG.md`.
- Contributors are never added as GitHub collaborators. Credit: MATERIALS.md,
  README + dataset-card contributor table, `.all-contributorsrc` (type `data`),
  `Co-authored-by:` trailer.
- Git pushes from `accept` run with `GIT_CONFIG_GLOBAL=/dev/null` and
  `-c credential.helper= -c 'credential.helper=!gh auth git-credential'`
  (the maintainer's global config rewrites HTTPS to SSH and pops a passphrase).
- Main is branch-protected and repository auto-merge is off: `accept` waits for
  checks with `gh pr checks --watch` and then merges with `gh pr merge --squash`.
- Lint/type/format as CI: `ruff check`, `mypy` (pinned versions in
  `.github/workflows/ci.yml`); coverage ≥ 80 % on `helpmate_server/contrib`.

## Review Focus

1. **Positions python-chess calls valid but the generator stores as
   `DTM_INVALID`.** `probe` returns `None` for both invalid and unsolvable, so
   V6 would read such a position as "unsolvable" and fail a correct table if a
   successor is solvable. Expected: a correct table never fails V6. Pinned by
   Task 4's test that runs V6 on every table the fixtures generate *and* (when
   `~/tb` exists) on five real corpus tables including a pawn table.
2. **En passant in pawn tables.** Sampled FENs carry no e.p. square, but a
   double push inside V7's search creates one, and the table's index cannot
   store it. Expected: V7 agrees with the table on pawn tables. Pinned by Task
   5's test on `KPvk` and `KPvkp`; if it disagrees, stop and investigate the
   generator's e.p. semantics before relaxing either side.
3. **A PR changed after verification.** Expected: `accept` refuses, naming both
   head shas. Pinned in Task 12.
4. **A contributor with no `Claim:` line and no registry entry** (every one of
   popeye37's 14 PRs today). Expected: the claim is found through the claims
   index (the open issue that claims the PR's materials) and the contributor
   through that issue's author; `accept` stops only if both fail. Pinned in
   Tasks 9 and 12.
5. **Re-running a command after a failure halfway** (network drop during
   download, CI failing on the docs PR). Expected: `verify` skips files
   already downloaded at the right size; `accept` resumes after its last
   completed step and never merges twice. Pinned in Tasks 7 and 12.

---

## File Structure

```
src/packages/api/helpmate_server/
  tables_cli.py                 MODIFY  dispatch to contrib; push --claim/--github; __main__
  contrib/__init__.py           CREATE  constants (repos, staging default)
  contrib/materials.py          CREATE  universe, canonical(), expand(), Material
  contrib/tablefile.py          CREATE  header, metadata, BlockReader, check_blocks()
  contrib/checks.py             CREATE  Check/TableReport, V2 V3 V4 V5, recompute_stats()
  contrib/consistency.py        CREATE  random_position(), V6
  contrib/oracle.py             CREATE  python-chess helpmate solver, V7
  contrib/report.py             CREATE  markdown + JSON rendering of reports
  contrib/verify.py             CREATE  verify_table(), verify_prs(), V1
  contrib/links.py              CREATE  "Claim:" / "GitHub:" lines: format + parse
  contrib/hf.py                 CREATE  Hub: PRs, files, download, comment, merge, commit
  contrib/github.py             CREATE  GitHub REST client (urllib)
  contrib/registry.py           CREATE  data/contributions.json load/save, resolve contributor
  contrib/claims.py             CREATE  claim parsing, status derivation, status comments
  contrib/docs_sync.py          CREATE  corpus facts, spans, MATERIALS.md, contributor tables
  contrib/accept.py             CREATE  accept steps + state file, manifest from hub, status
  contrib/cli.py                CREATE  argparse wiring for verify/status/accept/sync/claims
src/packages/api/pyproject.toml MODIFY  [verify] extra
tools/verify_corpus.py          MODIFY  thin wrapper over contrib.tablefile.check_blocks
Makefile, .github/workflows/ci.yml MODIFY  install [verify]
.github/workflows/claims.yml    CREATE
.github/ISSUE_TEMPLATE/claim.yml CREATE
data/contributions.json         CREATE  seeded with T31M
docs/MATERIALS.md, .all-contributorsrc CREATE (generated)
README.md, docs/CONTRIBUTING-TABLES.md, docs/COOPERATIVE-TABLEBASE.md,
docs/hf-dataset-card.md, CHANGELOG.md  MODIFY
```

Run all Python commands from the repository root. Setup once per checkout:

```bash
make install-dev GIT_CONFIG_GLOBAL=/dev/null
python -m pip install -e './src/packages/api[dev,verify]'
```

(The editable reinstall makes edits under `helpmate_server/` live without
reinstalling. `make install-dev` builds the C++ bindings, a few minutes.)

---

### Task 1: Material universe and the `[verify]` extra

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/__init__.py`
- Create: `src/packages/api/helpmate_server/contrib/materials.py`
- Modify: `src/packages/api/pyproject.toml`, `Makefile:33-35`, `.github/workflows/ci.yml:117-118,153-154`
- Test: `src/packages/api/tests/test_contrib_materials.py`

**Interfaces:**
- Produces: `Material(name)` with `.name .white .black .pieces .pawns .bare_king .plane_size .ram_tier_gib`; `canonical(text) -> str | None`; `expand(pattern) -> list[str]`; `universe() -> list[Material]`; constants `DATASET_REPO`, `GITHUB_REPO`, `DEFAULT_STAGING`.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_materials.py
from helpmate_server.contrib.materials import Material, canonical, expand, universe


def test_universe_has_1000_materials_by_piece_count():
    by = {}
    for m in universe():
        by[m.pieces] = by.get(m.pieces, 0) + 1
    assert by == {3: 10, 4: 55, 5: 220, 6: 715}
    names = [m.name for m in universe()]
    assert len(set(names)) == 1000


def test_bare_white_king_count_at_six_pieces():
    six = [m for m in universe() if m.pieces == 6]
    assert sum(m.bare_king for m in six) == 70
    assert sum(not m.bare_king for m in six) == 645


def test_canonical_orders_each_side_and_rejects_non_materials():
    assert canonical("KBRvkqq") == "KRBvkqq"
    assert canonical("KRBvkqq") == "KRBvkqq"
    assert canonical("KPBBvk") == "KBBPvk"
    assert canonical("Kvk") is None            # 2 pieces: outside the universe
    assert canonical("KQQQQvk") is None        # 7 pieces
    assert canonical("KQvkK") is None
    assert canonical("kqvK") is None


def test_plane_size_matches_corpus_headers():
    assert Material("KQvk").plane_size == 29568
    assert Material("KRBvkqq").plane_size == 7751073792
    assert Material("KBBPvk").plane_size == 1806 * 48 * 64 ** 3


def test_expand_wildcards():
    got = expand("KQvk???")
    assert len(got) == 35                      # multisets of 3 over 5 black kinds
    assert "KQvkqbb" in got and "KQvkppp" in got
    assert expand("KRRvk??") == sorted(expand("KRRvk??"), key=lambda n: universe_index(n))
    assert expand("KRBvkqq") == ["KRBvkqq"]
    assert expand("KQvk?????") == []           # 7 pieces


def universe_index(name):
    return [m.name for m in universe()].index(name)


def test_ram_tiers():
    assert Material("KRBvkqq").ram_tier_gib == 32
    assert Material("KRBvkqp").ram_tier_gib == 96
    assert Material("KRPvkpp").ram_tier_gib == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_materials.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'helpmate_server.contrib'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/packages/api/helpmate_server/contrib/__init__.py
"""Contribution pipeline: claims, verification, acceptance, generated docs.

Every module here is importable without the C++ bindings; the ones that need
them (or numpy / zstandard / python-chess) import inside functions.
"""
from pathlib import Path

DATASET_REPO = "osick/helpmate-tables"
GITHUB_REPO = "osick/helpmate-tablebase"
DEFAULT_STAGING = Path("~/tb-staging").expanduser()
```

```python
# src/packages/api/helpmate_server/contrib/materials.py
"""The material universe: every 3-6-man material the project can hold.

Names are White then 'v' then Black, each side in Q R B N P order
("KRBvkqq"). Kvk (two men) is outside the universe on purpose: the claim
list and MATERIALS.md start at three.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/packages/api/tests/test_contrib_materials.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Add the `[verify]` extra and install it everywhere tests run**

In `src/packages/api/pyproject.toml`, `[project.optional-dependencies]`:

```toml
dev = ["pytest", "httpx"]
# helpmate-tables verify: block decoding, plane statistics, independent oracle.
verify = ["zstandard>=0.22", "numpy>=1.24", "chess>=1.10"]
```

In `Makefile` target `install`, change the second line to
`python -m pip install './src/packages/api[verify]' ./src/packages/web`; in
`install-dev`, change `'./src/packages/api[dev]'` to
`'./src/packages/api[dev,verify]'`. In `.github/workflows/ci.yml` change both
`'./src/packages/api[dev]'` occurrences to `'./src/packages/api[dev,verify]'`.

Run: `python -m pip install -e './src/packages/api[dev,verify]' && python -c "import zstandard, numpy, chess"`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/packages/api/helpmate_server/contrib src/packages/api/tests/test_contrib_materials.py \
        src/packages/api/pyproject.toml Makefile .github/workflows/ci.yml
git commit -m "contrib: material universe (1000 materials) and the [verify] extra"
```

---

### Task 2: Table file reader and block integrity (V3 core)

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/tablefile.py`
- Modify: `tools/verify_corpus.py` (replace `check_table`'s body)
- Create: `src/packages/api/tests/contrib_helpers.py` (fixtures' mutation helpers)
- Modify: `src/packages/api/tests/conftest.py` (add fixtures)
- Test: `src/packages/api/tests/test_contrib_tablefile.py`; existing `tests/repo/test_verify_corpus.py` must pass unchanged

**Interfaces:**
- Consumes: nothing.
- Produces: `Header` (fields as in Global Constraints + `.marker`), `TableFormatError`, `read_header(path) -> Header`, `read_meta(path, header) -> dict`, `BlockReader(path)` (context manager; `.header`, `.nblocks`, `.block(b) -> bytes`, `.read(offset, n) -> bytes`, `.plane_chunks(plane, chunk=1<<22)` yielding `bytes`), `check_blocks(path) -> tuple[str, int]` (verdict `"OK"`, `"skip ..."`, or `"BAD ..."`; blocks checked), constants `DTM_UNSET=253, DTM_INVALID=254, DTM_UNSOLVABLE=255, COUNT_SAT=255`.
- Test helpers produced: fixtures `compressed_tables` (a directory with the compressed closure of `KQvk` and `KPvk`, generated once per session) and `table_copy(material)` (a function-scoped fresh copy of that directory); `contrib_helpers.rewrite_payload(path, mutate)`, `contrib_helpers.flip_frame_byte(path, block)`, `contrib_helpers.edit_sidecar(path, fn)`.

- [ ] **Step 1: Write the fixtures and helpers**

Append to `src/packages/api/tests/conftest.py`:

```python
import shutil


@pytest.fixture(scope="session")
def compressed_tables(tmp_path_factory) -> Path:
    """Block-compressed closure of KQvk and KPvk (KPvk promotes into KQvk,
    KRvk, KBvk, KNvk and captures into Kvk), 1 KiB blocks so even these small
    tables have many blocks. Generated once; tests that damage a table must
    use `table_copy`."""
    d = tmp_path_factory.mktemp("compressed")
    for mat in ("KQvk", "KPvk"):
        helpmate.generate(mat, tables=str(d), threads=2, compress=True, block_size=1)
    return Path(d)


@pytest.fixture()
def table_copy(tmp_path, compressed_tables) -> Path:
    d = tmp_path / "tables"
    shutil.copytree(compressed_tables, d)
    return d
```

```python
# src/packages/api/tests/contrib_helpers.py
"""Ways to damage a block-compressed table, for tests that must watch a
check fail. Each rewrites the file in place with a valid container, so only
the check aimed at that damage can notice."""
from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Callable

import zstandard

from helpmate_server.contrib.tablefile import HEADER_LEN, read_header


def _payload(path: Path) -> tuple[bytes, bytes, bytearray]:
    raw = path.read_bytes()
    h = read_header(path)
    head = raw[: HEADER_LEN + h.json_len]
    pos = HEADER_LEN + h.json_len
    (nb,) = struct.unpack_from("<Q", raw, pos)
    offsets = struct.unpack_from(f"<{nb + 1}Q", raw, pos + 8)
    start = pos + 8 + 8 * (nb + 1)
    d = zstandard.ZstdDecompressor()
    out = bytearray()
    for b in range(nb):
        out += d.decompress(raw[start + offsets[b]: start + offsets[b + 1]],
                            max_output_size=h.block_size)
    return head, raw, out


def rewrite_payload(path: Path, mutate: Callable[[bytearray, int], None]) -> None:
    """Decode the whole logical payload, let `mutate(payload, plane_size)` edit
    it, and recompress with a correct index and checksums."""
    h = read_header(path)
    head, _, payload = _payload(path)
    mutate(payload, h.plane_size)
    c = zstandard.ZstdCompressor(level=3, write_checksum=True, write_content_size=True)
    frames = [c.compress(bytes(payload[i:i + h.block_size]))
              for i in range(0, len(payload), h.block_size)]
    offsets, pos = [], 0
    for f in frames:
        offsets.append(pos)
        pos += len(f)
    offsets.append(pos)
    path.write_bytes(head + struct.pack("<Q", len(frames))
                     + struct.pack(f"<{len(offsets)}Q", *offsets) + b"".join(frames))


def flip_frame_byte(path: Path, block: int) -> None:
    """Flip one byte in the middle of a compressed frame (the zstd content
    checksum must catch it)."""
    h = read_header(path)
    raw = bytearray(path.read_bytes())
    pos = HEADER_LEN + h.json_len
    (nb,) = struct.unpack_from("<Q", raw, pos)
    offsets = struct.unpack_from(f"<{nb + 1}Q", raw, pos + 8)
    start = pos + 8 + 8 * (nb + 1)
    mid = start + (offsets[block] + offsets[block + 1]) // 2
    raw[mid] ^= 0xFF
    path.write_bytes(bytes(raw))


def edit_sidecar(path: Path, fn: Callable[[dict], None]) -> None:
    sc = path.with_name(path.name[: -len(".hm")] + ".stats.json")
    data = json.loads(sc.read_text())
    fn(data)
    sc.write_text(json.dumps(data, indent=2))
```

- [ ] **Step 2: Write the failing test**

```python
# src/packages/api/tests/test_contrib_tablefile.py
import pytest

from contrib_helpers import flip_frame_byte
from helpmate_server.contrib.tablefile import (
    BlockReader, TableFormatError, check_blocks, read_header, read_meta,
)


def test_header_of_a_generated_table(compressed_tables):
    h = read_header(compressed_tables / "KQvk.hm")
    assert (h.version, h.encoding, h.codec, h.symmetry) == (3, 2, 1, 1)
    assert h.material == "KQvk" and h.plane_size == 29568 and not h.marker
    assert read_header(compressed_tables / "KPvk.hm").symmetry == 0
    meta = read_meta(compressed_tables / "KQvk.hm", h)
    assert meta["material"] == "KQvk"


def test_plane_chunks_cover_each_plane_exactly(compressed_tables):
    with BlockReader(compressed_tables / "KQvk.hm") as r:
        for plane in range(4):
            data = b"".join(r.plane_chunks(plane, chunk=5000))
            assert len(data) == r.header.plane_size
            assert data == r.read(plane * r.header.plane_size, r.header.plane_size)


def test_clean_table_ok_and_marker_skipped(compressed_tables):
    verdict, nb = check_blocks(compressed_tables / "KQvk.hm")
    assert verdict == "OK" and nb == -(-4 * 29568 // 1024)
    markers = [p for p in compressed_tables.glob("*.hm") if read_header(p).marker]
    assert markers, "the KQvk/KPvk closure contains at least one marker (Kvk)"
    assert check_blocks(markers[0])[0].startswith("skip marker")


def test_flipped_frame_byte_is_bad(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 7)
    verdict, _ = check_blocks(table_copy / "KQvk.hm")
    assert verdict.startswith("BAD block 7:"), verdict


def test_not_a_table(tmp_path):
    p = tmp_path / "x.hm"
    p.write_bytes(b"nope")
    with pytest.raises(TableFormatError):
        read_header(p)
    assert check_blocks(p)[0] == "BAD not a helpmate table (magic)"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_tablefile.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.tablefile`

- [ ] **Step 4: Write the implementation**

```python
# src/packages/api/helpmate_server/contrib/tablefile.py
"""Read a .hm file without the C++ reader.

verify has to look inside files the C++ reader would refuse, and report why,
so this parses TableHeader (src/core/format/table_file.h) itself. Read-only.
"""
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

MAGIC = b"HM8P"
HEADER_LEN = 64
DTM_UNSET, DTM_INVALID, DTM_UNSOLVABLE = 253, 254, 255
COUNT_SAT = 255
MAX_REPORTED = 20  # bad blocks listed before giving up on a table


class TableFormatError(Exception):
    pass


@dataclass(frozen=True)
class Header:
    version: int
    encoding: int
    symmetry: int
    material: str
    plane_size: int
    max_dtm: int
    flags: int
    block_size: int
    codec: int
    json_len: int

    @property
    def marker(self) -> bool:
        return bool(self.flags & 1)


def read_header(path: Path | str) -> Header:
    with open(path, "rb") as fh:
        raw = fh.read(HEADER_LEN)
    if len(raw) < HEADER_LEN or raw[:4] != MAGIC:
        raise TableFormatError("not a helpmate table (magic)")
    version, encoding, symmetry = struct.unpack_from("<IBB", raw, 4)
    material = raw[10:36].split(b"\0", 1)[0].decode("ascii", "replace")
    (plane_size,) = struct.unpack_from("<Q", raw, 36)
    max_dtm, flags, block_size, codec = struct.unpack_from("<BBIB", raw, 44)
    (json_len,) = struct.unpack_from("<I", raw, 60)
    return Header(version, encoding, symmetry, material, plane_size, max_dtm,
                  flags, block_size, codec, json_len)


def read_meta(path: Path | str, header: Header) -> dict:
    with open(path, "rb") as fh:
        fh.seek(HEADER_LEN)
        return json.loads(fh.read(header.json_len))


def _read_index(fh, header: Header) -> tuple[int, tuple[int, ...], int]:
    fh.seek(HEADER_LEN + header.json_len)
    raw = fh.read(8)
    if len(raw) < 8:
        raise TableFormatError("truncated before block index")
    (nb,) = struct.unpack("<Q", raw)
    index = fh.read(8 * (nb + 1))
    if len(index) < 8 * (nb + 1):
        raise TableFormatError("truncated block index")
    offsets = struct.unpack(f"<{nb + 1}Q", index)
    start = fh.tell()
    if start + offsets[-1] > os.fstat(fh.fileno()).st_size:
        raise TableFormatError("block index points past end of file")
    return nb, offsets, start


class BlockReader:
    """Random access to the logical payload (4 planes) of an encoding-2 table.
    Keeps the last four decoded blocks: a lockstep walk over a dtm plane and
    its count plane touches two blocks at a time."""

    def __init__(self, path: Path | str):
        import zstandard

        self.header = h = read_header(path)
        if h.marker or h.encoding != 2 or h.block_size == 0:
            raise TableFormatError("not a block-compressed table")
        self._fh = open(path, "rb")
        try:
            self.nblocks, self._offsets, self._start = _read_index(self._fh, h)
        except Exception:
            self._fh.close()
            raise
        self.logical_size = 4 * h.plane_size
        self._dctx = zstandard.ZstdDecompressor()
        self._cache: dict[int, bytes] = {}

    def __enter__(self) -> "BlockReader":
        return self

    def __exit__(self, *exc) -> None:
        self._fh.close()

    def block_len(self, b: int) -> int:
        return min(self.header.block_size, self.logical_size - b * self.header.block_size)

    def block(self, b: int) -> bytes:
        hit = self._cache.get(b)
        if hit is not None:
            return hit
        self._fh.seek(self._start + self._offsets[b])
        src = self._fh.read(self._offsets[b + 1] - self._offsets[b])
        out = self._dctx.decompress(src, max_output_size=self.header.block_size)
        if len(out) != self.block_len(b):
            raise TableFormatError(
                f"block {b}: decoded {len(out)} bytes, index says {self.block_len(b)}")
        if len(self._cache) >= 4:
            self._cache.pop(next(iter(self._cache)))
        self._cache[b] = out
        return out

    def read(self, offset: int, n: int) -> bytes:
        bs = self.header.block_size
        parts, end = [], offset + n
        while offset < end:
            b = offset // bs
            data = self.block(b)
            lo = offset - b * bs
            hi = min(len(data), end - b * bs)
            parts.append(data[lo:hi])
            offset += hi - lo
        return b"".join(parts)

    def plane_chunks(self, plane: int, chunk: int = 1 << 22) -> Iterator[bytes]:
        ps = self.header.plane_size
        base = plane * ps
        for off in range(0, ps, chunk):
            yield self.read(base + off, min(chunk, ps - off))


def check_blocks(path: Path | str) -> tuple[str, int]:
    """Decode every block; verdict 'OK', 'skip ...' or 'BAD ...'."""
    import zstandard

    try:
        h = read_header(path)
    except TableFormatError as exc:
        return f"BAD {exc}", 0
    if h.marker:
        return f"skip marker (v{h.version})", 0
    if h.encoding != 2 or h.block_size == 0:
        return f"skip raw (v{h.version}, encoding {h.encoding})", 0
    with open(path, "rb") as fh:
        try:
            nb, offsets, start = _read_index(fh, h)
        except TableFormatError as exc:
            return f"BAD {exc}", 0
        total = 4 * h.plane_size
        dctx = zstandard.ZstdDecompressor()
        bad: list[str] = []
        for b in range(nb):
            expect = min(h.block_size, total - b * h.block_size)
            fh.seek(start + offsets[b])
            src = fh.read(offsets[b + 1] - offsets[b])
            try:
                out = dctx.decompress(src, max_output_size=expect)
            except zstandard.ZstdError as exc:
                bad.append(f"block {b}: {exc}")
            else:
                if len(out) != expect:
                    bad.append(f"block {b}: decoded {len(out)} bytes, index says {expect}")
            if len(bad) >= MAX_REPORTED:
                bad.append("...")
                break
    return ("OK" if not bad else "BAD " + "; ".join(bad)), nb
```

- [ ] **Step 5: Make `tools/verify_corpus.py` a wrapper**

Replace everything from `MAGIC = b"HM8P"` through the end of `check_table`
(keep the module docstring, `main()` and `__main__` block) with:

```python
# The block check lives in the helpmate-tables package now (it is verify's
# V3); this script keeps its command line and output for existing runbooks.
try:
    from helpmate_server.contrib.tablefile import check_blocks
except ImportError:  # running from a checkout without helpmate-api installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "packages" / "api"))
    from helpmate_server.contrib.tablefile import check_blocks


def check_table(path: str) -> tuple[str, str, int, float]:
    """Return (path, verdict, blocks_checked, seconds). verdict is 'OK', a
    'skip ...' reason, or 'BAD ...' with the first bad blocks listed."""
    t0 = time.time()
    verdict, nb = check_blocks(path)
    return path, verdict, nb, time.time() - t0
```

Remove the now-unused imports `struct` and the `zstandard` import block.

- [ ] **Step 6: Run both test files**

Run: `python -m pytest src/packages/api/tests/test_contrib_tablefile.py tests/repo/test_verify_corpus.py -v`
Expected: PASS — all new tests and all 5 existing `test_verify_corpus` tests (their verdict strings are unchanged).

- [ ] **Step 7: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/tablefile.py tools/verify_corpus.py \
        src/packages/api/tests/contrib_helpers.py src/packages/api/tests/conftest.py \
        src/packages/api/tests/test_contrib_tablefile.py
git commit -m "contrib: table file reader; verify_corpus becomes a wrapper over it"
```

---

### Task 3: Checks V2–V5 (header, blocks, sidecar, deepest)

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/checks.py`
- Test: `src/packages/api/tests/test_contrib_checks.py`

**Interfaces:**
- Consumes: `tablefile.*`, `materials.Material`, `materials.canonical`.
- Produces: `Check(id, title, status, detail="")` with `status in {"pass","fail","warn","skip"}`; `TableReport(material, checks=[])` with `.passed -> bool` (no `fail`); `check_header(path, installed_version) -> Check` (V2); `check_block_integrity(path) -> Check` (V3); `recompute_stats(reader) -> dict` (keys `cells`, `dtm_histogram`, `uniqueness`, `max_dtm`, `unset`); `check_sidecar(path) -> Check` (V4); `check_deepest(path, tables) -> Check` (V5).

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_checks.py
import json
import struct

from contrib_helpers import edit_sidecar, flip_frame_byte, rewrite_payload
from helpmate_server.contrib.checks import (
    check_block_integrity, check_deepest, check_header, check_sidecar,
)

V = "99.0.0"  # "installed" version newer than any generator


def test_clean_tables_pass_v2_to_v5(compressed_tables):
    for mat in ("KQvk", "KPvk"):
        p = compressed_tables / f"{mat}.hm"
        assert check_header(p, V).status == "pass"
        assert check_block_integrity(p).status == "pass"
        assert check_sidecar(p).status == "pass", check_sidecar(p).detail
        assert check_deepest(p, compressed_tables).status == "pass"


def test_v2_catches_a_renamed_file(table_copy):
    (table_copy / "KQvk.hm").rename(table_copy / "KBBvk.hm")      # not in the closure
    (table_copy / "KQvk.stats.json").rename(table_copy / "KBBvk.stats.json")
    c = check_header(table_copy / "KBBvk.hm", V)
    assert c.status == "fail" and "header says 'KQvk'" in c.detail


def test_v2_catches_a_raw_table_and_a_newer_generator(table_copy):
    p = table_copy / "KQvk.hm"
    assert "newer than the installed" in check_header(p, "0.0.1").detail
    raw = bytearray(p.read_bytes())
    struct.pack_into("<I", raw, 4, 1)          # version 1
    raw[8] = 1                                 # encoding raw
    p.write_bytes(bytes(raw))
    assert "block-compressed" in check_header(p, V).detail


def test_v2_catches_sidecar_drift(table_copy):
    edit_sidecar(table_copy / "KQvk.hm", lambda d: d.update(max_dtm=3))
    assert "sidecar differs" in check_header(table_copy / "KQvk.hm", V).detail


def test_v3_catches_a_damaged_frame(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 3)
    assert check_block_integrity(table_copy / "KQvk.hm").status == "fail"


def test_v4_catches_one_changed_dtm_cell(table_copy):
    p = table_copy / "KQvk.hm"

    def bump(payload, ps):                     # first solvable btm cell: +2 plies
        for i in range(ps, 2 * ps):
            if payload[i] < 250:
                payload[i] += 2
                return
    rewrite_payload(p, bump)
    c = check_sidecar(p)
    assert c.status == "fail" and "dtm_histogram" in c.detail
    assert check_block_integrity(p).status == "pass"   # V3 cannot see it


def test_v4_catches_a_changed_count_cell(table_copy):
    p = table_copy / "KQvk.hm"

    def bump(payload, ps):
        for i in range(ps, 2 * ps):
            if payload[i] < 250:
                payload[2 * ps + i] = 2 if payload[2 * ps + i] == 1 else 1
                return
    rewrite_payload(p, bump)
    c = check_sidecar(p)
    assert c.status == "fail" and "uniqueness" in c.detail


def test_v5_catches_a_wrong_deepest_list(table_copy):
    p = table_copy / "KQvk.hm"
    sc = json.loads((table_copy / "KQvk.stats.json").read_text())
    sc["deepest"] = sc["deepest_unique"][:1]   # a unique-deepest position is shallower
    (table_copy / "KQvk.stats.json").write_text(json.dumps(sc))
    c = check_deepest(p, table_copy)
    assert c.status == "fail", c.detail
```

(`test_v5_catches_a_wrong_deepest_list` relies on KQvk's deepest unique
position being shallower than `max_dtm`; the fixture's sidecar shows
`max_dtm` 14 with unique-deepest positions at a smaller depth — if that ever
changes, pick any FEN whose probe differs from `max_dtm`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_checks.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.checks`

- [ ] **Step 3: Write the implementation**

```python
# src/packages/api/helpmate_server/contrib/checks.py
"""V2-V5: checks that need only the file, its sidecar and a few probes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .materials import Material, canonical
from .tablefile import (
    DTM_INVALID, DTM_UNSET, DTM_UNSOLVABLE, BlockReader, TableFormatError,
    check_blocks, read_header, read_meta,
)


@dataclass
class Check:
    id: str
    title: str
    status: str  # "pass" | "fail" | "warn" | "skip"
    detail: str = ""


@dataclass
class TableReport:
    material: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


def _stem(path: Path) -> str:
    return path.name[: -len(".hm")]


def _sidecar(path: Path) -> Path:
    return path.with_name(_stem(path) + ".stats.json")


def _version(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return None


def check_header(path: Path, installed_version: str) -> Check:
    title = "header and identity"
    stem = _stem(path)
    try:
        h = read_header(path)
        meta = read_meta(path, h)
    except TableFormatError as exc:
        return Check("V2", title, "fail", str(exc))
    except ValueError as exc:
        return Check("V2", title, "fail", f"embedded metadata is not JSON: {exc}")
    problems: list[str] = []
    canon = canonical(stem)
    if canon != stem:
        problems.append(f"file name {stem!r} is not a canonical material"
                        + (f" (canonical: {canon})" if canon else ""))
    if h.material != stem:
        problems.append(f"header says {h.material!r}, file name says {stem!r}")
    if canon:
        m = Material(canon)
        if h.plane_size != m.plane_size:
            problems.append(f"plane_size {h.plane_size}, index size for {canon} is {m.plane_size}")
        if h.symmetry != (0 if m.pawns else 1):
            problems.append(f"symmetry byte {h.symmetry} is wrong for this material")
    if h.marker:
        if h.version != 2:
            problems.append(f"marker with format version {h.version}, expected 2")
    elif not (h.version == 3 and h.encoding == 2 and h.codec == 1 and h.block_size):
        problems.append(f"format version {h.version}, encoding {h.encoding}: the dataset "
                        "serves only block-compressed tables (gen --compress, or "
                        "helpmate compact --compress)")
    sc_path = _sidecar(path)
    if not sc_path.exists():
        problems.append("no .stats.json sidecar next to the table")
    else:
        sc = json.loads(sc_path.read_text())
        if sc != meta:
            problems.append("sidecar differs from the metadata embedded in the table")
        gv = str(sc.get("generator_version", ""))
        got, inst = _version(gv), _version(installed_version)
        if got is None:
            problems.append(f"generator_version {gv!r} is not a version")
        elif inst is not None and got > inst:
            problems.append(f"generated with {gv}, newer than the installed helpmate "
                            f"{installed_version}; upgrade before verifying")
    if problems:
        return Check("V2", title, "fail", "; ".join(problems))
    return Check("V2", title, "pass",
                 f"{h.material}, plane_size {h.plane_size:,}, format v{h.version}")


def check_block_integrity(path: Path) -> Check:
    verdict, nb = check_blocks(path)
    if verdict.startswith("skip"):
        return Check("V3", "block integrity", "skip", verdict)
    if verdict == "OK":
        return Check("V3", "block integrity", "pass", f"{nb:,} blocks decoded, checksums match")
    return Check("V3", "block integrity", "fail", verdict)


def recompute_stats(reader: BlockReader) -> dict:
    """The sidecar's statistics, recomputed from the payload the way
    SliceGen::stats_json computes them (src/core/generator/generator.cpp)."""
    import numpy as np

    out: dict = {"cells": {"invalid": {}, "unsolvable": {}},
                 "dtm_histogram": {}, "uniqueness": {}, "unset": 0}
    max_dtm = -1
    for s, stm in ((0, "wtm"), (1, "btm")):
        joint = np.zeros(65536, dtype=np.uint64)
        for d, c in zip(reader.plane_chunks(s), reader.plane_chunks(2 + s)):
            dv = np.frombuffer(d, dtype=np.uint8).astype(np.uint32)
            cv = np.frombuffer(c, dtype=np.uint8).astype(np.uint32)
            joint += np.bincount(dv * 256 + cv, minlength=65536).astype(np.uint64)
        grid = joint.reshape(256, 256)
        per = grid.sum(axis=1)
        out["cells"]["invalid"][stm] = int(per[DTM_INVALID])
        out["cells"]["unsolvable"][stm] = int(per[DTM_UNSOLVABLE])
        out["unset"] += int(per[DTM_UNSET])
        depths = [d for d in range(DTM_UNSET) if per[d]]
        out["dtm_histogram"][stm] = {str(d): int(per[d]) for d in depths}
        out["uniqueness"][stm] = {
            str(d): {str(int(c)): int(grid[d, c]) for c in np.nonzero(grid[d])[0]}
            for d in depths}
        if depths:
            max_dtm = max(max_dtm, depths[-1])
    out["max_dtm"] = max_dtm if max_dtm >= 0 else DTM_UNSOLVABLE
    return out


def check_sidecar(path: Path) -> Check:
    title = "sidecar recomputed from the payload"
    h = read_header(path)
    if h.marker:
        return Check("V4", title, "skip", "marker table: no payload")
    sc = json.loads(_sidecar(path).read_text())
    try:
        with BlockReader(path) as r:
            got = recompute_stats(r)
    except TableFormatError as exc:
        return Check("V4", title, "fail", str(exc))
    diffs = [k for k in ("cells", "dtm_histogram", "uniqueness", "max_dtm") if sc.get(k) != got[k]]
    if got["unset"]:
        diffs.append(f"{got['unset']} cells still DTM_UNSET")
    if h.max_dtm != got["max_dtm"]:
        diffs.append(f"header max_dtm {h.max_dtm}, payload {got['max_dtm']}")
    if diffs:
        return Check("V4", title, "fail", "differs: " + ", ".join(diffs))
    return Check("V4", title, "pass", f"{2 * h.plane_size:,} cells, max_dtm {got['max_dtm']}")


def check_deepest(path: Path, tables: Path) -> Check:
    """Probe the sidecar's deepest positions through the C++ reader. This is
    also where the reader's own identity check (material, plane_size) runs."""
    import helpmate

    title = "deepest positions probe as recorded"
    sc = json.loads(_sidecar(path).read_text())
    if sc.get("max_dtm") == DTM_UNSOLVABLE:
        return Check("V5", title, "skip", "no solvable cell")
    bad: list[str] = []
    try:
        tb = helpmate.Tablebase(str(tables))
        for fen in sc.get("deepest", []):
            p = tb.probe(fen)
            if p is None or p[0] != sc["max_dtm"]:
                bad.append(f"deepest {fen}: probe {p}, max_dtm {sc['max_dtm']}")
        uniq = sc.get("deepest_unique", [])
        depth = None
        for fen in uniq:
            p = tb.probe(fen)
            if p is None or p[1] != 1 or (depth is not None and p[0] != depth):
                bad.append(f"deepest_unique {fen}: probe {p}")
            elif depth is None:
                depth = p[0]
        if depth is not None:
            for stm, by_depth in sc["uniqueness"].items():
                for d, counts in by_depth.items():
                    if int(d) > depth and "1" in counts:
                        bad.append(f"uniqueness has unique {stm} cells at {d} > {depth}")
    except Exception as exc:  # the reader refusing the file is the finding
        return Check("V5", title, "fail", f"reader error: {exc}")
    if bad:
        return Check("V5", title, "fail", "; ".join(bad[:10]))
    return Check("V5", title, "pass",
                 f"{len(sc.get('deepest', []))} deepest + {len(uniq)} deepest-unique positions")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/packages/api/tests/test_contrib_checks.py -v`
Expected: PASS (8 tests). If `test_clean_tables_pass_v2_to_v5` fails on V4
for a clean table, the recomputation disagrees with the generator — compare
`recompute_stats` output against the sidecar key by key before touching the
test; the generator is the reference.

- [ ] **Step 5: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/checks.py src/packages/api/tests/test_contrib_checks.py
git commit -m "contrib: checks V2-V5 (header, blocks, sidecar recomputed, deepest probes)"
```

---

### Task 4: V6 local consistency

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/consistency.py`
- Test: `src/packages/api/tests/test_contrib_consistency.py`

**Interfaces:**
- Consumes: `Check`, `Material`, `helpmate.Tablebase` (`probe(fen) -> (dtm, count, flipped) | None`, `moves(fen) -> list[dict(uci, dtm, count, solvable, ...)]`).
- Produces: `random_position(material: Material, rng: random.Random) -> str | None`; `check_position(tb, fen) -> str | None` (mismatch text or None); `check_consistency(material: str, tables: Path, samples: int, seed: int, extra_fens: list[str]) -> tuple[Check, list[str]]` (the check and the sampled FENs, reused by V7); exception `MissingSubtable(Exception)`.

The recurrence (from `oracle.h`, plies to "Black is checkmated", both sides
cooperating): a position with no legal moves reads `(0, 1)` if Black is to
move and in check, else unsolvable; otherwise, over solvable successors,
`dtm = 1 + min(dtm)` and `count = min(255, Σ count of the minimising
successors)`; no solvable successor ⇒ unsolvable. `probe` returns `None` for
unsolvable (and for invalid).

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_consistency.py
import os
import random
from pathlib import Path

import chess
import helpmate
import pytest

from contrib_helpers import rewrite_payload
from helpmate_server.contrib.consistency import (
    MissingSubtable, check_consistency, check_position, random_position,
)
from helpmate_server.contrib.materials import Material


def test_random_positions_are_legal_and_of_the_material():
    rng = random.Random(1)
    fens = [f for f in (random_position(Material("KPvkp"), rng) for _ in range(300)) if f]
    assert len(fens) > 100
    for f in fens:
        b = chess.Board(f)
        assert b.is_valid()
        assert sorted(p.symbol() for p in b.piece_map().values()) == sorted("KPkp")


@pytest.mark.parametrize("mat", ["KQvk", "KPvk"])
def test_clean_tables_are_consistent(compressed_tables, mat):
    c, fens = check_consistency(mat, compressed_tables, samples=400, seed=7, extra_fens=[])
    assert c.status == "pass", c.detail
    assert len(fens) == 800


def test_mate_and_stalemate(compressed_tables):
    tb = helpmate.Tablebase(str(compressed_tables))
    assert check_position(tb, "k7/1Q6/1K6/8/8/8/8/8 b - - 0 1") is None   # mate: (0, 1)
    assert check_position(tb, "k7/2Q5/1K6/8/8/8/8/8 b - - 0 1") is None   # stalemate: None


def test_one_wrong_cell_is_caught(table_copy):
    p = table_copy / "KQvk.hm"
    tb = helpmate.Tablebase(str(table_copy))
    fen = "8/8/8/8/8/2k5/8/K1Q5 b - - 0 1"
    dtm, count, _ = tb.probe(fen)

    # Find that position's cell by value scan is not possible without the
    # index; instead damage EVERY btm cell with this (dtm, count) pair.
    def damage(payload, ps):
        for i in range(ps, 2 * ps):
            if payload[i] == dtm and payload[2 * ps + i] == count:
                payload[2 * ps + i] = count - 1
    rewrite_payload(p, damage)
    tb2 = helpmate.Tablebase(str(table_copy))
    assert "successors imply" in (check_position(tb2, fen) or "")


def test_missing_subtable_is_an_environment_error(tmp_path, compressed_tables):
    for ext in (".hm", ".stats.json"):
        (tmp_path / f"KPvk{ext}").write_bytes((compressed_tables / f"KPvk{ext}").read_bytes())
    with pytest.raises(MissingSubtable):
        check_consistency("KPvk", tmp_path, samples=50, seed=1, extra_fens=[])


CORPUS = Path(os.path.expanduser("~/tb"))


@pytest.mark.skipif(not (CORPUS / "KRBvkqp.hm").exists(), reason="needs the real corpus")
@pytest.mark.parametrize("mat", ["KQvkr", "KBNvk", "KRvkp", "KQPvkr", "KRBvkqp"])
def test_real_corpus_tables_are_consistent(mat):
    c, _ = check_consistency(mat, CORPUS, samples=300, seed=11, extra_fens=[])
    assert c.status == "pass", c.detail
```

(The damage test lowers `count` on the btm cells sharing the probed
position's pair; the probed position is among them, so its stored count no
longer equals the sum its successors imply.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_consistency.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.consistency`

- [ ] **Step 3: Write the implementation**

```python
# src/packages/api/helpmate_server/contrib/consistency.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/packages/api/tests/test_contrib_consistency.py -v`
Expected: PASS (fixture tests; corpus tests PASS on the maintainer box, SKIP
elsewhere). **If a clean or corpus table fails**, do not loosen the check:
print the failing FEN's `tb.moves(fen)` and `tb.probe(fen)`, decide whether
it is Review Focus item 1 (python-chess-valid, generator-invalid) and, if so,
treat exactly that class of position as "skip" with a comment naming it.

- [ ] **Step 5: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/consistency.py src/packages/api/tests/test_contrib_consistency.py
git commit -m "contrib: V6 local consistency against successors and sub-tables"
```

---

### Task 5: V7 independent oracle

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/oracle.py`
- Test: `src/packages/api/tests/test_contrib_oracle.py`

**Interfaces:**
- Consumes: `Check`; `helpmate.Tablebase.probe/mine`.
- Produces: `solve(fen, max_plies) -> tuple[int, int] | None`; `check_oracle(material, tables, *, samples, max_plies, seed, others) -> Check`.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_oracle.py
import helpmate
import pytest

from contrib_helpers import rewrite_payload
from helpmate_server.contrib.oracle import check_oracle, solve


def test_solve_mate_in_zero_one_and_none():
    assert solve("k7/1Q6/1K6/8/8/8/8/8 b - - 0 1", 3) == (0, 1)
    d, n = solve("k7/2Q5/1K6/8/8/8/8/8 w - - 0 1", 3)
    assert d == 1 and n >= 1
    assert solve("k7/2Q5/1K6/8/8/8/8/8 b - - 0 1", 3) is None     # stalemate


def test_solve_agrees_with_table_probe(compressed_tables):
    tb = helpmate.Tablebase(str(compressed_tables))
    for d in range(4):
        for fen in tb.mine("KQvk", dtm=d, max=5):
            p = tb.probe(fen)
            assert solve(fen, 3) == (p[0], p[1]), fen


@pytest.mark.parametrize("mat", ["KQvk", "KPvk"])
def test_clean_tables_pass(compressed_tables, mat):
    c = check_oracle(mat, compressed_tables, samples=5, max_plies=3, seed=3, others=[])
    assert c.status == "pass", c.detail


def test_shallow_value_error_is_caught(table_copy):
    def damage(payload, ps):                   # every wtm mate-in-1 becomes mate-in-3
        for i in range(ps):
            if payload[i] == 1:
                payload[i] = 3
    rewrite_payload(table_copy / "KQvk.hm", damage)
    c = check_oracle("KQvk", table_copy, samples=5, max_plies=3, seed=3, others=[])
    assert c.status == "fail", c.detail
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_oracle.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.oracle`

- [ ] **Step 3: Write the implementation**

```python
# src/packages/api/helpmate_server/contrib/oracle.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest src/packages/api/tests/test_contrib_oracle.py -v`
Expected: PASS (5 tests). Then Review Focus item 2, on the real corpus
(maintainer box only):

Run: `python -c "from pathlib import Path; from helpmate_server.contrib.oracle import check_oracle; import os; print(check_oracle('KPvkp', Path(os.path.expanduser('~/tb')), samples=10, max_plies=3, seed=5, others=[]))"`
Expected: `status='pass'`. A failure here involving a double pawn push is an
e.p. semantics question: stop and report it, do not adjust the solver.

- [ ] **Step 5: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/oracle.py src/packages/api/tests/test_contrib_oracle.py
git commit -m "contrib: V7 independent python-chess oracle"
```

---

### Task 6: `helpmate-tables verify --material` and reports

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/report.py`
- Create: `src/packages/api/helpmate_server/contrib/verify.py`
- Create: `src/packages/api/helpmate_server/contrib/cli.py`
- Modify: `src/packages/api/helpmate_server/tables_cli.py` (dispatch + `__main__`)
- Test: `src/packages/api/tests/test_contrib_verify.py`

**Interfaces:**
- Consumes: checks V2–V7.
- Produces: `VerifyOptions(samples=2000, oracle_samples=20, oracle_plies=3, seed=None)`; `verify_table(material, tables, opts, installed_version) -> TableReport`; `render_markdown(reports, *, heading, seed, tool, pr_checks=()) -> str`; `report_json(reports, *, seed, tool, head, pr, pr_checks=()) -> dict` (`{"result": "pass"|"fail", "seed", "tool", "head", "pr", "pr_checks": [...], "tables": {material: {"passed", "checks": [...]}}}`); `cli.add_parsers(sub)`; `cli.run(args, hub_factory, gh_factory) -> int`; `cli.CONTRIB_COMMANDS = {"verify", "status", "accept", "sync", "claims"}`; `UsageError(Exception)` in `cli`.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_verify.py
import json

from contrib_helpers import flip_frame_byte
from helpmate_server import tables_cli
from helpmate_server.contrib.verify import VerifyOptions, verify_table

FAST = VerifyOptions(samples=100, oracle_samples=3, oracle_plies=3, seed=42)


def test_verify_table_runs_v2_to_v7(compressed_tables):
    r = verify_table("KQvk", compressed_tables, FAST, "99.0.0")
    assert [c.id for c in r.checks] == ["V2", "V3", "V4", "V5", "V6", "V7"]
    assert r.passed


def test_verify_stops_after_a_structural_failure(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 2)
    r = verify_table("KQvk", table_copy, FAST, "99.0.0")
    assert [c.id for c in r.checks] == ["V2", "V3"] and not r.passed


def test_cli_verify_material(compressed_tables, capsys, tmp_path):
    out = tmp_path / "r.json"
    rc = tables_cli.main(["verify", "--tables", str(compressed_tables), "--material", "KQvk",
                          "--samples", "100", "--oracle-samples", "3", "--seed", "42",
                          "--report", str(out)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "KQvk" in text and "✅" in text and "seed 42" in text
    data = json.loads(out.read_text())
    assert data["result"] == "pass" and data["tables"]["KQvk"]["passed"]


def test_cli_verify_failure_exit_code(table_copy, capsys):
    flip_frame_byte(table_copy / "KQvk.hm", 2)
    rc = tables_cli.main(["verify", "--tables", str(table_copy), "--material", "KQvk"])
    assert rc == 1
    assert "❌" in capsys.readouterr().out


def test_cli_verify_unknown_material_is_usage_error(compressed_tables, capsys):
    assert tables_cli.main(["verify", "--tables", str(compressed_tables),
                            "--material", "KQQQQvk"]) == 2


def test_tables_cli_imports_nothing_heavy():
    import subprocess
    import sys
    code = ("import sys, helpmate_server.tables_cli; "
            "bad = [m for m in ('helpmate', 'numpy', 'zstandard', 'chess', 'huggingface_hub') "
            "if m in sys.modules]; print(bad); sys.exit(1 if bad else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_verify.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.verify`

- [ ] **Step 3: Write `report.py`**

```python
# src/packages/api/helpmate_server/contrib/report.py
"""Verification reports: markdown for humans (HF / GitHub comments), JSON
for accept (which checks the result and the PR head it was made for)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .checks import Check, TableReport

ICON = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "➖"}


def _rows(checks: Iterable[Check]) -> list[str]:
    return [f"| {ICON[c.status]} | {c.id} | {c.title} | {c.detail.replace('|', '/')} |"
            for c in checks]


def render_markdown(reports: list[TableReport], *, heading: str, seed: int, tool: str,
                    pr_checks: Iterable[Check] = ()) -> str:
    pr_checks = list(pr_checks)
    ok = all(r.passed for r in reports) and all(c.status != "fail" for c in pr_checks)
    lines = [f"## {heading}: {'passed ✅' if ok else 'FAILED ❌'}", "",
             f"{tool}, seed {seed}.", ""]
    if pr_checks:
        lines += ["| | | pull request | |", "|---|---|---|---|", *_rows(pr_checks), ""]
    for r in reports:
        lines += [f"### {r.material} {'✅' if r.passed else '❌'}", "",
                  "| | | check | detail |", "|---|---|---|---|", *_rows(r.checks), ""]
    if not ok:
        lines += ["Please push a corrected table to the same pull request; it will be "
                  "verified again. Nothing has been merged or closed."]
    return "\n".join(lines) + "\n"


def report_json(reports: list[TableReport], *, seed: int, tool: str, head: str | None,
                pr: int | None, pr_checks: Iterable[Check] = ()) -> dict:
    pr_checks = list(pr_checks)
    ok = all(r.passed for r in reports) and all(c.status != "fail" for c in pr_checks)
    return {"result": "pass" if ok else "fail", "seed": seed, "tool": tool,
            "head": head, "pr": pr, "pr_checks": [asdict(c) for c in pr_checks],
            "tables": {r.material: {"passed": r.passed, "checks": [asdict(c) for c in r.checks]}
                       for r in reports}}
```

- [ ] **Step 4: Write `verify.py` (table part)**

```python
# src/packages/api/helpmate_server/contrib/verify.py
"""verify: run V2-V7 on tables in a directory; V1 and downloading for PRs."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from pathlib import Path

from .checks import (
    Check, TableReport, check_block_integrity, check_deepest, check_header, check_sidecar,
)
from .consistency import check_consistency
from .oracle import check_oracle
from .tablefile import read_header

import json


@dataclass
class VerifyOptions:
    samples: int = 2000
    oracle_samples: int = 20
    oracle_plies: int = 3
    seed: int | None = None

    def resolved_seed(self) -> int:
        if self.seed is None:
            self.seed = secrets.randbelow(2**31)
        return self.seed


def verify_table(material: str, tables: Path, opts: VerifyOptions,
                 installed_version: str) -> TableReport:
    rep = TableReport(material)
    path = tables / f"{material}.hm"
    if not path.exists():
        rep.checks.append(Check("V2", "header and identity", "fail", f"{path} not found"))
        return rep
    for check in (lambda: check_header(path, installed_version),
                  lambda: check_block_integrity(path)):
        rep.checks.append(check())
        if not rep.passed:
            return rep  # later checks would only restate a structural failure
    rep.checks.append(check_sidecar(path))
    rep.checks.append(check_deepest(path, tables))
    if read_header(path).marker:
        rep.checks.append(Check("V6", "local consistency", "skip", "marker table"))
        rep.checks.append(Check("V7", "independent solver", "skip", "marker table"))
        return rep
    seed = opts.resolved_seed()
    sc = json.loads(path.with_name(f"{material}.stats.json").read_text())
    extra = list(sc.get("deepest", [])) + list(sc.get("deepest_unique", []))
    v6, fens = check_consistency(material, tables, opts.samples, seed, extra)
    rep.checks.append(v6)
    rep.checks.append(check_oracle(material, tables, samples=opts.oracle_samples,
                                   max_plies=opts.oracle_plies, seed=seed, others=fens))
    return rep
```

- [ ] **Step 5: Write `cli.py` and hook it into `tables_cli.py`**

```python
# src/packages/api/helpmate_server/contrib/cli.py
"""Argument wiring for the contribution subcommands of helpmate-tables.
Module level stays import-light: see tables_cli's constraint."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import DATASET_REPO, DEFAULT_STAGING, GITHUB_REPO

CONTRIB_COMMANDS = {"verify", "status", "accept", "sync", "claims"}


class UsageError(Exception):
    pass


def add_parsers(sub) -> None:
    v = sub.add_parser("verify", help="check tables (yours before a PR, or a dataset PR)")
    v.add_argument("--tables", required=True, metavar="DIR",
                   help="directory holding the table and every published sub-table")
    what = v.add_mutually_exclusive_group(required=True)
    what.add_argument("--material", action="append", metavar="M")
    what.add_argument("--pr", action="append", type=int, metavar="N",
                      help="maintainer: verify a pull request on the dataset")
    v.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    v.add_argument("--github-repo", default=GITHUB_REPO)
    v.add_argument("--samples", type=int, default=2000)
    v.add_argument("--oracle-samples", type=int, default=20)
    v.add_argument("--seed", type=int)
    v.add_argument("--report", metavar="FILE", help="also write the JSON report here")
    v.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    v.add_argument("--plan-only", action="store_true", help="--pr: list files and sizes, then stop")
    v.add_argument("--yes", action="store_true", help="--pr: download without asking")
    v.add_argument("--no-post", action="store_true", help="--pr: do not comment anywhere")


def _installed_version() -> str:
    try:
        import helpmate
        return helpmate.__version__
    except ImportError as exc:
        raise UsageError("verify needs the helpmate bindings: run `make install`") from exc


def _require_verify_deps() -> None:
    try:
        import chess  # noqa: F401
        import numpy  # noqa: F401
        import zstandard  # noqa: F401
    except ImportError as exc:
        raise UsageError("verify needs its extra: pip install './src/packages/api[verify]' "
                         f"(missing: {exc.name})") from exc


def _tool() -> str:
    from .. import __version__
    return f"helpmate-tables {__version__}"


def run(a: argparse.Namespace, hub_factory=None, gh_factory=None) -> int:
    try:
        if a.cmd == "verify":
            return _verify(a, hub_factory, gh_factory)
        raise UsageError(f"{a.cmd}: not implemented yet")
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _verify(a, hub_factory, gh_factory) -> int:
    from .materials import canonical
    from .report import render_markdown, report_json
    from .verify import VerifyOptions, verify_table

    _require_verify_deps()
    version = _installed_version()
    opts = VerifyOptions(samples=a.samples, oracle_samples=a.oracle_samples, seed=a.seed)
    if a.pr:
        from .verify import verify_prs
        return verify_prs(a, opts, version, _tool(), hub_factory, gh_factory)
    tables = Path(a.tables).expanduser()
    for m in a.material:
        if canonical(m) != m:
            raise UsageError(f"{m!r} is not a canonical material name"
                             + (f" (did you mean {canonical(m)}?)" if canonical(m) else ""))
    reports = [verify_table(m, tables, opts, version) for m in a.material]
    seed = opts.resolved_seed()
    print(render_markdown(reports, heading="Verification", seed=seed, tool=_tool()))
    if a.report:
        Path(a.report).write_text(json.dumps(
            report_json(reports, seed=seed, tool=_tool(), head=None, pr=None), indent=2))
    return 0 if all(r.passed for r in reports) else 1
```

In `tables_cli.py`:
- add `from .contrib import cli as contrib_cli` after the existing imports;
- in `main`, after the `for name in ("push", "pull")` loop and the
  `--create-pr` argument, add `contrib_cli.add_parsers(sub)`;
- change `main`'s signature to `def main(argv=None, hub_factory=_default_hub, gh_factory=None) -> int:`;
- right after `if a.cmd is None: ... return 2`, add:

```python
    if a.cmd in contrib_cli.CONTRIB_COMMANDS:
        return contrib_cli.run(a, hub_factory=None if hub_factory is _default_hub
                               else hub_factory, gh_factory=gh_factory)
```

  (the push/pull `hub_factory` is a different interface from the contrib
  `Hub`; `None` means "build the real one");
- at the end of the file:

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 6: Run the tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_verify.py src/packages/api/tests/test_tables_cli.py -v`
Expected: PASS (all new tests; existing `test_tables_cli.py` unchanged and passing)

- [ ] **Step 7: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{report,verify,cli}.py \
        src/packages/api/helpmate_server/tables_cli.py src/packages/api/tests/test_contrib_verify.py
git commit -m "helpmate-tables verify --material: V2-V7 with markdown and JSON reports"
```

---

### Task 7: Hugging Face client and `verify --pr`

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/hf.py`
- Create: `src/packages/api/helpmate_server/contrib/github.py` (minimal; extended in Task 10)
- Create: `src/packages/api/helpmate_server/contrib/links.py`
- Modify: `src/packages/api/helpmate_server/contrib/verify.py` (add `check_pr_hygiene`, `verify_prs`)
- Test: `src/packages/api/tests/test_contrib_verify_pr.py`, `src/packages/api/tests/fakes.py`

**Interfaces:**
- Produces:
  - `links.format_links(claim: int | None, github: str | None) -> str`; `links.parse_links(text) -> tuple[int | None, str | None]` (accepts `Claim: osick/helpmate-tablebase#39`, `Claim: #39`, and `https://github.com/osick/helpmate-tablebase/issues/39`; `GitHub: @login`).
  - `hf.PullRequest(num, title, author, status, description, files, head, url)` with `.materials -> list[str]`; `hf.FileMeta(path, size, sha256)`; `hf.Hub(repo_id, api=None)` with `pull_request(num)`, `open_pull_requests()`, `file_sizes(files, revision) -> dict[str,int]`, `download(filename, revision, dest) -> Path`, `comment(num, text)`, `merge(num)`, `main_files() -> dict[str, FileMeta]`, `read_bytes(filename, revision="main") -> bytes`, `fetch_manifest() -> dict`, `commit(files: dict[str, bytes], message) -> None`.
  - `github.GitHub(repo, token=None, opener=None)` with `comment(issue, body)`, `issue(num) -> dict`, and in Task 10 more.
  - `verify.check_pr_hygiene(pr, manifest_files) -> Check` (V1); `verify.verify_prs(args, opts, version, tool, hub_factory, gh_factory) -> int`.
  - Staging layout: `<staging>/pr-N/files/` (downloads), `<staging>/pr-N/overlay/` (symlinks), `<staging>/pr-N/report.md`, `<staging>/pr-N/report.json`.
  - `fakes.FakeHub`, `fakes.FakeGitHub` test doubles.

- [ ] **Step 1: Write the fakes**

```python
# src/packages/api/tests/fakes.py
"""In-memory stand-ins for the dataset (Hub) and GitHub, recording every
write so tests can assert what would have been posted, merged or pushed."""
from __future__ import annotations

import json
from pathlib import Path

from helpmate_server.contrib.hf import FileMeta, PullRequest


class FakeHub:
    def __init__(self, main: dict[str, bytes] | None = None):
        self.repo = "osick/helpmate-tables"
        self.main: dict[str, bytes] = dict(main or {})
        self.prs: dict[int, tuple[PullRequest, dict[str, bytes]]] = {}
        self.comments: list[tuple[int, str]] = []
        self.merged: list[int] = []
        self.commits: list[tuple[str, dict[str, bytes]]] = []
        self.downloads: list[str] = []

    def add_pr(self, num, files: dict[str, bytes], *, author="popeye37", description="",
               head="h1", status="open"):
        pr = PullRequest(num, f"Add {num}", author, status, description, sorted(files), head,
                         f"https://hf.example/discussions/{num}")
        self.prs[num] = (pr, dict(files))

    def pull_request(self, num):
        return self.prs[num][0]

    def open_pull_requests(self):
        return [p for p, _ in self.prs.values() if p.status == "open"]

    def file_sizes(self, files, revision):
        num = int(revision.rsplit("/", 1)[1])
        return {f: len(self.prs[num][1][f]) for f in files}

    def download(self, filename, revision, dest: Path) -> Path:
        num = int(revision.rsplit("/", 1)[1])
        self.downloads.append(filename)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / filename).write_bytes(self.prs[num][1][filename])
        return dest / filename

    def comment(self, num, text):
        self.comments.append((num, text))

    def merge(self, num):
        pr, files = self.prs[num]
        self.main.update(files)
        pr.status = "merged"
        self.merged.append(num)

    def main_files(self):
        import hashlib
        return {k: FileMeta(k, len(v), hashlib.sha256(v).hexdigest()) for k, v in self.main.items()}

    def read_bytes(self, filename, revision="main"):
        return self.main[filename]

    def fetch_manifest(self):
        return json.loads(self.main.get("manifest.json", b'{"schema":1,"files":{}}'))

    def commit(self, files, message):
        self.commits.append((message, dict(files)))
        self.main.update(files)


class FakeGitHub:
    def __init__(self, issues: list[dict] | None = None):
        self.issues = {i["number"]: i for i in (issues or [])}
        self.posted: list[tuple[int, str]] = []
        self.edited: list[tuple[int, str]] = []
        self.labels: dict[int, set[str]] = {n: set(i.get("labels", [])) for n, i in self.issues.items()}
        self.closed: list[int] = []
        self.issue_comments: dict[int, list[dict]] = {n: [] for n in self.issues}

    def comment(self, issue, body):
        self.posted.append((issue, body))
        self.issue_comments.setdefault(issue, []).append(
            {"id": len(self.posted), "body": body, "user": "github-actions[bot]",
             "created_at": "2026-09-30T00:00:00Z"})

    def issue(self, num):
        return self.issues[num]
```

- [ ] **Step 2: Write the failing test**

```python
# src/packages/api/tests/test_contrib_verify_pr.py
import json

from fakes import FakeGitHub, FakeHub
from helpmate_server import tables_cli
from helpmate_server.contrib.hf import PullRequest
from helpmate_server.contrib.links import format_links, parse_links
from helpmate_server.contrib.verify import check_pr_hygiene


def test_links_roundtrip_and_legacy_forms():
    assert parse_links(format_links(39, "popeye37")) == (39, "popeye37")
    assert parse_links("see https://github.com/osick/helpmate-tablebase/issues/41") == (41, None)
    assert parse_links("Claim: #45\nGitHub: @T31M") == (45, "T31M")
    assert parse_links("nothing here") == (None, None)


def _pr(files, description="Claim: #39"):
    return PullRequest(2, "Add", "popeye37", "open", description, files, "h", "u")


def test_v1_hygiene():
    ok = check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"]), {})
    assert ok.status == "pass"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm"]), {}).status == "fail"            # no sidecar
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json", "manifest.json"]),
                            {}).status == "fail"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"]),
                            {"KRRvkqq.hm": {"sha256": "ab", "size": 1}}).status == "fail"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"], ""), {}).status == "warn"


def _hub_with_kqvk_pr(corpus, description="Claim: osick/helpmate-tablebase#39"):
    """Main has the corpus minus KQvk; PR 2 adds KQvk."""
    main = {p.name: p.read_bytes() for p in corpus.iterdir() if not p.name.startswith("KQvk.")}
    hub = FakeHub(main)
    hub.add_pr(2, {n: (corpus / n).read_bytes() for n in ("KQvk.hm", "KQvk.stats.json")},
               description=description, head="abc123")
    return hub


def _tables_without_kqvk(tmp_path, corpus):
    d = tmp_path / "tb"
    d.mkdir()
    for p in corpus.iterdir():
        if not p.name.startswith("KQvk."):
            (d / p.name).write_bytes(p.read_bytes())
    return d


ARGS = ["--samples", "50", "--oracle-samples", "2", "--seed", "1"]


def test_plan_only_downloads_nothing(tmp_path, compressed_tables, capsys):
    hub = _hub_with_kqvk_pr(compressed_tables)
    rc = tables_cli.main(["verify", "--tables", str(_tables_without_kqvk(tmp_path, compressed_tables)),
                          "--pr", "2", "--staging", str(tmp_path / "st"), "--plan-only"],
                         hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())
    assert rc == 0 and hub.downloads == []
    assert "KQvk.hm" in capsys.readouterr().out


def test_verify_pr_passes_and_posts(tmp_path, compressed_tables):
    hub, gh = _hub_with_kqvk_pr(compressed_tables), FakeGitHub()
    staging = tmp_path / "st"
    rc = tables_cli.main(["verify", "--tables", str(_tables_without_kqvk(tmp_path, compressed_tables)),
                          "--pr", "2", "--staging", str(staging), "--yes", *ARGS],
                         hub_factory=lambda r: hub, gh_factory=lambda r: gh)
    assert rc == 0
    rep = json.loads((staging / "pr-2" / "report.json").read_text())
    assert rep["result"] == "pass" and rep["head"] == "abc123" and rep["pr"] == 2
    assert hub.comments[0][0] == 2 and "passed" in hub.comments[0][1]
    assert gh.posted[0][0] == 39 and "HF PR #2" in gh.posted[0][1]


def test_verify_pr_rerun_skips_downloaded_files(tmp_path, compressed_tables):
    hub = _hub_with_kqvk_pr(compressed_tables)
    tables = _tables_without_kqvk(tmp_path, compressed_tables)
    base = ["verify", "--tables", str(tables), "--pr", "2", "--staging", str(tmp_path / "st"),
            "--yes", "--no-post", *ARGS]
    tables_cli.main(base, hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())
    n = len(hub.downloads)
    tables_cli.main(base, hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())
    assert len(hub.downloads) == n


def test_verify_pr_without_confirmation_stops(tmp_path, compressed_tables, monkeypatch):
    hub = _hub_with_kqvk_pr(compressed_tables)
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    rc = tables_cli.main(["verify", "--tables", str(_tables_without_kqvk(tmp_path, compressed_tables)),
                          "--pr", "2", "--staging", str(tmp_path / "st")],
                         hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())
    assert rc == 2 and hub.downloads == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest src/packages/api/tests/test_contrib_verify_pr.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.hf`

- [ ] **Step 4: Write `links.py`**

```python
# src/packages/api/helpmate_server/contrib/links.py
"""The two lines that tie a dataset PR to GitHub: which claim, which person.
HF and GitHub share no identity, so these lines are the only link."""
from __future__ import annotations

import re

from . import GITHUB_REPO

_CLAIM = re.compile(r"(?im)^\s*claim:\s*(?:[\w.-]+/[\w.-]+)?#(\d+)")
_ISSUE_URL = re.compile(r"github\.com/" + re.escape(GITHUB_REPO) + r"/issues/(\d+)")
_GITHUB = re.compile(r"(?im)^\s*github:\s*@?([A-Za-z0-9-]+)")


def format_links(claim: int | None, github: str | None) -> str:
    lines = []
    if claim is not None:
        lines.append(f"Claim: {GITHUB_REPO}#{claim}")
    if github:
        lines.append(f"GitHub: @{github.lstrip('@')}")
    return "\n".join(lines)


def parse_links(text: str) -> tuple[int | None, str | None]:
    m = _CLAIM.search(text or "") or _ISSUE_URL.search(text or "")
    g = _GITHUB.search(text or "")
    return (int(m.group(1)) if m else None), (g.group(1) if g else None)
```

- [ ] **Step 5: Write `hf.py`**

```python
# src/packages/api/helpmate_server/contrib/hf.py
"""The dataset side: pull requests, their files, comments, merges, commits."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/\S+$", re.M)


@dataclass
class PullRequest:
    num: int
    title: str
    author: str
    status: str            # "open" | "merged" | "closed" | "draft"
    description: str
    files: list[str] = field(default_factory=list)
    head: str | None = None
    url: str = ""

    @property
    def materials(self) -> list[str]:
        return sorted({f[: -len(".hm")] for f in self.files if f.endswith(".hm")})


@dataclass(frozen=True)
class FileMeta:
    path: str
    size: int
    sha256: str | None     # None for non-LFS files: hash their bytes


class Hub:
    def __init__(self, repo_id: str, api=None):
        from huggingface_hub import HfApi

        self.repo = repo_id
        self.api = api or HfApi()

    def _url(self, num: int) -> str:
        return f"https://huggingface.co/datasets/{self.repo}/discussions/{num}"

    def pull_request(self, num: int) -> PullRequest:
        d = self.api.get_discussion_details(self.repo, num, repo_type="dataset")
        if not d.is_pull_request:
            raise ValueError(f"#{num} on {self.repo} is a discussion, not a pull request")
        desc = next((getattr(e, "content", "") for e in d.events
                     if getattr(e, "type", "") == "comment"), "")
        head = None
        refs = self.api.list_repo_refs(self.repo, repo_type="dataset", include_pull_requests=True)
        for r in refs.pull_requests or []:
            if r.ref == f"refs/pr/{num}":
                head = r.target_commit
        return PullRequest(num, d.title, d.author, d.status, desc,
                           sorted(set(_DIFF_FILE.findall(d.diff or ""))), head, self._url(num))

    def open_pull_requests(self) -> list[PullRequest]:
        ds = self.api.get_repo_discussions(self.repo, repo_type="dataset",
                                           discussion_type="pull_request",
                                           discussion_status="open")
        return [self.pull_request(d.num) for d in ds]

    def file_sizes(self, files: list[str], revision: str) -> dict[str, int]:
        infos = self.api.get_paths_info(self.repo, files, revision=revision, repo_type="dataset")
        return {i.path: i.size for i in infos}

    def download(self, filename: str, revision: str, dest: Path) -> Path:
        from huggingface_hub import hf_hub_download

        return Path(hf_hub_download(self.repo, filename, repo_type="dataset",
                                    revision=revision, local_dir=dest))

    def comment(self, num: int, text: str) -> None:
        self.api.comment_discussion(self.repo, num, text, repo_type="dataset")

    def merge(self, num: int) -> None:
        self.api.merge_pull_request(self.repo, num, repo_type="dataset")

    def main_files(self) -> dict[str, FileMeta]:
        from huggingface_hub.hf_api import RepoFile

        out = {}
        for f in self.api.list_repo_tree(self.repo, repo_type="dataset", expand=True):
            if isinstance(f, RepoFile):
                out[f.path] = FileMeta(f.path, f.size, f.lfs.sha256 if f.lfs else None)
        return out

    def read_bytes(self, filename: str, revision: str = "main") -> bytes:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return self.download(filename, revision, Path(tmp)).read_bytes()

    def fetch_manifest(self) -> dict:
        import json

        return json.loads(self.read_bytes("manifest.json"))

    def commit(self, files: dict[str, bytes], message: str) -> None:
        from huggingface_hub import CommitOperationAdd

        ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=v) for k, v in files.items()]
        self.api.create_commit(repo_id=self.repo, repo_type="dataset", operations=ops,
                               commit_message=message)
```

- [ ] **Step 6: Write the minimal `github.py`**

```python
# src/packages/api/helpmate_server/contrib/github.py
"""GitHub REST over urllib: the Action has GITHUB_TOKEN, the maintainer has
`gh auth token`. No third-party client, so the Action installs nothing."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Any, Callable


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


class GitHub:
    def __init__(self, repo: str, token: str | None = None,
                 opener: Callable[..., Any] | None = None):
        self.repo = repo
        self.token = token if token is not None else _token()
        self._open = opener or urllib.request.urlopen

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with self._open(req) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def comment(self, issue: int, body: str) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{issue}/comments", {"body": body})

    def issue(self, num: int) -> dict:
        return self._req("GET", f"/repos/{self.repo}/issues/{num}")
```

- [ ] **Step 7: Add V1 and `verify_prs` to `verify.py`**

Append to `verify.py`:

```python
import shutil
import sys

from .links import parse_links
from .materials import canonical
from .report import render_markdown, report_json


def check_pr_hygiene(pr, manifest_files: dict) -> Check:
    title = "only canonical table + sidecar pairs, nothing already published"
    problems: list[str] = []
    hms = {f[:-3] for f in pr.files if f.endswith(".hm")}
    sidecars = {f[: -len(".stats.json")] for f in pr.files if f.endswith(".stats.json")}
    for f in pr.files:
        if not (f.endswith(".hm") or f.endswith(".stats.json")):
            problems.append(f"unexpected file {f}")
    for stem in sorted(hms | sidecars):
        if canonical(stem) != stem:
            problems.append(f"{stem} is not a canonical material name")
    for stem in sorted(hms ^ sidecars):
        problems.append(f"{stem}: table and sidecar must come together")
    for f in pr.files:
        if f in manifest_files:
            problems.append(f"{f} is already published "
                            f"(sha256 {manifest_files[f]['sha256'][:12]}…)")
    if problems:
        return Check("V1", title, "fail", "; ".join(problems))
    if parse_links(pr.description)[0] is None:
        return Check("V1", title, "warn", f"{len(hms)} table(s); no `Claim:` line in the "
                     "description (push with --claim N next time)")
    return Check("V1", title, "pass", f"{len(hms)} table(s)")


def _build_overlay(tables: Path, files_dir: Path, overlay: Path) -> None:
    if overlay.exists():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True)
    for src in (tables, files_dir):
        for p in src.iterdir():
            if p.name.endswith((".hm", ".stats.json")):
                link = overlay / p.name
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(p.resolve())


def _gib(n: int) -> str:
    return f"{n / 2**30:.2f} GiB"


def verify_prs(a, opts: VerifyOptions, version: str, tool: str, hub_factory, gh_factory) -> int:
    from .hf import Hub
    from .github import GitHub

    hub = (hub_factory or Hub)(a.repo)
    tables = Path(a.tables).expanduser()
    staging = Path(a.staging).expanduser()
    staging.mkdir(parents=True, exist_ok=True)
    prs, total = [], 0
    for num in a.pr:
        pr = hub.pull_request(num)
        if pr.status != "open":
            print(f"error: PR #{num} is {pr.status}", file=sys.stderr)
            return 2
        sizes = hub.file_sizes(pr.files, f"refs/pr/{num}")
        have = staging / f"pr-{num}" / "files"
        todo = {f: s for f, s in sizes.items()
                if not ((have / f).exists() and (have / f).stat().st_size == s)}
        total += sum(todo.values())
        print(f"PR #{num} by {pr.author}: {', '.join(pr.materials) or '(no tables)'}")
        for f, s in sorted(sizes.items()):
            print(f"  {f:28} {_gib(s):>12}{'' if f in todo else '  (already downloaded)'}")
        prs.append(pr)
    free = shutil.disk_usage(staging).free
    print(f"to download: {_gib(total)}; free in {staging}: {_gib(free)}")
    if total > free * 0.95:
        print("error: not enough disk space in the staging directory", file=sys.stderr)
        return 2
    if a.plan_only:
        return 0
    if total and not a.yes and input(f"download {_gib(total)}? [y/N] ").strip().lower() != "y":
        return 2
    manifest_files = hub.fetch_manifest().get("files", {})
    gh = None if a.no_post else (gh_factory or GitHub)(a.github_repo)
    rc = 0
    for pr in prs:
        d = staging / f"pr-{pr.num}"
        files_dir = d / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        for f in pr.files:
            p = files_dir / f
            if not p.exists():
                hub.download(f, f"refs/pr/{pr.num}", files_dir)
        _build_overlay(tables, files_dir, d / "overlay")
        v1 = check_pr_hygiene(pr, manifest_files)
        reports = [verify_table(m, d / "overlay", opts, version) for m in pr.materials]
        seed = opts.resolved_seed()
        md = render_markdown(reports, heading=f"Verification of PR #{pr.num}", seed=seed,
                             tool=tool, pr_checks=[v1])
        js = report_json(reports, seed=seed, tool=tool, head=pr.head, pr=pr.num, pr_checks=[v1])
        (d / "report.md").write_text(md)
        (d / "report.json").write_text(json.dumps(js, indent=2))
        print(md)
        if js["result"] != "pass":
            rc = 1
        if gh is not None:
            hub.comment(pr.num, md)
            claim, _ = parse_links(pr.description)
            if claim is not None:
                verdict = "passed ✅" if js["result"] == "pass" else "FAILED ❌"
                gh.comment(claim, f"Verification of [HF PR #{pr.num}]({pr.url}) "
                                  f"({', '.join(pr.materials)}): {verdict}. "
                                  "Full report on the pull request.")
    return rc
```

(ruff will want the late imports moved to the top of the module; do that.)

- [ ] **Step 8: Run the tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_verify_pr.py src/packages/api/tests/test_contrib_verify.py -v`
Expected: PASS

- [ ] **Step 9: Live read-only smoke test (maintainer box, network, no download)**

Run: `helpmate-tables verify --tables ~/tb --pr 2 --plan-only`
Expected: `PR #2 by popeye37: KRRvkqq`, two files with sizes, a download
total and free space; exit 0. If the file list is empty, `d.diff` is not
populated for LFS PRs: switch `pull_request` to diffing
`list_repo_tree(revision=f"refs/pr/{num}")` against `main_files()` (compare
`FileMeta.sha256`/size) and add a fake-based test for that path.

- [ ] **Step 10: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{hf,github,links,verify}.py \
        src/packages/api/tests/fakes.py src/packages/api/tests/test_contrib_verify_pr.py
git commit -m "helpmate-tables verify --pr: download to staging, overlay, V1, post reports"
```

---

### Task 8: `push --create-pr --claim N --github LOGIN`

**Files:**
- Modify: `src/packages/api/helpmate_server/tables_cli.py` (create-pr branch + `_default_hub.open_pr`)
- Test: `src/packages/api/tests/test_tables_cli.py` (append)

**Interfaces:**
- Consumes: `links.format_links`.
- Produces: `hub.open_pr(paths, message, description="")` (the fake in `test_tables_cli.py` must accept the new keyword).

- [ ] **Step 1: Write the failing test** (append to `test_tables_cli.py`; also give the existing fake's `open_pr` at line 146 a `description=""` parameter that it stores on `self.description`)

```python
def test_create_pr_writes_claim_and_github_lines(tmp_path):
    seed(tmp_path)
    hub = PRHub()   # the existing fake class defined above line 146 -- use its real name
    assert tables_cli.main(["push", "--tables", str(tmp_path), "--repo", "u/ds",
                            "--material", "KQvk", "--create-pr", "--claim", "39",
                            "--github", "popeye37"], hub_factory=lambda repo: hub) == 0
    assert hub.description == "Claim: osick/helpmate-tablebase#39\nGitHub: @popeye37"


def test_claim_without_create_pr_is_a_usage_error(tmp_path, capsys):
    seed(tmp_path)
    assert tables_cli.main(["push", "--tables", str(tmp_path), "--repo", "u/ds",
                            "--claim", "39"], hub_factory=lambda repo: RecorderHub()) == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_tables_cli.py -v -k "claim"`
Expected: FAIL — `unrecognized arguments: --claim 39 --github popeye37`

- [ ] **Step 3: Implement**

In `main`, after the `--create-pr` argument:

```python
    sub.choices["push"].add_argument(
        "--claim", type=int, metavar="N",
        help="with --create-pr: the GitHub claim issue number this table belongs to")
    sub.choices["push"].add_argument(
        "--github", metavar="LOGIN",
        help="with --create-pr: your GitHub login, so the maintainer can credit you")
```

After `hub = hub_factory(a.repo)` add:

```python
    if a.cmd == "push" and (getattr(a, "claim", None) or getattr(a, "github", None)) \
            and not a.create_pr:
        print("error: --claim and --github only apply with --create-pr", file=sys.stderr)
        return 2
```

(Place it before `hub = hub_factory(...)` so no hub is built on a usage error.)

In the `create_pr` branch replace `url = hub.open_pr(paths, "Add " + ", ".join(names))` with:

```python
            from .contrib.links import format_links
            url = hub.open_pr(paths, "Add " + ", ".join(names),
                              description=format_links(a.claim, a.github))
```

In `_default_hub`, give `commit_files` a `description: str = ""` parameter
passed to `create_commit(..., commit_description=description or None)`, and
change `hub.open_pr` to
`lambda paths, message, description="": commit_files(paths, message, create_pr=True, description=description)`.

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/packages/api/tests/test_tables_cli.py -v`
Expected: PASS (all old and new)

- [ ] **Step 5: Commit**

```bash
git add src/packages/api/helpmate_server/tables_cli.py src/packages/api/tests/test_tables_cli.py
git commit -m "helpmate-tables push --create-pr --claim N --github LOGIN"
```

---

### Task 9: Contribution registry and contributor resolution

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/registry.py`
- Create: `data/contributions.json`
- Test: `src/packages/api/tests/test_contrib_registry.py`

**Interfaces:**
- Consumes: `links.parse_links`, `hf.PullRequest`.
- Produces: `Contributor(key, github, hf, display, anonymous=False, note="")`; `Registry.load(path)`, `.save()`, `.contributors: dict[str, Contributor]`, `.tables: dict[str, dict]`, `.by_github(login)`, `.by_hf(user)`, `.add_contributor(c)`, `.record_table(material, *, contributor, hf_pr, claim, merged, generator_version, verification)`, `.tables_of(key) -> list[str]`; `resolve_contributor(registry, pr, claim_author: str | None, override: str | None) -> Contributor | None`; `REGISTRY_PATH = Path("data/contributions.json")`.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_registry.py
import json
from pathlib import Path

from helpmate_server.contrib.hf import PullRequest
from helpmate_server.contrib.registry import Contributor, Registry, resolve_contributor

REPO_ROOT = Path(__file__).resolve().parents[4]


def _reg(tmp_path):
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema": 1, "contributors": {
        "T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"}}, "tables": {}}))
    return Registry.load(p)


def _pr(author="popeye37", description=""):
    return PullRequest(2, "Add", author, "open", description, ["KRRvkqq.hm"], "h", "u")


def test_resolution_order(tmp_path):
    reg = _reg(tmp_path)
    # 1. explicit override wins
    assert resolve_contributor(reg, _pr(), "x", "someone").github == "someone"
    # 2. GitHub: line in the description
    assert resolve_contributor(reg, _pr(description="GitHub: @pop"), "x", None).github == "pop"
    # 3. claim issue author
    c = resolve_contributor(reg, _pr(), "popeye37", None)
    assert (c.github, c.hf) == ("popeye37", "popeye37")
    # 4. registry by HF user
    assert resolve_contributor(reg, _pr(author="T31M"), None, None).key == "T31M"
    # 5. nothing
    assert resolve_contributor(reg, _pr(author="stranger"), None, None) is None


def test_record_and_save_roundtrip(tmp_path):
    reg = _reg(tmp_path)
    reg.add_contributor(Contributor("popeye37", "popeye37", "popeye37", "popeye37"))
    reg.record_table("KRRvkqq", contributor="popeye37", hf_pr=2, claim=39, merged="2026-10-01",
                     generator_version="0.20.0", verification={"result": "pass"})
    reg.save()
    again = Registry.load(reg.path)
    assert again.tables_of("popeye37") == ["KRRvkqq"]
    assert again.by_hf("popeye37").key == "popeye37"


def test_seeded_registry_credits_t31m_with_fifteen_tables():
    reg = Registry.load(REPO_ROOT / "data" / "contributions.json")
    assert len(reg.tables_of("T31M")) == 15
    assert all(reg.tables[m]["hf_pr"] == 1 and reg.tables[m]["claim"] == 41
               for m in reg.tables_of("T31M"))
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_contrib_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `registry.py`**

```python
# src/packages/api/helpmate_server/contrib/registry.py
"""data/contributions.json: who contributed which table. The one hand-owned
record; every credit list is generated from it."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .links import parse_links

REGISTRY_PATH = Path("data/contributions.json")


@dataclass
class Contributor:
    key: str
    github: str | None
    hf: str | None
    display: str
    anonymous: bool = False
    note: str = ""


class Registry:
    def __init__(self, path: Path, data: dict):
        self.path = Path(path)
        self.contributors = {k: Contributor(k, **v) for k, v in data.get("contributors", {}).items()}
        self.tables: dict[str, dict] = dict(data.get("tables", {}))

    @classmethod
    def load(cls, path: Path) -> "Registry":
        return cls(path, json.loads(Path(path).read_text()))

    def save(self) -> None:
        data = {"schema": 1,
                "contributors": {k: {f: v for f, v in asdict(c).items() if f != "key"}
                                 for k, c in sorted(self.contributors.items())},
                "tables": dict(sorted(self.tables.items()))}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def by_github(self, login: str) -> Contributor | None:
        return next((c for c in self.contributors.values()
                     if c.github and c.github.lower() == login.lower()), None)

    def by_hf(self, user: str) -> Contributor | None:
        return next((c for c in self.contributors.values()
                     if c.hf and c.hf.lower() == user.lower()), None)

    def add_contributor(self, c: Contributor) -> None:
        self.contributors[c.key] = c

    def record_table(self, material: str, *, contributor: str, hf_pr: int, claim: int | None,
                     merged: str, generator_version: str, verification: dict | None) -> None:
        self.tables[material] = {"contributor": contributor, "hf_pr": hf_pr, "claim": claim,
                                 "merged": merged, "generator_version": generator_version,
                                 "verification": verification}

    def tables_of(self, key: str) -> list[str]:
        return sorted(m for m, t in self.tables.items() if t["contributor"] == key)


def resolve_contributor(registry: Registry, pr, claim_author: str | None,
                        override: str | None) -> Contributor | None:
    """override > 'GitHub: @' line > claim issue author > registry by HF user."""
    login = override or parse_links(pr.description)[1] or claim_author
    if login:
        known = registry.by_github(login)
        if known:
            return known
        return Contributor(login, login, pr.author, login)
    return registry.by_hf(pr.author)
```

- [ ] **Step 4: Seed `data/contributions.json`**

Write the file with `contributors.T31M = {"github": "T31M", "hf": "T31M",
"display": "T31M", "anonymous": false, "note": "king, rook and bishop against
every three-man Black set, 120 GiB compressed, computed on a 192-thread,
369 GiB machine. The pawn tables need about 85 GiB of RAM each."}` and one
`tables` entry for each of KRBvkqq, KRBvkqr, KRBvkqb, KRBvkqn, KRBvkrr,
KRBvkrb, KRBvkrn, KRBvkbb, KRBvkbn, KRBvknn, KRBvkqp, KRBvkrp, KRBvkbp,
KRBvknp, KRBvkpp: `{"contributor": "T31M", "hf_pr": 1, "claim": 41,
"merged": "2026-09-26", "generator_version": <that table's sidecar
generator_version>, "verification": null}`. Generate it rather than typing:

```bash
python - <<'EOF'
import json, os
from pathlib import Path
from helpmate_server.contrib.registry import Contributor, Registry
p = Path("data/contributions.json"); p.parent.mkdir(exist_ok=True)
p.write_text('{"schema": 1, "contributors": {}, "tables": {}}')
reg = Registry.load(p)
reg.add_contributor(Contributor("T31M", "T31M", "T31M", "T31M", note=(
    "king, rook and bishop against every three-man Black set, 120 GiB compressed, "
    "computed on a 192-thread, 369 GiB machine. The pawn tables need about 85 GiB of RAM each.")))
for b in "qq qr qb qn rr rb rn bb bn nn qp rp bp np pp".split():
    m = f"KRBvk{b}"
    gv = json.load(open(os.path.expanduser(f"~/tb/{m}.stats.json")))["generator_version"]
    reg.record_table(m, contributor="T31M", hf_pr=1, claim=41, merged="2026-09-26",
                     generator_version=gv, verification=None)
reg.save()
EOF
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_registry.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/registry.py data/contributions.json \
        src/packages/api/tests/test_contrib_registry.py
git commit -m "contrib: contribution registry, seeded with T31M's fifteen tables"
```

---

### Task 10: Claims — parsing, status, the `claims` command, workflow and issue form

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/claims.py`
- Modify: `src/packages/api/helpmate_server/contrib/github.py` (claim issues, comments, labels, close, user id)
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`claims` parser + runner)
- Modify: `src/packages/api/tests/fakes.py` (`FakeGitHub` gains the new methods)
- Create: `.github/workflows/claims.yml`, `.github/ISSUE_TEMPLATE/claim.yml`
- Test: `src/packages/api/tests/test_contrib_claims.py`

**Interfaces:**
- Consumes: `materials.expand/canonical/universe`, `Registry`, `Hub.open_pull_requests()`, `Hub.fetch_manifest()`.
- Produces:
  - `claims.parse_claim(text) -> tuple[list[str], list[str]]` (claimed, released-by-strikethrough), both in universe order.
  - `claims.Claim(issue, author, created_at, materials, released, body)`; `claims.ClaimIndex(claims)` with `.claim_for(material) -> Claim | None` (lowest issue number wins).
  - `claims.Status(state, hf_pr=None, claim=None, contributor=None)`, `state in {"done", "in review", "claimed", "open", "not needed"}`.
  - `claims.material_status(done: set[str], in_review: dict[str, PullRequest], index: ClaimIndex, registry) -> dict[str, Status]` over the whole universe.
  - `claims.status_comment(claim, statuses, conflicts, stale, body_sha, seen, hf_url) -> str` (starts with `<!-- contrib-status body-sha=… seen=YYYY-MM-DD -->`).
  - `claims.run_claims(hub, gh, registry, today: date) -> int`.
  - `GitHub.claim_issues() -> list[dict]`, `GitHub.comments(issue) -> list[dict]`, `GitHub.edit_comment(comment_id, body)`, `GitHub.add_labels(issue, labels)`, `GitHub.remove_label(issue, label)`, `GitHub.close(issue, comment)`, `GitHub.user_id(login) -> int`.
  - Issue dicts as the REST API returns them, used keys: `number, title, body, user.login, created_at, labels[].name, pull_request (absent for issues)`.

- [ ] **Step 1: Write the failing test** (issue texts are copies of the live issues #39, #40, #45)

```python
# src/packages/api/tests/test_contrib_claims.py
from datetime import date

from fakes import FakeGitHub, FakeHub
from helpmate_server.contrib.claims import (
    Claim, ClaimIndex, material_status, parse_claim, run_claims,
)
from helpmate_server.contrib.registry import Registry

ISSUE_39 = """Hi Oliver,\n\nI like to contribute to your fantastic project !
I will generate all types of six-piece tablebases\nof the type KRRvk?? in the next weeks/months.\n"""
ISSUE_40 = "I will generate all types of six-piece tablebases\nof the type KQvk??? in the next weeks."
ISSUE_45 = "- KRNvkqq ✔️\n- KRNvkqr ✔️\n- KRNvkpp ✔️\nNeeds a verification pass"


def test_parse_the_live_claims():
    assert len(parse_claim(ISSUE_39)[0]) == 15
    assert len(parse_claim(ISSUE_40)[0]) == 35
    assert parse_claim(ISSUE_45)[0] == ["KRNvkqq", "KRNvkqr", "KRNvkpp"]


def test_strikethrough_releases_a_material():
    claimed, released = parse_claim("KRRvk??\n~~KRRvkpp 🚧~~ handed to T31M")
    assert "KRRvkpp" not in claimed and released == ["KRRvkpp"]


def test_non_materials_are_ignored():
    assert parse_claim("Kvk KQQQQvk KRBvkqq, and kqvK") == (["KRBvkqq"], [])


def _claim(n, author, text, created="2026-09-20T00:00:00Z"):
    mats, rel = parse_claim(text)
    return Claim(n, author, created, mats, rel, text)


def test_status_precedence(tmp_path):
    from fakes import FakeHub
    hub = FakeHub()
    hub.add_pr(3, {"KRRvkqr.hm": b"x", "KRRvkqr.stats.json": b"{}"})
    reg = Registry(tmp_path / "c.json", {"contributors": {}, "tables": {}})
    idx = ClaimIndex([_claim(39, "popeye37", "KRRvk??")])
    st = material_status({"KRRvkqq"}, {"KRRvkqr": hub.pull_request(3)}, idx, reg)
    assert st["KRRvkqq"].state == "done"
    assert st["KRRvkqr"].state == "in review" and st["KRRvkqr"].hf_pr == 3
    assert st["KRRvkrr"].state == "claimed" and st["KRRvkrr"].claim == 39
    assert st["KQRvkqq"].state == "open"
    assert st["Kvkqqqq"].state == "not needed"
    assert len(st) == 1000


def _gh_issue(n, author, body, created="2026-09-20T00:00:00Z"):
    return {"number": n, "title": f"claim: {n}", "body": body, "user": {"login": author},
            "created_at": created, "labels": [], "state": "open"}


def test_run_claims_posts_one_status_comment_and_edits_it_later(tmp_path):
    hub = FakeHub({"manifest.json": b'{"schema":1,"files":{"KRRvkqq.hm":{"sha256":"a","size":1}}}'})
    gh = FakeGitHub([_gh_issue(39, "popeye37", ISSUE_39)])
    reg = Registry(tmp_path / "c.json", {"contributors": {}, "tables": {}})
    assert run_claims(hub, gh, reg, date(2026, 9, 30)) == 0
    assert len(gh.posted) == 1 and "<!-- contrib-status" in gh.posted[0][1]
    assert "KRRvkqq" in gh.posted[0][1] and "done" in gh.posted[0][1]
    run_claims(hub, gh, reg, date(2026, 10, 1))
    assert gh.edited == []                                    # nothing changed: no edit
    hub.add_pr(3, {"KRRvkqr.hm": b"x", "KRRvkqr.stats.json": b"{}"})
    run_claims(hub, gh, reg, date(2026, 10, 2))
    assert len(gh.posted) == 1 and len(gh.edited) == 1        # edited in place
    assert "in review" in gh.edited[0][1]


def test_overlap_is_a_conflict_first_claim_wins(tmp_path):
    hub = FakeHub()
    gh = FakeGitHub([_gh_issue(39, "popeye37", ISSUE_39),
                     _gh_issue(50, "late", "claim KRRvkpp please")])
    reg = Registry(tmp_path / "c.json", {"contributors": {}, "tables": {}})
    run_claims(hub, gh, reg, date(2026, 9, 30))
    assert "claim-conflict" in gh.labels[50] and "claim-conflict" not in gh.labels[39]


def test_stale_after_21_days_without_author_activity(tmp_path):
    hub = FakeHub()
    gh = FakeGitHub([_gh_issue(40, "popeye37", ISSUE_40, created="2026-09-01T00:00:00Z")])
    reg = Registry(tmp_path / "c.json", {"contributors": {}, "tables": {}})
    # first run records the body; nothing new afterwards
    run_claims(hub, gh, reg, date(2026, 9, 5))
    run_claims(hub, gh, reg, date(2026, 9, 27))
    assert "claim-stale" in gh.labels[40]
    assert 40 not in gh.closed                                  # never closes
```

- [ ] **Step 2: Extend `FakeGitHub`** (append methods to the class in `fakes.py`)

```python
    def claim_issues(self):
        return [i for i in self.issues.values()
                if i.get("state", "open") == "open" and i["title"].lower().startswith("claim")]

    def comments(self, issue):
        return list(self.issue_comments.get(issue, []))

    def edit_comment(self, comment_id, body):
        self.edited.append((comment_id, body))
        for cs in self.issue_comments.values():
            for c in cs:
                if c["id"] == comment_id:
                    c["body"] = body

    def add_labels(self, issue, labels):
        self.labels.setdefault(issue, set()).update(labels)

    def remove_label(self, issue, label):
        self.labels.setdefault(issue, set()).discard(label)

    def close(self, issue, comment):
        self.comment(issue, comment)
        self.closed.append(issue)
        self.issues[issue]["state"] = "closed"

    def user_id(self, login):
        return 1000 + len(login)
```

(`FakeGitHub` records posted comments in `.posted`, so `.comments(issue)` is
free to be the method the real client has.)

- [ ] **Step 3: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_contrib_claims.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.claims`

- [ ] **Step 4: Implement the GitHub methods** (append to `GitHub` in `github.py`)

```python
    def claim_issues(self) -> list[dict]:
        out, page = [], 1
        while True:
            batch = self._req("GET", f"/repos/{self.repo}/issues?state=open&per_page=100&page={page}")
            out += [i for i in batch if "pull_request" not in i
                    and (i["title"].lower().startswith("claim")
                         or any(lb["name"] == "claim" for lb in i.get("labels", [])))]
            if len(batch) < 100:
                return out
            page += 1

    def comments(self, issue: int) -> list[dict]:
        cs = self._req("GET", f"/repos/{self.repo}/issues/{issue}/comments?per_page=100")
        return [{"id": c["id"], "body": c["body"], "user": c["user"]["login"],
                 "created_at": c["created_at"]} for c in cs]

    def edit_comment(self, comment_id: int, body: str) -> None:
        self._req("PATCH", f"/repos/{self.repo}/issues/comments/{comment_id}", {"body": body})

    def add_labels(self, issue: int, labels: list[str]) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{issue}/labels", {"labels": labels})

    def remove_label(self, issue: int, label: str) -> None:
        import urllib.error
        try:
            self._req("DELETE", f"/repos/{self.repo}/issues/{issue}/labels/{label}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def close(self, issue: int, comment: str) -> None:
        self.comment(issue, comment)
        self._req("PATCH", f"/repos/{self.repo}/issues/{issue}",
                  {"state": "closed", "state_reason": "completed"})

    def user_id(self, login: str) -> int:
        return int(self._req("GET", f"/users/{login}")["id"])
```

- [ ] **Step 5: Implement `claims.py`**

```python
# src/packages/api/helpmate_server/contrib/claims.py
"""Claim issues: what they claim, what state each material is in, and the
one status comment the bot keeps up to date on each claim."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .materials import canonical, expand, universe

_NAME = re.compile(r"(?<![A-Za-z])K[QRBNP?]*vk[qrbnp?]*(?![A-Za-z?])")
_STRUCK = re.compile(r"~~(.*?)~~", re.S)
_MARKER = re.compile(r"<!-- contrib-status body-sha=(\w+) seen=(\d{4}-\d{2}-\d{2}) -->")
STALE_DAYS = 21
BOT_NOTE = ("*Updated automatically from the dataset and the other claims — "
            "you no longer need to keep a status list in the issue by hand.*")


def _names(text: str) -> list[str]:
    out: list[str] = []
    for tok in _NAME.findall(text):
        out += expand(tok) if "?" in tok else ([tok] if canonical(tok) == tok else [])
    return out


def _ordered(names) -> list[str]:
    want = set(names)
    return [m.name for m in universe() if m.name in want]


def parse_claim(text: str) -> tuple[list[str], list[str]]:
    released = _names(" ".join(_STRUCK.findall(text or "")))
    claimed = set(_names(_STRUCK.sub(" ", text or ""))) - set(released)
    return _ordered(claimed), _ordered(released)


@dataclass
class Claim:
    issue: int
    author: str
    created_at: str
    materials: list[str]
    released: list[str] = field(default_factory=list)
    body: str = ""


class ClaimIndex:
    def __init__(self, claims: list[Claim]):
        self.claims = sorted(claims, key=lambda c: c.issue)
        self._first: dict[str, Claim] = {}
        for c in self.claims:
            for m in c.materials:
                self._first.setdefault(m, c)

    def claim_for(self, material: str) -> Claim | None:
        return self._first.get(material)


@dataclass
class Status:
    state: str
    hf_pr: int | None = None
    claim: int | None = None
    contributor: str | None = None


def material_status(done: set[str], in_review: dict, index: ClaimIndex, registry) -> dict[str, Status]:
    out = {}
    for m in universe():
        name = m.name
        who = registry.tables.get(name, {}).get("contributor")
        c = index.claim_for(name)
        if name in done:
            out[name] = Status("done", registry.tables.get(name, {}).get("hf_pr"), None, who)
        elif name in in_review:
            out[name] = Status("in review", in_review[name].num, c.issue if c else None,
                               in_review[name].author)
        elif m.bare_king:
            out[name] = Status("not needed")
        elif c:
            out[name] = Status("claimed", None, c.issue, c.author)
        else:
            out[name] = Status("open")
    return out


ICON = {"done": "✅ done", "in review": "🔍 in review", "claimed": "🚧 claimed",
        "open": "⬜ open", "not needed": "➖ not needed"}


def status_comment(claim: Claim, statuses: dict[str, Status], conflicts: list[str],
                   stale: bool, body_sha: str, seen: str, hf_url: str) -> str:
    rows = []
    for m in claim.materials:
        s = statuses[m]
        extra = f" — [HF PR #{s.hf_pr}]({hf_url}/discussions/{s.hf_pr})" if s.state == "in review" else ""
        rows.append(f"| {m} | {ICON[s.state]}{extra} |")
    parts = [f"<!-- contrib-status body-sha={body_sha} seen={seen} -->",
             f"**Claim status** — {sum(statuses[m].state == 'done' for m in claim.materials)} "
             f"of {len(claim.materials)} done", "", BOT_NOTE, "",
             "| material | status |", "|---|---|", *rows]
    if conflicts:
        parts += ["", "**Conflicts** (the earlier claim or the finished table wins; "
                      "strike a name through with `~~name~~` to release it):", "",
                  *[f"- {c}" for c in conflicts]]
    if stale:
        parts += ["", f"⏳ No activity by @{claim.author} for {STALE_DAYS} days. "
                      "Claims lapse after three weeks of silence — a short comment keeps it."]
    return "\n".join(parts) + "\n"


def _day(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()


def run_claims(hub, gh, registry, today: date) -> int:
    issues = gh.claim_issues()
    claims = []
    for i in issues:
        mats, rel = parse_claim(f"{i['title']}\n{i.get('body') or ''}")
        claims.append(Claim(i["number"], i["user"]["login"], i["created_at"], mats, rel,
                            i.get("body") or ""))
    index = ClaimIndex(claims)
    done = {f[:-3] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}
    in_review = {m: pr for pr in hub.open_pull_requests() for m in pr.materials}
    statuses = material_status(done, in_review, index, registry)
    hf_url = f"https://huggingface.co/datasets/{hub.repo}"
    for c in index.claims:
        conflicts = []
        for m in c.materials:
            first = index.claim_for(m)
            if first and first.issue != c.issue:
                conflicts.append(f"{m} is already claimed in #{first.issue}")
            s = statuses[m]
            if s.state == "done" and s.contributor and s.contributor.lower() != c.author.lower():
                conflicts.append(f"{m} is already done")
            elif s.state == "done" and s.contributor is None and m not in registry.tables:
                conflicts.append(f"{m} is already done")
        comments = gh.comments(c.issue)
        mine = next((x for x in comments if _MARKER.search(x["body"])), None)
        body_sha = hashlib.sha256(c.body.encode()).hexdigest()[:12]
        seen = today.isoformat()
        if mine:
            old_sha, old_seen = _MARKER.search(mine["body"]).groups()
            if old_sha == body_sha:
                seen = old_seen
        activity = max([_day(c.created_at), date.fromisoformat(seen)]
                       + [_day(x["created_at"]) for x in comments if x["user"] == c.author])
        stale = (today - activity).days >= STALE_DAYS
        text = status_comment(c, statuses, conflicts, stale, body_sha, seen, hf_url)
        if mine is None:
            gh.comment(c.issue, text)
        elif mine["body"] != text:
            gh.edit_comment(mine["id"], text)
        gh.add_labels(c.issue, ["claim"])
        for label, on in (("claim-conflict", bool(conflicts)), ("claim-stale", stale)):
            if on:
                gh.add_labels(c.issue, [label])
            else:
                gh.remove_label(c.issue, label)
    return 0
```


- [ ] **Step 6: Wire `claims` into `cli.py`**

In `add_parsers`:

```python
    c = sub.add_parser("claims", help="(CI) update the status comment on every claim issue")
    c.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    c.add_argument("--github-repo", default=GITHUB_REPO)
    c.add_argument("--registry", type=Path, default=Path("data/contributions.json"))
```

In `run`, before the `raise UsageError(...)`:

```python
        if a.cmd == "claims":
            from datetime import date
            from .claims import run_claims
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            return run_claims((hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                              Registry.load(a.registry), date.today())
```

- [ ] **Step 7: The workflow and the issue form**

```yaml
# .github/workflows/claims.yml
# Keeps one status comment on every open claim issue: which claimed materials
# are done (in the dataset manifest), in review (in an open dataset PR),
# conflicting or stale. Commits nothing; needs no C++ build -- tables_cli
# imports nothing from the bindings (tested in test_contrib_verify.py).
name: Claims

on:
  issues:
    types: [opened, edited, reopened]
  issue_comment:
    types: [created]
  schedule:
    - cron: "17 5 * * *"
  workflow_dispatch:

permissions:
  issues: write
  contents: read

concurrency:
  group: claims
  cancel-in-progress: false

jobs:
  claims:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install "huggingface_hub>=0.23"
      - run: python -m helpmate_server.tables_cli claims --github-repo "${{ github.repository }}"
        env:
          PYTHONPATH: src/packages/api
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

```yaml
# .github/ISSUE_TEMPLATE/claim.yml
name: Claim a material
description: Reserve one or more tablebases before you spend CPU on them.
title: "claim: "
labels: [claim]
body:
  - type: markdown
    attributes:
      value: |
        See [docs/CONTRIBUTING-TABLES.md](../blob/main/docs/CONTRIBUTING-TABLES.md) and
        [docs/MATERIALS.md](../blob/main/docs/MATERIALS.md) for what is still open.
        A bot will comment with the status of every material you claim.
  - type: textarea
    id: materials
    attributes:
      label: Materials
      description: One name or pattern per line, e.g. `KRBvkqq` or `KQvk???` (`?` = any piece of that colour).
    validations:
      required: true
  - type: input
    id: hf
    attributes:
      label: Hugging Face username
      description: The account your dataset pull requests will come from.
  - type: input
    id: credit
    attributes:
      label: Name to credit
  - type: checkboxes
    id: anonymous
    attributes:
      label: Credit
      options:
        - label: Do not name me in the credits.
  - type: input
    id: hardware
    attributes:
      label: Hardware (optional)
```

- [ ] **Step 8: Run tests; lint the workflow if actionlint is available**

Run: `python -m pytest src/packages/api/tests/test_contrib_claims.py src/packages/api/tests/test_contrib_verify_pr.py -v`
Expected: PASS
Run: `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in ('.github/workflows/claims.yml','.github/ISSUE_TEMPLATE/claim.yml')]"`
Expected: no output (valid YAML). (`actionlint` is not installed on the box;
the workflow's first real run is the check — see Task 13.)

- [ ] **Step 9: Live read-only dry run against the real issues (maintainer box)**

Run:
```bash
python - <<'EOF'
from helpmate_server.contrib.claims import parse_claim
from helpmate_server.contrib.github import GitHub
for i in GitHub("osick/helpmate-tablebase").claim_issues():
    print(i["number"], parse_claim(f"{i['title']}\n{i['body'] or ''}"))
EOF
```
Expected: #39 → 15 KRR materials, #40 → 35 KQ materials, #41 → 15 KRB, #45 →
15 KRN; #43 ("Observation") absent.

- [ ] **Step 10: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{claims,github,cli}.py src/packages/api/tests/fakes.py \
        src/packages/api/tests/test_contrib_claims.py src/packages/api/tests/test_contrib_verify_pr.py \
        .github/workflows/claims.yml .github/ISSUE_TEMPLATE/claim.yml
git commit -m "claims: parse claim issues, keep one status comment per claim (Action)"
```

---

### Task 11: Generated docs — `helpmate-tables sync`

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/docs_sync.py`
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`sync`)
- Modify: `README.md`, `docs/CONTRIBUTING-TABLES.md`, `docs/COOPERATIVE-TABLEBASE.md`, `docs/hf-dataset-card.md` (wrap live numbers in spans)
- Create: `docs/MATERIALS.md`, `.all-contributorsrc` (generated)
- Test: `src/packages/api/tests/test_contrib_docs_sync.py`

**Interfaces:**
- Consumes: `universe`, `Registry`, `material_status`, `ClaimIndex`, `Hub.fetch_manifest()`, `Hub.open_pull_requests()`, `GitHub.claim_issues()`, local sidecars.
- Produces: `CorpusFacts.from_manifest(manifest, tables: Path)`; `facts.values() -> dict[str, str]` with keys `tables, gib, cells-billion, deepest, six-done, six-open, six-open-p0 … six-open-p4`; `replace_spans(text, values) -> str` (raises `KeyError` on an unknown key); `render_materials(statuses, registry) -> str`; `render_contributors(registry, statuses) -> str`; `all_contributors_rc(registry, gh) -> dict`; `sync(checkout, hub, gh, registry, tables) -> list[Path]` (files written); `close_finished_claims(gh, index, statuses) -> list[int]`; `SPAN_FILES = ["README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md", "docs/hf-dataset-card.md"]`.

Span syntax: `<!-- contrib:KEY -->value<!-- /contrib -->`. Multi-line spans
(the contributor table) use the same syntax across lines.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_docs_sync.py
import json
import os
from pathlib import Path

import pytest

from helpmate_server.contrib.claims import ClaimIndex, material_status
from helpmate_server.contrib.docs_sync import (
    CorpusFacts, render_contributors, render_materials, replace_spans,
)
from helpmate_server.contrib.registry import Registry

REPO = Path(__file__).resolve().parents[4]
CORPUS = Path(os.path.expanduser("~/tb"))


def test_replace_spans():
    t = "a <!-- contrib:x -->1<!-- /contrib --> b <!-- contrib:y -->\nold\n<!-- /contrib -->"
    assert replace_spans(t, {"x": "2", "y": "\nnew\n"}) == \
        "a <!-- contrib:x -->2<!-- /contrib --> b <!-- contrib:y -->\nnew\n<!-- /contrib -->"
    with pytest.raises(KeyError):
        replace_spans("<!-- contrib:nope -->1<!-- /contrib -->", {})


@pytest.mark.skipif(not (CORPUS / "manifest.json").exists(), reason="needs the real corpus")
def test_facts_reproduce_the_v0_20_0_numbers():
    f = CorpusFacts.from_manifest(json.loads((CORPUS / "manifest.json").read_text()), CORPUS)
    v = f.values()
    assert (v["tables"], v["gib"], v["six-done"], v["six-open"], v["six-open-p0"],
            v["deepest"], v["cells-billion"]) == ("317", "172.5", "31", "614", "269", "h#17", "713.9")


def _statuses(done):
    reg = Registry.load(REPO / "data" / "contributions.json")
    return material_status(set(done), {}, ClaimIndex([]), reg), reg


def test_materials_page_lists_all_1000():
    st, reg = _statuses({"KRBvkqq", "KQvk"})
    page = render_materials(st, reg)
    assert page.count("| K") >= 715          # every six-piece row
    assert "KRBvkqq" in page and "T31M" in page
    assert "## Six pieces" in page and "Kvkqqqq" in page


def test_contributor_table_lists_t31m():
    reg = Registry.load(REPO / "data" / "contributions.json")
    st, reg = _statuses(set(reg.tables))
    table = render_contributors(reg, st)
    assert "T31M" in table and "15" in table and "KRBvkqq" in table
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_contrib_docs_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.docs_sync`

- [ ] **Step 3: Implement `docs_sync.py`**

```python
# src/packages/api/helpmate_server/contrib/docs_sync.py
"""Everything the docs say about the corpus and its contributors, generated.

Prose stays hand-written; the numbers and credit lists inside it live in
<!-- contrib:KEY -->...<!-- /contrib --> spans that `sync` rewrites.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .materials import Material, universe

SPAN = re.compile(r"(<!-- contrib:([\w-]+) -->)(.*?)(<!-- /contrib -->)", re.S)
SPAN_FILES = ["README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md",
              "docs/hf-dataset-card.md"]
HF_USER = "https://huggingface.co/"
GH_USER = "https://github.com/"


def replace_spans(text: str, values: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return m.group(1) + values[m.group(2)] + m.group(4)
    return SPAN.sub(sub, text)


@dataclass
class CorpusFacts:
    files: dict[str, dict]
    max_dtm: int
    cells: int

    @classmethod
    def from_manifest(cls, manifest: dict, tables: Path) -> "CorpusFacts":
        files = manifest.get("files", {})
        max_dtm, cells = 0, 0
        for name in files:
            if name.endswith(".stats.json") and (tables / name).exists():
                sc = json.loads((tables / name).read_text())
                cells += 2 * int(sc["plane_size"])
                if sc["max_dtm"] < 253:
                    max_dtm = max(max_dtm, int(sc["max_dtm"]))
        return cls(files, max_dtm, cells)

    def done(self) -> set[str]:
        return {f[:-3] for f in self.files if f.endswith(".hm")}

    def values(self) -> dict[str, str]:
        done = self.done()
        six_real = [m for m in universe() if m.pieces == 6 and not m.bare_king]
        missing = [m for m in six_real if m.name not in done]
        v = {"tables": str(len(done)),
             "gib": f"{sum(x['size'] for x in self.files.values()) / 2**30:.1f}",
             "cells-billion": f"{self.cells / 1e9:.1f}",
             # 34 plies = h#17 (Black starts); 33 plies = h#16.5 (White starts)
             "deepest": f"h#{self.max_dtm // 2}" + (".5" if self.max_dtm % 2 else ""),
             "six-done": str(len(six_real) - len(missing)),
             "six-open": str(len(missing))}
        for p in range(5):
            v[f"six-open-p{p}"] = str(sum(m.pawns == p for m in missing))
        return v


ICON = {"done": "✅", "in review": "🔍", "claimed": "🚧", "open": "⬜", "not needed": "➖"}


def _who(reg, key: str | None) -> str:
    if not key:
        return ""
    c = reg.contributors.get(key)
    if c is None:
        return key
    return "anonymous" if c.anonymous else c.display


def render_materials(statuses: dict, reg) -> str:
    counts: dict[str, int] = {}
    for s in statuses.values():
        counts[s.state] = counts.get(s.state, 0) + 1
    out = ["# Materials", "",
           "Every material from three to six men and who computed it. Generated by "
           "`helpmate-tables sync` — do not edit by hand.", "",
           " · ".join(f"{ICON[k]} {k}: {counts.get(k, 0)}"
                      for k in ("done", "in review", "claimed", "open", "not needed")), ""]
    names = {3: "Three pieces", 4: "Four pieces", 5: "Five pieces"}
    for n, title in names.items():
        mats = [m for m in universe() if m.pieces == n]
        out += [f"## {title}", "",
                " ".join(f"{ICON[statuses[m.name].state]}&nbsp;`{m.name}`" for m in mats), ""]
    out += ["## Six pieces", "",
            "RAM tier: peak memory to generate (see CONTRIBUTING-TABLES.md). "
            "➖ = White has a bare king, no helpmate exists.", ""]
    six = [m for m in universe() if m.pieces == 6]
    for white in dict.fromkeys(m.white for m in six):
        out += [f"### K{white}", "", "| material | pawns | RAM | status | contributor | PR |",
                "|---|---|---|---|---|---|"]
        for m in (x for x in six if x.white == white):
            s = statuses[m.name]
            pr = f"[#{s.hf_pr}](https://huggingface.co/datasets/osick/helpmate-tables/discussions/{s.hf_pr})" \
                if s.hf_pr else ""
            label = s.state + (f" (#{s.claim})" if s.state == "claimed" and s.claim else "")
            out.append(f"| {m.name} | {m.pawns} | {m.ram_tier_gib} GiB | {ICON[s.state]} {label} "
                       f"| {_who(reg, s.contributor)} | {pr} |")
        out.append("")
    return "\n".join(out)


def _ranges(mats: list[str]) -> str:
    return ", ".join(mats)


def render_contributors(reg, statuses: dict) -> str:
    rows = ["", "| contributor | tables | notes |", "| --- | --- | --- |"]
    for key, c in sorted(reg.contributors.items(), key=lambda kv: -len(reg.tables_of(kv[0]))):
        mats = [m for m in reg.tables_of(key) if statuses.get(m) and statuses[m].state == "done"]
        if not mats:
            continue
        prs = sorted({reg.tables[m]["hf_pr"] for m in mats})
        name = "anonymous" if c.anonymous else (
            f"[**{c.display}**]({HF_USER}{c.hf})" if c.hf else f"**{c.display}**")
        links = ", ".join(f"[PR #{p}](https://huggingface.co/datasets/osick/helpmate-tables/discussions/{p})"
                          for p in prs)
        rows.append(f"| {name} | {len(mats)}: {_ranges(mats)} | {links}: {c.note} |")
    return "\n".join(rows) + "\n"


def all_contributors_rc(reg, gh) -> dict:
    people = []
    for key, c in sorted(reg.contributors.items()):
        if c.anonymous or not c.github or not reg.tables_of(key):
            continue
        people.append({"login": c.github, "name": c.display,
                       "avatar_url": f"https://avatars.githubusercontent.com/u/{gh.user_id(c.github)}?v=4",
                       "profile": f"{GH_USER}{c.github}", "contributions": ["data"]})
    return {"projectName": "helpmate-tablebase", "projectOwner": "osick", "repoType": "github",
            "files": ["README.md"], "contributorsPerLine": 7, "contributors": people}


def close_finished_claims(gh, index, statuses: dict) -> list[int]:
    closed = []
    for c in index.claims:
        if c.materials and all(statuses[m].state in ("done", "not needed") for m in c.materials):
            gh.close(c.issue, f"All {len(c.materials)} claimed tables are in the dataset. "
                              "Thank you! See docs/MATERIALS.md for the credits.")
            closed.append(c.issue)
    return closed


def sync(checkout: Path, hub, gh, reg, tables: Path, *, close_claims: bool = True) -> list[Path]:
    from .claims import Claim, ClaimIndex, material_status, parse_claim

    manifest = hub.fetch_manifest()
    facts = CorpusFacts.from_manifest(manifest, tables)
    claims = []
    for i in gh.claim_issues():
        mats, rel = parse_claim(f"{i['title']}\n{i.get('body') or ''}")
        claims.append(Claim(i["number"], i["user"]["login"], i["created_at"], mats, rel))
    index = ClaimIndex(claims)
    in_review = {m: pr for pr in hub.open_pull_requests() for m in pr.materials}
    statuses = material_status(facts.done(), in_review, index, reg)
    values = facts.values()
    values["contributors-table"] = render_contributors(reg, statuses)
    written = []
    for rel_path in SPAN_FILES:
        p = checkout / rel_path
        new = replace_spans(p.read_text(), values)
        if new != p.read_text():
            p.write_text(new)
            written.append(p)
    for p, text in ((checkout / "docs" / "MATERIALS.md", render_materials(statuses, reg)),
                    (checkout / ".all-contributorsrc",
                     json.dumps(all_contributors_rc(reg, gh), indent=2) + "\n")):
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
            written.append(p)
    if close_claims:
        close_finished_claims(gh, index, statuses)
    return written
```

(Remove the unused `Material` import if ruff flags it.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_docs_sync.py -v`
Expected: PASS. `test_facts_reproduce_the_v0_20_0_numbers` is the check that
the generated numbers mean what the hand-written ones meant; if `gib` comes
out 172.4 instead of 172.5, it is summing `.hm` only — it must sum every
manifest file (measured: 172.46).

- [ ] **Step 5: Put the spans into the docs**

Wrap each live number (only these; everything else stays prose):

| file:line (v0.20.0) | text now | becomes |
|---|---|---|
| README.md:9 | `**614 six-piece …` and `269 of them` | `**<!-- contrib:six-open -->614<!-- /contrib --> six-piece …`, `<!-- contrib:six-open-p0 -->269<!-- /contrib --> of them` |
| README.md:76 | `31 done, 614 to go` | `<!-- contrib:six-done -->31<!-- /contrib --> done, <!-- contrib:six-open -->614<!-- /contrib --> to go` |
| README.md:79-80 | `317 tables, 172.5 GiB`, `h#17` | spans `tables`, `gib`, `deepest` |
| docs/CONTRIBUTING-TABLES.md:7 | `**31 are done**` | span `six-done` |
| docs/CONTRIBUTING-TABLES.md:18 | `614 six-piece tables` | span `six-open` |
| docs/CONTRIBUTING-TABLES.md:22-26 | tier table column "tables missing" 269/28/4/97/216 | spans `six-open-p0`, `-p3`, `-p4`, `-p2`, `-p1` |
| docs/hf-dataset-card.md:30, :41, :44, :106 | 614 / 269 / 31 / 317 / 172.5 / h#17 | same spans |
| docs/COOPERATIVE-TABLEBASE.md:147 | `**614 six-piece classes` | span `six-open`; also wrap `713.9` (`cells-billion`) where it appears |
| docs/hf-dataset-card.md "## Contributors" table (lines 125-127) | the hand-written T31M table | `<!-- contrib:contributors-table -->` … `<!-- /contrib -->` around the whole table |
| README.md after the T31M paragraph (line 86) | — | add `### Contributors` + a `contributors-table` span |

Find any occurrence the table missed:
Run: `grep -nE "\b(614|269|317|172\.5|713\.9)\b|31 (done|are done|published)" README.md docs/*.md | grep -v "contrib:"`
Expected: no line that states a *current* corpus number (CHANGELOG-style
history lines like "302 -> 317" are history and stay as they are).

- [ ] **Step 6: Add `sync` to the CLI and run it once**

In `add_parsers`:

```python
    s = sub.add_parser("sync", help="(maintainer) regenerate MATERIALS.md, credits and counts")
    s.add_argument("--tables", required=True, metavar="DIR")
    s.add_argument("--checkout", type=Path, default=Path("."))
    s.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    s.add_argument("--github-repo", default=GITHUB_REPO)
    s.add_argument("--no-close", action="store_true", help="do not close finished claims")
```

In `run`:

```python
        if a.cmd == "sync":
            from .docs_sync import sync
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            checkout = Path(a.checkout)
            if not (checkout / "data" / "contributions.json").exists():
                raise UsageError(f"{checkout} is not a helpmate-tablebase checkout")
            for p in sync(checkout, (hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                          Registry.load(checkout / "data" / "contributions.json"),
                          Path(a.tables).expanduser(), close_claims=not a.no_close):
                print(f"wrote {p}")
            return 0
```

Run (maintainer box, network; `--no-close` so this first run changes nothing on GitHub):
`helpmate-tables sync --tables ~/tb --no-close`
Expected: `wrote docs/MATERIALS.md`, `wrote .all-contributorsrc`, and
`git diff README.md docs/` shows only the contributor table's re-rendering
(numbers unchanged: they already match). Read the diff; fix the renderer if
the T31M row lost information.

- [ ] **Step 7: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{docs_sync,cli}.py src/packages/api/tests/test_contrib_docs_sync.py \
        README.md docs/CONTRIBUTING-TABLES.md docs/COOPERATIVE-TABLEBASE.md docs/hf-dataset-card.md \
        docs/MATERIALS.md .all-contributorsrc
git commit -m "helpmate-tables sync: MATERIALS.md (1000 materials), generated counts and credits"
```

---

### Task 12: `helpmate-tables accept` and `status`

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/accept.py`
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`accept`, `status`)
- Test: `src/packages/api/tests/test_contrib_accept.py`

**Interfaces:**
- Consumes: `Hub` (`pull_request`, `merge`, `main_files`, `read_bytes`, `fetch_manifest`, `commit`), `GitHub` (`issue`, `comment`, `user_id`, `close`), `Registry`, `resolve_contributor`, `ClaimIndex`/`parse_claim`, `docs_sync.sync`, staging reports from Task 7.
- Produces: `manifest_from_hub(hub, generator_version) -> dict`; `add_changelog_data(text, line) -> str`; `class Git` (subprocess wrapper; methods `clean() -> bool`, `start_branch(name)`, `commit_all(message)`, `push(branch)`, `open_pr(title, body) -> str`, `wait_and_merge(url)`, `back(ref)`), and `accept(prs, *, hub, gh, git, checkout, tables, staging, contributor, today) -> int`; `status(hub, gh, registry, staging, checkout) -> str`. State file: `<staging>/accept-<n1>-<n2>….json` with `{"done": [step, ...], "contributor": key, "docs_pr": url}`; steps in order `merge`, `manifest`, `local`, `docs` (includes the dataset-card upload), `claims`.

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_accept.py
import json

import pytest

from fakes import FakeGitHub, FakeHub
from helpmate_server.contrib.accept import accept, add_changelog_data, manifest_from_hub


class FakeGit:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at

    def _do(self, name, *a):
        self.calls.append((name, *a))
        if name == self.fail_at:
            raise RuntimeError(f"{name} failed")

    def clean(self): return True
    def current(self): return "main"
    def start_branch(self, name): self._do("start_branch", name)
    def commit_all(self, message): self._do("commit_all", message)
    def push(self, branch): self._do("push", branch)
    def open_pr(self, title, body): self._do("open_pr", title); return "https://gh/pr/1"
    def wait_and_merge(self, url): self._do("wait_and_merge", url)
    def back(self, ref): self._do("back", ref)


def _setup(tmp_path, head="abc", report_head="abc", result="pass"):
    checkout = tmp_path / "repo"
    (checkout / "data").mkdir(parents=True)
    (checkout / "docs").mkdir()
    (checkout / "data" / "contributions.json").write_text(
        '{"schema":1,"contributors":{},"tables":{}}')
    (checkout / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n## [0.20.0] - x\n")
    for f in ("README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md",
              "docs/hf-dataset-card.md"):
        (checkout / f).write_text("x\n")
    staging = tmp_path / "st"
    d = staging / "pr-2"
    (d / "files").mkdir(parents=True)
    (d / "files" / "KRRvkqq.hm").write_bytes(b"table")
    (d / "files" / "KRRvkqq.stats.json").write_text('{"generator_version": "0.20.0", "plane_size": 1, "max_dtm": 9}')
    (d / "report.json").write_text(json.dumps({"result": result, "head": report_head, "pr": 2}))
    hub = FakeHub({"manifest.json": b'{"schema":1,"generator_version":"0.19.0","files":{}}'})
    hub.add_pr(2, {"KRRvkqq.hm": b"table", "KRRvkqq.stats.json": (d / "files" / "KRRvkqq.stats.json").read_bytes()},
               head=head, description="")
    gh = FakeGitHub([{"number": 39, "title": "claim: KRR", "body": "KRRvk??",
                      "user": {"login": "popeye37"}, "created_at": "2026-09-20T00:00:00Z",
                      "labels": [], "state": "open"}])
    tables = tmp_path / "tb"
    tables.mkdir()
    return checkout, staging, hub, gh, tables


def _run(checkout, staging, hub, gh, tables, git, **kw):
    return accept([2], hub=hub, gh=gh, git=git, checkout=checkout, tables=tables,
                  staging=staging, contributor=kw.get("contributor"), today="2026-10-01")


def test_accept_happy_path(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == [2]
    man = json.loads(hub.main["manifest.json"])
    assert "KRRvkqq.hm" in man["files"] and man["generator_version"] == "0.19.0"
    assert (tables / "KRRvkqq.hm").read_bytes() == b"table"
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "popeye37"
    assert reg["tables"]["KRRvkqq"]["claim"] == 39                 # found via the claims index
    assert "### Data" in (checkout / "CHANGELOG.md").read_text()
    commit_msg = next(c[1] for c in git.calls if c[0] == "commit_all")
    assert "Co-authored-by: popeye37 <1008+popeye37@users.noreply.github.com>" in commit_msg
    assert ("wait_and_merge", "https://gh/pr/1") in git.calls
    assert any(n == 39 and "KRRvkqq" in body for n, body in gh.posted)


def test_accept_refuses_a_pr_changed_after_verification(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path, head="new", report_head="old")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "old" in capsys.readouterr().err


def test_accept_refuses_a_failed_report(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path, result="fail")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2 and hub.merged == []


def test_accept_resumes_after_ci_failure_without_merging_twice(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="wait_and_merge"))
    assert hub.merged == [2]
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == [2]                                     # not merged again
    assert [c[0] for c in git.calls] == ["wait_and_merge", "back"]   # resumes at the docs PR


def test_unknown_contributor_stops_before_merging(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    gh.issues.clear()
    hub.prs[2][0].author = "stranger"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "--contributor" in capsys.readouterr().err


def test_changelog_data_entry_goes_under_unreleased():
    text = "# C\n\n## [Unreleased]\n\n## [0.20.0] - x\n"
    out = add_changelog_data(text, "- KRRvkqq by popeye37")
    assert out.index("### Data") < out.index("## [0.20.0]")
    assert add_changelog_data(out, "- KRRvkqr by popeye37").count("### Data") == 1


def test_manifest_from_hub_hashes_non_lfs_files():
    hub = FakeHub({"a.hm": b"1", "a.stats.json": b"{}", "README.md": b"x"})
    m = manifest_from_hub(hub, "0.19.0")
    assert set(m["files"]) == {"a.hm", "a.stats.json"} and m["schema"] == 1
```

(`FakeGitHub.user_id("popeye37")` is `1000 + len("popeye37") = 1008`.)

`sync` is called inside `accept`; in these tests it runs against the fake hub
and the stub docs (no spans), writing `docs/MATERIALS.md` and
`.all-contributorsrc` into the temporary checkout.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_contrib_accept.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.accept`

- [ ] **Step 3: Implement `accept.py`**

```python
# src/packages/api/helpmate_server/contrib/accept.py
"""accept: merge verified dataset PRs and land the bookkeeping.

Each step is recorded in a state file as it completes, so a rerun after a
failure (network, CI) resumes where it stopped and never merges twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .claims import Claim, ClaimIndex, parse_claim
from .links import parse_links
from .registry import Registry, resolve_contributor

STEPS = ("merge", "manifest", "local", "docs", "claims")


def manifest_from_hub(hub, generator_version: str) -> dict:
    files = {}
    for path, meta in sorted(hub.main_files().items()):
        if not path.endswith((".hm", ".stats.json")):
            continue
        sha = meta.sha256 or hashlib.sha256(hub.read_bytes(path)).hexdigest()
        files[path] = {"sha256": sha, "size": meta.size}
    return {"schema": 1, "generator_version": generator_version, "files": files}


def add_changelog_data(text: str, line: str) -> str:
    m = re.search(r"^## \[Unreleased\]\n", text, re.M)
    if not m:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' section")
    nxt = re.search(r"^## \[", text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    section = text[m.end():end]
    if "### Data\n" in section:
        i = m.end() + section.index("### Data\n") + len("### Data\n")
        return text[:i] + line + "\n" + text[i:]
    return text[:m.end()] + "\n### Data\n" + line + "\n" + text[m.end():]


class Git:
    """git and gh as the maintainer runs them (see Global Constraints: pushes
    bypass the global config that rewrites HTTPS to SSH)."""

    def __init__(self, checkout: Path):
        self.cwd = checkout

    def _run(self, *args: str, env: dict | None = None) -> str:
        return subprocess.run(args, cwd=self.cwd, check=True, capture_output=True, text=True,
                              env={**os.environ, **(env or {})}).stdout.strip()

    def clean(self) -> bool:
        return self._run("git", "status", "--porcelain") == ""

    def current(self) -> str:
        return self._run("git", "rev-parse", "--abbrev-ref", "HEAD")

    def start_branch(self, name: str) -> None:
        self._run("git", "fetch", "origin", "main", env={"GIT_CONFIG_GLOBAL": "/dev/null"})
        self._run("git", "switch", "-C", name, "origin/main")

    def commit_all(self, message: str) -> None:
        self._run("git", "add", "-A")
        self._run("git", "commit", "-m", message)

    def push(self, branch: str) -> None:
        self._run("git", "-c", "credential.helper=",
                  "-c", "credential.helper=!gh auth git-credential",
                  "push", "-u", "origin", branch, env={"GIT_CONFIG_GLOBAL": "/dev/null"})

    def open_pr(self, title: str, body: str) -> str:
        return self._run("gh", "pr", "create", "--base", "main", "--title", title, "--body", body)

    def wait_and_merge(self, url: str) -> None:
        subprocess.run(["gh", "pr", "checks", url, "--watch", "--fail-fast"], cwd=self.cwd, check=True)
        self._run("gh", "pr", "merge", url, "--squash", "--delete-branch")

    def back(self, ref: str) -> None:
        self._run("git", "switch", ref)


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _claims(gh) -> ClaimIndex:
    out = []
    for i in gh.claim_issues():
        mats, rel = parse_claim(f"{i['title']}\n{i.get('body') or ''}")
        out.append(Claim(i["number"], i["user"]["login"], i["created_at"], mats, rel))
    return ClaimIndex(out)


def accept(prs: list[int], *, hub, gh, git, checkout: Path, tables: Path, staging: Path,
           contributor: str | None, today: str) -> int:
    from .docs_sync import sync

    state_path = staging / f"accept-{'-'.join(map(str, sorted(prs)))}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}

    def mark(step: str, **extra) -> None:
        state["done"].append(step)
        state.update(extra)
        state_path.write_text(json.dumps(state, indent=2))

    reg_path = checkout / "data" / "contributions.json"
    pulls = {n: hub.pull_request(n) for n in prs}
    index = _claims(gh)

    if "merge" not in state["done"]:
        if not git.clean():
            return _err(f"{checkout} has uncommitted changes")
        reg = Registry.load(reg_path)
        people = {}
        for n, pr in pulls.items():
            rep_path = staging / f"pr-{n}" / "report.json"
            if not rep_path.exists():
                return _err(f"PR #{n} has no verification report; run verify --pr {n}")
            rep = json.loads(rep_path.read_text())
            if rep["result"] != "pass":
                return _err(f"PR #{n}: the last verification failed")
            if pr.status != "open":
                return _err(f"PR #{n} is {pr.status}")
            if rep.get("head") != pr.head:
                return _err(f"PR #{n} changed after verification (verified {rep.get('head')}, "
                            f"now {pr.head}); run verify --pr {n} again")
            claim_no = parse_links(pr.description)[0]
            claim = next((c for c in index.claims if c.issue == claim_no), None) \
                or (index.claim_for(pr.materials[0]) if pr.materials else None)
            who = resolve_contributor(reg, pr, claim.author if claim else None, contributor)
            if who is None:
                return _err(f"PR #{n} by HF user {pr.author}: no GitHub identity found; "
                            "pass --contributor LOGIN")
            people[n] = {"key": who.key, "github": who.github, "hf": who.hf,
                         "display": who.display, "claim": claim.issue if claim else None}
        for n in prs:
            hub.merge(n)
        mark("merge", people={str(k): v for k, v in people.items()})

    people = {int(k): v for k, v in state["people"].items()}

    if "manifest" not in state["done"]:
        old = hub.fetch_manifest()
        man = manifest_from_hub(hub, old.get("generator_version", "unknown"))
        hub.commit({"manifest.json": json.dumps(man, indent=2, sort_keys=True).encode()},
                   f"Manifest after merging PR(s) {', '.join(f'#{n}' for n in prs)}")
        mark("manifest")

    if "local" not in state["done"]:
        for n, pr in pulls.items():
            for f in pr.files:
                src = staging / f"pr-{n}" / "files" / f
                if src.exists():
                    os.replace(src, tables / f)
        mark("local")

    if "docs" not in state["done"]:
        branch = "data/accept-" + "-".join(map(str, sorted(prs)))
        original = git.current()
        if "docs_pr" not in state:
            git.start_branch(branch)
            from .registry import Contributor
            reg = Registry.load(reg_path)
            lines = []
            for n, pr in pulls.items():
                p = people[n]
                if p["key"] not in reg.contributors:
                    reg.add_contributor(Contributor(p["key"], p["github"], p["hf"], p["display"]))
                rep = json.loads((staging / f"pr-{n}" / "report.json").read_text())
                for m in pr.materials:
                    sc = json.loads((tables / f"{m}.stats.json").read_text())
                    reg.record_table(m, contributor=p["key"], hf_pr=n, claim=p["claim"],
                                     merged=today, generator_version=sc.get("generator_version", ""),
                                     verification={"tool": rep.get("tool"), "head": rep.get("head"),
                                                   "seed": rep.get("seed"), "result": rep["result"]})
                lines.append(f"- {', '.join(pr.materials)} contributed by {p['display']} "
                             f"(dataset PR #{n}" + (f", claim #{p['claim']}" if p["claim"] else "") + ").")
            reg.save()
            cl = checkout / "CHANGELOG.md"
            text = cl.read_text()
            for line in lines:
                text = add_changelog_data(text, line)
            cl.write_text(text)
            sync(checkout, hub, gh, reg, tables, close_claims=False)
            hub.commit({"README.md": (checkout / "docs" / "hf-dataset-card.md").read_bytes()},
                       "Dataset card: contributors and counts")
            trailers = sorted({f"Co-authored-by: {p['github']} <{gh.user_id(p['github'])}+"
                               f"{p['github']}@users.noreply.github.com>"
                               for p in people.values()
                               if p["github"] and not reg.contributors[p["key"]].anonymous})
            mats = [m for pr in pulls.values() for m in pr.materials]
            title = f"Data: {len(mats)} table(s) from dataset PR(s) {', '.join(f'#{n}' for n in prs)}"
            git.commit_all(title + "\n\n" + "\n".join(lines) + "\n\n" + "\n".join(trailers))
            git.push(branch)
            state["docs_pr"] = git.open_pr(title, "\n".join(lines))
            state_path.write_text(json.dumps(state, indent=2))
        git.wait_and_merge(state["docs_pr"])
        git.back(original)
        mark("docs")

    if "claims" not in state["done"]:
        for n, pr in pulls.items():
            c = people[n]["claim"]
            if c is not None:
                gh.comment(c, f"Accepted: {', '.join(pr.materials)} ([HF PR #{n}]({pr.url})) — "
                              f"now in the dataset and credited in docs/MATERIALS.md. Thank you!")
        from .docs_sync import close_finished_claims
        from .claims import material_status
        reg = Registry.load(reg_path)
        done = {f[:-3] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}
        idx = _claims(gh)
        close_finished_claims(gh, idx, material_status(done, {}, idx, reg))
        mark("claims")
    state_path.unlink()
    return 0
```

The spec's card upload is part of the `docs` step (it happens right after
`sync` rendered the card).

Note on the resume test: after `wait_and_merge` raised, `docs_pr` is in the
state file, so the rerun calls only `wait_and_merge` and `back` — matching
the test's expected call list.

- [ ] **Step 4: `status` and CLI wiring**

Append to `accept.py`:

```python
def status(hub, gh, registry, staging: Path, checkout: Path) -> str:
    index = _claims(gh)
    rows = ["| HF PR | author | materials | claim | verification | |", "|---|---|---|---|---|---|"]
    for pr in hub.open_pull_requests():
        rep_path = staging / f"pr-{pr.num}" / "report.json"
        if rep_path.exists():
            rep = json.loads(rep_path.read_text())
            ver = rep["result"] + ("" if rep.get("head") == pr.head else " (stale: PR changed)")
        else:
            ver = "not verified"
        c = parse_links(pr.description)[0] or (
            index.claim_for(pr.materials[0]).issue if pr.materials and index.claim_for(pr.materials[0]) else None)
        rows.append(f"| #{pr.num} | {pr.author} | {', '.join(pr.materials)} | "
                    f"{'#' + str(c) if c else '—'} | {ver} | |")
    try:
        last = subprocess.run(["git", "log", "-1", "--format=%cs", "--", "docs/DEEPEST.json"],
                              cwd=checkout, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        last = ""
    newer = sum(1 for t in registry.tables.values() if last and t["merged"] > last)
    rows += ["", f"{newer} contributed table(s) merged since the last DEEPEST refresh ({last or '?'})."]
    return "\n".join(rows)
```

In `cli.add_parsers`:

```python
    ac = sub.add_parser("accept", help="(maintainer) merge verified dataset PRs and credit them")
    ac.add_argument("pr", type=int, nargs="+")
    ac.add_argument("--tables", required=True, metavar="DIR")
    ac.add_argument("--contributor", metavar="GITHUB_LOGIN")
    ac.add_argument("--checkout", type=Path, default=Path("."))
    ac.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ac.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    ac.add_argument("--github-repo", default=GITHUB_REPO)
    st = sub.add_parser("status", help="(maintainer) open dataset PRs, claims, verification")
    st.add_argument("--checkout", type=Path, default=Path("."))
    st.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    st.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    st.add_argument("--github-repo", default=GITHUB_REPO)
```

In `run`:

```python
        if a.cmd in ("accept", "status"):
            from datetime import date
            from .accept import Git, accept, status
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            checkout = Path(a.checkout).resolve()
            if not (checkout / "data" / "contributions.json").exists():
                raise UsageError(f"{checkout} is not a helpmate-tablebase checkout")
            hub = (hub_factory or Hub)(a.repo)
            gh = (gh_factory or GitHub)(a.github_repo)
            if a.cmd == "status":
                print(status(hub, gh, Registry.load(checkout / "data" / "contributions.json"),
                             Path(a.staging).expanduser(), checkout))
                return 0
            return accept(a.pr, hub=hub, gh=gh, git=Git(checkout), checkout=checkout,
                          tables=Path(a.tables).expanduser(), staging=Path(a.staging).expanduser(),
                          contributor=a.contributor, today=date.today().isoformat())
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_accept.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Live read-only check (maintainer box)**

Run: `helpmate-tables status`
Expected: 14 rows #2–#15 by popeye37, claim `#39` found through the claims
index, verification "not verified"; the DEEPEST line.

- [ ] **Step 7: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{accept,cli}.py src/packages/api/tests/test_contrib_accept.py
git commit -m "helpmate-tables accept and status: resumable merge, manifest, credits, docs PR"
```

---

### Task 13: Contributor docs, CHANGELOG, full verification

**Files:**
- Modify: `docs/CONTRIBUTING-TABLES.md`, `CHANGELOG.md`, `docs/superpowers/specs/2026-09-30-contribution-pipeline-design.md`

- [ ] **Step 1: Rewrite the contributor steps in `docs/CONTRIBUTING-TABLES.md`**

- Step 1 ("Claim it first"): "Open an issue with the **Claim a material**
  form" (link `../../issues/new?template=claim.yml`); patterns `KQvk???`
  allowed; a bot keeps the status; strike a name through (`~~KRRvkpp~~`) to
  hand it over; point to docs/MATERIALS.md for what is open.
- Step 4 ("Sanity-check") becomes:

```bash
pip install './src/packages/api[verify]'    # once; `make install` already does it
helpmate-tables verify --tables ./tables --material KBBBvkb
```

  with one paragraph: the same checks the maintainer runs, V2–V7, a few
  minutes for a pawnless six-piece table; a ❌ means do not submit.
- Step 5's push command gains `--claim <issue> --github <your login>`, and
  the "Close the loop yourself" paragraph says those two flags do it.
- "What gets checked before a merge": replace the four bullets with a V1–V7
  list (one line each, as in the spec) and keep the honest paragraph that
  full correctness still needs regeneration and that the C++ oracle
  (`helpmate verify`) is the best code contribution still open.
- New final section "## For the maintainer":

```
helpmate-tables status                                  # what is waiting
helpmate-tables verify --tables ~/tb --pr 2 3 4         # asks before downloading; posts reports
helpmate-tables accept 2 3 4 --tables ~/tb              # merge, manifest, credits, docs PR
```

  plus: refresh DEEPEST/site/booklet when `status` reports enough new tables
  (commands from the existing regeneration chain:
  `tools/deepest_showcase.py … && make docs-deepest && python3 tools/build_site_data.py --tables ~/tb`).

- [ ] **Step 2: CHANGELOG `[Unreleased]`**

```markdown
## [Unreleased]

### Added
- `helpmate-tables verify`: seven checks on a contributed table (PR contents,
  header and identity, zstd blocks, sidecar recomputed from the payload,
  deepest positions, local consistency with successors and sub-tables, and an
  independent python-chess solver). Contributors run it with `--material`
  before pushing; the maintainer runs it with `--pr`, which downloads the
  dataset PR (after confirming its size) and posts the report.
- `helpmate-tables accept`, `status`, `sync`, `claims`; `push --claim --github`.
- Claim issue form and a Claims workflow that keeps one status comment per claim.
- `docs/MATERIALS.md`: all 1000 materials from three to six men, with status
  and contributor; `data/contributions.json` as the record behind it.

### Changed
- Corpus counts in README, CONTRIBUTING-TABLES, COOPERATIVE-TABLEBASE and the
  dataset card are generated (`helpmate-tables sync`).
- `tools/verify_corpus.py` is a wrapper over the package's block check.
```

- [ ] **Step 3: Align the spec with two facts found while planning**

In the spec: (a) "Terms": replace the marker sentence with "A material whose
White side is a bare king is **not needed** (no helpmate possible): 70 of the
715 six-piece materials, so 645 need a real table. Other materials can also
turn out to have no helpmate (the generator then writes a marker table);
that is only known after generation."; (b) component 3: the workflow does
`pip install huggingface_hub` (no C++ build) instead of "no `pip install`".

- [ ] **Step 4: Full verification**

Run each; all must succeed:

```bash
python -m pytest src/packages/api/tests tests/repo -q
python -m pytest src/packages/api/tests -q --cov=helpmate_server.contrib --cov-report=term-missing
ruff check src/packages/api tools
mypy src/packages/api/helpmate_server/contrib
```

Expected: all tests pass (corpus-dependent tests pass on the maintainer box);
coverage of `helpmate_server.contrib` ≥ 80 % (if `pytest-cov` is missing:
`pip install pytest-cov`); ruff and mypy clean. Paste the coverage total into
the PR description.

- [ ] **Step 5: Break-it check (per the project's verification lessons)**

Temporarily change `check_position`'s `min(255, ...)` to `min(254, ...)`;
run `python -m pytest src/packages/api/tests/test_contrib_consistency.py -q`
→ must FAIL on the saturated KQvk positions; revert. Temporarily make
`recompute_stats` skip `DTM_INVALID` counting; run the checks test → must
FAIL; revert. Record both in the PR description.

- [ ] **Step 6: Commit and open the PR**

```bash
git add docs/CONTRIBUTING-TABLES.md CHANGELOG.md docs/superpowers/specs/2026-09-30-contribution-pipeline-design.md
git commit -m "docs: contributor and maintainer workflow for helpmate-tables verify/accept"
GIT_CONFIG_GLOBAL=/dev/null git -c credential.helper= -c 'credential.helper=!gh auth git-credential' \
    push -u origin HEAD
gh pr create --base main --title "Contribution pipeline: verify, accept, claims, MATERIALS.md" \
    --body-file <(printf '%s\n\n%s\n' "Implements docs/superpowers/specs/2026-09-30-contribution-pipeline-design.md." "🤖 Generated with [Claude Code](https://claude.com/claude-code)")
```

After merge, the first `issues`/`schedule` event runs the Claims workflow:
check its log and the comments it posted on #39, #40, #41, #45 — that is
the workflow's real test.

- [ ] **Step 7: First live use (maintainer, not part of the PR)**

`helpmate-tables verify --tables ~/tb --pr 2` (confirm the download) → read
the report → if it passes, `verify` the rest (`--pr 3 … 15`) → `accept 2 … 15
--tables ~/tb`. In issue #39, strike `KRRvkpp` through (handed to T31M).

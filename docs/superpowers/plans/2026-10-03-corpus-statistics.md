# Corpus Statistics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish all per-table statistics as two Parquet files on Hugging Face and as a Statistics screen on the site, both refreshed by every `helpmate-tables accept`, with guards that catch a missed refresh.

**Architecture:** One pure module (`contrib/corpus_stats.py`) turns the `.stats.json` sidecars plus `data/contributions.json` into rows, Parquet bytes and a compact site JSON. `site_data.write_site_data` (already called by `sync`, `accept`'s docs step and `tools/build_site_data.py`) also writes `site/data/stats.json`; `accept`'s card step also uploads the Parquet files; a new `helpmate-tables stats-push` uploads/checks by hand. The site gets a `#/stats` screen drawn as plain SVG. A repo test (blocking, every PR) and a daily workflow (alerting) catch stale statistics.

**Tech Stack:** Python 3.11/3.12, pyarrow ≥ 14 (optional `verify` extra), huggingface_hub, pytest; vanilla ES modules, `node --test`; Playwright (Python) with `--no-sandbox`.

**Spec:** `docs/superpowers/specs/2026-10-03-corpus-statistics-design.md`

## Global Constraints

- Branch `feat/corpus-statistics` (exists, holds the spec). Never push to GitHub, never write to Hugging Face from tests: use `src/packages/api/tests/fakes.py` (`FakeHub`, `FakeGitHub`).
- `helpmate-tables` must stay importable without pyarrow: import pyarrow only inside functions.
- pyarrow (≥ 14) goes into the optional `verify` extra of `src/packages/api/pyproject.toml`.
- Parquet paths on Hugging Face: exactly `stats/materials.parquet` and `stats/histogram.parquet`.
- Site data file: `site/data/stats.json`, committed; bounded at 1 MB by a test.
- No chart library on the site; charts are SVG strings from `site/js/lib/charts.js`, colours from existing CSS variables.
- Statistics never describe a partial corpus: local `*.stats.json` (with `.hm`) must equal the manifest's `.hm` set before Parquet is uploaded.
- `accept` never fails because the local corpus is incomplete for statistics (skip + message); it does fail the card step if an upload happened and the post-check shows a mismatch.
- Contributor column: the registry's `display`, `anonymous` if the contributor is anonymous, `maintainer` if the table has no registry entry.
- Run Python tests with the working tree: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest …` (the user's installed copy in `~/.local` is not the tree).
- Commit trailer on every commit:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_0134BpWPYmTJCmwDwzWPA2BS
  ```
- Final checks: `python -m pytest src/packages/api/tests tests/repo -q --deselect tests/repo/test_deepest_render.py::test_booklet_compiles`, `ruff check src/packages/api tools`, `mypy src/packages/api/helpmate_server/contrib`, `make test-site`, coverage of `corpus_stats.py` ≥ 80 %.

## Review Focus

1. **Marker tables** (`all_unsolvable: true`, `max_dtm` 255, empty histograms): must appear in `materials.parquet` with `marker=True`, `max_dtm` null, and produce no histogram rows; the site picker shows "no helpmate in this material". → tests in Task 1 and Task 7.
2. **A `.stats.json` without its `.hm`** (half-downloaded corpus) must be ignored, exactly like `site_data.material_rows`. → test in Task 1.
3. **Stats on Hugging Face missing entirely** (first run, before any upload): `stats-push --check` reports "missing", `stats-push` uploads, the accept post-check does not crash. → tests in Task 4 and Task 5.
4. **Unknown material in the URL** (`#/stats/Nonsense`) or an empty input: the screen shows a short message, not a blank page or an exception. → test in Task 7.
5. **Log scale with zero cells at some depth** (gaps in the histogram, e.g. no wtm cells at even depths): no `-Infinity`/`NaN` in the SVG. → test in Task 6.

---

### Task 1: `corpus_stats` rows and site JSON

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/corpus_stats.py`
- Test: `src/packages/api/tests/test_contrib_corpus_stats.py`

**Interfaces:**
- Consumes: `helpmate_server.contrib.materials.Material` (`.white`, `.black` without kings, `.pieces`, `.pawns`); `helpmate_server.contrib.registry.Registry` (`.tables: dict[str, dict]` with keys `contributor`, `hf_pr`, `merged`; `.contributors: dict[str, Contributor]` with `.display`, `.anonymous`).
- Produces:
  - `@dataclass class TableStats: material: str; stats: dict; size_bytes: int`
  - `collect(tables: Path) -> list[TableStats]` — sidecars with an `.hm`, sorted by `(pieces, material)`
  - `is_marker(stats: dict) -> bool`
  - `contributor_of(material: str, registry: Registry | None) -> tuple[str, int | None, str | None]` — (contributor, hf_pr, merged)
  - `materials_rows(ts: list[TableStats], registry: Registry | None) -> list[dict]`
  - `histogram_rows(ts: list[TableStats]) -> list[dict]`
  - `site_stats(ts: list[TableStats]) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_corpus_stats.py
import json
from pathlib import Path

from helpmate_server.contrib.corpus_stats import (
    collect, contributor_of, histogram_rows, is_marker, materials_rows, site_stats)
from helpmate_server.contrib.registry import Registry

KQVK = {"material": "KQvk", "plane_size": 1000, "max_dtm": 3, "generator_version": "0.6.1",
        "cells": {"invalid": {"wtm": 10, "btm": 20}, "unsolvable": {"wtm": 0, "btm": 5}},
        "dtm_histogram": {"wtm": {"1": 4, "3": 6}, "btm": {"0": 2, "2": 8}},
        "uniqueness": {"wtm": {"1": {"1": 3, "2": 1}, "3": {"255": 6}},
                       "btm": {"0": {"1": 2}, "2": {"1": 5, "7": 3}}},
        "deepest": [], "deepest_unique": []}
MARKER = {"material": "Kvkq", "all_unsolvable": True, "plane_size": 500, "max_dtm": 255,
          "generator_version": "0.20.0",
          "cells": {"invalid": {"wtm": 0, "btm": 0}, "unsolvable": {"wtm": 500, "btm": 500}},
          "dtm_histogram": {"wtm": {}, "btm": {}}, "uniqueness": {"wtm": {}, "btm": {}},
          "deepest": [], "deepest_unique": []}
KPVK = dict(KQVK, material="KPvk", generator_version="0.20.0-t31m")


def _put(d: Path, stats: dict, size: int = 100, hm: bool = True) -> None:
    (d / f"{stats['material']}.stats.json").write_text(json.dumps(stats))
    if hm:
        (d / f"{stats['material']}.hm").write_bytes(b"x" * size)


def _registry(tmp_path: Path) -> Registry:
    data = {"schema": 1,
            "contributors": {"T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"},
                             "anon": {"github": "a", "hf": "a", "display": "A", "anonymous": True}},
            "tables": {"KPvk": {"contributor": "T31M", "hf_pr": 18, "merged": "2026-10-04"},
                       "Kvkq": {"contributor": "anon", "hf_pr": 3, "merged": "2026-09-30"}}}
    p = tmp_path / "contributions.json"
    p.write_text(json.dumps(data))
    return Registry.load(p)


def test_collect_skips_sidecars_without_a_table_and_sorts(tmp_path):
    _put(tmp_path, KPVK)
    _put(tmp_path, MARKER)
    _put(tmp_path, KQVK)
    _put(tmp_path, dict(KQVK, material="KRvk"), hm=False)   # half-downloaded
    assert [t.material for t in collect(tmp_path)] == ["Kvkq", "KPvk", "KQvk"]


def test_marker_detection():
    assert is_marker(MARKER) and not is_marker(KQVK)
    assert is_marker(dict(KQVK, max_dtm=255))


def test_contributor_lookup(tmp_path):
    reg = _registry(tmp_path)
    assert contributor_of("KPvk", reg) == ("T31M", 18, "2026-10-04")
    assert contributor_of("Kvkq", reg) == ("anonymous", 3, "2026-09-30")
    assert contributor_of("KQvk", reg) == ("maintainer", None, None)
    assert contributor_of("KQvk", None) == ("maintainer", None, None)


def test_materials_rows(tmp_path):
    _put(tmp_path, KQVK, size=123)
    _put(tmp_path, MARKER, size=7)
    rows = {r["material"]: r for r in materials_rows(collect(tmp_path), _registry(tmp_path))}
    q = rows["KQvk"]
    assert q == {"material": "KQvk", "pieces": 3, "pawns": 0, "white": "Q", "black": "",
                 "marker": False, "max_dtm": 3, "plane_size": 1000,
                 "invalid_wtm": 10, "invalid_btm": 20, "unsolvable_wtm": 0, "unsolvable_btm": 5,
                 "solvable": 2000 - 30 - 5, "unique": 3 + 2 + 5, "size_bytes": 123,
                 "generator_version": "0.6.1", "contributor": "maintainer",
                 "hf_pr": None, "merged": None}
    m = rows["Kvkq"]
    assert m["marker"] is True and m["max_dtm"] is None
    assert m["solvable"] == 0 and m["unique"] == 0 and m["contributor"] == "anonymous"


def test_minimal_sidecar_is_tolerated(tmp_path):
    _put(tmp_path, {"material": "KRRvkqq", "plane_size": 1, "max_dtm": 9, "generator_version": "0.20.0"})
    (row,) = materials_rows(collect(tmp_path), None)
    assert row["solvable"] == 2 and row["unique"] == 0 and row["invalid_wtm"] == 0
    assert histogram_rows(collect(tmp_path)) == []
    assert site_stats(collect(tmp_path))["materials"]["KRRvkqq"]["wtm"] == []


def test_histogram_rows_are_lossless_and_skip_markers(tmp_path):
    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    rows = histogram_rows(collect(tmp_path))
    assert {r["material"] for r in rows} == {"KQvk"}
    assert sorted((r["stm"], r["dtm"], r["count"], r["cells"]) for r in rows) == [
        ("btm", 0, 1, 2), ("btm", 2, 1, 5), ("btm", 2, 7, 3),
        ("wtm", 1, 1, 3), ("wtm", 1, 2, 1), ("wtm", 3, 255, 6)]
    assert all(r["pieces"] == 3 for r in rows)
    # lossless: cells per depth add up to the sidecar's dtm_histogram
    for stm in ("wtm", "btm"):
        for d, n in KQVK["dtm_histogram"][stm].items():
            assert sum(r["cells"] for r in rows if r["stm"] == stm and r["dtm"] == int(d)) == n


def test_site_stats_shape(tmp_path):
    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    s = site_stats(collect(tmp_path))
    assert s["materials"]["KQvk"] == {"pieces": 3, "max_dtm": 3,
                                      "wtm": [[1, 4, 3], [3, 6, 0]], "btm": [[0, 2, 2], [2, 8, 5]]}
    assert s["materials"]["Kvkq"] == {"pieces": 3, "max_dtm": None, "wtm": [], "btm": []}
    assert s["total"]["wtm"] == [[1, 4, 3], [3, 6, 0]]
    assert s["by_pieces"] == {"3": {"tables": 2, "solvable": 1965, "unique": 10}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'helpmate_server.contrib.corpus_stats'`

- [ ] **Step 3: Implement**

```python
# src/packages/api/helpmate_server/contrib/corpus_stats.py
"""Corpus statistics from the tables' .stats.json sidecars: one row per table, the
lossless DTM x solution-count histogram, Parquet for Hugging Face and a compact JSON
for the site's Statistics screen. Nothing here reads a table's payload."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .materials import Material

if TYPE_CHECKING:
    from .registry import Registry

STMS = ("wtm", "btm")


@dataclass
class TableStats:
    material: str
    stats: dict
    size_bytes: int


def collect(tables: Path) -> list[TableStats]:
    """Every sidecar whose table is present (the rule of site_data.material_rows)."""
    out = []
    for sc in Path(tables).glob("*.stats.json"):
        hm = sc.with_name(sc.name[: -len(".stats.json")] + ".hm")
        if hm.exists():
            stats = json.loads(sc.read_text())
            out.append(TableStats(stats["material"], stats, hm.stat().st_size))
    return sorted(out, key=lambda t: (Material(t.material).pieces, t.material))


def is_marker(stats: dict) -> bool:
    return bool(stats.get("all_unsolvable")) or int(stats.get("max_dtm", 255)) >= 255


def contributor_of(material: str, registry: Registry | None) -> tuple[str, int | None, str | None]:
    entry = registry.tables.get(material) if registry else None
    if not entry:
        return "maintainer", None, None
    c = registry.contributors.get(entry["contributor"]) if registry else None
    name = "anonymous" if c and c.anonymous else (c.display if c else entry["contributor"])
    return name, entry.get("hf_pr"), entry.get("merged")


def _unique(stats: dict) -> int:
    return sum(int(by_count.get("1", 0))
               for side in stats.get("uniqueness", {}).values() for by_count in side.values())


def materials_rows(ts: list[TableStats], registry: Registry | None) -> list[dict]:
    rows = []
    for t in ts:
        s, m = t.stats, Material(t.material)
        cells = s.get("cells", {})  # tolerant like site_data.stats_row: minimal sidecars exist in tests
        inv = {k: int(cells.get("invalid", {}).get(k, 0)) for k in STMS}
        uns = {k: int(cells.get("unsolvable", {}).get(k, 0)) for k in STMS}
        marker = is_marker(s)
        who, pr, merged = contributor_of(t.material, registry)
        rows.append({"material": t.material, "pieces": m.pieces, "pawns": m.pawns,
                     "white": m.white, "black": m.black, "marker": marker,
                     "max_dtm": None if marker else int(s["max_dtm"]),
                     "plane_size": int(s["plane_size"]),
                     "invalid_wtm": inv["wtm"], "invalid_btm": inv["btm"],
                     "unsolvable_wtm": uns["wtm"], "unsolvable_btm": uns["btm"],
                     "solvable": 0 if marker else 2 * int(s["plane_size"]) - sum(inv.values()) - sum(uns.values()),
                     "unique": 0 if marker else _unique(s), "size_bytes": t.size_bytes,
                     "generator_version": str(s.get("generator_version", "")),
                     "contributor": who, "hf_pr": pr, "merged": merged})
    return rows


def histogram_rows(ts: list[TableStats]) -> list[dict]:
    rows = []
    for t in ts:
        if is_marker(t.stats):
            continue
        pieces = Material(t.material).pieces
        for stm in STMS:
            by_dtm = t.stats.get("uniqueness", {}).get(stm, {})
            for d in sorted(by_dtm, key=int):
                for c in sorted(by_dtm[d], key=int):
                    rows.append({"material": t.material, "pieces": pieces, "stm": stm,
                                 "dtm": int(d), "count": int(c), "cells": int(by_dtm[d][c])})
    return rows


def _depths(stats: dict, stm: str) -> list[list[int]]:
    hist = stats.get("dtm_histogram", {}).get(stm, {})
    uniq = stats.get("uniqueness", {}).get(stm, {})
    return [[int(d), int(hist[d]), int(uniq.get(d, {}).get("1", 0))] for d in sorted(hist, key=int)]


def site_stats(ts: list[TableStats]) -> dict:
    materials: dict[str, dict] = {}
    total: dict[str, dict[int, list[int]]] = {k: {} for k in STMS}
    by_pieces: dict[str, dict[str, int]] = {}
    for row, t in zip(materials_rows(ts, None), ts):
        marker = row["marker"]
        entry = {"pieces": row["pieces"], "max_dtm": row["max_dtm"]}
        for stm in STMS:
            entry[stm] = [] if marker else _depths(t.stats, stm)
            for d, cells, uniq in entry[stm]:
                acc = total[stm].setdefault(d, [d, 0, 0])
                acc[1] += cells
                acc[2] += uniq
        materials[t.material] = entry
        bp = by_pieces.setdefault(str(row["pieces"]), {"tables": 0, "solvable": 0, "unique": 0})
        bp["tables"] += 1
        bp["solvable"] += row["solvable"]
        bp["unique"] += row["unique"]
    return {"materials": materials,
            "total": {stm: [total[stm][d] for d in sorted(total[stm])] for stm in STMS},
            "by_pieces": by_pieces}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py -q`
Expected: 7 passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add src/packages/api/helpmate_server/contrib/corpus_stats.py src/packages/api/tests/test_contrib_corpus_stats.py
git commit -m "corpus_stats: per-table rows, lossless histogram rows and site JSON from the sidecars"
```

---

### Task 2: Parquet bytes, content comparison, completeness

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/corpus_stats.py`
- Modify: `src/packages/api/pyproject.toml` (the `verify = [...]` line)
- Test: `src/packages/api/tests/test_contrib_corpus_stats.py`

**Interfaces:**
- Consumes: Task 1's `TableStats`, `materials_rows`, `histogram_rows`.
- Produces:
  - `MATERIALS_PATH = "stats/materials.parquet"`, `HISTOGRAM_PATH = "stats/histogram.parquet"`
  - `parquet_files(ts: list[TableStats], registry: Registry | None) -> dict[str, bytes]` — both paths → bytes
  - `same_content(a: bytes | None, b: bytes) -> bool` — `False` when `a` is `None`
  - `parquet_materials(data: bytes) -> list[str]` — the `material` column
  - `completeness(ts: list[TableStats], manifest: dict) -> tuple[list[str], list[str]]` — (missing locally, extra locally), sorted
  - `require_pyarrow() -> None` — raises `ImportError` with the install hint

- [ ] **Step 1: Write the failing tests** (append to the test file)

```python
import pytest

pa = pytest.importorskip("pyarrow")

from helpmate_server.contrib.corpus_stats import (  # noqa: E402
    HISTOGRAM_PATH, MATERIALS_PATH, completeness, parquet_files, parquet_materials, same_content)


def test_parquet_round_trip_with_fixed_schema(tmp_path):
    import io
    import pyarrow.parquet as pq
    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    files = parquet_files(collect(tmp_path), _registry(tmp_path))
    assert set(files) == {MATERIALS_PATH, HISTOGRAM_PATH}
    mat = pq.read_table(io.BytesIO(files[MATERIALS_PATH]))
    assert mat.column("material").to_pylist() == ["Kvkq", "KQvk"]
    assert str(mat.schema.field("max_dtm").type) == "int16"
    assert str(mat.schema.field("merged").type) == "date32[day]"
    assert mat.column("max_dtm").to_pylist() == [None, 3]
    hist = pq.read_table(io.BytesIO(files[HISTOGRAM_PATH]))
    assert hist.num_rows == 6
    assert [str(f.type) for f in hist.schema] == ["string", "int8", "string", "int16", "int16", "int64"]
    assert parquet_materials(files[MATERIALS_PATH]) == ["Kvkq", "KQvk"]


def test_same_content_ignores_bytes_compares_tables(tmp_path):
    _put(tmp_path, KQVK)
    a = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    b = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert same_content(a, b) and not same_content(None, b)
    _put(tmp_path, MARKER)
    c = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert not same_content(a, c)


def test_completeness_against_the_manifest(tmp_path):
    _put(tmp_path, KQVK)
    _put(tmp_path, KPVK)
    manifest = {"files": {"KQvk.hm": {}, "KQvk.stats.json": {}, "KRvk.hm": {}}}
    assert completeness(collect(tmp_path), manifest) == (["KRvk"], ["KPvk"])
    assert completeness(collect(tmp_path), {"files": {"KQvk.hm": {}, "KPvk.hm": {}}}) == ([], [])
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py -q`
Expected: FAIL with `ImportError: cannot import name 'HISTOGRAM_PATH'`

- [ ] **Step 3: Implement** (append to `corpus_stats.py`; add `import io` and `from datetime import date` at the top)

```python
MATERIALS_PATH = "stats/materials.parquet"
HISTOGRAM_PATH = "stats/histogram.parquet"


def require_pyarrow() -> None:
    try:
        import pyarrow  # noqa: F401
    except ImportError as exc:
        raise ImportError("statistics need pyarrow: pip install './src/packages/api[verify]'") from exc


def _schemas():
    import pyarrow as pa
    materials = pa.schema([
        ("material", pa.string()), ("pieces", pa.int8()), ("pawns", pa.int8()),
        ("white", pa.string()), ("black", pa.string()), ("marker", pa.bool_()),
        ("max_dtm", pa.int16()), ("plane_size", pa.int64()),
        ("invalid_wtm", pa.int64()), ("invalid_btm", pa.int64()),
        ("unsolvable_wtm", pa.int64()), ("unsolvable_btm", pa.int64()),
        ("solvable", pa.int64()), ("unique", pa.int64()), ("size_bytes", pa.int64()),
        ("generator_version", pa.string()), ("contributor", pa.string()),
        ("hf_pr", pa.int32()), ("merged", pa.date32())])
    histogram = pa.schema([
        ("material", pa.string()), ("pieces", pa.int8()), ("stm", pa.string()),
        ("dtm", pa.int16()), ("count", pa.int16()), ("cells", pa.int64())])
    return materials, histogram


def _to_parquet(rows: list[dict], schema) -> bytes:
    import pyarrow as pa
    import pyarrow.parquet as pq
    table = pa.Table.from_pylist(rows, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue()


def parquet_files(ts: list[TableStats], registry: Registry | None) -> dict[str, bytes]:
    require_pyarrow()
    ms, hs = _schemas()
    mrows = [dict(r, merged=date.fromisoformat(r["merged"]) if r["merged"] else None)
             for r in materials_rows(ts, registry)]
    return {MATERIALS_PATH: _to_parquet(mrows, ms), HISTOGRAM_PATH: _to_parquet(histogram_rows(ts), hs)}


def _read(data: bytes):
    import pyarrow.parquet as pq
    return pq.read_table(io.BytesIO(data))


def same_content(a: bytes | None, b: bytes) -> bool:
    return a is not None and _read(a).equals(_read(b))


def parquet_materials(data: bytes) -> list[str]:
    return [str(m) for m in _read(data).column("material").to_pylist()]


def completeness(ts: list[TableStats], manifest: dict) -> tuple[list[str], list[str]]:
    published = {f[: -len(".hm")] for f in manifest.get("files", {}) if f.endswith(".hm")}
    local = {t.material for t in ts}
    return sorted(published - local), sorted(local - published)
```

In `src/packages/api/pyproject.toml` change the verify extra to:

```toml
verify = ["zstandard>=0.22", "numpy>=1.24", "chess>=1.10", "pyarrow>=14"]
```

and adjust its comment line to `# helpmate-tables verify and statistics: block decoding, plane statistics, independent oracle, Parquet.`

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py -q`
Expected: 10 passed

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -u src/packages/api && git commit -m "corpus_stats: Parquet files with a fixed schema, content comparison, completeness against the manifest"
```

---

### Task 3: `site/data/stats.json` from `write_site_data`, plus the blocking freshness test

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/site_data.py:70-80` (`write_site_data`)
- Modify: `tools/build_site_data.py` docstring (four files → five; add `stats.json`)
- Create: `site/data/stats.json` (generated, committed)
- Create: `tests/repo/test_site_stats_fresh.py`
- Test: `src/packages/api/tests/test_contrib_corpus_stats.py` (one test for `write_site_data`)

**Interfaces:**
- Consumes: Task 1's `collect`, `site_stats`.
- Produces: `write_site_data(out_dir, tables)` additionally writes `out_dir/"stats.json"` (compact separators) when its content changes, and returns it in the written list.

- [ ] **Step 1: Write the failing tests**

Append to `src/packages/api/tests/test_contrib_corpus_stats.py`:

```python
def test_write_site_data_writes_stats_json(tmp_path):
    from helpmate_server.contrib.site_data import write_site_data
    tables, out = tmp_path / "tb", tmp_path / "out"
    tables.mkdir()
    out.mkdir()
    _put(tables, KQVK)
    written = write_site_data(out, tables)
    assert out / "stats.json" in written
    assert json.loads((out / "stats.json").read_text())["materials"]["KQvk"]["max_dtm"] == 3
    assert out / "stats.json" not in write_site_data(out, tables)   # unchanged → not rewritten
```

Create `tests/repo/test_site_stats_fresh.py`:

```python
"""The Statistics screen's data must describe exactly the corpus the Materials page
shows. Every docs PR that adds tables (helpmate-tables accept / sync) rewrites both;
this test makes a PR that updates one without the other unmergeable."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "site" / "data"


def test_stats_json_matches_the_materials_list():
    materials = json.loads((DATA / "materials.json").read_text())
    stats = json.loads((DATA / "stats.json").read_text())["materials"]
    done = {r["material"]: r for r in materials if r["done"]}
    assert sorted(stats) == sorted(done), (
        "site/data/stats.json is stale: run helpmate-tables sync --tables DIR")
    for name, r in done.items():
        assert stats[name]["max_dtm"] == r["max_dtm"], name
        unique = sum(u for stm in ("wtm", "btm") for _, _, u in stats[name][stm])
        assert unique == r["unique"], name


def test_stats_json_stays_small():
    assert (DATA / "stats.json").stat().st_size < 1_000_000
```

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py tests/repo/test_site_stats_fresh.py -q`
Expected: FAIL — `stats.json` not in written; `FileNotFoundError: site/data/stats.json`

- [ ] **Step 3: Implement**

`site_data.py`, replace `write_site_data` with:

```python
def write_site_data(out_dir: Path, tables: Path) -> list[Path]:
    from .corpus_stats import collect, site_stats

    out_dir = Path(out_dir)
    rows = material_rows(tables, out_dir / "material")
    written = []
    for name, text in (("materials.json", json.dumps(rows, separators=(",", ":"))),
                       ("corpus.json", json.dumps(corpus_summary(rows), indent=1)),
                       ("stats.json", json.dumps(site_stats(collect(tables)), separators=(",", ":")))):
        p = out_dir / name
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
            written.append(p)
    return written
```

Generate the committed file from the real corpus (419 tables in `~/tb`, matching the manifest):

```bash
PYTHONPATH=$PWD/src/packages/api python3 -c "
from pathlib import Path; from helpmate_server.contrib.site_data import write_site_data
print(write_site_data(Path('site/data'), Path.home()/'tb'))"
git diff --stat site/data
```

Expected: `stats.json` new; `materials.json` / `corpus.json` unchanged (if they change, stop and report — the corpus and the committed site data disagree, which is a separate issue).

- [ ] **Step 4: Run to verify they pass, then break the guard on purpose**

Run: `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py tests/repo/test_site_stats_fresh.py -q` → all pass.
Then delete one material from a copy and point the test at it to watch it fail:

```bash
cp site/data/stats.json /tmp/stats.bak
python3 -c "import json;p='site/data/stats.json';d=json.load(open(p));d['materials'].pop('KQvk');open(p,'w').write(json.dumps(d))"
PYTHONPATH=$PWD/src/packages/api python3 -m pytest tests/repo/test_site_stats_fresh.py -q   # expect FAIL "stale"
cp /tmp/stats.bak site/data/stats.json
```

- [ ] **Step 5: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/site_data.py tools/build_site_data.py site/data/stats.json tests/repo/test_site_stats_fresh.py src/packages/api/tests/test_contrib_corpus_stats.py
git commit -m "site data: stats.json written with materials.json; PR test keeps them in step"
```

---

### Task 4: `helpmate-tables stats-push` and the dataset card

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/stats_push.py`
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (`add_parsers`, `run`)
- Modify: `docs/hf-dataset-card.md` (front matter; new "Statistics" section)
- Test: `src/packages/api/tests/test_contrib_stats_push.py`, `tests/repo/test_hf_card.py`

**Interfaces:**
- Consumes: Task 2's `parquet_files`, `same_content`, `parquet_materials`, `completeness`, `MATERIALS_PATH`, `HISTOGRAM_PATH`, `require_pyarrow`; Task 1's `collect`; `Hub.fetch_manifest()`, `Hub.read_bytes(name)`, `Hub.commit(files, message)`; `FakeHub` in tests (`read_bytes` raises `KeyError` for a missing file).
- Produces:
  - `class StatsError(Exception)`
  - `read_published(hub, path: str) -> bytes | None` — `None` when the file does not exist (catch `KeyError` from the fake and `huggingface_hub.errors.EntryNotFoundError` from the real hub)
  - `check(hub) -> list[str]` — problems comparing manifest `.hm` set with the published `materials.parquet`; empty list = fresh
  - `push(hub, tables: Path, registry: Registry | None, card: bytes | None, dry_run: bool) -> str` — raises `StatsError` on incomplete corpus; returns a one-line summary
  - CLI: `helpmate-tables stats-push --tables DIR [--dry-run] [--checkout PATH] [--repo]` and `helpmate-tables stats-push --check [--repo]` (`--tables` not required with `--check`; exit 1 when stale)

- [ ] **Step 1: Write the failing tests**

```python
# src/packages/api/tests/test_contrib_stats_push.py
import json

import pytest

pytest.importorskip("pyarrow")

from fakes import FakeHub  # noqa: E402
from helpmate_server.contrib.corpus_stats import (  # noqa: E402
    HISTOGRAM_PATH, MATERIALS_PATH, collect, parquet_files)
from helpmate_server.contrib.stats_push import StatsError, check, push  # noqa: E402
from test_contrib_corpus_stats import KQVK, MARKER, _put  # noqa: E402


def _manifest(*names):
    return json.dumps({"schema": 1, "files": {f"{n}.hm": {} for n in names}}).encode()


def test_refuses_an_incomplete_corpus(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    with pytest.raises(StatsError, match="Kvkq"):
        push(hub, tmp_path, None, b"card", dry_run=False)
    assert hub.commits == []


def test_uploads_parquet_and_card_when_missing_then_nothing_when_equal(tmp_path):
    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    assert "uploaded" in push(hub, tmp_path, None, b"card", dry_run=False)
    (msg, files), = hub.commits
    assert set(files) == {MATERIALS_PATH, HISTOGRAM_PATH, "README.md"}
    assert "unchanged" in push(hub, tmp_path, None, b"card", dry_run=False)
    assert len(hub.commits) == 1


def test_dry_run_uploads_nothing(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    out = push(hub, tmp_path, None, b"card", dry_run=True)
    assert "would upload" in out and "1 tables" in out and hub.commits == []


def test_check_reports_missing_stale_and_fresh(tmp_path):
    _put(tmp_path, KQVK)
    hub = FakeHub({"manifest.json": _manifest("KQvk", "Kvkq")})
    assert check(hub) == [f"{MATERIALS_PATH} is not on the dataset yet"]
    hub.main[MATERIALS_PATH] = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert check(hub) == ["statistics lack Kvkq"]
    _put(tmp_path, MARKER)
    hub.main[MATERIALS_PATH] = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert check(hub) == []


def test_cli_check_exit_codes(tmp_path, capsys):
    from helpmate_server.contrib import cli
    import argparse
    hub = FakeHub({"manifest.json": _manifest("KQvk")})
    ns = argparse.Namespace(cmd="stats-push", check=True, tables=None, dry_run=False,
                            checkout=tmp_path, repo="x")
    assert cli.run(ns, hub_factory=lambda repo: hub) == 1
    assert "stats-push --tables" in capsys.readouterr().err
```

```python
# tests/repo/test_hf_card.py
"""The dataset card shows the two statistics files in the Hugging Face viewer
and nothing else (the .hm tables are not viewable data)."""
from pathlib import Path

import yaml

CARD = Path(__file__).resolve().parents[2] / "docs" / "hf-dataset-card.md"


def _front_matter() -> dict:
    text = CARD.read_text()
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1])


def test_card_configures_the_viewer_for_the_statistics():
    fm = _front_matter()
    assert fm.get("viewer") is not False
    configs = {c["config_name"]: c for c in fm["configs"]}
    assert configs["materials"]["data_files"] == "stats/materials.parquet"
    assert configs["materials"].get("default") is True
    assert configs["histogram"]["data_files"] == "stats/histogram.parquet"


def test_card_documents_the_statistics():
    text = CARD.read_text()
    assert "## Statistics" in text
    assert 'pd.read_parquet("hf://datasets/osick/helpmate-tables/stats/materials.parquet")' in text
```

Note for the implementer: `FakeHub.read_bytes` does `self.main[filename]`, which raises `KeyError` for a missing file — that is the fake's "not found".

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_stats_push.py tests/repo/test_hf_card.py -q`
Expected: FAIL — `No module named 'helpmate_server.contrib.stats_push'`; card has `viewer: false`.

- [ ] **Step 3: Implement**

```python
# src/packages/api/helpmate_server/contrib/stats_push.py
"""helpmate-tables stats-push: the corpus statistics on Hugging Face. Uploads the two
Parquet files (and main's dataset card) only when their content changed and the local
corpus is exactly the published one; --check compares the published statistics with
the manifest, for the daily stats-check workflow."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .corpus_stats import (
    HISTOGRAM_PATH, MATERIALS_PATH, collect, completeness, parquet_files, parquet_materials,
    same_content)

if TYPE_CHECKING:
    from .registry import Registry


class StatsError(Exception):
    pass


def read_published(hub, path: str) -> bytes | None:
    try:
        return hub.read_bytes(path)
    except KeyError:
        return None
    except Exception as exc:  # huggingface_hub's EntryNotFoundError, without importing it here
        if type(exc).__name__ in ("EntryNotFoundError", "RemoteEntryNotFoundError"):
            return None
        raise


def _published_tables(hub) -> set[str]:
    return {f[: -len(".hm")] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}


def check(hub) -> list[str]:
    data = read_published(hub, MATERIALS_PATH)
    if data is None:
        return [f"{MATERIALS_PATH} is not on the dataset yet"]
    published, listed = _published_tables(hub), set(parquet_materials(data))
    problems = []
    if published - listed:
        problems.append("statistics lack " + ", ".join(sorted(published - listed)))
    if listed - published:
        problems.append("statistics list tables not in the dataset: " + ", ".join(sorted(listed - published)))
    return problems


def push(hub, tables: Path, registry: Registry | None, card: bytes | None, dry_run: bool) -> str:
    ts = collect(tables)
    missing, extra = completeness(ts, hub.fetch_manifest())
    if missing or extra:
        raise StatsError("the local corpus is not the published one"
                         + (f"; missing locally: {', '.join(missing)}" if missing else "")
                         + (f"; not published: {', '.join(extra)}" if extra else ""))
    files = parquet_files(ts, registry)
    changed = {p: b for p, b in files.items() if not same_content(read_published(hub, p), b)}
    if not changed:
        return f"statistics unchanged ({len(ts)} tables)"
    if dry_run:
        return f"would upload {', '.join(sorted(changed))} ({len(ts)} tables)"
    upload = dict(files)
    if card is not None:
        upload["README.md"] = card
    hub.commit(upload, "Dataset statistics" + (" and card" if card is not None else ""))
    return f"uploaded {', '.join(sorted(upload))} ({len(ts)} tables)"
```

`cli.py`, in `add_parsers` after the `site-status` parser:

```python
    sp = sub.add_parser("stats-push", help="(maintainer) upload or check the corpus statistics on the dataset")
    sp.add_argument("--tables", metavar="DIR", help="the complete local corpus (not needed with --check)")
    sp.add_argument("--check", action="store_true",
                    help="only compare the published statistics with the manifest; exit 1 if stale")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--checkout", type=Path, default=Path("."))
    sp.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
```

In `run`, before `raise UsageError(f"{a.cmd}: not implemented yet")`:

```python
        if a.cmd == "stats-push":
            from .hf import Hub
            from .stats_push import StatsError, check, push
            hub = (hub_factory or Hub)(a.repo)
            try:
                from .corpus_stats import require_pyarrow
                require_pyarrow()
            except ImportError as exc:
                raise UsageError(str(exc)) from exc
            if a.check:
                problems = check(hub)
                for p in problems:
                    print(f"stale: {p}", file=sys.stderr)
                if problems:
                    print("fix: helpmate-tables stats-push --tables DIR (with the complete corpus)",
                          file=sys.stderr)
                    return 1
                print("statistics match the manifest")
                return 0
            if not a.tables:
                raise UsageError("stats-push needs --tables DIR (or --check)")
            from .registry import Registry
            checkout = Path(a.checkout)
            reg_file = checkout / "data" / "contributions.json"
            card_file = checkout / "docs" / "hf-dataset-card.md"
            try:
                print(push(hub, Path(a.tables).expanduser(),
                           Registry.load(reg_file) if reg_file.exists() else None,
                           card_file.read_bytes() if card_file.exists() else None, a.dry_run))
            except StatsError as exc:
                raise UsageError(str(exc)) from exc
            return 0
```

`docs/hf-dataset-card.md`: replace the line `viewer: false` with

```yaml
configs:
  - config_name: materials
    data_files: stats/materials.parquet
    default: true
  - config_name: histogram
    data_files: stats/histogram.parquet
```

and add before the card's licence/citation section (read the card and place it after the section describing the files):

````markdown
## Statistics

Two Parquet files, rebuilt with every accepted contribution, hold the statistics of every
table (the viewer above shows them):

- `stats/materials.parquet` — one row per table: material, pieces, pawns, the pieces besides
  the kings (`white`, `black`), `marker` (provably no helpmate), `max_dtm`, `plane_size`, invalid
  and unsolvable cells per side to move, `solvable`, `unique` (positions with exactly one
  solution), compressed size, generator version, contributor, dataset PR and merge date.
- `stats/histogram.parquet` — the full distribution: one row per material, side to move
  (`wtm`/`btm`), depth `dtm` (plies) and solution `count` (255 = 255 or more), with the number
  of positions in `cells`.

```python
import pandas as pd
m = pd.read_parquet("hf://datasets/osick/helpmate-tables/stats/materials.parquet")
h = pd.read_parquet("hf://datasets/osick/helpmate-tables/stats/histogram.parquet")
m.sort_values("max_dtm", ascending=False).head(10)
```
````

If `helpmate-tables sync` (docs_sync) rewrites marked regions of this card, keep the new section outside those regions; run `PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests -q -k "card or sync"` to confirm.

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_stats_push.py tests/repo/test_hf_card.py src/packages/api/tests -q -k "stats or card or sync or cli"`
Expected: all pass

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add src/packages/api/helpmate_server/contrib/stats_push.py src/packages/api/helpmate_server/contrib/cli.py docs/hf-dataset-card.md src/packages/api/tests/test_contrib_stats_push.py tests/repo/test_hf_card.py
git commit -m "helpmate-tables stats-push: upload or check the Parquet statistics; card shows them in the viewer"
```

---

### Task 5: `accept` uploads the statistics with the card and checks them

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/accept.py` (card step, around lines 489-492)
- Test: `src/packages/api/tests/test_contrib_accept.py`

**Interfaces:**
- Consumes: Task 1 `collect`; Task 2 `parquet_files`, `completeness`, `require_pyarrow`; Task 4 `check`; existing `git.main_file(path) -> bytes`, `hub.commit`, `hub.fetch_manifest`; `Registry(path, data)` constructor.
- Produces: card step = one commit `"Dataset card and statistics"` with `README.md` + both Parquet paths when the local corpus is complete; otherwise `"Dataset card: contributors and counts"` with `README.md` only and a stderr note. After a statistics upload, `check(hub)` must return `[]`, else the step returns an error (state not marked, so a rerun resumes at the card step).

- [ ] **Step 1: Write the failing tests** (in `src/packages/api/tests/test_contrib_accept.py`)

Facts about the existing fixtures: `_setup(tmp_path)` returns `(checkout, staging, hub, gh, tables)` for one dataset PR #2 adding `KRRvkqq` (a minimal sidecar without `cells`); `_run(checkout, staging, hub, gh, tables, git)` runs `accept([2], …)`. After the merge and manifest steps the fake manifest lists `KRRvkqq.hm`, and the local step moves `KRRvkqq.hm` + sidecar into `tables` — so in the happy path the local corpus is complete and the statistics are uploaded.

First extend `FakeGit` so the registry can be read from main:

```python
class FakeGit:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at
        self.main_card = b"x\n"          # docs/hf-dataset-card.md as origin/main has it right now
        self.main_registry = b'{"schema":1,"contributors":{},"tables":{}}'
    # (all other methods unchanged)
    def main_file(self, path):
        self._do("main_file", path)
        return self.main_registry if path == "data/contributions.json" else self.main_card
```

Change the existing `test_card_uploaded_is_mains_current_card_not_this_runs_snapshot` last-but-one assertion from the exact dict to:

```python
    (card_files,) = [f for m, f in hub.commits if "Dataset card" in m]
    assert card_files["README.md"] == git.main_card
```

New tests:

```python
pytest.importorskip("pyarrow")  # put this inside each of the three tests, not at module level


def test_card_step_uploads_statistics_when_the_local_corpus_is_complete(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    (msg, files), = [(m, f) for m, f in hub.commits if "Dataset card" in m]
    assert msg == "Dataset card and statistics"
    assert set(files) == {"README.md", "stats/materials.parquet", "stats/histogram.parquet"}
    from helpmate_server.contrib.corpus_stats import parquet_materials
    assert parquet_materials(hub.main["stats/materials.parquet"]) == ["KRRvkqq"]
    assert "statistics uploaded" in capsys.readouterr().err


def test_card_step_skips_statistics_for_an_incomplete_local_corpus(tmp_path, capsys):
    pytest.importorskip("pyarrow")
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.main["manifest.json"] = json.dumps(
        {"schema": 1, "generator_version": "0.19.0", "files": {"KQvk.hm": {"sha256": "0", "size": 1}}}).encode()
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    (msg, files), = [(m, f) for m, f in hub.commits if "Dataset card" in m]
    assert msg == "Dataset card: contributors and counts" and set(files) == {"README.md"}
    err = capsys.readouterr().err
    assert "statistics not uploaded" in err and "KQvk" in err


def test_card_step_fails_when_the_published_statistics_do_not_match(tmp_path, monkeypatch):
    pytest.importorskip("pyarrow")
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    monkeypatch.setattr("helpmate_server.contrib.stats_push.check", lambda hub: ["statistics lack X"])
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    state = json.loads((staging / "accept-2.json").read_text())
    assert "card" not in state["done"]            # a rerun resumes at the card step
    monkeypatch.undo()
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
```

Note for the incomplete-corpus test: the manifest step rebuilds `manifest.json` from the hub's main files, so check where it reads from (`manifest_from_hub`) — if it would overwrite the injected entry, instead put an extra `KQvk.hm` file into `hub.main` (e.g. `hub.main["KQvk.hm"] = b"t"`) before `_run`, so the rebuilt manifest lists a table that `tables` lacks. Use whichever makes the manifest list `KQvk.hm` at card time; the assertions stay the same.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_accept.py -q -k statistics`
Expected: FAIL — the card commit message is still "Dataset card: contributors and counts"

- [ ] **Step 3: Implement** — replace the card block in `accept.py`:

```python
    if "card" not in state["done"]:  # only now: the public card must not credit a failed docs PR
        # main's card, not a copy from this run's docs step: a later accept run may have published a newer one
        card = git.main_file("docs/hf-dataset-card.md")
        files, note = {"README.md": card}, _statistics(hub, git, tables)
        if isinstance(note, dict):
            files.update(note)
            hub.commit(files, "Dataset card and statistics")
            from .stats_push import check
            problems = check(hub)
            if problems:
                return _err("statistics on the dataset do not match the manifest after the upload: "
                            + "; ".join(problems) + " — rerun this accept to retry")
            print(f"statistics uploaded: {len(note)} files", file=sys.stderr)
        else:
            hub.commit(files, "Dataset card: contributors and counts")
            print(f"statistics not uploaded: {note}; run helpmate-tables stats-push --tables DIR "
                  "after syncing", file=sys.stderr)
        mark("card")
```

and add the helper near the other module-level helpers in `accept.py`:

```python
def _statistics(hub, git, tables: Path) -> dict[str, bytes] | str:
    """The Parquet statistics for the card commit, or why they are skipped. Never raises
    for an incomplete corpus or a missing pyarrow: statistics must not fail an accept."""
    from .corpus_stats import collect, completeness, parquet_files, require_pyarrow
    from .registry import Registry
    try:
        require_pyarrow()
    except ImportError as exc:
        return str(exc)
    ts = collect(tables)
    missing, extra = completeness(ts, hub.fetch_manifest())
    if missing or extra:
        return (f"{len(missing)} tables missing locally, {len(extra)} not published "
                f"({', '.join((missing + extra)[:5])})")
    reg = Registry(Path("data/contributions.json"), json.loads(git.main_file("data/contributions.json")))
    return parquet_files(ts, reg)
```

Check that `json` is imported in `accept.py` (add `import json` if not), and that the fake `Git.main_file` in the tests returns a valid registry for `data/contributions.json` — if it returns `self.main_card` for every path, extend the fake so `main_file("data/contributions.json")` returns `b'{"schema":1,"contributors":{},"tables":{}}'` unless a test sets otherwise; then run the whole accept test module to confirm existing tests still pass (they have no local sidecars, so they take the "not uploaded" branch, and their `"Dataset card" in m` assertions still hold).

- [ ] **Step 4: Run to verify they pass**

Run: `PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests/test_contrib_accept.py -q`
Expected: all pass (existing + 3 new)

- [ ] **Step 5: Lint, type-check, commit**

```bash
ruff check src/packages/api && mypy src/packages/api/helpmate_server/contrib
git add -u src/packages/api && git commit -m "accept: the card step uploads the Parquet statistics and checks them against the manifest"
```

---

### Task 6: Daily `stats-check` workflow and the SVG chart library

Two small deliverables that share nothing but size; a reviewer can judge each independently, so each has its own commit.

**Files:**
- Create: `.github/workflows/stats-check.yml`
- Create: `tests/repo/test_stats_check_workflow.py`
- Create: `site/js/lib/charts.js`
- Create: `site/tests/charts.test.js`

**Interfaces:**
- Consumes: Task 4's `helpmate-tables stats-push --check` (module entry `python -m helpmate_server.tables_cli stats-push --check`).
- Produces (`charts.js`):
  - `export function barChart({ bars, width = 640, height = 240, log = false, xLabel = "", yLabel = "" })` → SVG string. `bars`: `[{ x: string|number, value: number, part?: number, title?: string }]`; `part` (≤ value) is drawn as a highlighted segment (`class="part"`), the rest as `class="bar"`. Each bar group has a `<title>`. Empty `bars` → an SVG with a `<text class="empty">no data</text>`.
  - `export function niceMax(v)` → the axis maximum (1, 2, 5 × 10ⁿ ≥ v; 1 for v ≤ 0).
  - `export function scale(v, max, log)` → 0..1; with `log`, `log10(1+v)/log10(1+max)`; `0` for `v <= 0`; never `NaN`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/repo/test_stats_check_workflow.py
"""The published statistics are compared with the manifest every day and after
every Pages run; a failing run is the maintainer's notification."""
from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_stats_check_runs_daily_and_after_pages():
    wf = yaml.safe_load((WF / "stats-check.yml").read_text())
    on = wf.get("on", wf.get(True))
    assert on["schedule"][0]["cron"]
    assert on["workflow_run"]["workflows"] == ["Pages"]
    assert "workflow_dispatch" in on
    steps = wf["jobs"]["check"]["steps"]
    assert any("stats-push --check" in s.get("run", "") for s in steps)
    assert wf["permissions"] == {"contents": "read"}
```

```js
// site/tests/charts.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { barChart, niceMax, scale } from "../js/lib/charts.js";

test("niceMax rounds up to 1/2/5 steps", () => {
  assert.equal(niceMax(0), 1);
  assert.equal(niceMax(7), 10);
  assert.equal(niceMax(1200), 2000);
  assert.equal(niceMax(4.2e9), 5e9);
});

test("scale is finite, also on a log axis with zeros", () => {
  assert.equal(scale(0, 100, true), 0);
  assert.equal(scale(100, 100, true), 1);
  assert.ok(scale(10, 100, true) > scale(10, 100, false));
  assert.equal(scale(5, 0, false), 0);
});

test("bars with a highlighted part and titles", () => {
  const svg = barChart({ bars: [{ x: 1, value: 10, part: 4, title: "d1" }, { x: 3, value: 0 }] });
  assert.match(svg, /^<svg[^>]*role="img"/);
  assert.equal((svg.match(/class="bar"/g) || []).length, 2);
  assert.equal((svg.match(/class="part"/g) || []).length, 1);
  assert.match(svg, /<title>d1<\/title>/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("log axis with gaps stays finite", () => {
  const svg = barChart({ bars: [{ x: 0, value: 0 }, { x: 1, value: 3e9, part: 0 }, { x: 2, value: 1 }], log: true });
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("empty data", () => {
  assert.match(barChart({ bars: [] }), /class="empty">no data</);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `python3 -m pytest tests/repo/test_stats_check_workflow.py -q; node --test site/tests/charts.test.js`
Expected: FAIL — file not found / module not found

- [ ] **Step 3: Implement**

```yaml
# .github/workflows/stats-check.yml
# The corpus statistics on Hugging Face (stats/materials.parquet) must list exactly
# the tables in the dataset manifest. helpmate-tables accept uploads them with every
# contribution; this check catches a missed or failed upload. Read-only, no token:
# both files are public. A failing run is the notification; the log names the
# missing tables and the fix (helpmate-tables stats-push --tables DIR).
name: Stats check

on:
  schedule:
    - cron: "47 4 * * *"
  workflow_run:
    workflows: [Pages]
    types: [completed]
  workflow_dispatch:

permissions:
  contents: read

jobs:
  check:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Compare the published statistics with the manifest
        run: |
          python -m pip install "huggingface_hub>=0.23" "pyarrow>=14"
          python -m helpmate_server.tables_cli stats-push --check
        env:
          PYTHONPATH: src/packages/api
```

```js
// site/js/lib/charts.js
// Bar charts as SVG strings: no chart library, colours from the page's CSS
// variables (classes bar / part / axis / empty), so dark mode follows the site.

export function niceMax(v) {
  if (!(v > 0)) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

export function scale(v, max, log) {
  if (!(v > 0) || !(max > 0)) return 0;
  return log ? Math.log10(1 + v) / Math.log10(1 + max) : v / max;
}

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const fmt = (v) => (v >= 1e9 ? `${+(v / 1e9).toFixed(1)}G` : v >= 1e6 ? `${+(v / 1e6).toFixed(1)}M`
  : v >= 1e3 ? `${+(v / 1e3).toFixed(1)}k` : `${v}`);

export function barChart({ bars, width = 640, height = 240, log = false, xLabel = "", yLabel = "" }) {
  const open = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(yLabel || "chart")}">`;
  if (!bars.length) return `${open}<text class="empty" x="${width / 2}" y="${height / 2}" text-anchor="middle">no data</text></svg>`;
  const left = 48, bottom = 28, top = 8, plotW = width - left - 8, plotH = height - top - bottom;
  const max = log ? Math.max(...bars.map((b) => b.value), 1) : niceMax(Math.max(...bars.map((b) => b.value)));
  const step = plotW / bars.length, bw = Math.max(1, step * 0.8);
  const y = (v) => top + plotH * (1 - scale(v, max, log));
  let out = open;
  out += `<line class="axis" x1="${left}" y1="${top + plotH}" x2="${left + plotW}" y2="${top + plotH}"/>`;
  out += `<text class="axis" x="4" y="${top + 10}">${esc(fmt(max))}</text>`;
  out += `<text class="axis" x="4" y="${top + plotH}">0</text>`;
  const every = Math.ceil(bars.length / 20);
  bars.forEach((b, i) => {
    const x = left + i * step + (step - bw) / 2;
    const h = top + plotH - y(b.value);
    out += `<g><title>${esc(b.title ?? `${b.x}: ${b.value}`)}</title>`;
    out += `<rect class="bar" x="${x.toFixed(1)}" y="${y(b.value).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}"/>`;
    if (b.part > 0) {
      const ph = top + plotH - y(b.part);
      out += `<rect class="part" x="${x.toFixed(1)}" y="${y(b.part).toFixed(1)}" width="${bw.toFixed(1)}" height="${ph.toFixed(1)}"/>`;
    }
    out += "</g>";
    if (i % every === 0) out += `<text class="axis" x="${(x + bw / 2).toFixed(1)}" y="${height - 12}" text-anchor="middle">${esc(b.x)}</text>`;
  });
  if (xLabel) out += `<text class="axis" x="${left + plotW / 2}" y="${height - 1}" text-anchor="middle">${esc(xLabel)}</text>`;
  return `${out}</svg>`;
}
```

Note: on a log axis the `part` segment is drawn at its own log height, so it is a marker of the unique count, not a proportional share; the screen (Task 7) labels it accordingly.

- [ ] **Step 4: Run to verify they pass**

Run: `python3 -m pytest tests/repo/test_stats_check_workflow.py -q && node --test site/tests/charts.test.js && node --check site/js/lib/charts.js`
Expected: all pass

- [ ] **Step 5: Commit (two commits)**

```bash
git add .github/workflows/stats-check.yml tests/repo/test_stats_check_workflow.py
git commit -m "stats-check workflow: published statistics vs manifest, daily and after Pages"
git add site/js/lib/charts.js site/tests/charts.test.js
git commit -m "site: SVG bar charts without a library"
```

---

### Task 7: The Statistics screen

**Files:**
- Modify: `site/index.html` (nav entry + section)
- Modify: `site/js/app.js` (screen map, `show`)
- Create: `site/js/stats.js`
- Create: `site/js/lib/stats.js` (pure data transforms, testable in node)
- Modify: `site/js/materials.js` (stats link per done row)
- Modify: `site/css/*.css` (the site stylesheet: classes `bar`, `part`, `axis`, `empty`, `.stats-grid`)
- Test: `site/tests/stats.test.js`, `tests/repo/test_site_browser.py` (new test)

**Interfaces:**
- Consumes: `site/data/stats.json` (Task 3 shape), `barChart` (Task 6), `esc` from `site/js/lib/materials.js`.
- Produces (`site/js/lib/stats.js`):
  - `depthBars(rows)` — `[[d, cells, unique]]` → `[{ x: d, value: cells, part: unique, title }]`
  - `uniqueShareBars(byPieces)` — `{pieces: {solvable, unique}}` → bars of percentages (`value` = share × 100, rounded to 0.01), ordered by piece count
  - `maxDtmBars(materials, pieces)` — counts of materials per `max_dtm` (markers excluded; `pieces` = `"all"` or `"3"`…`"6"`), every depth from 0 to the maximum present (gaps as 0)
  - `deepest(materials, n = 10)` — `[{ material, max_dtm }]` sorted by `max_dtm` desc, then name
  - `lookup(stats, name)` — `{ ok: true, entry }` | `{ ok: false, message }` (`"unknown material"` for a name not in `stats.materials`; `"no helpmate in this material"` for a marker)
- Produces (`site/js/stats.js`): `initStats({ stats })`, `showStats(arg)`.

- [ ] **Step 1: Write the failing tests**

```js
// site/tests/stats.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { depthBars, uniqueShareBars, maxDtmBars, deepest, lookup } from "../js/lib/stats.js";

const stats = {
  materials: {
    KQvk: { pieces: 3, max_dtm: 3, wtm: [[1, 4, 3], [3, 6, 0]], btm: [[0, 2, 2], [2, 8, 5]] },
    KRvk: { pieces: 3, max_dtm: 5, wtm: [], btm: [[0, 1, 1]] },
    Kvkq: { pieces: 3, max_dtm: null, wtm: [], btm: [] },
    KQvkq: { pieces: 4, max_dtm: 5, wtm: [], btm: [] },
  },
  total: { wtm: [[1, 4, 3]], btm: [] },
  by_pieces: { 4: { tables: 1, solvable: 10, unique: 1 }, 3: { tables: 3, solvable: 200, unique: 50 } },
};

test("depth bars carry cells and the unique part", () => {
  assert.deepEqual(depthBars([[1, 4, 3]]), [{ x: 1, value: 4, part: 3, title: "depth 1: 4 positions, 3 unique" }]);
});

test("unique share per piece count, ordered", () => {
  assert.deepEqual(uniqueShareBars(stats.by_pieces).map((b) => [b.x, b.value]), [["3", 25], ["4", 10]]);
});

test("materials per max DTM, markers excluded, gaps filled", () => {
  assert.deepEqual(maxDtmBars(stats.materials, "all").map((b) => b.value), [0, 0, 0, 1, 0, 2]);
  assert.deepEqual(maxDtmBars(stats.materials, "4").map((b) => b.value), [0, 0, 0, 0, 0, 1]);
});

test("deepest materials", () => {
  assert.deepEqual(deepest(stats.materials, 2), [{ material: "KQvkq", max_dtm: 5 }, { material: "KRvk", max_dtm: 5 }]);
});

test("lookup handles unknown names and markers", () => {
  assert.equal(lookup(stats, "KQvk").ok, true);
  assert.deepEqual(lookup(stats, "Nonsense"), { ok: false, message: "unknown material" });
  assert.deepEqual(lookup(stats, ""), { ok: false, message: "unknown material" });
  assert.deepEqual(lookup(stats, "Kvkq"), { ok: false, message: "no helpmate in this material" });
});
```

Add to `tests/repo/test_site_browser.py` (reuse its `server` fixture and the browser setup its other tests use, `chromium.launch(args=["--no-sandbox"])`):

```python
def test_statistics_screen_renders(server):
    with playwright_api.sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{server}/index.html#/stats")
        page.wait_for_selector("#screen-stats svg rect.bar")
        assert page.locator("#screen-stats svg").count() >= 3
        page.goto(f"{server}/index.html#/stats/KQvk")
        page.wait_for_selector("#stats-material svg rect.bar")
        page.goto(f"{server}/index.html#/stats/Nonsense")
        page.wait_for_selector("#stats-material :text('unknown material')")
        browser.close()
        assert errors == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `node --test site/tests/stats.test.js; make site && python3 -m pytest tests/repo/test_site_browser.py -q -k statistics`
Expected: FAIL — module not found; `#screen-stats` missing

- [ ] **Step 3: Implement**

```js
// site/js/lib/stats.js
// Pure transforms from site/data/stats.json to chart bars (tested in node).

export function depthBars(rows) {
  return rows.map(([d, cells, unique]) => ({ x: d, value: cells, part: unique,
    title: `depth ${d}: ${cells.toLocaleString("en")} positions, ${unique.toLocaleString("en")} unique` }));
}

export function uniqueShareBars(byPieces) {
  return Object.keys(byPieces).sort((a, b) => a - b).map((k) => {
    const { solvable, unique } = byPieces[k];
    const value = solvable ? Math.round((unique / solvable) * 10000) / 100 : 0;
    return { x: k, value, title: `${k} pieces: ${value}% of solvable positions have one solution` };
  });
}

export function maxDtmBars(materials, pieces) {
  const ds = Object.values(materials)
    .filter((m) => m.max_dtm !== null && (pieces === "all" || String(m.pieces) === pieces))
    .map((m) => m.max_dtm);
  const top = ds.length ? Math.max(...ds) : -1;
  const counts = Array.from({ length: top + 1 }, () => 0);
  for (const d of ds) counts[d] += 1;
  return counts.map((n, d) => ({ x: d, value: n, title: `max DTM ${d}: ${n} materials` }));
}

export function deepest(materials, n = 10) {
  return Object.entries(materials).filter(([, m]) => m.max_dtm !== null)
    .map(([material, m]) => ({ material, max_dtm: m.max_dtm }))
    .sort((a, b) => b.max_dtm - a.max_dtm || a.material.localeCompare(b.material))
    .slice(0, n);
}

export function lookup(stats, name) {
  const entry = name ? stats.materials[name] : undefined;
  if (!entry) return { ok: false, message: "unknown material" };
  if (entry.max_dtm === null) return { ok: false, message: "no helpmate in this material" };
  return { ok: true, entry };
}
```

```js
// site/js/stats.js
// #/stats and #/stats/MATERIAL: corpus charts and one material's distribution.
import { barChart } from "./lib/charts.js";
import { depthBars, uniqueShareBars, maxDtmBars, deepest, lookup } from "./lib/stats.js";
import { esc } from "./lib/materials.js";

let S = null;
const state = { stm: "btm", log: true, pieces: "all" };
const $ = (id) => document.getElementById(id);

function drawCorpus() {
  $("stats-total").innerHTML = barChart({ bars: depthBars(S.total[state.stm]), log: state.log,
    xLabel: "depth (plies)", yLabel: "positions per depth" });
  $("stats-share").innerHTML = barChart({ bars: uniqueShareBars(S.by_pieces), height: 200,
    xLabel: "pieces", yLabel: "unique share (%)" });
  $("stats-maxdtm").innerHTML = barChart({ bars: maxDtmBars(S.materials, state.pieces),
    xLabel: "maximum DTM (plies)", yLabel: "materials" });
  $("stats-deepest").innerHTML = deepest(S.materials).map((d) =>
    `<li><a href="#/stats/${esc(d.material)}">${esc(d.material)}</a> — ${d.max_dtm} plies</li>`).join("");
}

function drawMaterial(name) {
  const box = $("stats-material");
  const r = lookup(S, name);
  if (!name) { box.innerHTML = ""; return; }
  if (!r.ok) { box.innerHTML = `<p class="status">${esc(name)}: ${esc(r.message)}</p>`; return; }
  const e = r.entry;
  box.innerHTML = `<h3>${esc(name)} — max DTM ${e.max_dtm}</h3>`
    + `<p><a href="material/${esc(name)}.html">material page</a></p>`
    + barChart({ bars: depthBars(e[state.stm]), log: state.log, xLabel: "depth (plies)",
      yLabel: `${name} positions per depth` });
}

export function initStats({ stats }) {
  S = stats;
  const names = Object.keys(S.materials).filter((n) => S.materials[n].max_dtm !== null).sort();
  $("stats-names").innerHTML = names.map((n) => `<option value="${esc(n)}">`).join("");
  $("stats-pick").addEventListener("change", (ev) => { location.hash = `#/stats/${ev.target.value.trim()}`; });
  for (const [id, key, on] of [["stats-stm", "stm", "wtm"], ["stats-log", "log", true]]) {
    $(id).addEventListener("change", (ev) => {
      state[key] = key === "log" ? ev.target.checked : (ev.target.checked ? on : "btm");
      drawCorpus();
      drawMaterial(decodeURIComponent(location.hash.split("/")[2] || ""));
    });
  }
  $("stats-pieces").addEventListener("change", (ev) => { state.pieces = ev.target.value; drawCorpus(); });
  drawCorpus();
}

export function showStats(arg) {
  const name = decodeURIComponent(arg || "");
  $("stats-pick").value = name;
  drawMaterial(name);
}
```

`site/index.html`: add `<a href="#/stats" data-screen="stats">Statistics</a>` after the Materials nav link, and inside `<main>`:

```html
  <section id="screen-stats" hidden>
    <h2>Statistics</h2>
    <p>From every table's statistics file; updated with each accepted contribution.
      The full data is on Hugging Face as Parquet (<code>stats/materials.parquet</code>,
      <code>stats/histogram.parquet</code>).</p>
    <p class="stats-controls">
      <label><input type="checkbox" id="stats-stm"> White to move (default: Black)</label>
      <label><input type="checkbox" id="stats-log" checked> logarithmic scale</label>
    </p>
    <div class="stats-grid">
      <figure><figcaption>Positions per depth, all tables (highlighted: exactly one solution)</figcaption><div id="stats-total"></div></figure>
      <figure><figcaption>Share of solvable positions with exactly one solution</figcaption><div id="stats-share"></div></figure>
      <figure><figcaption>Materials per maximum depth
        <select id="stats-pieces"><option value="all">all</option><option>3</option><option>4</option><option>5</option><option>6</option></select></figcaption>
        <div id="stats-maxdtm"></div><ol id="stats-deepest"></ol></figure>
    </div>
    <h3>One material</h3>
    <p><input id="stats-pick" list="stats-names" placeholder="e.g. KRvkrb" aria-label="material"><datalist id="stats-names"></datalist></p>
    <div id="stats-material"></div>
  </section>
```

`site/js/app.js`: `import { initStats, showStats } from "./stats.js";`, add `stats: { init: initStats, data: ["stats"] },` to `screens`, and in `show()` after the deepest line: `if (name === "stats") showStats(arg);`. Update the header comment's route list with `#/stats[/MATERIAL]`.

`site/js/materials.js`: in the row template (around line 70), after the material name cell for a done row append ` <a class="stats-link" href="#/stats/${esc(r.material)}">stats</a>` (only when `r.done`).

CSS (in the site's main stylesheet under `site/css/`, using its existing variable names — read the file to pick the accent/foreground/muted variables):

```css
.stats-grid { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr)); }
.stats-grid svg, #stats-material svg { width: 100%; height: auto; }
svg .bar { fill: var(--muted); }
svg .part { fill: var(--accent); }
svg .axis { fill: var(--fg); stroke: var(--fg); font-size: 11px; stroke-width: 0.5; }
svg text.axis { stroke: none; }
svg .empty { fill: var(--muted); }
```

(Replace `--muted`, `--accent`, `--fg` with the stylesheet's actual variable names; the test `tests/repo/test_accent_confined_to_focus_and_hover.py` restricts where the accent colour may be used — run it, and if it rejects `.part`, use the site's highlight/secondary colour variable instead and note it.)

- [ ] **Step 4: Run to verify they pass**

Run: `node --test site/tests/stats.test.js && make test-site && python3 -m pytest tests/repo/test_site_browser.py tests/repo/test_accent_confined_to_focus_and_hover.py tests/repo/test_site_ui.py -q`
Expected: all pass. Then look at it: `make serve-site`, open `#/stats` and `#/stats/KRvkrb` with Playwright, take a screenshot at 1280 px and 390 px width, check light and dark mode, no horizontal scroll at 390 px.

- [ ] **Step 5: Commit**

```bash
git add site/index.html site/js/app.js site/js/stats.js site/js/lib/stats.js site/js/materials.js site/css site/tests/stats.test.js tests/repo/test_site_browser.py
git commit -m "site: Statistics screen with corpus charts and a material picker"
```

---

### Task 8: Docs, changelog, full verification

**Files:**
- Modify: `CHANGELOG.md` (Unreleased: the Statistics screen, Parquet on Hugging Face, `stats-push`, stats-check workflow)
- Modify: `docs/CONTRIBUTING-TABLES.md` — maintainer section: `accept` now also uploads the statistics; `helpmate-tables stats-push --tables ~/tb [--dry-run]`, `--check`; the first-upload step after merge
- Modify: `docs/ROADMAP.md` — in "Ideas from the 2026-10-03 brainstorm", mark "Statistics as Parquet on Hugging Face" and "Statistics page with charts" as done (shipped in this PR); if PR #61 is not merged yet, skip this edit and note it in the PR description
- Modify: `.github/workflows/pages.yml` header comment: `site/data/stats.json` is committed site data like `materials.json`

- [ ] **Step 1: Write the docs** (plain English, the existing style of each file; no placeholders).

- [ ] **Step 2: Full verification**

```bash
PYTHONPATH=$PWD/src/packages/api:$PWD/src/packages/api/tests python3 -m pytest src/packages/api/tests tests/repo -q --deselect tests/repo/test_deepest_render.py::test_booklet_compiles
ruff check src/packages/api tools
mypy src/packages/api/helpmate_server/contrib
make test-site
PYTHONPATH=$PWD/src/packages/api python3 -m pytest src/packages/api/tests/test_contrib_corpus_stats.py src/packages/api/tests/test_contrib_stats_push.py --cov=helpmate_server.contrib.corpus_stats --cov=helpmate_server.contrib.stats_push --cov-report=term-missing -q
```

Expected: all green; coverage ≥ 80 % for both modules.

- [ ] **Step 3: Dry run against the real dataset (read-only)**

```bash
PYTHONPATH=$PWD/src/packages/api python3 -m helpmate_server.tables_cli stats-push --tables ~/tb --dry-run
PYTHONPATH=$PWD/src/packages/api python3 -m helpmate_server.tables_cli stats-push --check; echo "exit $?"
```

Expected: `would upload stats/histogram.parquet, stats/materials.parquet (419 tables)` (or the current count) and `stale: stats/materials.parquet is not on the dataset yet`, exit 1. Nothing is uploaded.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/CONTRIBUTING-TABLES.md docs/ROADMAP.md .github/workflows/pages.yml
git commit -m "docs: corpus statistics — maintainer steps, changelog"
```

## After the plan (maintainer, not the implementer)

1. Review and merge the PR (CI green).
2. `helpmate-tables stats-push --tables ~/tb` once (after reinstalling the CLI from main), then open the dataset page and check the viewer shows `materials` and `histogram`. If the viewer tries the `.hm` files despite `configs`, fall back to a separate statistics dataset (spec, Risks).
3. Run the "Stats check" workflow by hand once; it must pass.

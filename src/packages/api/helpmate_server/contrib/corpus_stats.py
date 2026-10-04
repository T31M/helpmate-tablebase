"""Corpus statistics from the tables' .stats.json sidecars: one row per table, the
lossless DTM x solution-count histogram, Parquet for Hugging Face and a compact JSON
for the site's Statistics screen. Nothing here reads a table's payload."""
from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import date
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

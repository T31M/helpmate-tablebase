import io
import json
from pathlib import Path

import pytest

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
    assert [t.material for t in collect(tmp_path)] == ["KPvk", "KQvk", "Kvkq"]


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


def test_parquet_round_trip_with_fixed_schema(tmp_path):
    pa = pytest.importorskip("pyarrow")  # noqa: F841
    import pyarrow.parquet as pq

    from helpmate_server.contrib.corpus_stats import (
        HISTOGRAM_PATH, MATERIALS_PATH, parquet_files, parquet_materials)

    _put(tmp_path, KQVK)
    _put(tmp_path, MARKER)
    files = parquet_files(collect(tmp_path), _registry(tmp_path))
    assert set(files) == {MATERIALS_PATH, HISTOGRAM_PATH}
    mat = pq.read_table(io.BytesIO(files[MATERIALS_PATH]))
    assert mat.column("material").to_pylist() == ["KQvk", "Kvkq"]
    assert str(mat.schema.field("max_dtm").type) == "int16"
    assert str(mat.schema.field("merged").type) == "date32[day]"
    assert mat.column("max_dtm").to_pylist() == [3, None]
    hist = pq.read_table(io.BytesIO(files[HISTOGRAM_PATH]))
    assert hist.num_rows == 6
    assert [str(f.type) for f in hist.schema] == ["string", "int8", "string", "int16", "int16", "int64"]
    assert parquet_materials(files[MATERIALS_PATH]) == ["KQvk", "Kvkq"]


def test_same_content_ignores_bytes_compares_tables(tmp_path):
    pa = pytest.importorskip("pyarrow")  # noqa: F841

    from helpmate_server.contrib.corpus_stats import (
        MATERIALS_PATH, parquet_files, same_content)

    _put(tmp_path, KQVK)
    a = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    b = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert same_content(a, b) and not same_content(None, b)
    _put(tmp_path, MARKER)
    c = parquet_files(collect(tmp_path), None)[MATERIALS_PATH]
    assert not same_content(a, c)


def test_completeness_against_the_manifest(tmp_path):
    pa = pytest.importorskip("pyarrow")  # noqa: F841

    from helpmate_server.contrib.corpus_stats import completeness

    _put(tmp_path, KQVK)
    _put(tmp_path, KPVK)
    manifest = {"files": {"KQvk.hm": {}, "KQvk.stats.json": {}, "KRvk.hm": {}}}
    assert completeness(collect(tmp_path), manifest) == (["KRvk"], ["KPvk"])
    assert completeness(collect(tmp_path), {"files": {"KQvk.hm": {}, "KPvk.hm": {}}}) == ([], [])


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

import json
from pathlib import Path

from helpmate_server.contrib.materials import Material
from helpmate_server.contrib.site_data import (
    corpus_summary, material_rows, priority, stats_row, write_site_data,
)

REFERENCE = Path(__file__).parent / "data" / "site_rows_reference.json"


def test_priority_counts_white_pieces():
    assert priority(Material("KQvkqbb")) == 1
    assert priority(Material("KRRvkbp")) == 2
    assert priority(Material("KRBNvkq")) == 3
    assert priority(Material("KQRBNvk")) == 4
    assert priority(Material("Kvkqqqq")) is None


def test_rows_cover_the_universe_plus_kvk(compressed_tables, tmp_path):
    pages = tmp_path / "material"
    pages.mkdir()
    (pages / "KQvk.json").write_text("{}")
    rows = material_rows(compressed_tables, pages)
    by = {r["material"]: r for r in rows}
    assert len(rows) == 1001 and "Kvk" in by
    assert by["KQvk"]["done"] and by["KQvk"]["page"] and by["KQvk"]["max_dtm"] == 14
    assert by["KPvk"]["done"] and not by["KPvk"]["page"]
    assert by["KRBvkqq"] == {"material": "KRBvkqq", "pieces": 6, "pawns": 0, "ram_gib": 32,
                             "priority": 2, "done": False, "page": False, "max_dtm": None,
                             "solvable": None, "unique": None, "size_bytes": None}
    assert by["KQvk"]["ram_gib"] is None and by["Kvkqqqq"]["priority"] is None


def test_done_rows_and_summary_equal_the_old_tool(compressed_tables):
    """The reference was produced by the original tools/build_site_data.py
    (material_row / corpus_summary) on this fixture, before it became a re-export.

    It holds no file sizes: the generator compresses with the system libzstd,
    and different zstd versions write different bytes for the same planes
    (CI and this box differ by ~0.05 %). Sizes are checked against the files."""
    ref = json.loads(REFERENCE.read_text())
    new = {r["material"]: r for r in material_rows(compressed_tables, None) if r["done"]}
    assert set(new) == {r["material"] for r in ref["rows"]}
    for r in ref["rows"]:
        assert {k: new[r["material"]][k] for k in r} == r
        assert new[r["material"]]["size_bytes"] == (compressed_tables / f'{r["material"]}.hm').stat().st_size
    summary = corpus_summary(list(new.values()))
    assert summary.pop("size_bytes") == sum(r["size_bytes"] for r in new.values())
    assert summary == ref["summary"]


def test_write_site_data_only_rewrites_on_change(compressed_tables, tmp_path):
    first = write_site_data(tmp_path, compressed_tables)
    assert {p.name for p in first} == {"materials.json", "corpus.json"}
    assert write_site_data(tmp_path, compressed_tables) == []
    assert json.loads((tmp_path / "corpus.json").read_text())["tables"] == \
        len(list(compressed_tables.glob("*.stats.json")))


def test_stats_row_matches_the_documented_example():
    real = {"material": "KQvk", "plane_size": 100, "max_dtm": 14,
            "cells": {"invalid": {"wtm": 10, "btm": 10}, "unsolvable": {"wtm": 5, "btm": 5}},
            "uniqueness": {"wtm": {"2": {"1": 3, "2": 9}}, "btm": {"1": {"1": 4}}}}
    assert stats_row(real, 1000) == {"material": "KQvk", "pieces": 3, "max_dtm": 14,
                                     "solvable": 170, "unique": 7, "size_bytes": 1000}

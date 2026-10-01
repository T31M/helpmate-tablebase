import json
import os
import re
from pathlib import Path

import pytest

from helpmate_server.contrib.claims import ClaimIndex, material_status
from helpmate_server.contrib.docs_sync import (
    CorpusFacts, render_contributors, replace_spans,
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


def _fake_corpus(tmp_path):
    """Two real six-piece tables, a marker with a real White piece, a bare-king
    marker, a five-piece table and a five-piece marker."""
    files, sidecars = {}, {
        "KQRvkqr": {"plane_size": 10, "max_dtm": 20},
        "KRRvkqr": {"plane_size": 10, "max_dtm": 30},
        "KBvkrrr": {"plane_size": 10, "max_dtm": 0, "all_unsolvable": True},
        "Kvkqqqq": {"plane_size": 10, "max_dtm": 255},       # marker by max_dtm alone
        "KQvk": {"plane_size": 5, "max_dtm": 10},
        "KBvkn": {"plane_size": 5, "max_dtm": 0, "all_unsolvable": True},
    }
    for name, sc in sidecars.items():
        files[f"{name}.hm"] = {"size": 2**30}
        files[f"{name}.stats.json"] = {"size": 1}
        (tmp_path / f"{name}.stats.json").write_text(json.dumps({"material": name, **sc}))
    return {"files": files}


def test_six_piece_counts_use_the_715_frame(tmp_path):
    f = CorpusFacts.from_manifest(_fake_corpus(tmp_path), tmp_path)
    v = f.values()
    assert v["six-total"] == "715"
    assert v["six-done"] == "4"          # KQRvkqr KRRvkqr KBvkrrr Kvkqqqq; five-piece ones do not count
    assert v["six-empty"] == "2"         # KBvkrrr, Kvkqqqq
    assert v["six-open"] == "711"
    # missing by pawns: 715 six-piece classes, 4 done (all pawnless)
    from helpmate_server.contrib.materials import universe
    by_p = [sum(m.pieces == 6 and m.pawns == p for m in universe()) for p in range(5)]
    assert [int(v[f"six-open-p{p}"]) for p in range(5)] == [by_p[0] - 4, *by_p[1:]]
    assert v["tables"] == "6"
    # markers store a verdict, not cells: only the three real tables count
    assert v["tables-real"] == "3"
    assert v["cells-billion"] == f"{2 * (10 + 10 + 5) / 1e9:.1f}"
    assert f.cells == 50
    # the deepest ignores markers
    assert v["deepest"] == "h#15"


def test_bare_king_table_missing_counts_as_open(tmp_path):
    m = _fake_corpus(tmp_path)
    del m["files"]["Kvkqqqq.hm"], m["files"]["Kvkqqqq.stats.json"]
    v = CorpusFacts.from_manifest(m, tmp_path).values()
    assert (v["six-done"], v["six-empty"], v["six-open"]) == ("3", "1", "712")


@pytest.mark.skipif(not (CORPUS / "manifest.json").exists(), reason="needs the real corpus")
def test_real_corpus_six_piece_invariants():
    f = CorpusFacts.from_manifest(json.loads((CORPUS / "manifest.json").read_text()), CORPUS)
    v = f.values()
    done, empty, opened = int(v["six-done"]), int(v["six-empty"]), int(v["six-open"])
    assert v["six-total"] == "715"
    assert done + opened == 715
    assert sum(int(v[f"six-open-p{p}"]) for p in range(5)) == opened
    assert 0 <= empty <= done
    assert 0 < int(v["tables-real"]) <= int(v["tables"])
    assert int(v["tables-real"]) == int(v["tables"]) - len(f.markers & f.done())
    assert re.fullmatch(r"h#\d+(\.5)?", v["deepest"])


def _statuses(done):
    reg = Registry.load(REPO / "data" / "contributions.json")
    return material_status(set(done), {}, ClaimIndex([]), reg), reg


def test_contributor_table_lists_t31m():
    reg = Registry.load(REPO / "data" / "contributions.json")
    st, reg = _statuses(set(reg.tables))
    table = render_contributors(reg, st)
    n = len([m for m in reg.tables_of("T31M") if st[m].state == "done"])   # grows as T31M contributes
    assert "T31M" in table and f"| {n}: " in table and "KRBvkqq" in table
    assert "PR #1" in table and "h#17" in table


def test_sync_rewrites_spans_writes_files_and_closes_finished_claims(tmp_path):
    from fakes import FakeGitHub, FakeHub

    from helpmate_server.contrib.docs_sync import SPAN_FILES, sync

    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "site" / "data").mkdir(parents=True)
    for f in SPAN_FILES:
        (tmp_path / f).write_text("n=<!-- contrib:tables -->0<!-- /contrib -->\n")
    manifest = {"files": {"KQvk.hm": {"size": 2**30}, "KRvk.hm": {"size": 2**30},
                          "KQvk.stats.json": {"size": 1}}}
    (tmp_path / "KQvk.stats.json").write_text('{"material": "KQvk", "plane_size": 1000000000, "max_dtm": 34}')
    (tmp_path / "KQvk.hm").write_bytes(b"hm")
    hub = FakeHub({"manifest.json": json.dumps(manifest).encode()})
    issue = {"number": 7, "title": "Claim: KQvk", "body": "", "user": {"login": "bob"},
             "created_at": "2026-09-01T00:00:00Z"}
    gh = FakeGitHub([issue])
    # A registry of its own: the real data/contributions.json grows with every
    # accepted contribution, and this test must not pin its contents.
    (tmp_path / "data" / "contributions.json").write_text(json.dumps({
        "schema": 1,
        "contributors": {"T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"}},
        "tables": {"KRBvkqq": {"contributor": "T31M", "hf_pr": 1, "claim": 41, "merged": "2026-09-26",
                               "generator_version": "0.19.0", "verification": None}}}))
    reg = Registry.load(tmp_path / "data" / "contributions.json")
    written = sync(tmp_path, hub, gh, reg, tmp_path)
    assert (tmp_path / "README.md").read_text() == "n=<!-- contrib:tables -->2<!-- /contrib -->\n"
    assert {p.name for p in written} >= {"materials.json", "corpus.json", ".all-contributorsrc",
                                         "README.md"}
    assert not list((tmp_path / "docs").glob("[Mm]aterials*"))
    rows = json.loads((tmp_path / "site" / "data" / "materials.json").read_text())
    assert any(r["material"] == "KQvk" and r["done"] for r in rows)
    corpus = json.loads((tmp_path / "site" / "data" / "corpus.json").read_text())
    assert corpus["tables"] == sum(r["done"] for r in rows) == 1
    assert corpus["by_pieces"] == {"3": 1}
    rc = json.loads((tmp_path / ".all-contributorsrc").read_text())
    assert [c["login"] for c in rc["contributors"]] == ["T31M"]
    assert rc["contributors"][0]["contributions"] == ["data"]
    assert gh.closed == [7]
    # second run: nothing to rewrite
    assert sync(tmp_path, hub, FakeGitHub(), reg, tmp_path, close_claims=False) == []


def test_cli_sync_rejects_a_non_checkout(tmp_path, capsys):
    import argparse

    from helpmate_server.contrib import cli
    a = argparse.Namespace(cmd="sync", tables=str(tmp_path), checkout=tmp_path, repo="x/y",
                           github_repo="x/y", no_close=True)
    assert cli.run(a) != 0
    assert "not a helpmate-tablebase checkout" in capsys.readouterr().err


def test_sync_refuses_when_sidecars_are_missing(tmp_path, capsys):
    import argparse

    from fakes import FakeGitHub, FakeHub

    from helpmate_server.contrib import cli
    from helpmate_server.contrib.docs_sync import SPAN_FILES, SyncError, sync

    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "site" / "data").mkdir(parents=True)
    (tmp_path / "data" / "contributions.json").write_text(
        (REPO / "data" / "contributions.json").read_text())
    for f in SPAN_FILES:
        (tmp_path / f).write_text("n=<!-- contrib:tables -->0<!-- /contrib -->\n")
    manifest = {"files": {"KQvk.hm": {"size": 1}, "KQvk.stats.json": {"size": 1}}}
    hub = FakeHub({"manifest.json": json.dumps(manifest).encode()})
    empty = tmp_path / "tb"
    empty.mkdir()
    reg = Registry.load(REPO / "data" / "contributions.json")
    with pytest.raises(SyncError, match=r"1 of 1 sidecars.*KQvk.stats.json"):
        sync(tmp_path, hub, FakeGitHub(), reg, empty)
    assert not list((tmp_path / "docs").glob("[Mm]aterials*"))
    assert list((tmp_path / "site" / "data").iterdir()) == []
    assert (tmp_path / "README.md").read_text() == "n=<!-- contrib:tables -->0<!-- /contrib -->\n"
    a = argparse.Namespace(cmd="sync", tables=str(empty), checkout=tmp_path, repo="x/y",
                           github_repo="x/y", no_close=True)
    assert cli.run(a, lambda repo: hub, lambda repo: FakeGitHub()) == 2
    assert "sidecars" in capsys.readouterr().err

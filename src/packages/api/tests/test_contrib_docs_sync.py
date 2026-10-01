import json
import os
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


@pytest.mark.skipif(not (CORPUS / "manifest.json").exists(), reason="needs the real corpus")
def test_facts_reproduce_the_v0_20_0_numbers():
    f = CorpusFacts.from_manifest(json.loads((CORPUS / "manifest.json").read_text()), CORPUS)
    v = f.values()
    assert (v["tables"], v["gib"], v["six-done"], v["six-open"], v["six-open-p0"],
            v["deepest"], v["cells-billion"]) == ("317", "172.5", "31", "614", "269", "h#17", "713.9")


def _statuses(done):
    reg = Registry.load(REPO / "data" / "contributions.json")
    return material_status(set(done), {}, ClaimIndex([]), reg), reg


def test_contributor_table_lists_t31m():
    reg = Registry.load(REPO / "data" / "contributions.json")
    st, reg = _statuses(set(reg.tables))
    table = render_contributors(reg, st)
    assert "T31M" in table and "15" in table and "KRBvkqq" in table
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
    reg = Registry.load(REPO / "data" / "contributions.json")
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

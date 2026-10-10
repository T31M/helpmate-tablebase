import json
import re

from fakes import FakeGitHub, FakeHub
from helpmate_server import tables_cli
from helpmate_server.contrib.verify import reusable

SETTINGS = {"samples": 2000, "oracle_samples": 20, "oracle_plies": 3, "date": "2026-10-09"}
TOOL = "helpmate-tables 0.21.0"
PREV = {"tool": TOOL, "head": "h1", "samples": 2000, "oracle_samples": 20,
        "oracle_plies": 3, "date": "2026-10-01",
        "tables": {"KQvk": {"passed": True, "checks": [], "hm_sha256": "a", "stats_sha256": "b",
                            "payload_sha256": "p", "seed": 7},
                   "KRvk": {"passed": False, "checks": [], "hm_sha256": "c", "stats_sha256": "d",
                            "payload_sha256": "q", "seed": 7}}}


def test_reuse_when_everything_matches_even_on_another_date():
    assert reusable(PREV, "KQvk", ("a", "b"), TOOL, SETTINGS) is PREV["tables"]["KQvk"]


def test_no_reuse_when_the_sidecar_changed():
    assert reusable(PREV, "KQvk", ("a", "X"), TOOL, SETTINGS) is None


def test_no_reuse_for_failed_tables_other_tools_settings_or_no_report():
    assert reusable(PREV, "KRvk", ("c", "d"), TOOL, SETTINGS) is None
    assert reusable(PREV, "KQvk", ("a", "b"), "helpmate-tables 0.22.0", SETTINGS) is None
    assert reusable(PREV, "KQvk", ("a", "b"), TOOL, dict(SETTINGS, samples=10)) is None
    assert reusable(None, "KQvk", ("a", "b"), TOOL, SETTINGS) is None


def test_reuse_needs_the_same_comparison_source():
    entry = PREV["tables"]["KQvk"]
    assert reusable(PREV, "KQvk", ("a", "b"), TOOL, SETTINGS, "pub") is None   # verified fully, now a duplicate
    prev = {**PREV, "tables": {"KQvk": {**entry, "source_payload": "pub"}}}
    assert reusable(prev, "KQvk", ("a", "b"), TOOL, SETTINGS, "pub") is prev["tables"]["KQvk"]
    assert reusable(prev, "KQvk", ("a", "b"), TOOL, SETTINGS, "other") is None
    assert reusable(prev, "KQvk", ("a", "b"), TOOL, SETTINGS) is None           # duplicate gone


ARGS = ["--samples", "50", "--oracle-samples", "2", "--oracle-plies", "1", "--seed", "1"]


def _setup(tmp_path, corpus):
    main = {p.name: p.read_bytes() for p in corpus.iterdir()
            if not p.name.startswith(("KQvk.", "KRvk."))}
    pair = {n: (corpus / n).read_bytes() for n in
            ("KQvk.hm", "KQvk.stats.json", "KRvk.hm", "KRvk.stats.json")}
    hub = FakeHub(main)
    hub.add_pr(2, pair, description="Claim: #39", head="h1")
    tables = tmp_path / "tb"
    tables.mkdir()
    for n, b in main.items():
        (tables / n).write_bytes(b)
    return hub, pair, tables


def _run(hub, tables, staging, *extra):
    return tables_cli.main(["verify", "--tables", str(tables), "--pr", "2", "--staging",
                            str(staging), "--yes", "--no-post", *ARGS, *extra],
                           hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())


def _revise(hub, pair):
    """New head where only KRvk's sidecar bytes differ (same JSON content)."""
    sc = json.loads(pair["KRvk.stats.json"])
    hub.add_pr(2, {**pair, "KRvk.stats.json": json.dumps(sc, indent=3).encode()},
               description="Claim: #39", head="h2")


def test_progress_lines(tmp_path, compressed_tables, capsys):
    hub, _, tables = _setup(tmp_path, compressed_tables)
    assert _run(hub, tables, tmp_path / "st") == 0
    assert re.search(r"\[1/2\] KQvk V2 .* pass \(", capsys.readouterr().out)


def test_revised_pr_reuses_unchanged_tables(tmp_path, compressed_tables, capsys):
    hub, pair, tables = _setup(tmp_path, compressed_tables)
    st = tmp_path / "st"
    assert _run(hub, tables, st) == 0
    first = json.loads((st / "pr-2" / "report.json").read_text())
    capsys.readouterr()
    _revise(hub, pair)
    assert _run(hub, tables, st) == 0
    out = capsys.readouterr().out
    rep = json.loads((st / "pr-2" / "report.json").read_text())
    assert rep["head"] == "h2"
    assert "KQvk reused from h1" in out and "KRvk reused" not in out
    assert all(c["reused_from"] == "h1" for c in rep["tables"]["KQvk"]["checks"])
    assert all("reused_from" not in c for c in rep["tables"]["KRvk"]["checks"])
    assert rep["tables"]["KQvk"]["seed"] == first["tables"]["KQvk"]["seed"]
    assert rep["tables"]["KQvk"]["payload_sha256"]
    assert "(reused from h1)" in (st / "pr-2" / "report.md").read_text()
    assert json.loads((st / "pr-2" / "report.prev.json").read_text()) == first


def test_full_reuses_nothing(tmp_path, compressed_tables, capsys):
    hub, pair, tables = _setup(tmp_path, compressed_tables)
    st = tmp_path / "st"
    _run(hub, tables, st)
    _revise(hub, pair)
    capsys.readouterr()
    assert _run(hub, tables, st, "--full") == 0
    assert "reused" not in capsys.readouterr().out
    rep = json.loads((st / "pr-2" / "report.json").read_text())
    assert all("reused_from" not in c for t in rep["tables"].values() for c in t["checks"])

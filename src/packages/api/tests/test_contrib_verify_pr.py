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


def test_claim_line_must_point_at_this_repository():
    assert parse_links("Claim: someone/else#12") == (None, None)
    assert parse_links("Claim: someone/helpmate-tablebase#12") == (None, None)
    assert parse_links("Claim: Osick/Helpmate-Tablebase#12") == (12, None)   # GitHub ignores case
    assert parse_links("claim: #7") == (7, None)


def _pr(files, description="Claim: #39", deleted=()):
    return PullRequest(2, "Add", "popeye37", "open", description, files, "h", "u", list(deleted))


def test_v1_hygiene():
    ok = check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"]), {})
    assert ok.status == "pass"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm"]), {}).status == "fail"            # no sidecar
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json", "manifest.json"]),
                            {}).status == "fail"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"]),
                            {"KRRvkqq.hm": {"sha256": "ab", "size": 1}}).status == "fail"
    assert check_pr_hygiene(_pr(["KRRvkqq.hm", "KRRvkqq.stats.json"], ""), {}).status == "warn"


def test_v1_fails_deletions_subdirectories_and_prs_without_tables():
    pair = ["KRRvkqq.hm", "KRRvkqq.stats.json"]
    c = check_pr_hygiene(_pr(pair, deleted=["KQvk.hm"]), {})
    assert c.status == "fail" and "PR deletes KQvk.hm" in c.detail
    c = check_pr_hygiene(_pr(pair + ["sub/KRRvkqr.hm", "sub/KRRvkqr.stats.json"]), {})
    assert c.status == "fail" and "sub/KRRvkqr.hm" in c.detail
    c = check_pr_hygiene(_pr([]), {})
    assert c.status == "fail" and "no tables in this PR" in c.detail
    c = check_pr_hygiene(_pr([], deleted=["README.md"]), {})
    assert c.status == "fail" and "PR deletes README.md" in c.detail


def test_verify_pr_fails_a_pr_that_deletes_a_published_file(tmp_path, compressed_tables):
    main = {p.name: p.read_bytes() for p in compressed_tables.iterdir() if not p.name.startswith("KQvk.")}
    hub = FakeHub(main)
    hub.add_pr(2, {n: (compressed_tables / n).read_bytes() for n in ("KQvk.hm", "KQvk.stats.json")},
               description="Claim: #39", head="abc123", delete=["KPvk.stats.json"])
    staging = tmp_path / "st"
    assert _run_pr(hub, _tables_without_kqvk(tmp_path, compressed_tables), staging) == 1
    rep = json.loads((staging / "pr-2" / "report.json").read_text())
    assert rep["result"] == "fail" and "PR deletes KPvk.stats.json" in rep["pr_checks"][0]["detail"]


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


def test_main_moving_on_does_not_add_files_to_the_pr(tmp_path, compressed_tables):
    hub = _hub_with_kqvk_pr(compressed_tables)
    hub.commit({"manifest.json": b'{"schema":1,"files":{}}', "README.md": b"card"}, "another accept")
    staging = tmp_path / "st"
    assert _run_pr(hub, _tables_without_kqvk(tmp_path, compressed_tables), staging) == 0
    rep = json.loads((staging / "pr-2" / "report.json").read_text())
    assert rep["pr_checks"][0]["status"] == "pass"
    assert sorted(hub.downloads) == ["KQvk.hm", "KQvk.stats.json"]


def test_report_records_the_sampling_settings_and_date(tmp_path, compressed_tables):
    import datetime
    hub = _hub_with_kqvk_pr(compressed_tables)
    staging = tmp_path / "st"
    assert _run_pr(hub, _tables_without_kqvk(tmp_path, compressed_tables), staging,
                   "--oracle-plies", "2") == 0
    rep = json.loads((staging / "pr-2" / "report.json").read_text())
    assert (rep["samples"], rep["oracle_samples"], rep["oracle_plies"]) == (50, 2, 2)
    assert rep["date"] == datetime.datetime.now(datetime.timezone.utc).date().isoformat()


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


def test_missing_subtable_stops_and_posts_nothing(tmp_path, compressed_tables, capsys):
    """An incomplete maintainer corpus is not the contributor's fault."""
    hub, gh = _hub_with_kqvk_pr(compressed_tables), FakeGitHub()
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = tables_cli.main(["verify", "--tables", str(empty), "--pr", "2",
                          "--staging", str(tmp_path / "st"), "--yes", *ARGS],
                         hub_factory=lambda r: hub, gh_factory=lambda r: gh)
    assert rc == 2
    assert hub.comments == [] and gh.posted == []
    assert capsys.readouterr().err.strip()


def _run_pr(hub, tables, staging, *extra):
    return tables_cli.main(["verify", "--tables", str(tables), "--pr", "2", "--staging",
                            str(staging), "--yes", "--no-post", *ARGS, *extra],
                           hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())


def test_truncated_staged_file_is_redownloaded(tmp_path, compressed_tables):
    hub = _hub_with_kqvk_pr(compressed_tables)
    tables, staging = _tables_without_kqvk(tmp_path, compressed_tables), tmp_path / "st"
    _run_pr(hub, tables, staging)
    n = len(hub.downloads)
    f = staging / "pr-2" / "files" / "KQvk.hm"
    f.write_bytes(f.read_bytes()[:10])
    assert _run_pr(hub, tables, staging) == 0
    assert len(hub.downloads) > n
    assert json.loads((staging / "pr-2" / "report.json").read_text())["result"] == "pass"


def test_new_head_with_same_sizes_is_redownloaded(tmp_path, compressed_tables):
    hub = _hub_with_kqvk_pr(compressed_tables)
    tables, staging = _tables_without_kqvk(tmp_path, compressed_tables), tmp_path / "st"
    _run_pr(hub, tables, staging)
    n = len(hub.downloads)
    pr, files = hub.prs[2]
    pr.head = "h2"
    hub.prs[2] = (pr, files)
    _run_pr(hub, tables, staging)
    assert len(hub.downloads) > n
    assert json.loads((staging / "pr-2" / "report.json").read_text())["head"] == "h2"
    assert (staging / "pr-2" / "files" / ".head").read_text() == "h2"


def test_unsafe_file_name_downloads_nothing_and_fails(tmp_path, compressed_tables):
    hub = FakeHub()
    hub.add_pr(2, {"../evil.hm": b"x", "../evil.stats.json": b"y"}, description="Claim: #39")
    assert _run_pr(hub, tmp_path / "tb", tmp_path / "st") == 1
    assert hub.downloads == []
    rep = json.loads((tmp_path / "st" / "pr-2" / "report.json").read_text())
    assert rep["result"] == "fail"


def test_interrupted_download_resumes_with_only_the_missing_file(tmp_path, compressed_tables):
    import pytest

    class Flaky(FakeHub):
        fail = True

        def download(self, filename, revision, dest):
            if self.fail and len(self.downloads) == 1:
                raise OSError("network dropped")
            return super().download(filename, revision, dest)

    base = _hub_with_kqvk_pr(compressed_tables)
    hub = Flaky(base.main)
    hub.prs, hub.bases, hub.deletes = base.prs, base.bases, base.deletes
    tables, staging = _tables_without_kqvk(tmp_path, compressed_tables), tmp_path / "st"
    with pytest.raises(OSError):
        _run_pr(hub, tables, staging)
    assert len(hub.downloads) == 1
    hub.fail = False
    assert _run_pr(hub, tables, staging) == 0
    assert len(hub.downloads) == 2
    assert json.loads((staging / "pr-2" / "report.json").read_text())["result"] == "pass"


def test_plan_only_lists_several_prs_after_one_flag(tmp_path, compressed_tables, capsys):
    hub = _hub_with_kqvk_pr(compressed_tables)
    for n in ("KPvk.hm", "KPvk.stats.json"):
        hub.main.pop(n)                                   # PR 3 adds KPvk
    hub.add_pr(3, {n: (compressed_tables / n).read_bytes() for n in ("KPvk.hm", "KPvk.stats.json")},
               head="def456")
    tb = _tables_without_kqvk(tmp_path, compressed_tables)
    rc = tables_cli.main(["verify", "--tables", str(tb), "--pr", "2", "3",
                          "--staging", str(tmp_path / "st"), "--plan-only"],
                         hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())
    out = capsys.readouterr().out
    assert rc == 0 and hub.downloads == [] and "KQvk.hm" in out and "KPvk.hm" in out

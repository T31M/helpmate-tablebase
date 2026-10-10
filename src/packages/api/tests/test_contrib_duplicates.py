# src/packages/api/tests/test_contrib_duplicates.py
import json
import shutil

import pytest

from fakes import FakeGitHub, FakeHub
from helpmate_server import tables_cli
from helpmate_server.contrib.checks import MissingPublished, check_identical
from helpmate_server.contrib.claims import Claim, ClaimIndex
from helpmate_server.contrib.tablefile import payload_sha256
from helpmate_server.contrib.verify import (
    PublishedHashes, VerifyOptions, check_pr_hygiene, classify, verify_table,
)
from test_contrib_verify_pr import ARGS, _pr


def test_v1_names_duplicates_instead_of_failing():
    check, dups = check_pr_hygiene(_pr(["KQvk.hm", "KQvk.stats.json", "KRvk.hm", "KRvk.stats.json"]),
                                   {"KQvk.hm": {"sha256": "ab", "size": 1}})
    assert check.status in ("pass", "warn") and dups == {"KQvk"}
    assert "duplicates of published tables: KQvk" in check.detail


def test_v8_pass_fail_and_unknown():
    assert check_identical("a" * 64, "a" * 64).status == "pass"
    assert check_identical("a" * 64, "b" * 64).status == "fail"
    assert check_identical(None, "b" * 64).status == "fail"
    assert check_identical("marker:x", "a" * 64).status == "fail"     # real vs marker
    assert "HF PR #2" in check_identical("a" * 64, "a" * 64, "HF PR #2").detail


def test_published_hashes_cache_and_invalidation(tmp_path, compressed_tables):
    shutil.copy(compressed_tables / "KQvk.hm", tmp_path)
    shutil.copy(compressed_tables / "KQvk.stats.json", tmp_path)
    ph = PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s1", "size": 1}})
    h = ph.get("KQvk")
    assert h == payload_sha256(tmp_path / "KQvk.hm")
    cache = json.loads((tmp_path / ".payload-sha256.json").read_text())
    assert cache["KQvk"] == {"hm_sha256": "s1", "payload": h}
    cache["KQvk"]["payload"] = "stale"
    (tmp_path / ".payload-sha256.json").write_text(json.dumps(cache))
    assert PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s1", "size": 1}}).get("KQvk") == "stale"  # cache hit
    assert PublishedHashes(tmp_path, {"KQvk.hm": {"sha256": "s2", "size": 1}}).get("KQvk") == h        # sha changed
    with pytest.raises(MissingPublished):
        PublishedHashes(tmp_path, {"KRvk.hm": {"sha256": "x", "size": 1}}).get("KRvk")


def test_duplicate_runs_v2_to_v4_and_v8_and_skips_v5_to_v7(table_copy):
    published = payload_sha256(table_copy / "KQvk.hm")
    rep = verify_table("KQvk", table_copy, VerifyOptions(samples=10, oracle_samples=1, oracle_plies=1, seed=1),
                       "99.0.0", published=published)
    ids = {c.id: c for c in rep.checks}
    assert [ids[k].status for k in ("V2", "V3", "V4", "V8")] == ["pass"] * 4
    assert all(ids[k].status == "skip" and "independent reproduction: identical to the published table"
               in ids[k].detail for k in ("V5", "V6", "V7"))
    assert rep.passed


def test_duplicate_with_different_content_fails(table_copy):
    rep = verify_table("KQvk", table_copy, VerifyOptions(seed=1), "99.0.0", published="f" * 64)
    assert not rep.passed and any(c.id == "V8" and c.status == "fail" for c in rep.checks)
    assert {c.id: c.detail for c in rep.checks}["V5"] == "an earlier check failed"


def test_classify_labels():
    pr = _pr(["KQvk.hm", "KQvk.stats.json", "KRvk.hm", "KRvk.stats.json",
              "KBvk.hm", "KBvk.stats.json", "KNvk.hm", "KNvk.stats.json"])
    index = ClaimIndex([Claim(7, "alice", "2026-10-01T00:00:00Z", ["KBvk"]),
                        Claim(8, "Bob", "2026-10-01T00:00:00Z", ["KNvk"])])
    files = {"KQvk.hm": {}}
    got = classify(pr, files, index, {"KRvk": 1}, "bob")
    assert got == {"KQvk": "duplicate of published", "KRvk": "duplicate of HF PR #1",
                   "KBvk": "held for claim #7", "KNvk": "new"}
    assert classify(pr, files, index, {}, None)["KNvk"] == "held for claim #8"
    assert classify(pr, files, None, {}, None)["KBvk"] == "new"


def _dup_hub(corpus):
    main = {p.name: p.read_bytes() for p in corpus.iterdir() if not p.name.startswith("KQvk.")}
    main["KQvk.hm"] = b"published elsewhere"     # the PR's bytes differ; the payload is what matters
    main["manifest.json"] = json.dumps({"schema": 1, "files": {"KQvk.hm": {"sha256": "ab", "size": 19}}}).encode()
    hub = FakeHub(main)
    hub.add_pr(2, {n: (corpus / n).read_bytes() for n in ("KQvk.hm", "KQvk.stats.json")},
               description="Claim: #39", head="abc123")
    return hub


def _verify(hub, tables, staging, *prs):
    argv = ["verify", "--tables", str(tables), "--staging", str(staging), "--yes", "--no-post", *ARGS]
    for n in prs:
        argv += ["--pr", str(n)]
    return tables_cli.main(argv, hub_factory=lambda r: hub, gh_factory=lambda r: FakeGitHub())


def test_verify_prs_duplicate_of_published(tmp_path, compressed_tables):
    rc = _verify(_dup_hub(compressed_tables), compressed_tables, tmp_path / "st", 2)
    assert rc == 0
    rep = json.loads((tmp_path / "st" / "pr-2" / "report.json").read_text())
    checks = {c["id"]: c for c in rep["tables"]["KQvk"]["checks"]}
    assert checks["V8"]["status"] == "pass"
    assert all(checks[k]["status"] == "skip" for k in ("V5", "V6", "V7"))
    assert "duplicate of published" in rep["pr_checks"][0]["detail"]


def test_verify_prs_published_table_missing_locally(tmp_path, compressed_tables, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _verify(_dup_hub(compressed_tables), empty, tmp_path / "st", 2) == 2
    assert "sync the corpus first" in capsys.readouterr().err


def test_second_pr_repeating_the_first_is_verified_against_it(tmp_path, compressed_tables):
    main = {p.name: p.read_bytes() for p in compressed_tables.iterdir() if not p.name.startswith("KQvk.")}
    hub = FakeHub(main)
    for n in (2, 3):
        hub.add_pr(n, {k: (compressed_tables / k).read_bytes() for k in ("KQvk.hm", "KQvk.stats.json")},
                   description="Claim: #39", head=f"h{n}")
    tables = tmp_path / "tb"
    tables.mkdir()
    for p in compressed_tables.iterdir():
        if not p.name.startswith("KQvk."):
            (tables / p.name).write_bytes(p.read_bytes())
    assert _verify(hub, tables, tmp_path / "st", 2, 3) == 0
    r2 = json.loads((tmp_path / "st" / "pr-2" / "report.json").read_text())
    r3 = json.loads((tmp_path / "st" / "pr-3" / "report.json").read_text())
    c2 = {c["id"]: c for c in r2["tables"]["KQvk"]["checks"]}
    c3 = {c["id"]: c for c in r3["tables"]["KQvk"]["checks"]}
    assert "V8" not in c2 and c2["V6"]["status"] == "pass"
    assert c3["V8"]["status"] == "pass" and "HF PR #2" in c3["V8"]["detail"]
    assert all(c3[k]["status"] == "skip" and "HF PR #2" in c3[k]["detail"] for k in ("V5", "V6", "V7"))
    assert "KQvk: duplicate of HF PR #2" in r3["pr_checks"][0]["detail"]

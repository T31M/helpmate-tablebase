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
    assert c3["V5"]["status"] == "pass"           # its sidecar may be the one published (R19)
    assert all(c3[k]["status"] == "skip" and "HF PR #2" in c3[k]["detail"] for k in ("V6", "V7"))
    assert "KQvk: duplicate of HF PR #2" in r3["pr_checks"][0]["detail"]


def test_marker_redelivered_as_identical_marker_passes_v8(table_copy):
    from helpmate_server.contrib.tablefile import read_header
    marker = next(p.stem for p in sorted(table_copy.glob("*.hm")) if read_header(p).marker)
    published = PublishedHashes(table_copy, {f"{marker}.hm": {"sha256": "s", "size": 1}}).get(marker)
    assert published.startswith("marker:")
    rep = verify_table(marker, table_copy, VerifyOptions(seed=1), "99.0.0", published=published)
    assert rep.passed and {c.id: c.status for c in rep.checks}["V8"] == "pass"
    assert not verify_table(marker, table_copy, VerifyOptions(seed=1), "99.0.0",
                            published="a" * 64).passed


def _fresh_hub(corpus, tmp_path, prs=(2,), description="Claim: #39", broken=()):
    """Main and --tables lack KQvk; each PR in `prs` delivers it (truncated if in `broken`)."""
    main = {p.name: p.read_bytes() for p in corpus.iterdir() if not p.name.startswith("KQvk.")}
    hub = FakeHub(main)
    for n in prs:
        hm = (corpus / "KQvk.hm").read_bytes()
        hub.add_pr(n, {"KQvk.hm": hm[:200] if n in broken else hm,
                       "KQvk.stats.json": (corpus / "KQvk.stats.json").read_bytes()},
                   description=description, head=f"h{n}")
    tables = tmp_path / "tb"
    tables.mkdir()
    for name in main:
        if name != "manifest.json":
            (tables / name).write_bytes(main[name])
    return hub, tables


def _report(tmp_path, n):
    return json.loads((tmp_path / "st" / f"pr-{n}" / "report.json").read_text())


def test_failed_earlier_pr_is_neither_source_nor_named(tmp_path, compressed_tables):
    hub, tables = _fresh_hub(compressed_tables, tmp_path, prs=(2, 3), broken=(2,))
    assert _verify(hub, tables, tmp_path / "st", 2, 3) == 1
    assert _report(tmp_path, 2)["result"] == "fail"
    r3 = _report(tmp_path, 3)
    ids = {c["id"] for c in r3["tables"]["KQvk"]["checks"]}
    assert r3["result"] == "pass" and "V8" not in ids
    assert "HF PR #2" not in r3["pr_checks"][0]["detail"]


def test_duplicate_whose_v8_fails_fails_the_run(tmp_path, compressed_tables, monkeypatch):
    hub = _dup_hub(compressed_tables)
    monkeypatch.setattr(PublishedHashes, "get", lambda self, m: "f" * 64)
    assert _verify(hub, compressed_tables, tmp_path / "st", 2) == 1
    checks = {c["id"]: c for c in _report(tmp_path, 2)["tables"]["KQvk"]["checks"]}
    assert checks["V8"]["status"] == "fail" and "differs" in checks["V8"]["detail"]


def _claim_issue(n, author, title):
    return {"number": n, "title": title, "body": "", "user": {"login": author},
            "created_at": "2026-10-01T00:00:00Z", "labels": [], "state": "open"}


def test_no_post_still_reads_claims_and_notes_held_material(tmp_path, compressed_tables, monkeypatch):
    hub, tables = _fresh_hub(compressed_tables, tmp_path, description="Claim: #39\nGitHub: @bob")
    gh = FakeGitHub([_claim_issue(39, "alice", "Claim: KQvk")])
    monkeypatch.setattr("helpmate_server.contrib.github.GitHub", lambda repo: gh)
    argv = ["verify", "--tables", str(tables), "--staging", str(tmp_path / "st"), "--yes",
            "--no-post", "--pr", "2", *ARGS]
    assert tables_cli.main(argv, hub_factory=lambda r: hub) == 0     # gh_factory=None, as the real CLI
    r = _report(tmp_path, 2)
    assert "KQvk: held for claim #39" in r["pr_checks"][0]["detail"] and r["result"] == "pass"
    assert gh.posted == []


def test_claims_unavailable_is_noted(tmp_path, compressed_tables):
    hub, tables = _fresh_hub(compressed_tables, tmp_path)

    class Broken(FakeGitHub):
        def claim_issues(self):
            raise OSError("offline")

    argv = ["verify", "--tables", str(tables), "--staging", str(tmp_path / "st"), "--yes",
            "--no-post", "--pr", "2", *ARGS]
    assert tables_cli.main(argv, hub_factory=lambda r: hub, gh_factory=lambda r: Broken()) == 0
    assert "claims unavailable" in _report(tmp_path, 2)["pr_checks"][0]["detail"]


def _wrong_deepest(hm):
    """A shallower position listed as deepest, in the sidecar and the table's embedded metadata
    alike (so V2 to V4 and V8 still pass and only V5 can notice)."""
    import struct

    from helpmate_server.contrib.tablefile import HEADER_LEN, read_header
    sc_path = hm.with_name("KQvk.stats.json")
    sc = json.loads(sc_path.read_text())
    sc["deepest"] = sc["deepest_unique"][:1] if sc["deepest_unique"] != sc["deepest"][:1] else []
    h = read_header(hm)
    raw = hm.read_bytes()
    meta = json.loads(raw[HEADER_LEN:HEADER_LEN + h.json_len])
    meta["deepest"] = sc["deepest"]
    blob = json.dumps(meta).encode()
    head = bytearray(raw[:HEADER_LEN])
    struct.pack_into("<I", head, 60, len(blob))
    hm.write_bytes(bytes(head) + blob + raw[HEADER_LEN + h.json_len:])
    sc_path.write_text(json.dumps(sc, indent=2))


def test_same_run_duplicate_probes_its_own_deepest_positions(table_copy):
    source = payload_sha256(table_copy / "KQvk.hm")
    opts = VerifyOptions(samples=10, oracle_samples=1, oracle_plies=1, seed=1)
    rep = verify_table("KQvk", table_copy, opts, "99.0.0", published=source, source="HF PR #2",
                       probe_deepest=True)
    ids = {c.id: c for c in rep.checks}
    assert rep.passed and ids["V8"].status == "pass" and ids["V5"].status == "pass"
    assert all(ids[k].status == "skip" and ids[k].detail == "independent reproduction: identical to HF PR #2"
               for k in ("V6", "V7"))
    # a wrong deepest list in this delivery's sidecar (which accept may publish) fails it
    _wrong_deepest(table_copy / "KQvk.hm")
    rep = verify_table("KQvk", table_copy, opts, "99.0.0", published=source, source="HF PR #2",
                       probe_deepest=True)
    ids = {c.id: c for c in rep.checks}
    assert not rep.passed and ids["V8"].status == "pass" and ids["V5"].status == "fail"
    assert ids["V6"].detail == "an earlier check failed"


def test_rerun_does_not_reuse_a_same_run_duplicate_verified_without_v5(tmp_path, compressed_tables):
    main = {p.name: p.read_bytes() for p in compressed_tables.iterdir() if not p.name.startswith("KQvk.")}
    hub = FakeHub(main)
    for n in (2, 3):
        hub.add_pr(n, {k: (compressed_tables / k).read_bytes() for k in ("KQvk.hm", "KQvk.stats.json")},
                   description="Claim: #39", head=f"h{n}")
    tables = tmp_path / "tb"
    tables.mkdir()
    for name, b in main.items():
        (tables / name).write_bytes(b)
    assert _verify(hub, tables, tmp_path / "st", 2, 3) == 0
    path = tmp_path / "st" / "pr-3" / "report.json"
    rep = json.loads(path.read_text())   # as the old rule wrote it: V5 skipped
    for c in rep["tables"]["KQvk"]["checks"]:
        if c["id"] == "V5":
            c.update(status="skip", detail="independent reproduction: identical to HF PR #2")
    path.write_text(json.dumps(rep))
    assert _verify(hub, tables, tmp_path / "st", 2, 3) == 0
    c2 = {c["id"]: c for c in json.loads((tmp_path / "st" / "pr-2" / "report.json").read_text())
          ["tables"]["KQvk"]["checks"]}
    c3 = {c["id"]: c for c in json.loads(path.read_text())["tables"]["KQvk"]["checks"]}
    assert "reused_from" in c2["V6"]                           # PR #2 unchanged: reused
    assert c3["V5"]["status"] == "pass" and "reused_from" not in c3["V5"]

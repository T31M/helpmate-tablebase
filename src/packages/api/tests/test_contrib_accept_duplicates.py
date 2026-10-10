"""accept with duplicates and claims (spec section 3): identical deliveries add producers,
the claim holder's (else the earliest) delivery is published, someone else's delivery of
claimed, unpublished material is held, and differing content stops accept before any write."""
import hashlib
import json

import pytest

from helpmate_server.contrib.accept import Decision, accept, decide
from helpmate_server.contrib.claims import Claim, ClaimIndex
from helpmate_server.contrib.hf import PullRequest
from test_contrib_accept import BINARY, FakeGit, PageBuilder, _setup

PAY = "p" * 64
OTHER = "o" * 64
T31M = {"github": "T31M", "hf": "T31M", "display": "T31M"}
POPEYE = {"github": "popeye37", "hf": "popeye37", "display": "popeye37"}


# --- decide: the pure per-material decision ---

def _pr(num, *materials):
    files = [f for m in materials for f in (f"{m}.hm", f"{m}.stats.json")]
    return PullRequest(num, f"Add {num}", "x", "open", "", files, f"h{num}", "")


def _reps(**payloads):
    """_reps(p2={"KRRvkqq": PAY}) -> {2: report}"""
    return {int(k[1:]): {"result": "pass", "tables": {m: {"passed": True, "payload_sha256": v}
                                                     for m, v in tbl.items()}}
            for k, tbl in payloads.items()}


class Hashes:
    def __init__(self, **published):
        self.published = published

    def get(self, m):
        return self.published[m]


def _index(*claims):
    return ClaimIndex([Claim(issue, author, "2026-09-20T00:00:00Z", list(mats))
                       for issue, author, mats in claims])


MAN = {"files": {"KRRvkqq.hm": {"sha256": "s", "size": 1}}}


def test_decide_new_material_is_published_from_its_delivery():
    d = decide([_pr(2, "KRRvkqr")], _reps(p2={"KRRvkqr": PAY}), {"files": {}}, Hashes(), _index(),
               {2: "popeye37"}, set())
    assert d == {"KRRvkqr": Decision("new", 2, [2], None, d["KRRvkqr"].reason)}


def test_decide_identical_published_table_is_a_reproduction():
    d = decide([_pr(2, "KRRvkqq")], _reps(p2={"KRRvkqq": PAY}), MAN, Hashes(KRRvkqq=PAY), _index(),
               {2: "T31M"}, set())
    assert (d["KRRvkqq"].kind, d["KRRvkqq"].publish_from, d["KRRvkqq"].producers) == ("reproduction", None, [2])


def test_decide_published_table_with_other_content_is_a_conflict():
    d = decide([_pr(2, "KRRvkqq"), _pr(3, "KRRvkqq")], _reps(p2={"KRRvkqq": PAY}, p3={"KRRvkqq": OTHER}),
               MAN, Hashes(KRRvkqq=PAY), _index(), {2: "a", 3: "b"}, set())
    assert d["KRRvkqq"].kind == "conflict" and "#3" in d["KRRvkqq"].reason
    assert "#2" not in d["KRRvkqq"].reason


def test_decide_a_report_without_a_payload_hash_cannot_be_compared():
    reps = {2: {"result": "pass", "tables": {"KRRvkqq": {"passed": True}}}}
    d = decide([_pr(2, "KRRvkqq")], reps, MAN, Hashes(KRRvkqq=PAY), _index(), {2: "a"}, set())
    assert d["KRRvkqq"].kind == "conflict" and "verify" in d["KRRvkqq"].reason


def test_decide_two_deliveries_publish_the_claim_holders_even_when_later():
    d = decide([_pr(3, "KQvkqq"), _pr(2, "KQvkqq")], _reps(p2={"KQvkqq": PAY}, p3={"KQvkqq": PAY}),
               {"files": {}}, Hashes(), _index((39, "Popeye37", ["KQvkqq"])),
               {2: "T31M", 3: "popeye37"}, set())
    assert (d["KQvkqq"].kind, d["KQvkqq"].publish_from, d["KQvkqq"].producers) == ("new", 3, [2, 3])


def test_decide_two_deliveries_publish_the_claim_holders_when_earlier():
    d = decide([_pr(2, "KQvkqq"), _pr(3, "KQvkqq")], _reps(p2={"KQvkqq": PAY}, p3={"KQvkqq": PAY}),
               {"files": {}}, Hashes(), _index((39, "T31M", ["KQvkqq"])),
               {2: "T31M", 3: "popeye37"}, set())
    assert (d["KQvkqq"].publish_from, d["KQvkqq"].producers) == (2, [2, 3])


def test_decide_two_deliveries_without_a_claim_publish_the_earliest():
    d = decide([_pr(3, "KQvkqq"), _pr(2, "KQvkqq")], _reps(p2={"KQvkqq": PAY}, p3={"KQvkqq": PAY}),
               {"files": {}}, Hashes(), _index(), {2: "T31M", 3: "popeye37"}, set())
    assert (d["KQvkqq"].kind, d["KQvkqq"].publish_from) == ("new", 2)


def test_decide_two_deliveries_with_other_content_conflict():
    d = decide([_pr(2, "KQvkqq"), _pr(3, "KQvkqq")], _reps(p2={"KQvkqq": PAY}, p3={"KQvkqq": OTHER}),
               {"files": {}}, Hashes(), _index(), {2: "a", 3: "b"}, set())
    assert d["KQvkqq"].kind == "conflict" and "#2" in d["KQvkqq"].reason and "#3" in d["KQvkqq"].reason


def test_decide_someone_elses_claim_holds_unpublished_material_unless_released():
    args = ([_pr(2, "KQvkqq")], _reps(p2={"KQvkqq": PAY}), {"files": {}}, Hashes(),
            _index((39, "popeye37", ["KQvkqq"])), {2: "T31M"})
    held = decide(*args, set())["KQvkqq"]
    assert (held.kind, held.held_for, held.publish_from, held.producers) == ("held", 39, None, [])
    released = decide(*args, {"KQvkqq"})["KQvkqq"]
    assert (released.kind, released.publish_from, released.producers) == ("new", 2, [2])
    unknown = decide(*args[:5], {2: None}, set())["KQvkqq"]
    assert unknown.kind == "held"                       # no login: not shown to be the holder


def test_decide_published_material_is_never_held():
    d = decide([_pr(2, "KRRvkqq")], _reps(p2={"KRRvkqq": PAY}), MAN, Hashes(KRRvkqq=PAY),
               _index((39, "popeye37", ["KRRvkqq"])), {2: "T31M"}, set())
    assert d["KRRvkqq"].kind == "reproduction"


# --- accept scenarios ---

def _report(staging, num, head, payloads):
    d = staging / f"pr-{num}"
    (d / "files").mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps({
        "result": "pass", "head": head, "pr": num, "tool": "helpmate-tables 0.21.0", "seed": 7,
        "date": "2026-09-30", "samples": 2000,
        "tables": {m: {"passed": True, "payload_sha256": p} for m, p in payloads.items()}}))


def _stats(m, gv="0.20.0"):
    return json.dumps({"generator_version": gv, "material": m, "plane_size": 1, "max_dtm": 9}).encode()


def _base(tmp_path, author="T31M", contributors=None, payload=PAY):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.prs[2][0].author = author
    _report(staging, 2, "abc", {"KRRvkqq": payload})
    (checkout / "data" / "contributions.json").write_text(json.dumps(
        {"schema": 1, "tables": {}, "contributors": contributors if contributors is not None else {"T31M": T31M}}))
    return checkout, staging, hub, gh, tables


def _add_pr(hub, staging, num, materials, *, author, gv="0.20.0", description="", payload=PAY):
    files = {}
    for m in materials:
        files[f"{m}.hm"] = b"table" if m == "KRRvkqq" else f"t-{m}".encode()
        files[f"{m}.stats.json"] = _stats(m, gv)
    hub.add_pr(num, files, author=author, head=f"h{num}", description=description)
    _report(staging, num, f"h{num}", {m: payload for m in materials})
    for k, v in files.items():
        (staging / f"pr-{num}" / "files" / k).write_bytes(v)


def _publish(hub, checkout, tables, m="KRRvkqq", publisher="popeye37", hf_pr=1):
    """`m` is on main, in the manifest, in --tables and in the registry (by `publisher`)."""
    hm, sc = b"published", _stats(m, "0.19.0")
    hub.main.update({f"{m}.hm": hm, f"{m}.stats.json": sc})
    man = json.loads(hub.main["manifest.json"])
    man["files"].update({f"{m}.hm": {"sha256": hashlib.sha256(hm).hexdigest(), "size": len(hm)},
                         f"{m}.stats.json": {"sha256": hashlib.sha256(sc).hexdigest(), "size": len(sc)}})
    hub.main["manifest.json"] = json.dumps(man).encode()
    (tables / f"{m}.hm").write_bytes(hm)
    (tables / f"{m}.stats.json").write_bytes(sc)
    p = checkout / "data" / "contributions.json"
    reg = json.loads(p.read_text())
    reg["contributors"].setdefault(publisher, POPEYE if publisher == "popeye37" else T31M)
    reg["tables"][m] = {"contributor": publisher, "hf_pr": hf_pr, "claim": None, "merged": "2026-10-01",
                        "generator_version": "0.19.0", "verification": None}
    p.write_text(json.dumps(reg))


def _accept(prs, checkout, staging, hub, gh, tables, git=None, **kw):
    return accept(prs, hub=hub, gh=gh, git=git or FakeGit(), checkout=checkout, tables=tables,
                  staging=staging, contributor=kw.get("contributor"), today="2026-10-10",
                  binary=BINARY, build_pages=PageBuilder(), release=kw.get("release"))


def _reg(checkout):
    return json.loads((checkout / "data" / "contributions.json").read_text())


def _producers(checkout, m):
    return [(p["contributor"], p["hf_pr"]) for p in _reg(checkout)["tables"][m]["producers"]]


@pytest.fixture
def published_hash(monkeypatch):
    monkeypatch.setattr("helpmate_server.contrib.verify.PublishedHashes.get", lambda self, m: PAY)


def test_reproduction_of_a_published_table_adds_a_producer_and_copies_nothing(tmp_path, published_hash):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _publish(hub, checkout, tables)
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    assert hub.copies == [] and hub.merged == []
    ((num, comment),) = hub.closed
    assert num == 2 and "co-producer" in comment and "KRRvkqq" in comment
    assert _producers(checkout, "KRRvkqq") == [("popeye37", 1), ("T31M", 2)]
    reg = _reg(checkout)
    assert reg["tables"]["KRRvkqq"]["published_from"] == 1 and reg["tables"]["KRRvkqq"]["contributor"] == "popeye37"
    assert "independently reproduced by popeye37 and T31M" in (checkout / "CHANGELOG.md").read_text()
    assert (tables / "KRRvkqq.hm").read_bytes() == b"published"
    assert not any("Manifest" in m for m, _ in hub.commits)       # main's tables did not change


def test_mixed_pr_copies_only_the_new_materials_files(tmp_path, published_hash):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    del hub.prs[2]
    _add_pr(hub, staging, 2, ["KRRvkqq", "KQvkqq"], author="T31M")
    _publish(hub, checkout, tables)
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    (copy,) = hub.copies
    assert copy["files"] == ["KQvkqq.hm", "KQvkqq.stats.json"] and hub.merged == []
    assert copy["message"] == "Add KQvkqq from dataset PR #2 by T31M"
    ((num, comment),) = hub.closed
    assert "KQvkqq" in comment and "co-producer" in comment
    assert (tables / "KRRvkqq.hm").read_bytes() == b"published"
    assert (tables / "KQvkqq.hm").read_bytes() == b"t-KQvkqq"
    assert _producers(checkout, "KRRvkqq") == [("popeye37", 1), ("T31M", 2)]
    assert _producers(checkout, "KQvkqq") == [("T31M", 2)]


def test_two_prs_same_material_publish_the_later_claim_holders_file(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)              # #2 by T31M, claim #39 popeye37
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", gv="0.21.0")
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 0
    assert hub.merged == [3] and hub.copies == []
    ((num, comment),) = hub.closed
    assert num == 2 and "co-producer" in comment
    assert json.loads((tables / "KRRvkqq.stats.json").read_text())["generator_version"] == "0.21.0"
    reg = _reg(checkout)
    assert _producers(checkout, "KRRvkqq") == [("T31M", 2), ("popeye37", 3)]
    assert reg["tables"]["KRRvkqq"]["published_from"] == 3 and reg["tables"]["KRRvkqq"]["hf_pr"] == 3
    assert reg["tables"]["KRRvkqq"]["claim"] == 39
    accepted = [b for n, b in gh.posted if n == 39 and b.startswith("Accepted")]
    assert accepted and "independently reproduced — credited to both" in accepted[0]
    changelog = (checkout / "CHANGELOG.md").read_text()
    assert "KRRvkqq contributed by popeye37 (dataset PR #3" in changelog
    assert "KRRvkqq (independently reproduced by T31M and popeye37)." in changelog
    assert (staging / "pr-2" / "files" / "KRRvkqq.stats.json").exists()         # not moved into --tables


def test_two_prs_without_a_claim_publish_the_earliest(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    gh.issues.clear()
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", gv="0.21.0", description="GitHub: @popeye37")
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 0
    assert hub.merged == [2] and [n for n, _ in hub.closed] == [3]
    assert json.loads((tables / "KRRvkqq.stats.json").read_text())["generator_version"] == "0.20.0"
    assert _producers(checkout, "KRRvkqq") == [("T31M", 2), ("popeye37", 3)]
    assert _reg(checkout)["tables"]["KRRvkqq"]["published_from"] == 2


def _nothing_written(hub, gh, git):
    return (hub.copies == [] and hub.merged == [] and hub.closed == [] and hub.comments == []
            and hub.commits == [] and gh.posted == [] and git.calls == [])


def test_content_differing_from_the_published_table_stops_before_any_write(tmp_path, capsys, published_hash):
    checkout, staging, hub, gh, tables = _base(tmp_path, payload=OTHER)
    _publish(hub, checkout, tables)
    before = (checkout / "data" / "contributions.json").read_text()
    git = FakeGit()
    assert _accept([2], checkout, staging, hub, gh, tables, git) == 2
    err = capsys.readouterr().err
    assert "KRRvkqq" in err and "#2" in err and "nothing merged" in err
    assert _nothing_written(hub, gh, git)
    assert (checkout / "data" / "contributions.json").read_text() == before


def test_content_differing_between_two_prs_stops_before_any_write(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _add_pr(hub, staging, 3, ["KRRvkqq", "KQvkqq"], author="popeye37", payload=OTHER,
            description="GitHub: @popeye37")
    git = FakeGit()
    assert _accept([2, 3], checkout, staging, hub, gh, tables, git) == 2
    err = capsys.readouterr().err
    assert "KRRvkqq" in err and "#2" in err and "#3" in err and "content differs" in err
    assert _nothing_written(hub, gh, git) and not (tables / "KQvkqq.hm").exists()


def test_someone_elses_claim_holds_unpublished_material_and_leaves_the_pr_open(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)              # #2 by T31M, claim #39 popeye37
    git = FakeGit()
    assert _accept([2], checkout, staging, hub, gh, tables, git) == 0
    assert hub.copies == [] and hub.merged == [] and hub.closed == [] and hub.commits == []
    ((num, comment),) = hub.comments
    assert num == 2 and "held for claim #39 by @popeye37" in comment
    assert hub.prs[2][0].status == "open"
    assert "KRRvkqq" not in _reg(checkout)["tables"] and not (tables / "KRRvkqq.hm").exists()
    assert git.calls == [] and gh.posted == []                    # no docs PR, no claim comment
    assert not list(staging.glob("accept-*.json"))


def test_held_and_new_materials_in_one_pr_copy_the_new_ones_and_keep_the_pr_open(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    del hub.prs[2]
    _add_pr(hub, staging, 2, ["KRRvkqq", "KQvkqq"], author="T31M")    # KQvkqq: not claimed
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    (copy,) = hub.copies
    assert copy["files"] == ["KQvkqq.hm", "KQvkqq.stats.json"] and hub.closed == []
    ((num, comment),) = hub.comments
    assert "held for claim #39" in comment and "KQvkqq" in comment
    assert hub.prs[2][0].status == "open"
    assert sorted(_reg(checkout)["tables"]) == ["KQvkqq"]
    assert sorted(p.name for p in tables.iterdir()) == ["KQvkqq.hm", "KQvkqq.stats.json"]


def test_release_publishes_held_material(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    assert _accept([2], checkout, staging, hub, gh, tables, release=["KRRvkqq"]) == 0
    assert hub.merged == [2]
    assert "#39" in capsys.readouterr().err                      # which claim the release overrides
    reg = _reg(checkout)
    assert reg["tables"]["KRRvkqq"]["contributor"] == "T31M" and reg["tables"]["KRRvkqq"]["published_from"] == 2


def test_release_of_something_that_is_not_a_material_is_refused(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    assert _accept([2], checkout, staging, hub, gh, tables, release=["39"]) == 2
    assert "39" in capsys.readouterr().err and hub.merged == []


def test_held_then_the_holder_delivers_then_a_rerun_is_idempotent(tmp_path, monkeypatch):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    assert _accept([2], checkout, staging, hub, gh, tables) == 0           # run 1: held
    assert hub.prs[2][0].status == "open"
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", gv="0.21.0")
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 0        # run 2: the holder delivers
    assert hub.merged == [3] and hub.copies == []
    assert _producers(checkout, "KRRvkqq") == [("T31M", 2), ("popeye37", 3)]
    assert _reg(checkout)["tables"]["KRRvkqq"]["published_from"] == 3
    assert hub.prs[2][0].status == "closed"
    published = (tables / "KRRvkqq.stats.json").read_bytes()
    # accept #2 alone again: the PR is closed, nothing happens
    assert _accept([2], checkout, staging, hub, gh, tables) == 2
    # even if the Hub still showed it open: a reproduction of its own credited delivery
    hub.prs[2][0].status = "open"
    monkeypatch.setattr("helpmate_server.contrib.verify.PublishedHashes.get", lambda self, m: PAY)
    cards = len(hub.commits)
    git = FakeGit()
    assert _accept([2], checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == [3] and hub.copies == []
    assert _producers(checkout, "KRRvkqq") == [("T31M", 2), ("popeye37", 3)]
    assert (tables / "KRRvkqq.stats.json").read_bytes() == published
    assert (checkout / "CHANGELOG.md").read_text().count("independently reproduced") == 1
    assert "commit_all" not in [c[0] for c in git.calls] and len(hub.commits) == cards
    assert not list(staging.glob("accept-*.json"))


def test_someone_elses_claim_no_longer_blocks_the_prs_identity(tmp_path, capsys, published_hash):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    hub.prs[2][0].description = "GitHub: @T31M"
    _publish(hub, checkout, tables)
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    assert "claimed in" not in capsys.readouterr().err
    assert _producers(checkout, "KRRvkqq") == [("popeye37", 1), ("T31M", 2)]


def test_a_named_claim_of_someone_else_still_needs_contributor(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    hub.prs[2][0].description = "Claim: #39\nGitHub: @T31M"
    assert _accept([2], checkout, staging, hub, gh, tables) == 2
    assert "--contributor" in capsys.readouterr().err and hub.comments == []


def test_old_accept_state_without_decisions_decides_now(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path, author="popeye37", contributors={})
    (staging / "accept-2.json").write_text(json.dumps({"done": [], "pulls": {}}))
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    assert hub.merged == [2] and _producers(checkout, "KRRvkqq") == [("popeye37", 2)]


def test_decisions_are_stored_before_the_first_hub_write_and_reused(tmp_path, monkeypatch):
    from helpmate_server.contrib import accept as accept_mod
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", gv="0.21.0")
    real = hub.merge

    def fail(num):
        raise RuntimeError("network")
    hub.merge = fail
    with pytest.raises(RuntimeError):
        _accept([2, 3], checkout, staging, hub, gh, tables)
    state = json.loads((staging / "accept-2-3.json").read_text())
    assert state["decisions"]["KRRvkqq"]["publish_from"] == 3
    assert hub.closed == []              # the publishing PR goes first: no credit comment before it
    hub.merge = real
    monkeypatch.setattr(accept_mod, "decide", lambda *a: pytest.fail("decided again"))
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 0
    assert hub.merged == [3] and [n for n, _ in hub.closed] == [2]
    assert _reg(checkout)["tables"]["KRRvkqq"]["published_from"] == 3


def test_published_table_missing_from_tables_stops_before_any_write(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _publish(hub, checkout, tables)
    (tables / "KRRvkqq.hm").unlink()
    git = FakeGit()
    assert _accept([2], checkout, staging, hub, gh, tables, git) == 2
    assert "KRRvkqq.hm is missing" in capsys.readouterr().err and _nothing_written(hub, gh, git)


def test_cli_passes_release_materials_to_accept(tmp_path, monkeypatch):
    from helpmate_server import tables_cli
    from helpmate_server.contrib import accept as accept_mod
    checkout, staging, hub, gh, tables = _base(tmp_path)
    seen = {}
    monkeypatch.setattr(accept_mod, "accept", lambda prs, **kw: seen.update(kw, prs=prs) or 0)
    assert tables_cli.main(["accept", "2", "--tables", str(tables), "--checkout", str(checkout),
                            "--binary", BINARY, "--release", "KRRvkqq", "KQvkqq"],
                           hub_factory=lambda r: hub, gh_factory=lambda r: gh) == 0
    assert seen["release"] == ["KRRvkqq", "KQvkqq"] and seen["prs"] == [2]


def test_reproduction_of_a_maintainer_table_credits_the_maintainer_and_the_reproducer(tmp_path, published_hash):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _publish(hub, checkout, tables)
    reg = _reg(checkout)
    del reg["tables"]["KRRvkqq"]                     # published, but not a contribution
    (checkout / "data" / "contributions.json").write_text(json.dumps(reg))
    assert _accept([2], checkout, staging, hub, gh, tables) == 0
    entry = _reg(checkout)["tables"]["KRRvkqq"]
    assert entry["producers"] == [
        {"contributor": "maintainer", "hf_pr": None, "date": None, "generator_version": "0.19.0"},
        {"contributor": "T31M", "hf_pr": 2, "date": "2026-10-10", "generator_version": "0.20.0"}]
    assert (entry["published_from"], entry["contributor"], entry["hf_pr"], entry["merged"],
            entry["generator_version"]) == (None, "maintainer", None, None, "0.19.0")
    assert "maintainer" not in _reg(checkout)["contributors"]
    assert "KRRvkqq (independently reproduced by maintainer and T31M)." in (checkout / "CHANGELOG.md").read_text()
    assert "co-producer" in hub.closed[0][1] and hub.copies == []


def test_a_pr_revised_after_the_decisions_is_decided_again(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)              # #2 by T31M, claim #39 popeye37
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", gv="0.21.0")
    real = hub.pr_head
    hub.pr_head = lambda n: "h3b" if n == 3 else real(n)            # pushed after verify
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 2
    assert "decisions" in json.loads((staging / "accept-2-3.json").read_text())
    hub.pr_head = real
    hub.prs[3][0].head = "h3b"                                       # verified again: other content
    _report(staging, 3, "h3b", {"KRRvkqq": OTHER})
    git = FakeGit()
    assert _accept([2, 3], checkout, staging, hub, gh, tables, git) == 2
    assert _nothing_written(hub, gh, git)


def test_release_decides_again_over_stored_decisions(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)              # KRRvkqq held for #39
    _add_pr(hub, staging, 3, ["KQvkqq"], author="popeye37", description="GitHub: @popeye37")
    real = hub.merge

    def fail(num):
        raise RuntimeError("network")
    hub.merge = fail
    with pytest.raises(RuntimeError):
        _accept([2, 3], checkout, staging, hub, gh, tables)
    assert json.loads((staging / "accept-2-3.json").read_text())["decisions"]["KRRvkqq"]["kind"] == "held"
    hub.merge = real
    assert _accept([2, 3], checkout, staging, hub, gh, tables, release=["KRRvkqq"]) == 0
    assert hub.merged == [2, 3] and hub.comments == []
    assert _reg(checkout)["tables"]["KRRvkqq"]["published_from"] == 2

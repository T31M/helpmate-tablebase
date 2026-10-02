import json
import subprocess
import sys
from pathlib import Path

import pytest

from helpmate_server.contrib import SITE_MATERIALS_URL
from fakes import FakeGitHub, FakeHub
from helpmate_server.contrib.accept import accept, add_changelog_data, manifest_from_hub


class FakeGit:
    def __init__(self, fail_at=None):
        self.calls, self.fail_at = [], fail_at
        self.main_card = b"x\n"          # docs/hf-dataset-card.md as origin/main has it right now

    def _do(self, name, *a):
        self.calls.append((name, *a))
        if name == self.fail_at:
            raise RuntimeError(f"{name} failed")

    def clean(self): return True
    def current(self): return "main"
    def dirty_paths(self): return []
    def reset_to_origin_main(self, branch, paths): self._do("reset_to_origin_main", branch)
    def commit_all(self, message): self._do("commit_all", message)
    def push(self, branch): self._do("push", branch)
    def open_pr(self, title, body, branch=None): self._do("open_pr", title); return "https://gh/pr/1"
    def wait_and_merge(self, url, branch): self._do("wait_and_merge", url)
    def back(self, ref): self._do("back", ref)
    def close_pr(self, url): self._do("close_pr", url)
    def main_file(self, path): self._do("main_file", path); return self.main_card


class ConflictingGit(FakeGit):
    """The docs PR conflicts with main `conflicts` times; the reset restores the
    generated files the way `reset_to_origin_main` does on a real checkout."""

    def __init__(self, checkout, conflicts):
        super().__init__()
        self.checkout, self.conflicts, self.snap, self.prs = checkout, conflicts, None, 0

    def reset_to_origin_main(self, branch, paths):
        super().reset_to_origin_main(branch, paths)
        def files():
            for p in (self.checkout / p for p in paths):
                yield from (f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        if self.snap is None:
            self.snap = {f: f.read_bytes() for f in files() if f.exists()}
        for f in list(files()):
            if f not in self.snap:
                f.unlink(missing_ok=True)
        for f, data in self.snap.items():
            f.write_bytes(data)

    def open_pr(self, title, body, branch=None):
        super().open_pr(title, body, branch)
        self.prs += 1
        return f"https://gh/pr/{self.prs}"

    def wait_and_merge(self, url, branch):
        from helpmate_server.contrib.accept import MergeConflict
        self._do("wait_and_merge", url)
        if self.conflicts:
            self.conflicts -= 1
            raise MergeConflict(url)


def _setup(tmp_path, head="abc", report_head="abc", result="pass"):
    checkout = tmp_path / "repo"
    (checkout / "data").mkdir(parents=True)
    (checkout / "docs").mkdir()
    (checkout / "site" / "data").mkdir(parents=True)
    (checkout / "data" / "contributions.json").write_text(
        '{"schema":1,"contributors":{},"tables":{}}')
    (checkout / "CHANGELOG.md").write_text("# Changelog\n\n## [Unreleased]\n\n## [0.20.0] - x\n")
    for f in ("README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md",
              "docs/hf-dataset-card.md"):
        (checkout / f).write_text("x\n")
    staging = tmp_path / "st"
    d = staging / "pr-2"
    (d / "files").mkdir(parents=True)
    (d / "files" / "KRRvkqq.hm").write_bytes(b"table")
    (d / "files" / "KRRvkqq.stats.json").write_text('{"generator_version": "0.20.0", "material": "KRRvkqq", "plane_size": 1, "max_dtm": 9}')
    (d / "report.json").write_text(json.dumps({"result": result, "head": report_head, "pr": 2,
                                               "tool": "helpmate-tables 0.21.0", "seed": 7,
                                               "date": "2026-09-30", "samples": 2000}))
    hub = FakeHub({"manifest.json": b'{"schema":1,"generator_version":"0.19.0","files":{}}'})
    hub.add_pr(2, {"KRRvkqq.hm": b"table", "KRRvkqq.stats.json": (d / "files" / "KRRvkqq.stats.json").read_bytes()},
               head=head, description="")
    gh = FakeGitHub([{"number": 39, "title": "claim: KRR", "body": "KRRvk??",
                      "user": {"login": "popeye37"}, "created_at": "2026-09-20T00:00:00Z",
                      "labels": [], "state": "open"}])
    tables = tmp_path / "tb"
    tables.mkdir()
    return checkout, staging, hub, gh, tables


BINARY = sys.executable          # any existing file stands in for the helpmate binary


class PageBuilder:
    """Stands in for tools/build_problems.py: records each call and, like the real
    tool, writes a page only for a material that materials.json lists as done."""

    def __init__(self, fail=False, skip=()):
        self.calls, self.fail, self.skip = [], fail, set(skip)

    def __call__(self, args, *, cwd, check):
        self.calls.append((list(args), cwd, check))
        if self.fail:
            raise subprocess.CalledProcessError(1, args)
        out = Path(args[args.index("--out") + 1])
        rows = {r["material"]: r for r in json.loads((out / "materials.json").read_text())}
        (out / "material").mkdir(exist_ok=True)
        for i, a in enumerate(args):
            if a == "--material" and rows.get(args[i + 1], {}).get("done") and args[i + 1] not in self.skip:
                (out / "material" / f"{args[i + 1]}.json").write_text(json.dumps({"material": args[i + 1]}))
        return subprocess.CompletedProcess(args, 0)


def _run(checkout, staging, hub, gh, tables, git, **kw):
    return accept([2], hub=hub, gh=gh, git=git, checkout=checkout, tables=tables,
                  staging=staging, contributor=kw.get("contributor"), today="2026-10-01",
                  binary=kw.get("binary", BINARY), build_pages=kw.get("pages") or PageBuilder())


def test_accept_happy_path(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == [2]
    man = json.loads(hub.main["manifest.json"])
    assert "KRRvkqq.hm" in man["files"] and man["generator_version"] == "0.19.0"
    assert (tables / "KRRvkqq.hm").read_bytes() == b"table"
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "popeye37"
    assert reg["tables"]["KRRvkqq"]["claim"] == 39                 # found via the claims index
    assert reg["tables"]["KRRvkqq"]["verification"] == {
        "tool": "helpmate-tables 0.21.0", "head": "abc", "date": "2026-09-30", "samples": 2000,
        "seed": 7, "result": "pass"}
    assert "### Data" in (checkout / "CHANGELOG.md").read_text()
    commit_msg = next(c[1] for c in git.calls if c[0] == "commit_all")
    assert "Co-authored-by: popeye37 <1008+popeye37@users.noreply.github.com>" in commit_msg
    assert ("wait_and_merge", "https://gh/pr/1") in git.calls
    assert any(n == 39 and "KRRvkqq" in body for n, body in gh.posted)
    assert any(n == 39 and SITE_MATERIALS_URL in body for n, body in gh.posted)


ANON_FORM = ("### Materials\n\nKRRvk??\n\n### Hugging Face username\n\npopeye37\n\n"
             "### Name to credit\n\nPop Eye\n\n### Credit\n\n- [X] Do not name me in the credits.\n")


def test_anonymous_claim_form_keeps_the_name_out_of_every_credit(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    gh.issues[39]["body"] = ANON_FORM
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["contributors"]["popeye37"]["anonymous"] is True
    assert reg["contributors"]["popeye37"]["display"] == "Pop Eye"
    msg = next(c[1] for c in git.calls if c[0] == "commit_all")
    assert "Co-authored-by" not in msg and "Pop Eye" not in msg and "popeye37" not in msg
    assert "Pop Eye" not in (checkout / "CHANGELOG.md").read_text()
    assert json.loads((checkout / ".all-contributorsrc").read_text())["contributors"] == []


def test_anonymous_claim_form_makes_an_existing_contributor_anonymous_for_good(tmp_path):
    """Anonymity is per person and permanent: a registered, named contributor who ticks
    the box on a later claim form becomes anonymous in the registry and in every credit."""
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (checkout / "data" / "contributions.json").write_text(json.dumps({"schema": 1, "tables": {},
        "contributors": {"popeye37": {"github": "popeye37", "hf": "popeye37", "display": "Pop Eye"}}}))
    gh.issues[39]["body"] = ANON_FORM
    (checkout / "README.md").write_text("<!-- contrib:contributors-table --><!-- /contrib -->\n")
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["contributors"]["popeye37"]["anonymous"] is True
    msg = next(c[1] for c in git.calls if c[0] == "commit_all")
    assert "Co-authored-by" not in msg and "Pop Eye" not in msg and "popeye37" not in msg
    changelog = (checkout / "CHANGELOG.md").read_text()
    assert "Pop Eye" not in changelog and "an anonymous contributor" in changelog
    readme = (checkout / "README.md").read_text()
    assert "Pop Eye" not in readme and "| anonymous |" in readme
    assert json.loads((checkout / ".all-contributorsrc").read_text())["contributors"] == []


def test_a_later_named_claim_never_makes_an_anonymous_contributor_named_again(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (checkout / "data" / "contributions.json").write_text(json.dumps({"schema": 1, "tables": {},
        "contributors": {"popeye37": {"github": "popeye37", "hf": "popeye37", "display": "Pop Eye",
                                      "anonymous": True}}}))
    gh.issues[39]["body"] = ANON_FORM.replace("- [X]", "- [ ]")
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["contributors"]["popeye37"]["anonymous"] is True
    assert "Pop Eye" not in (checkout / "CHANGELOG.md").read_text()


def test_claim_form_credit_name_is_used(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    gh.issues[39]["body"] = ANON_FORM.replace("- [X]", "- [ ]")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["contributors"]["popeye37"]["display"] == "Pop Eye"
    assert reg["contributors"]["popeye37"]["anonymous"] is False
    assert "contributed by Pop Eye" in (checkout / "CHANGELOG.md").read_text()


def test_accept_refuses_a_pr_changed_after_verification(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path, head="new", report_head="old")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "old" in capsys.readouterr().err


def test_accept_refuses_a_failed_report(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path, result="fail")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2 and hub.merged == []


def _forget_merged_prs(hub):
    """After a merge the resume must not depend on the Hub's view of the PR."""
    def gone(num):
        raise AssertionError(f"PR #{num} fetched again after the merge")
    hub.pull_request = gone


def test_accept_resumes_after_ci_failure_without_merging_twice(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="wait_and_merge"))
    assert hub.merged == [2]
    hub.commit({"manifest.json": hub.main["manifest.json"], "README.md": b"moved"}, "main moves on")
    _forget_merged_prs(hub)
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == [2]                                     # not merged again
    assert [c[0] for c in git.calls] == ["back", "wait_and_merge", "main_file"]   # resumes at the docs PR, then the card


class ManifestFails(FakeHub):
    def commit(self, files, message):
        if "manifest.json" in files and not getattr(self, "healed", False):
            raise RuntimeError("network")
        super().commit(files, message)


def test_resume_after_merge_records_the_prs_tables(tmp_path):
    checkout, staging, hub0, gh, tables = _setup(tmp_path)
    hub = ManifestFails(dict(hub0.main))
    hub.prs, hub.bases, hub.deletes = hub0.prs, hub0.bases, hub0.deletes
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit())
    assert hub.merged == [2]
    hub.healed = True
    hub.commit({"README.md": b"moved"}, "main moves on after the merge")
    _forget_merged_prs(hub)
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert list(reg["tables"]) == ["KRRvkqq"]
    assert (tables / "KRRvkqq.hm").exists()
    msg = next(c[1] for c in git.calls if c[0] == "commit_all")
    assert msg.startswith("Data: 1 table(s)")


def test_pr_by_a_known_contributor_inside_someone_elses_claim_needs_contributor(tmp_path, capsys):
    """T31M (registered) pushes KRRvkpp-style work that #39 (popeye37) still claims:
    the claims bot calls it 'in review by someone else', so accept must not credit popeye37."""
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (checkout / "data" / "contributions.json").write_text(json.dumps({"schema": 1, "tables": {},
        "contributors": {"T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"}}}))
    hub.prs[2][0].author = "T31M"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    err = capsys.readouterr().err
    assert hub.merged == [] and "--contributor" in err and "#39" in err
    assert _run(checkout, staging, hub, gh, tables, FakeGit(), contributor="T31M") == 0
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "T31M"


def test_head_is_checked_again_right_before_the_merge(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.pr_head = lambda n: "pushed-meanwhile"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    err = capsys.readouterr().err
    assert hub.merged == [] and "abc" in err and "pushed-meanwhile" in err


def test_material_already_in_the_manifest_is_refused(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.main["manifest.json"] = json.dumps({"schema": 1, "generator_version": "0.19.0", "files": {
        "KRRvkqq.hm": {"sha256": "x", "size": 1}}}).encode()
    (tables / "KRRvkqq.stats.json").write_text('{"material": "KRRvkqq", "plane_size": 1, "max_dtm": 1}')
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "already in the dataset" in capsys.readouterr().err


def test_same_material_in_two_prs_of_a_batch_is_refused(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _two_prs(tmp_path)
    files = dict(hub.prs[2][1])
    hub.healed = True
    hub.add_pr(3, files, head="h3")
    for k, v in files.items():
        (staging / "pr-3" / "files" / k).write_bytes(v)
    assert _run2(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "KRRvkqq" in capsys.readouterr().err


def test_unknown_contributor_stops_before_merging(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    gh.issues.clear()
    hub.prs[2][0].author = "stranger"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "--contributor" in capsys.readouterr().err


def test_changelog_data_entry_goes_under_unreleased():
    text = "# C\n\n## [Unreleased]\n\n## [0.20.0] - x\n"
    out = add_changelog_data(text, "- KRRvkqq by popeye37")
    assert out.index("### Data") < out.index("## [0.20.0]")
    assert add_changelog_data(out, "- KRRvkqr by popeye37").count("### Data") == 1


def test_manifest_from_hub_hashes_non_lfs_files():
    hub = FakeHub({"a.hm": b"1", "a.stats.json": b"{}", "README.md": b"x"})
    m = manifest_from_hub(hub, "0.19.0")
    assert set(m["files"]) == {"a.hm", "a.stats.json"} and m["schema"] == 1


def test_local_step_moves_only_table_files_not_the_head_marker(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (staging / "pr-2" / "files" / ".head").write_text("abc")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert not (tables / ".head").exists()
    assert sorted(p.name for p in tables.iterdir()) == ["KRRvkqq.hm", "KRRvkqq.stats.json"]


def test_registry_key_collision_stops_before_merging(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    reg = checkout / "data" / "contributions.json"
    reg.write_text(json.dumps({"schema": 1, "tables": {}, "contributors": {
        "popeye37": {"github": "someone-else", "hf": None, "display": "Other"}}}))
    before = reg.read_text()
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "popeye37" in capsys.readouterr().err
    assert reg.read_text() == before


def test_incomplete_tables_dir_stops_before_merging(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.main["manifest.json"] = json.dumps(
        {"schema": 1, "generator_version": "0.19.0", "files": {"Kvk.stats.json": {"size": 1}}}).encode()
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "missing" in capsys.readouterr().err


def test_dirty_checkout_stops_before_merging(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    git.clean = lambda: False
    assert _run(checkout, staging, hub, gh, tables, git) == 2 and hub.merged == []


def test_status_lists_open_prs(tmp_path):
    from helpmate_server.contrib.accept import status
    from helpmate_server.contrib.registry import Registry
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    out = status(hub, gh, Registry.load(checkout / "data" / "contributions.json"), staging, checkout)
    assert "| #2 | popeye37 | KRRvkqq | #39 | pass (stale" not in out
    assert "| #2 | popeye37 | KRRvkqq | #39 | pass |" in out
    hub.prs[2][0].head = "changed"
    out = status(hub, gh, Registry.load(checkout / "data" / "contributions.json"), staging, checkout)
    assert "stale" in out and "since the last DEEPEST refresh" in out
    assert "not verified" in status(hub, gh, Registry.load(checkout / "data" / "contributions.json"),
                                    tmp_path / "empty", checkout)


class FlakyHub(FakeHub):
    def merge(self, num):
        if num == 3 and not getattr(self, "healed", False):
            raise RuntimeError("network")
        super().merge(num)


def _two_prs(tmp_path, marker=False):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    flaky = FlakyHub(dict(hub.main))
    stats = {"generator_version": "0.20.0", "material": "KRRvkqr", "plane_size": 1, "max_dtm": 9}
    if marker:                                       # a table without a single helpmate
        stats.update(max_dtm=255, all_unsolvable=True)
    files = {"KRRvkqr.hm": b"t2", "KRRvkqr.stats.json": json.dumps(stats).encode()}
    flaky.prs, flaky.bases, flaky.deletes = hub.prs, hub.bases, hub.deletes
    flaky.add_pr(3, files, head="h3")
    d = staging / "pr-3"
    (d / "files").mkdir(parents=True)
    for k, v in files.items():
        (d / "files" / k).write_bytes(v)
    (d / "report.json").write_text(json.dumps({"result": "pass", "head": "h3", "pr": 3}))
    return checkout, staging, flaky, gh, tables


def _run2(checkout, staging, hub, gh, tables, git, pages=None):
    return accept([2, 3], hub=hub, gh=gh, git=git, checkout=checkout, tables=tables,
                  staging=staging, contributor=None, today="2026-10-01",
                  binary=BINARY, build_pages=pages or PageBuilder())


def test_partial_batch_merge_resumes(tmp_path):
    checkout, staging, hub, gh, tables = _two_prs(tmp_path)
    with pytest.raises(RuntimeError):
        _run2(checkout, staging, hub, gh, tables, FakeGit())
    assert hub.merged == [2]
    hub.healed = True
    assert _run2(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert hub.merged == [2, 3]
    assert (tables / "KRRvkqr.hm").exists()


@pytest.mark.parametrize("fail_at", ["push", "open_pr"])
def test_docs_failure_before_pr_resumes_without_duplicate_changelog(tmp_path, fail_at):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at=fail_at))
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert (checkout / "CHANGELOG.md").read_text().count("KRRvkqq contributed by") == 1
    assert ("back", "main") in git.calls and hub.merged == [2]
    names = [c[0] for c in git.calls]
    assert "commit_all" not in names if fail_at == "open_pr" else "push" in names


def test_dirty_unrelated_path_stops_docs_step(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    git.dirty_paths = lambda: ["src/other.py"]
    assert _run(checkout, staging, hub, gh, tables, git) == 2
    assert "src/other.py" in capsys.readouterr().err


def test_original_branch_survives_a_resume_from_the_data_branch(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="push"))
    git = FakeGit()
    git.current = lambda: "data/accept-2"
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert ("back", "main") in git.calls


def test_card_uploaded_only_after_docs_pr_merged(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="wait_and_merge"))
    assert not any("Dataset card" in m for m, _ in hub.commits)
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert sum("Dataset card" in m for m, _ in hub.commits) == 1


def test_card_uploaded_is_mains_current_card_not_this_runs_snapshot(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    git.main_card = b"newer card from a later accept run\n"
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert ("main_file", "docs/hf-dataset-card.md") in git.calls
    assert [f for m, f in hub.commits if "Dataset card" in m] == [{"README.md": git.main_card}]
    assert not list(staging.glob("*.card.md"))


def test_resume_with_docs_done_uploads_mains_card_and_ignores_an_old_card_file(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="wait_and_merge"))
    state_file = next(staging.glob("accept-*.json"))
    state = json.loads(state_file.read_text())
    state["done"] = [s for s in state["done"] if s not in ("docs", "card", "claims")]
    state["done"] += ["docs"]
    state_file.write_text(json.dumps(state))
    state_file.with_suffix(".card.md").write_bytes(b"stale snapshot with 393 tables\n")
    git = FakeGit()
    git.main_card = b"main card with 403 tables\n"
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert [f for m, f in hub.commits if "Dataset card" in m] == [{"README.md": b"main card with 403 tables\n"}]


def test_claim_comment_not_posted_twice_after_rerun(tmp_path):
    checkout, staging, hub, gh, tables = _two_prs(tmp_path)
    (staging / "pr-3" / "files" / "KRRvkqr.hm").write_bytes(b"t2")
    calls = {"n": 0}
    orig = gh.comment

    def flaky(issue, body):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("api")
        orig(issue, body)
    gh.comment = flaky
    hub.healed = True
    with pytest.raises(RuntimeError):
        _run2(checkout, staging, hub, gh, tables, FakeGit())
    gh.comment = orig
    assert _run2(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert sum("KRRvkqq" in b and b.startswith("Accepted") for _, b in gh.posted) == 1
    assert sum("KRRvkqr" in b and b.startswith("Accepted") for _, b in gh.posted) == 1


def test_missing_or_short_staged_file_stops_before_merging(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (staging / "pr-2" / "files" / "KRRvkqq.hm").write_bytes(b"tab")
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.merged == [] and "KRRvkqq.hm" in capsys.readouterr().err


class Runner:
    def __init__(self, checks, fail=None):
        self.checks, self.calls, self.envs, self.slept = list(checks), [], [], 0
        self.fail = fail or {}          # command prefix (tuple) -> stderr of a failing run

    def __call__(self, args, **kw):
        import subprocess
        self.calls.append(args)
        self.envs.append(kw.get("env") or {})
        out = ""
        for prefix, err in self.fail.items():
            if tuple(args[:len(prefix)]) == prefix:
                if kw.get("check"):
                    raise subprocess.CalledProcessError(1, args, "", err)
                return subprocess.CompletedProcess(args, 1, "", err)
        if args[:3] == ["gh", "pr", "view"]:
            out = '{"state": "OPEN", "mergeable": "MERGEABLE"}'
        elif args[:3] == ["gh", "pr", "checks"] and "--watch" not in args:
            out = self.checks.pop(0)
        return subprocess.CompletedProcess(args, 0, out, "")


PUSH_DELETE = ["git", "-c", "credential.helper=", "-c", "credential.helper=!gh auth git-credential",
               "push", "origin", "--delete", "br"]


def test_wait_and_merge_squashes_then_deletes_the_branch_without_the_global_config(tmp_path):
    from helpmate_server.contrib.accept import Git
    r = Runner(["ci pending"])
    Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")
    merge = r.calls.index(["gh", "pr", "merge", "u", "--squash"])
    assert r.envs[merge]["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert r.calls[merge + 1:] == [PUSH_DELETE, ["git", "branch", "-D", "br"]]
    assert r.envs[merge + 1]["GIT_CONFIG_GLOBAL"] == "/dev/null"


def test_main_file_fetches_origin_main_then_shows_the_file_without_the_global_config(tmp_path):
    from helpmate_server.contrib.accept import Git

    class Show(Runner):
        def __call__(self, args, **kw):
            done = super().__call__(args, **kw)
            if args[:2] == ["git", "show"]:
                done.stdout = b"card\n"
            return done

    r = Show([])
    assert Git(tmp_path, runner=r).main_file("docs/hf-dataset-card.md") == b"card\n"
    assert r.calls == [["git", "fetch", "origin", "main"],
                       ["git", "show", "origin/main:docs/hf-dataset-card.md"]]
    assert r.envs[0]["GIT_CONFIG_GLOBAL"] == "/dev/null"


def test_branch_cleanup_tolerates_branches_already_gone(tmp_path):
    import subprocess
    from helpmate_server.contrib.accept import Git
    r = Runner(["ci"], fail={tuple(PUSH_DELETE): "error: unable to delete 'br': remote ref does not exist",
                             ("git", "branch", "-D"): "error: branch 'br' not found."})
    Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")
    r = Runner(["ci"], fail={tuple(PUSH_DELETE): "fatal: could not read from remote"})
    with pytest.raises(subprocess.CalledProcessError):
        Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")


def test_docs_pr_conflict_is_redone_once_from_origin_main(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = ConflictingGit(checkout, conflicts=1)
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    names = [c[0] for c in git.calls]
    assert ("close_pr", "https://gh/pr/1") in git.calls
    assert names.count("reset_to_origin_main") == 2 and names.count("commit_all") == 2
    assert names.count("push") == 2 and ("wait_and_merge", "https://gh/pr/2") in git.calls
    assert (checkout / "CHANGELOG.md").read_text().count("KRRvkqq contributed by") == 1
    assert sum("Dataset card" in m for m, _ in hub.commits) == 1


def test_docs_pr_conflicting_twice_stops_and_never_retries_again(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = ConflictingGit(checkout, conflicts=5)
    assert _run(checkout, staging, hub, gh, tables, git) == 2
    assert "again" in capsys.readouterr().err
    assert [c[0] for c in git.calls].count("close_pr") == 1
    state = json.loads(next(staging.glob("accept-*.json")).read_text())
    assert state["docs_retried"] is True and "docs" not in state["done"]
    again = ConflictingGit(checkout, conflicts=5)
    assert _run(checkout, staging, hub, gh, tables, again) == 2
    assert "close_pr" not in [c[0] for c in again.calls]          # at most one retry, ever
    assert not any("Dataset card" in m for m, _ in hub.commits)


def test_git_reports_a_conflicting_pr(tmp_path):
    import subprocess
    from helpmate_server.contrib.accept import Git, MergeConflict

    class Conflicting(Runner):
        def __call__(self, args, **kw):
            if args[:3] == ["gh", "pr", "view"]:
                self.calls.append(args)
                return subprocess.CompletedProcess(args, 0, '{"state": "OPEN", "mergeable": "CONFLICTING"}', "")
            return super().__call__(args, **kw)
    r = Conflicting(["ci"])
    with pytest.raises(MergeConflict):
        Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")
    assert not any(c[:3] == ["gh", "pr", "merge"] for c in r.calls)


def test_git_turns_a_failed_merge_of_a_now_conflicting_pr_into_a_conflict(tmp_path):
    import subprocess
    from helpmate_server.contrib.accept import Git, MergeConflict

    class Late(Runner):
        views = 0

        def __call__(self, args, **kw):
            if args[:3] == ["gh", "pr", "view"]:
                self.views += 1
                m = "CONFLICTING" if self.views > 1 else "MERGEABLE"
                return subprocess.CompletedProcess(args, 0, f'{{"state": "OPEN", "mergeable": "{m}"}}', "")
            return super().__call__(args, **kw)
    r = Late(["ci"], fail={("gh", "pr", "merge"): "Pull request is not mergeable"})
    with pytest.raises(MergeConflict):
        Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")
    r = Runner(["ci"], fail={("gh", "pr", "merge"): "HTTP 502"})
    with pytest.raises(subprocess.CalledProcessError):
        Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")


def test_close_pr_closes_with_a_comment(tmp_path):
    from helpmate_server.contrib.accept import Git
    r = Runner([])
    Git(tmp_path, runner=r).close_pr("u")
    assert r.calls[0][:4] == ["gh", "pr", "close", "u"]


def test_accept_leaves_the_data_branch_before_merging_the_docs_pr(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    names = [c[0] for c in git.calls]
    assert names.index("back") < names.index("wait_and_merge")


def test_wait_and_merge_polls_until_checks_are_reported(tmp_path):
    from helpmate_server.contrib.accept import Git
    r = Runner(["no checks reported on the 'x' branch", "no checks reported", "ci pending"])
    g = Git(tmp_path, runner=r, sleep=lambda s: setattr(r, "slept", r.slept + 1))
    g.wait_and_merge("u", "br")
    assert r.slept == 2
    watch = next(c for c in r.calls if "--watch" in c)
    assert watch[:4] == ["gh", "pr", "checks", "u"]
    assert r.calls.index(watch) < r.calls.index(["gh", "pr", "merge", "u", "--squash"])


def test_wait_and_merge_skips_an_already_merged_pr(tmp_path):
    import subprocess
    from helpmate_server.contrib.accept import Git
    calls = []

    def run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, '{"state": "MERGED"}', "")
    Git(tmp_path, runner=run).wait_and_merge("u", "br")
    assert not any(c[:3] == ["gh", "pr", "merge"] or "--watch" in c for c in calls)


def test_wait_and_merge_gives_up_without_checks(tmp_path):
    from helpmate_server.contrib.accept import Git
    r = Runner(["no checks reported"] * 12)
    with pytest.raises(RuntimeError, match="no checks"):
        Git(tmp_path, runner=r, sleep=lambda s: None).wait_and_merge("u", "br")


def test_open_pr_reuses_an_existing_one(tmp_path):
    import subprocess
    from helpmate_server.contrib.accept import Git

    def run(args, **kw):
        assert "create" not in args
        return subprocess.CompletedProcess(args, 0, '[{"url": "https://gh/pr/9"}]', "")
    assert Git(tmp_path, runner=run).open_pr("t", "b", "br") == "https://gh/pr/9"


def test_first_docs_attempt_with_dirty_listed_path_stops_and_discards_nothing(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    answers = iter([True])                          # clean for the merge step, dirty from then on
    git.clean = lambda: next(answers, False)
    git.dirty_paths = lambda: ["CHANGELOG.md"]
    assert _run(checkout, staging, hub, gh, tables, git) == 2
    assert hub.merged == [2]                        # got past the merge step, into docs
    assert "commit or stash" in capsys.readouterr().err
    assert not any(c[0] in ("reset_to_origin_main", "commit_all") for c in git.calls)
    assert "docs_started" not in json.loads(next(staging.glob("accept-*.json")).read_text())


def test_redo_after_docs_started_resets_even_when_listed_paths_are_dirty(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit(fail_at="commit_all"))
    git = FakeGit()
    git.clean = lambda: False                       # leftovers of the failed attempt
    git.dirty_paths = lambda: ["CHANGELOG.md", "site/data/materials.json"]
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert any(c[0] == "reset_to_origin_main" for c in git.calls)


def _git_env():
    import os
    return {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _sh(cwd, *args):
    import subprocess
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True,
                          env=_git_env()).stdout


@pytest.fixture
def clone(tmp_path):
    origin = tmp_path / "origin.git"
    _sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    work = tmp_path / "clone"
    _sh(tmp_path, "git", "clone", "-q", str(origin), str(work))
    _sh(work, "git", "config", "user.name", "t")
    _sh(work, "git", "config", "user.email", "t@example.com")
    _sh(work, "git", "config", "commit.gpgsign", "false")
    (work / "docs").mkdir()
    (work / "CHANGELOG.md").write_text("# C\n\n## [Unreleased]\n")
    (work / "docs" / "other.md").write_text("keep\n")
    _sh(work, "git", "add", "-A")
    _sh(work, "git", "commit", "-q", "-m", "init")
    _sh(work, "git", "push", "-q", "-u", "origin", "main")
    return work


def test_real_git_reset_discards_staged_and_untracked_generated_files(clone, monkeypatch):
    from helpmate_server.contrib.accept import Git
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    (clone / "CHANGELOG.md").write_text("# C\n\n## [Unreleased]\n### Data\n- dup\n")
    _sh(clone, "git", "add", "CHANGELOG.md")                 # staged, as after a failed commit
    (clone / "site" / "data").mkdir(parents=True)
    (clone / "site" / "data" / "materials.json").write_text("[]\n")
    _sh(clone, "git", "add", "site/data/materials.json")      # staged new generated file
    (clone / ".all-contributorsrc").write_text("{}")
    _sh(clone, "git", "add", ".all-contributorsrc")           # staged new file
    (clone / "docs" / "other.md").write_text("mine\n")         # unlisted, unstaged edit
    Git(clone).reset_to_origin_main("data/accept-2")
    assert _sh(clone, "git", "rev-parse", "--abbrev-ref", "HEAD").strip() == "data/accept-2"
    assert (clone / "CHANGELOG.md").read_text() == _sh(clone, "git", "show", "origin/main:CHANGELOG.md")
    assert _sh(clone, "git", "diff", "--cached", "--name-only") == ""
    assert not (clone / "site" / "data" / "materials.json").exists() and not (clone / ".all-contributorsrc").exists()
    assert (clone / "docs" / "other.md").read_text() == "mine\n"   # unrelated edit untouched


def test_real_git_dirty_paths_lets_accept_refuse_unlisted_edits(clone, tmp_path, capsys):
    from helpmate_server.contrib.accept import DOCS_PATHS, Git
    (clone / "docs" / "other.md").write_text("mine\n")
    (clone / "CHANGELOG.md").write_text("changed\n")
    dirty = Git(clone).dirty_paths()
    assert sorted(dirty) == ["CHANGELOG.md", "docs/other.md"]
    assert [d for d in dirty if d not in DOCS_PATHS] == ["docs/other.md"]


# --- a dataset PR that conflicts with main on `.gitattributes` only ---

def test_gitattributes_only_conflict_is_merged_by_copy_and_closed(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.conflicts[2] = [".gitattributes"]
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    assert hub.merged == []
    (copy,) = hub.copies
    assert copy["num"] == 2 and copy["head"] == "abc"
    assert copy["files"] == ["KRRvkqq.hm", "KRRvkqq.stats.json"]
    assert copy["message"] == "Add KRRvkqq from dataset PR #2 by popeye37"
    ((num, comment),) = hub.closed
    assert num == 2 and "https://hf.example/commit/copy-1" in comment
    assert "`.gitattributes`" in comment and "abc" in comment and "Thank you" in comment
    assert "KRRvkqq.hm" in json.loads(hub.main["manifest.json"])["files"]
    assert (tables / "KRRvkqq.hm").read_bytes() == b"table"
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "popeye37" and reg["tables"]["KRRvkqq"]["hf_pr"] == 2
    assert "popeye37" in (checkout / "CHANGELOG.md").read_text()
    assert not (staging / "accept-2.json").exists()


def test_files_already_on_main_close_the_pr_without_claiming_a_merge(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.conflicts[2] = [".gitattributes"]
    hub.main.update(hub.prs[2][1])                 # the PR's files reached main some other way
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    ((num, comment),) = hub.closed
    assert comment.startswith("Already on main as of main-sha (copied from this PR's verified head abc")
    assert "Merged as" not in comment
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "popeye37"


def test_copy_message_keeps_an_anonymous_contributor_anonymous(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    gh.issues[39]["body"] = ANON_FORM
    hub.conflicts[2] = [".gitattributes"]
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    msg = hub.copies[0]["message"]
    assert "Pop Eye" not in msg and "popeye37" not in msg and "an anonymous contributor" in msg


@pytest.mark.parametrize("files", [["README.md"], [".gitattributes", "KRRvkqq.hm"],
                                   ["(files not listed by the Hub)"]])
def test_any_other_conflict_stops_before_copying(tmp_path, capsys, files):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.conflicts[2] = files
    git = FakeGit()
    assert _run(checkout, staging, hub, gh, tables, git) == 2
    err = capsys.readouterr().err
    assert all(f in err for f in files) and "#2" in err
    assert hub.copies == [] and hub.closed == [] and hub.commits == [] and git.calls == []


def test_head_changed_before_the_copy_is_refused(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.conflicts[2] = [".gitattributes"]
    hub.pr_head = lambda n: "pushed-meanwhile"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 2
    assert hub.copies == [] and hub.closed == [] and "pushed-meanwhile" in capsys.readouterr().err


class CloseFails(FakeHub):
    """The copy commit lands; closing the PR fails (after or before the Hub applied it)."""

    def close_pr(self, num, comment):
        if getattr(self, "applied_then_fail", False):
            super().close_pr(num, comment)
        if not getattr(self, "healed", False):
            raise RuntimeError("network")
        super().close_pr(num, comment)


def _close_fails(tmp_path, applied):
    checkout, staging, hub0, gh, tables = _setup(tmp_path)
    hub = CloseFails(dict(hub0.main))
    hub.prs, hub.bases, hub.deletes = hub0.prs, hub0.bases, hub0.deletes
    hub.conflicts[2] = [".gitattributes"]
    hub.applied_then_fail = applied
    with pytest.raises(RuntimeError):
        _run(checkout, staging, hub, gh, tables, FakeGit())
    state = json.loads((staging / "accept-2.json").read_text())
    assert state["copied"] == {"2": {"ref": "https://hf.example/commit/copy-1", "already": False}}
    assert state["merged"] == []
    hub.healed = True
    _forget_merged_prs(hub)
    return checkout, staging, hub, gh, tables


def test_resume_after_the_copy_only_closes_the_pr(tmp_path):
    checkout, staging, hub, gh, tables = _close_fails(tmp_path, applied=False)
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert len(hub.copies) == 1                                   # never copied twice
    ((num, comment),) = hub.closed
    assert num == 2 and "https://hf.example/commit/copy-1" in comment and "abc" in comment
    reg = json.loads((checkout / "data" / "contributions.json").read_text())
    assert reg["tables"]["KRRvkqq"]["contributor"] == "popeye37"


def test_resume_with_the_pr_already_closed_neither_copies_nor_closes_again(tmp_path):
    checkout, staging, hub, gh, tables = _close_fails(tmp_path, applied=True)
    assert hub.prs[2][0].status == "closed"
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert len(hub.copies) == 1 and len(hub.closed) == 1


def test_a_pr_closed_by_the_copy_is_done_not_in_review(tmp_path):
    from datetime import datetime, timezone
    from helpmate_server.contrib.claims import material_status, load_index
    from helpmate_server.contrib.registry import Registry
    from helpmate_server.contrib.site_status import build_status
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    hub.conflicts[2] = [".gitattributes"]
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert hub.open_pull_requests() == []
    reg = Registry.load(checkout / "data" / "contributions.json")
    s = build_status(hub, gh, reg, datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert s["materials"]["KRRvkqq"]["state"] == "done" and s["materials"]["KRRvkqq"]["hf_pr"] == 2
    done = {f[:-3] for f in hub.fetch_manifest()["files"] if f.endswith(".hm")}
    assert material_status(done, {}, load_index(gh), reg)["KRRvkqq"].state == "done"


def test_resume_reads_a_copy_recorded_in_the_earlier_bare_string_format(tmp_path):
    """State files written before {ref, already} hold the commit URL as a plain string."""
    checkout, staging, hub, gh, tables = _close_fails(tmp_path, applied=False)
    path = staging / "accept-2.json"
    state = json.loads(path.read_text())
    state["copied"] = {"2": "https://hf.example/commit/abc"}
    path.write_text(json.dumps(state))
    assert _run(checkout, staging, hub, gh, tables, FakeGit()) == 0
    assert len(hub.copies) == 1                                   # only the first run's copy
    ((num, comment),) = hub.closed
    assert num == 2 and comment.startswith("Merged as https://hf.example/commit/abc:")
    assert not path.exists()


# --- material pages: accept runs tools/build_problems.py for what it accepts ---

def test_accept_builds_the_pages_of_every_accepted_material_markers_too(tmp_path):
    checkout, staging, hub, gh, tables = _two_prs(tmp_path, marker=True)
    hub.healed = True
    pages = PageBuilder()
    assert _run2(checkout, staging, hub, gh, tables, FakeGit(), pages=pages) == 0
    assert pages.calls == [([sys.executable, str(checkout / "tools" / "build_problems.py"),
                             "--tables", str(tables), "--binary", BINARY,
                             "--out", str(checkout / "site" / "data"),
                             "--material", "KRRvkqq", "--material", "KRRvkqr"], checkout, True)]


class SnapshotGit(FakeGit):
    """Records what the checkout holds when the docs commit is made."""

    def __init__(self, checkout):
        super().__init__()
        self.checkout, self.at_commit = checkout, None

    def commit_all(self, message):
        super().commit_all(message)
        data = self.checkout / "site" / "data"
        rows = {r["material"]: r for r in json.loads((data / "materials.json").read_text())}
        self.at_commit = {"pages": sorted(p.name for p in (data / "material").glob("*.json")),
                          "page_flag": rows["KRRvkqq"]["page"], "done": rows["KRRvkqq"]["done"]}


def test_docs_commit_includes_the_built_pages_and_the_page_flags_they_set(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = SnapshotGit(checkout)
    assert _run(checkout, staging, hub, gh, tables, git) == 0
    # the builder saw KRRvkqq as done (it skips materials that are not), and the
    # materials data committed with the page says the page exists
    assert git.at_commit == {"pages": ["KRRvkqq.json"], "page_flag": True, "done": True}


@pytest.mark.parametrize("binary", [None, "/nonexistent/helpmate"])
def test_missing_binary_stops_before_merging(tmp_path, capsys, binary):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    pages = PageBuilder()
    assert _run(checkout, staging, hub, gh, tables, FakeGit(), binary=binary, pages=pages) == 2
    assert hub.merged == [] and pages.calls == []
    assert "--binary" in capsys.readouterr().err


def test_cli_without_a_helpmate_binary_on_path_stops_before_merging(tmp_path, capsys, monkeypatch):
    from helpmate_server import tables_cli
    from helpmate_server.contrib import cli
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    rc = tables_cli.main(["accept", "2", "--tables", str(tables), "--checkout", str(checkout),
                          "--staging", str(staging)], hub_factory=lambda r: hub, gh_factory=lambda r: gh)
    assert rc == 2 and hub.merged == []
    assert "--binary" in capsys.readouterr().err


def test_resume_after_the_page_builder_failed_merges_nothing_twice_and_builds_again(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = ConflictingGit(checkout, conflicts=0)      # its reset restores the files, like git's
    with pytest.raises(subprocess.CalledProcessError):
        _run(checkout, staging, hub, gh, tables, git, pages=PageBuilder(fail=True))
    assert hub.merged == [2] and not any(c[0] == "commit_all" for c in git.calls)
    _forget_merged_prs(hub)
    snap, git, pages = git.snap, ConflictingGit(checkout, conflicts=0), PageBuilder()
    git.snap = snap                                   # origin/main as the first run found it
    assert _run(checkout, staging, hub, gh, tables, git, pages=pages) == 0
    assert hub.merged == [2] and len(pages.calls) == 1
    assert [c[0] for c in git.calls].count("commit_all") == 1
    assert (checkout / "CHANGELOG.md").read_text().count("KRRvkqq contributed by") == 1
    assert (checkout / "site" / "data" / "material" / "KRRvkqq.json").exists()


def test_generated_page_files_count_as_accepts_own_leftovers(tmp_path):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    with pytest.raises(subprocess.CalledProcessError):
        _run(checkout, staging, hub, gh, tables, FakeGit(), pages=PageBuilder(fail=True))
    git = FakeGit()
    git.clean = lambda: False
    git.dirty_paths = lambda: ["site/data/material/KRRvkqq.json", "site/data/index.json",
                               "site/data/themes.json"]
    assert _run(checkout, staging, hub, gh, tables, git) == 0


def test_a_path_that_only_starts_like_a_generated_directory_is_not_ours(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    git = FakeGit()
    git.dirty_paths = lambda: ["site/data/material.bak"]
    assert _run(checkout, staging, hub, gh, tables, git) == 2
    assert "site/data/material.bak" in capsys.readouterr().err


def test_real_git_reset_restores_a_generated_directory_without_deleting_it(clone, monkeypatch):
    from helpmate_server.contrib.accept import Git
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    pages = clone / "site" / "data" / "material"
    pages.mkdir(parents=True)
    (pages / "A.json").write_text('{"a": 1}\n')
    (pages / "K.json").write_text('{"k": 1}\n')
    _sh(clone, "git", "add", "-A")
    _sh(clone, "git", "commit", "-q", "-m", "pages")
    _sh(clone, "git", "push", "-q", "origin", "main")
    (pages / "A.json").write_text('{"a": 2}\n')                # modified
    (pages / "B.json").write_text("{}\n")                       # untracked
    (pages / "C.json").write_text("{}\n")
    _sh(clone, "git", "add", "site/data/material/C.json")        # staged new, as after a failed commit
    Git(clone).reset_to_origin_main("data/accept-2")
    assert (pages / "A.json").read_text() == '{"a": 1}\n'
    assert (pages / "K.json").read_text() == '{"k": 1}\n'
    assert not (pages / "B.json").exists() and not (pages / "C.json").exists()
    assert _sh(clone, "git", "status", "--porcelain") == ""


def test_real_git_dirty_paths_lists_new_files_inside_an_untracked_directory(clone):
    from helpmate_server.contrib.accept import Git
    (clone / "site" / "data" / "material").mkdir(parents=True)
    (clone / "site" / "data" / "material" / "B.json").write_text("{}\n")
    assert Git(clone).dirty_paths() == ["site/data/material/B.json"]


def test_cli_resolves_a_relative_binary_before_handing_it_on(tmp_path, monkeypatch):
    from helpmate_server import tables_cli
    from helpmate_server.contrib import accept as accept_mod
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "helpmate").write_text("")
    monkeypatch.chdir(tmp_path)
    seen = {}
    monkeypatch.setattr(accept_mod, "accept", lambda prs, **kw: seen.update(kw) or 0)
    assert tables_cli.main(["accept", "2", "--tables", str(tables), "--checkout", str(checkout),
                            "--binary", "build/helpmate"],
                           hub_factory=lambda r: hub, gh_factory=lambda r: gh) == 0
    assert seen["binary"] == str(tmp_path.resolve() / "build" / "helpmate")


def test_a_material_the_builder_skipped_stops_the_docs_step_and_a_rerun_completes(tmp_path):
    checkout, staging, hub, gh, tables = _two_prs(tmp_path)
    hub.healed = True
    git = ConflictingGit(checkout, conflicts=0)
    with pytest.raises(RuntimeError, match="no page built for KRRvkqr"):
        _run2(checkout, staging, hub, gh, tables, git, pages=PageBuilder(skip={"KRRvkqr"}))
    assert hub.merged == [2, 3] and not any(c[0] == "commit_all" for c in git.calls)
    _forget_merged_prs(hub)
    snap, git, pages = git.snap, ConflictingGit(checkout, conflicts=0), PageBuilder()
    git.snap = snap
    assert _run2(checkout, staging, hub, gh, tables, git, pages=pages) == 0
    assert hub.merged == [2, 3] and len(pages.calls) == 1
    assert [c[0] for c in git.calls].count("commit_all") == 1


def test_cli_resolves_the_helpmate_found_on_path(tmp_path, monkeypatch):
    from helpmate_server import tables_cli
    from helpmate_server.contrib import accept as accept_mod
    from helpmate_server.contrib import cli
    checkout, staging, hub, gh, tables = _setup(tmp_path)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "helpmate").write_text("")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "bin/helpmate")   # a relative PATH entry
    seen = {}
    monkeypatch.setattr(accept_mod, "accept", lambda prs, **kw: seen.update(kw) or 0)
    assert tables_cli.main(["accept", "2", "--tables", str(tables), "--checkout", str(checkout)],
                           hub_factory=lambda r: hub, gh_factory=lambda r: gh) == 0
    assert seen["binary"] == str(tmp_path.resolve() / "bin" / "helpmate")


def test_git_runs_with_english_messages(tmp_path, monkeypatch):
    """accept matches git's English messages ("remote ref does not exist"); a German
    locale made it stop on an already-deleted branch. Every git call runs with LC_ALL=C."""
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    from helpmate_server.contrib.accept import Git
    seen = []

    def runner(args, **kw):
        seen.append(kw.get("env") or {})
        return subprocess.CompletedProcess(args, 0, "", "")

    Git(tmp_path, runner=runner).commit_all("m")
    assert seen and all(e.get("LC_ALL") == "C" and e.get("LANGUAGE") == "C" for e in seen)

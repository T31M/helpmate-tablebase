import json
import sys
from pathlib import Path

import pytest

from helpmate_server import tables_cli
from helpmate_server.contrib import pages
from helpmate_server.contrib.pages import missing_pages, run_pages, split_jobs

ROOT = Path(__file__).resolve().parents[4]


def test_missing_pages_lists_done_materials_without_a_page(tmp_path):
    data = tmp_path / "site" / "data"
    (data / "material").mkdir(parents=True)
    (data / "materials.json").write_text(json.dumps([
        {"material": "KQvk", "done": True}, {"material": "KRvk", "done": True},
        {"material": "KBvk", "done": False}]))
    (data / "material" / "KQvk.json").write_text("{}")
    assert missing_pages(tmp_path) == ["KRvk"]


def test_split_jobs_round_robin_without_empty_jobs():
    assert split_jobs(["a", "b", "c", "d", "e"], 2) == [["a", "c", "e"], ["b", "d"]]
    assert split_jobs(["a"], 4) == [["a"]]
    assert split_jobs(["a", "b"], 0) == [["a", "b"]]


class FakeGit:
    def __init__(self, merge_fails=0):
        self.calls, self.merge_fails = [], merge_fails

    def _do(self, name, *a):
        self.calls.append((name, *a))

    def current(self): return "main"
    def reset_to_origin_main(self, branch, paths): self._do("reset", branch)
    def commit_all(self, message): self._do("commit_all", message)
    def push(self, branch): self._do("push", branch)
    def open_pr(self, title, body, branch=None): self._do("open_pr", title, body); return "https://gh/pr/9"
    def back(self, ref): self._do("back", ref)

    def wait_and_merge(self, url, branch):
        self._do("wait_and_merge", url)
        if self.merge_fails:
            self.merge_fails -= 1
            raise RuntimeError("CI failed")

    def names(self): return [c[0] for c in self.calls]


class Runner:
    """Stands in for Popen(build_problems.py): per job writes pages, index.json, themes.json."""

    def __init__(self, fail=(), crash=()):
        self.calls, self.fail, self.crash = [], set(fail), set(crash)

    def __call__(self, cmd, cwd):
        self.calls.append((cmd, cwd))
        out = Path(cmd[cmd.index("--out") + 1])
        mats = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--material"]
        rows, themes = [], {}
        for m in mats:
            if m in self.fail:
                continue
            (out / "material" / f"{m}.json").write_text(json.dumps({"material": m}))
            rows.append({"material": m, "pieces": 3, "unique": 1})
            themes.setdefault("t", {"count": 0, "problems": []})["problems"].append({"material": m})
        (out / "index.json").write_text(json.dumps(rows))
        (out / "themes.json").write_text(json.dumps(themes))
        rc = 1 if self.crash & set(mats) else 0
        return type("P", (), {"wait": lambda self: rc})()


def _setup(tmp_path):
    checkout = tmp_path / "repo"
    data = checkout / "site" / "data"
    (data / "material").mkdir(parents=True)
    (checkout / "tools").mkdir()
    # the real merge functions, as the checkout would have them
    (checkout / "tools" / "build_problems.py").write_text(
        "def merge_index(existing, new_rows, processed):\n"
        "    kept = [r for r in existing if r['material'] not in processed]\n"
        "    return sorted(kept + new_rows, key=lambda r: (r['pieces'], r['material']))\n"
        "def merge_themes(existing, new_entries, processed):\n"
        "    out = {}\n"
        "    for t, i in existing.items():\n"
        "        out.setdefault(t, []).extend(p for p in i['problems'] if p['material'] not in processed)\n"
        "    for t, ps in new_entries.items():\n"
        "        out.setdefault(t, []).extend(ps)\n"
        "    return {t: {'count': len(ps), 'problems': ps} for t, ps in sorted(out.items()) if ps}\n")
    (data / "materials.json").write_text(json.dumps(
        [{"material": m, "done": True} for m in "ABCX"]))
    (data / "index.json").write_text(json.dumps([{"material": "X", "pieces": 2, "unique": 5}]))
    (data / "themes.json").write_text(json.dumps({"t": {"count": 1, "problems": [{"material": "X"}]}}))
    tables = tmp_path / "tb"
    tables.mkdir()
    return checkout, tmp_path / "st", tables


@pytest.fixture(autouse=True)
def no_site_data(monkeypatch):
    import helpmate_server.contrib.site_data as sd
    monkeypatch.setattr(sd, "write_site_data", lambda out, tables: [])


def _go(tmp_path, runner, git, mats=("A", "B", "C"), **kw):
    checkout, staging, tables = _setup(tmp_path) if not (tmp_path / "repo").exists() else (
        tmp_path / "repo", tmp_path / "st", tmp_path / "tb")
    rc = run_pages(list(mats), checkout=checkout, tables=tables, binary="/bin/h", jobs=2,
                   staging=staging, git=git, today="2026-10-10", runner=runner, **kw)
    return rc, checkout, staging


def test_run_pages_folds_jobs_and_opens_the_docs_pr(tmp_path):
    git, runner = FakeGit(), Runner()
    rc, checkout, staging = _go(tmp_path, runner, git)
    assert rc == 0
    data = checkout / "site" / "data"
    assert sorted(p.stem for p in (data / "material").glob("*.json")) == ["A", "B", "C"]
    assert [r["material"] for r in json.loads((data / "index.json").read_text())] == ["X", "A", "B", "C"]
    th = json.loads((data / "themes.json").read_text())["t"]
    assert th["count"] == 4
    assert git.names() == ["reset", "commit_all", "push", "open_pr", "back", "wait_and_merge"]
    assert "3 material(s)" in git.calls[1][1]
    assert not (staging / "pages-2026-10-10.json").exists()
    assert len(runner.calls) == 2
    assert runner.calls[0][1] == checkout and "--out" in runner.calls[0][0]


def test_resume_does_not_rerun_finished_jobs(tmp_path):
    git, runner = FakeGit(merge_fails=1), Runner()
    with pytest.raises(RuntimeError):
        _go(tmp_path, runner, git)
    assert len(runner.calls) == 2
    rc, checkout, staging = _go(tmp_path, runner, git)
    assert rc == 0 and len(runner.calls) == 2
    assert git.names().count("commit_all") == 1 and git.names().count("wait_and_merge") == 2
    assert not (staging / "pages-2026-10-10.json").exists()


def test_failed_material_stops_before_the_pr_and_keeps_the_others(tmp_path):
    git = FakeGit()
    rc, checkout, staging = _go(tmp_path, Runner(fail={"B"}), git)
    assert rc == 1 and "open_pr" not in git.names() and "commit_all" not in git.names()
    assert sorted(p.stem for p in (checkout / "site/data/material").glob("*.json")) == ["A", "C"]
    assert (staging / "pages-2026-10-10.json").exists()


def test_allow_failures_opens_the_pr_and_lists_the_failed(tmp_path):
    git = FakeGit()
    rc, checkout, _ = _go(tmp_path, Runner(fail={"B"}), git, allow_failures=True)
    assert rc == 0
    opened = [c for c in git.calls if c[0] == "open_pr"][0]
    assert "2 material(s)" in opened[1] and "failed (no page): B" in opened[2]


def test_nonzero_exit_fails_only_materials_without_a_page_file(tmp_path):
    git = FakeGit()
    # job 1 holds B (and nothing else); it exits 1 although it wrote B's page: B is kept
    rc, checkout, _ = _go(tmp_path, Runner(crash={"B"}), git)
    assert rc == 0 and (checkout / "site/data/material/B.json").exists()
    runner2 = Runner(fail={"C"}, crash={"A", "C"})   # job 0 holds A, C: C has no page
    git2 = FakeGit()
    rc, _, _ = _go(tmp_path / "two", runner2, git2, allow_failures=True)
    assert rc == 0
    assert "failed (no page): C" in [c for c in git2.calls if c[0] == "open_pr"][0][2]


def test_nothing_to_build_is_a_noop(tmp_path):
    checkout, staging, tables = _setup(tmp_path)
    assert run_pages([], checkout=checkout, tables=tables, binary="b", jobs=2, staging=staging,
                     git=FakeGit(), today="2026-10-10", runner=Runner()) == 0


def test_cli_parses_pages(tmp_path, monkeypatch):
    seen = {}
    checkout = tmp_path / "repo"
    (checkout / "data").mkdir(parents=True)
    (checkout / "data" / "contributions.json").write_text("{}")
    monkeypatch.setattr(pages, "missing_pages", lambda c: ["KQvk"])
    monkeypatch.setattr(pages, "run_pages", lambda mats, **kw: seen.update(mats=mats, **kw) or 0)
    rc = tables_cli.main(["pages", "--tables", str(tmp_path), "--missing", "--jobs", "3",
                          "--binary", sys.executable, "--checkout", str(checkout),
                          "--staging", str(tmp_path / "s"), "--allow-failures"])
    assert rc == 0 and seen["mats"] == ["KQvk"] and seen["jobs"] == 3 and seen["allow_failures"]
    assert tables_cli.main(["pages", "--tables", str(tmp_path), "--missing", "--jobs", "0",
                            "--binary", sys.executable, "--checkout", str(checkout)]) == 2


def test_real_build_problems_merge_functions_match_the_fold(tmp_path):
    """The fold relies on merge_index/merge_themes of the real tool."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("bp", ROOT / "tools" / "build_problems.py")
    bp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bp)
    assert bp.merge_index([], [{"material": "A", "pieces": 3}], {"A"})[0]["material"] == "A"
    assert bp.merge_themes({}, {"t": [{"material": "A"}]}, {"A"}) == {"t": {"count": 1, "problems": [{"material": "A"}]}}

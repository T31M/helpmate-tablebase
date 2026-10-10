"""accept --plan: what accept would do with a batch, printed; nothing is written anywhere
(no Hub or GitHub write, no git operation that changes the checkout, no state file, no
staging, tables or registry change)."""

import pytest

from helpmate_server.contrib.accept import accept, plan_accept
from test_contrib_accept import BINARY, FakeGit, PageBuilder
from test_contrib_accept_duplicates import (OTHER, PAY, _accept, _add_pr, _base, _publish,
                                            _nothing_written)


def _git(checkout):
    """origin/main has the checkout's registry (what accept's reset to origin/main gives it)."""
    git = FakeGit()
    git.main_registry = (checkout / "data" / "contributions.json").read_bytes()
    return git


def _plan(prs, checkout, staging, hub, gh, tables, git=None, **kw):
    return plan_accept(prs, hub=hub, gh=gh, git=git or _git(checkout), checkout=checkout, tables=tables,
                       staging=staging, contributor=kw.get("contributor"), today="2026-10-10",
                       binary=kw.get("binary", BINARY), release=kw.get("release"))


def _snapshot(*dirs):
    """Every file under `dirs` with its bytes: any write shows up as a difference."""
    return {str(f): f.read_bytes() for d in dirs if d.exists() for f in sorted(d.rglob("*")) if f.is_file()}


@pytest.fixture
def published_hash(monkeypatch):
    monkeypatch.setattr("helpmate_server.contrib.verify.PublishedHashes.get", lambda self, m: PAY)


def _holder_later(tmp_path):
    """#2 by T31M and #3 by popeye37 (claim #39 holder) deliver KRRvkqq; #3 also KQvkqq."""
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _add_pr(hub, staging, 3, ["KRRvkqq", "KQvkqq"], author="popeye37", gv="0.21.0",
            description="GitHub: @popeye37")
    return checkout, staging, hub, gh, tables


def _held(tmp_path):
    return _base(tmp_path)                                         # #2 by T31M, claim #39 popeye37


def _reproduction(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _publish(hub, checkout, tables)
    return checkout, staging, hub, gh, tables


def _partial(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    del hub.prs[2]
    _add_pr(hub, staging, 2, ["KRRvkqq", "KQvkqq"], author="T31M")    # KRRvkqq held, KQvkqq new
    return checkout, staging, hub, gh, tables


def _conflict(tmp_path):
    checkout, staging, hub, gh, tables = _base(tmp_path)
    _add_pr(hub, staging, 3, ["KRRvkqq"], author="popeye37", payload=OTHER)
    return checkout, staging, hub, gh, tables


SCENARIOS = {"holder_later": (_holder_later, [2, 3], 0), "held": (_held, [2], 0),
             "reproduction": (_reproduction, [2], 0), "partial": (_partial, [2], 0),
             "conflict": (_conflict, [2, 3], 1)}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_plan_writes_nothing_anywhere(tmp_path, published_hash, name):
    make, prs, rc = SCENARIOS[name]
    checkout, staging, hub, gh, tables = make(tmp_path)
    before = _snapshot(checkout, staging, tables)
    git = _git(checkout)
    assert _plan(prs, checkout, staging, hub, gh, tables, git) == rc
    assert _nothing_written(hub, gh, git)
    assert hub.downloads == []
    assert not list(staging.glob("accept-*.json"))
    assert _snapshot(checkout, staging, tables) == before


def test_plan_of_two_deliveries_names_the_published_file_and_the_co_producer(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _holder_later(tmp_path)
    assert _plan([2, 3], checkout, staging, hub, gh, tables) == 0
    out = capsys.readouterr().out
    pr2, pr3 = out.split("HF PR #2", 1)[1].split("HF PR #3", 1)
    assert "T31M" in pr2 and "KRRvkqq: co-producer (file published from #3)" in pr2
    assert "close with thank-you" in pr2
    assert "popeye37" in pr3 and "claim #39" in pr3
    assert "KRRvkqq: publish from #3" in pr3 and "KQvkqq: publish from #3" in pr3
    assert "-> merge" in pr3
    assert "KRRvkqq: T31M (HF PR #2), popeye37 (HF PR #3)" in out
    assert "- KQvkqq, KRRvkqq contributed by popeye37 (dataset PR #3, claim #39)." in out
    assert "- KRRvkqq (independently reproduced by T31M and popeye37)." in out


def test_plan_shows_the_changelog_lines_the_real_accept_writes(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _holder_later(tmp_path)
    assert _plan([2, 3], checkout, staging, hub, gh, tables) == 0
    planned = [line.strip() for line in capsys.readouterr().out.splitlines() if line.strip().startswith("- ")]
    assert planned
    assert _accept([2, 3], checkout, staging, hub, gh, tables) == 0
    changelog = (checkout / "CHANGELOG.md").read_text()
    written = [line for line in changelog.splitlines() if line.startswith("- ")]
    assert sorted(planned) == sorted(written)


def test_plan_of_a_held_delivery(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _held(tmp_path)
    assert _plan([2], checkout, staging, hub, gh, tables) == 0
    out = capsys.readouterr().out
    assert "KRRvkqq: held for claim #39 by @popeye37" in out
    assert "comment only, stays open" in out
    assert "nothing changes on main or in the credits" in out


def test_plan_of_a_reproduction(tmp_path, capsys, published_hash):
    checkout, staging, hub, gh, tables = _reproduction(tmp_path)
    assert _plan([2], checkout, staging, hub, gh, tables) == 0
    out = capsys.readouterr().out
    assert "KRRvkqq: reproduction of published table -> producer" in out
    assert "close with thank-you" in out
    assert "KRRvkqq: T31M (HF PR #2)" in out
    assert "- KRRvkqq (independently reproduced by popeye37 and T31M)." in out


def test_plan_of_a_partial_copy_that_stays_open(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _partial(tmp_path)
    assert _plan([2], checkout, staging, hub, gh, tables) == 0
    out = capsys.readouterr().out
    assert "KQvkqq: publish from #2" in out and "KRRvkqq: held for claim #39" in out
    assert "partial copy, stays open" in out


def test_plan_of_a_partial_copy_that_closes(tmp_path, capsys, published_hash):
    checkout, staging, hub, gh, tables = _partial(tmp_path)
    _publish(hub, checkout, tables)                                   # KRRvkqq: a reproduction now
    assert _plan([2], checkout, staging, hub, gh, tables) == 0
    assert "partial copy + close" in capsys.readouterr().out


def test_plan_with_a_conflict_prints_everything_and_returns_1(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _conflict(tmp_path)
    assert _plan([2, 3], checkout, staging, hub, gh, tables) == 1
    out = capsys.readouterr().out
    assert "HF PR #2" in out and "HF PR #3" in out
    assert "KRRvkqq: CONFLICT: content differs between HF PRs #2 and #3" in out
    assert "nothing would be merged" in out


def test_plan_with_release_shows_the_override(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _held(tmp_path)
    assert _plan([2], checkout, staging, hub, gh, tables, release=["KRRvkqq"]) == 0
    captured = capsys.readouterr()
    assert "KRRvkqq: publish from #2 (released by the maintainer)" in captured.out
    assert "-> merge" in captured.out
    assert "overrides claim #39 by popeye37" in captured.err


def test_plan_with_contributor_names_the_given_login(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _base(tmp_path, author="someone", contributors={})
    hub.prs[2][0].description = "Claim: #39\nGitHub: @someone"
    assert _plan([2], checkout, staging, hub, gh, tables) == 2         # as accept: needs --contributor
    assert "--contributor" in capsys.readouterr().err
    assert _plan([2], checkout, staging, hub, gh, tables, contributor="popeye37") == 0
    assert "contributor popeye37 (@popeye37)" in capsys.readouterr().out


@pytest.mark.parametrize("break_it, message", [
    (lambda hub, staging: setattr(hub.prs[2][0], "head", "pushed"), "changed after verification"),
    (lambda hub, staging: (staging / "pr-2" / "report.json").unlink(), "has no verification report"),
    (lambda hub, staging: (staging / "pr-2" / "files" / "KRRvkqq.hm").unlink(), "staged files missing"),
    (lambda hub, staging: setattr(hub.prs[2][0], "status", "closed"), "PR #2 is closed"),
])
def test_plan_reports_accepts_errors_the_same_way(tmp_path, capsys, break_it, message):
    checkout, staging, hub, gh, tables = _base(tmp_path, author="popeye37", contributors={})
    break_it(hub, staging)
    assert _plan([2], checkout, staging, hub, gh, tables) == 2
    planned = capsys.readouterr().err
    assert message in planned
    assert accept([2], hub=hub, gh=gh, git=FakeGit(), checkout=checkout, tables=tables, staging=staging,
                  contributor=None, today="2026-10-10", binary=BINARY, build_pages=PageBuilder()) == 2
    assert capsys.readouterr().err == planned


def test_plan_usage_errors(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _holder_later(tmp_path)
    assert _plan([2, 3], checkout, staging, hub, gh, tables, contributor="T31M") == 2
    assert "on its own" in capsys.readouterr().err
    assert _plan([2], checkout, staging, hub, gh, tables, release=["39"]) == 2
    assert _plan([2], checkout, staging, hub, gh, tables, binary=str(tmp_path / "nope")) == 2


def test_plan_leaves_an_interrupted_runs_state_file_as_it_is(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _holder_later(tmp_path)
    real = hub.merge

    def fail(num):
        raise RuntimeError("network")
    hub.merge = fail
    with pytest.raises(RuntimeError):
        _accept([2, 3], checkout, staging, hub, gh, tables)
    hub.merge = real
    state = (staging / "accept-2-3.json").read_bytes()
    before = _snapshot(checkout, staging, tables)
    assert _plan([2, 3], checkout, staging, hub, gh, tables, release=["KQvkqq"]) == 0  # would decide again
    assert (staging / "accept-2-3.json").read_bytes() == state
    assert _snapshot(checkout, staging, tables) == before
    assert "KRRvkqq: publish from #3" in capsys.readouterr().out


def test_plan_after_the_merge_step_says_where_accept_resumes(tmp_path, capsys):
    checkout, staging, hub, gh, tables = _holder_later(tmp_path)
    with pytest.raises(RuntimeError):
        _accept([2, 3], checkout, staging, hub, gh, tables, git=FakeGit(fail_at="wait_and_merge"))
    before = _snapshot(checkout, staging, tables)
    git = FakeGit()
    commits = list(hub.commits)
    assert _plan([2, 3], checkout, staging, hub, gh, tables, git) == 0
    out = capsys.readouterr().out
    assert "resumes with: docs, card, claims" in out
    assert "done by the interrupted run" in out
    assert _snapshot(checkout, staging, tables) == before
    assert git.writes() == [] and hub.commits == commits


def test_cli_accept_plan_runs_the_plan_not_accept(tmp_path, monkeypatch, capsys):
    from helpmate_server import tables_cli
    from helpmate_server.contrib import accept as accept_mod
    checkout, staging, hub, gh, tables = _held(tmp_path)
    monkeypatch.setattr(accept_mod, "accept", lambda *a, **kw: pytest.fail("accept ran"))
    before = _snapshot(checkout, staging, tables)
    git = FakeGit()
    assert tables_cli.main(["accept", "2", "--plan", "--tables", str(tables), "--checkout", str(checkout),
                            "--staging", str(staging), "--binary", BINARY, "--release", "KRRvkqq"],
                           hub_factory=lambda r: hub, gh_factory=lambda r: gh,
                           git_factory=lambda c: git) == 0
    assert "KRRvkqq: publish from #2" in capsys.readouterr().out
    assert _nothing_written(hub, gh, git) and _snapshot(checkout, staging, tables) == before

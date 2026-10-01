"""GitHub REST client against a fake urlopen: what it requests, and what it returns."""
import io
import json
import urllib.error

import pytest

from helpmate_server.contrib import github
from helpmate_server.contrib.github import GitHub


class Opener:
    """Answers by (method, path without the API host); records every request."""

    def __init__(self, answers):
        self.answers, self.requests, self.timeouts = answers, [], []

    def __call__(self, req, timeout=None):
        self.timeouts.append(timeout)
        path = req.full_url.replace("https://api.github.com", "")
        self.requests.append((req.get_method(), path, dict(req.header_items()),
                              json.loads(req.data) if req.data else None))
        ans = self.answers.get((req.get_method(), path), b"")
        if isinstance(ans, Exception):
            raise ans
        return io.BytesIO(ans if isinstance(ans, bytes) else json.dumps(ans).encode())


def test_every_request_has_a_timeout():
    """The Pages workflow's state step must not hang on a stalled connection."""
    op = Opener({("GET", "/repos/o/r/issues/5"): {"number": 5}})
    GitHub("o/r", token="t", opener=op).issue(5)
    assert op.timeouts == [30]


def _issue(n, title="claim: x", labels=(), pr=False):
    i = {"number": n, "title": title, "labels": [{"name": lb} for lb in labels]}
    if pr:
        i["pull_request"] = {}
    return i


def _comment(i, login="u"):
    return {"id": i, "body": f"c{i}", "user": {"login": login}, "created_at": "2026-09-30T00:00:00Z"}


def test_requests_carry_the_token_and_the_api_media_type():
    op = Opener({("GET", "/repos/o/r/issues/5"): {"number": 5}})
    assert GitHub("o/r", token="tok", opener=op).issue(5) == {"number": 5}
    headers = op.requests[0][2]
    assert headers["Authorization"] == "Bearer tok"
    assert headers["Accept"] == "application/vnd.github+json"
    op = Opener({("GET", "/repos/o/r/issues/5"): {"number": 5}})
    GitHub("o/r", token="", opener=op).issue(5)
    assert "Authorization" not in op.requests[0][2]


def test_claim_issues_pages_and_filters():
    first = [_issue(i, title="other") for i in range(98)] + [_issue(200, pr=True, title="claim: pr"),
                                                            _issue(201, title="Claim: KQvk???")]
    op = Opener({("GET", "/repos/o/r/issues?state=open&per_page=100&page=1"): first,
                 ("GET", "/repos/o/r/issues?state=open&per_page=100&page=2"):
                     [_issue(300, title="help", labels=["claim"]), _issue(301, title="bug")]})
    got = GitHub("o/r", token="t", opener=op).claim_issues()
    assert [i["number"] for i in got] == [201, 300]
    assert len(op.requests) == 2


def test_comments_are_paginated():
    op = Opener({("GET", "/repos/o/r/issues/7/comments?per_page=100&page=1"): [_comment(i) for i in range(100)],
                 ("GET", "/repos/o/r/issues/7/comments?per_page=100&page=2"): [_comment(100, "bot[bot]")]})
    got = GitHub("o/r", token="t", opener=op).comments(7)
    assert len(got) == 101 and got[-1] == {"id": 100, "body": "c100", "user": "bot[bot]",
                                           "created_at": "2026-09-30T00:00:00Z"}


def test_writes_send_the_right_requests():
    op = Opener({("GET", "/users/popeye37"): {"id": 42}})
    gh = GitHub("o/r", token="t", opener=op)
    gh.comment(3, "hi")
    gh.edit_comment(9, "new")
    gh.add_labels(3, ["claim"])
    gh.close(3, "done")
    assert gh.user_id("popeye37") == 42
    assert [(m, p, b) for m, p, _, b in op.requests] == [
        ("POST", "/repos/o/r/issues/3/comments", {"body": "hi"}),
        ("PATCH", "/repos/o/r/issues/comments/9", {"body": "new"}),
        ("POST", "/repos/o/r/issues/3/labels", {"labels": ["claim"]}),
        ("POST", "/repos/o/r/issues/3/comments", {"body": "done"}),
        ("PATCH", "/repos/o/r/issues/3", {"state": "closed", "state_reason": "completed"}),
        ("GET", "/users/popeye37", None)]


def _http(code):
    return urllib.error.HTTPError("u", code, "x", {}, None)


def test_remove_label_tolerates_a_missing_label_only():
    path = ("DELETE", "/repos/o/r/issues/3/labels/claim-stale")
    GitHub("o/r", token="t", opener=Opener({path: _http(404)})).remove_label(3, "claim-stale")
    with pytest.raises(urllib.error.HTTPError):
        GitHub("o/r", token="t", opener=Opener({path: _http(500)})).remove_label(3, "claim-stale")


def test_token_comes_from_the_environment_or_gh(monkeypatch):
    import subprocess
    monkeypatch.setenv("GITHUB_TOKEN", "env-tok")
    assert github._token() == "env-tok"
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "gh-tok\n", ""))
    assert github._token() == "gh-tok"

    def fail(*a, **k):
        raise OSError("no gh")
    monkeypatch.setattr(subprocess, "run", fail)
    assert github._token() is None

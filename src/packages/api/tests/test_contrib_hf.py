"""Hub against a fake HfApi that models commits, trees, refs and discussions
the way the Hub serves them (checked live on osick/helpmate-tables, PRs #1/#2):
a PR's commits are listed as `commit` events, `list_repo_commits(revision=head)`
walks from the head back through main's history, and refs/pr/N stays after a merge."""
import pytest

from helpmate_server.contrib.hf import Hub


class _Response:
    """Just enough of an HTTP response for HfHubHTTPError: huggingface_hub 0.34 (requests)
    takes it optionally, 2.x (httpx) requires it and reads .headers and .request."""
    status_code = 400
    headers: dict = {}
    request = None


def _bad_request(message):
    from huggingface_hub.errors import BadRequestError
    return BadRequestError(message, response=_Response())


class _Event:
    def __init__(self, type_, **kw):
        self.type = type_
        self.__dict__.update(kw)


class _Commit:
    def __init__(self, sha):
        self.commit_id = sha


def _sha(n):
    return f"{n:040x}"


class FakeApi:
    """Commits are (parent, tree) with tree = {path: (size, lfs_sha256 | None, blob_id)}."""

    def __init__(self, main_tree):
        self.commits = {_sha(0): (None, dict(main_tree))}
        self.main = _sha(0)
        self.prs = {}                  # num -> dict(author, status, desc, oids)
        self.calls = []
        self._n = 0

    def _new(self, parent, tree):
        self._n += 1
        sha = _sha(self._n)
        self.commits[sha] = (parent, tree)
        return sha

    def commit_main(self, add=(), delete=()):
        tree = dict(self.commits[self.main][1])
        tree.update(dict(add))
        for p in delete:
            tree.pop(p, None)
        self.main = self._new(self.main, tree)

    def open_pr(self, num, add, delete=(), commits=1, desc="Claim: #39"):
        parent, oids = self.main, []
        items = list(dict(add).items())
        for i in range(commits):
            tree = dict(self.commits[parent][1])
            tree.update(items[i::commits])
            if i == commits - 1:
                for p in delete:
                    tree.pop(p, None)
            parent = self._new(parent, tree)
            oids.append(parent)
        self.prs[num] = {"author": "popeye37", "status": "open", "desc": desc, "oids": oids}

    def merge(self, num):
        """A squash merge: a new commit on main with the PR's changes."""
        pr = self.prs[num]
        head_tree = self.commits[pr["oids"][-1]][1]
        base_tree = self.commits[self.commits[pr["oids"][0]][0]][1]
        tree = dict(self.commits[self.main][1])
        for p, v in head_tree.items():
            if base_tree.get(p) != v:
                tree[p] = v
        for p in base_tree:
            if p not in head_tree:
                tree.pop(p, None)
        self.main = self._new(self.main, tree)
        pr["status"] = "merged"

    def _rev(self, revision):
        if revision in (None, "main"):
            return self.main
        if revision.startswith("refs/pr/"):
            return self.prs[int(revision.rsplit("/", 1)[1])]["oids"][-1]
        return revision

    # --- the HfApi surface Hub uses ---
    def get_discussion_details(self, repo, num, repo_type=None):
        pr = self.prs[num]
        events = [_Event("comment", content=pr["desc"])] + [_Event("commit", oid=o) for o in pr["oids"]]
        return type("D", (), {"is_pull_request": True, "title": f"Add {num}", "author": pr["author"],
                              "status": pr["status"], "diff": "", "events": events})()

    def list_repo_refs(self, repo, repo_type=None, include_pull_requests=False):
        self.calls.append(("refs",))
        refs = [type("R", (), {"ref": f"refs/pr/{n}", "target_commit": p["oids"][-1]})()
                for n, p in self.prs.items() if p["oids"]]
        return type("Refs", (), {"pull_requests": refs})()

    def list_repo_commits(self, repo, repo_type=None, revision=None):
        self.calls.append(("commits", revision))
        sha, out = self._rev(revision), []
        while sha is not None:
            out.append(_Commit(sha))
            sha = self.commits[sha][0]
        return out

    def list_repo_tree(self, repo, path_in_repo=None, *, recursive=False, expand=False,
                       revision=None, repo_type=None):
        from huggingface_hub.hf_api import RepoFile, RepoFolder
        self.calls.append(("tree", revision, recursive, expand))
        tree = self.commits[self._rev(revision)][1]
        out, dirs = [], set()
        for p, (size, sha, blob) in sorted(tree.items()):
            if "/" in p and not recursive:
                dirs.add(p.split("/")[0])
                continue
            lfs = {"oid": sha, "size": size, "pointerSize": 1} if sha else None
            out.append(RepoFile(path=p, size=size, oid=blob, lfs=lfs))
        out += [RepoFolder(path=d, oid="d") for d in sorted(dirs)]
        return out

    def get_repo_discussions(self, repo, repo_type=None, discussion_type=None, discussion_status=None):
        return [type("S", (), {"num": n})() for n, p in self.prs.items() if p["status"] == "open"]

    def get_paths_info(self, repo, files, revision=None, repo_type=None):
        tree = self.commits[self._rev(revision)][1]
        return [type("I", (), {"path": f, "size": tree[f][0]})() for f in files if f in tree]


MAIN = {".gitattributes": (10, None, "g0"), "README.md": (5, None, "r0"),
        "manifest.json": (9, None, "m0"), "KQvk.hm": (100, "aa", "b1"),
        "KQvk.stats.json": (3, None, "s0")}
KRR = {"KRRvkqq.hm": (700, "bb", "b2"), "KRRvkqq.stats.json": (4, None, "s1")}


def test_files_are_the_diff_against_the_prs_base_not_current_main():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)
    api.commit_main(add={"manifest.json": (11, None, "m1"), "README.md": (6, None, "r1"),
                         ".gitattributes": (11, None, "g1")})         # main moves on (another accept)
    pr = Hub("o/d", api=api).pull_request(2)
    assert pr.files == ["KRRvkqq.hm", "KRRvkqq.stats.json"]
    assert pr.deleted == [] and pr.head == api.prs[2]["oids"][-1]


def test_files_survive_the_merge():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR, commits=2)
    api.commit_main(add={"manifest.json": (11, None, "m1")})
    api.merge(2)
    pr = Hub("o/d", api=api).pull_request(2)
    assert pr.files == ["KRRvkqq.hm", "KRRvkqq.stats.json"] and pr.materials == ["KRRvkqq"]


def test_deletions_and_subdirectories_are_reported():
    api = FakeApi(MAIN)
    api.open_pr(2, {**KRR, "extra/KRRvkqr.hm": (1, "cc", "b3")}, delete=["KQvk.stats.json", ".gitattributes"])
    pr = Hub("o/d", api=api).pull_request(2)
    assert pr.files == ["KRRvkqq.hm", "KRRvkqq.stats.json", "extra/KRRvkqr.hm"]
    assert pr.deleted == ["KQvk.stats.json"]                 # .gitattributes is the Hub's own


def test_no_commit_events_is_an_error_not_a_fallback_to_main():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)
    api.prs[2]["oids"] = []
    with pytest.raises(ValueError, match="base"):
        Hub("o/d", api=api).pull_request(2)


def test_listings_are_cached_and_not_expanded():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)
    api.open_pr(3, {"KRRvkqr.hm": (1, "cc", "b3"), "KRRvkqr.stats.json": (1, None, "s3")})
    hub = Hub("o/d", api=api)
    prs = hub.open_pull_requests()
    assert [p.materials for p in prs] == [["KRRvkqq"], ["KRRvkqr"]]
    trees = [c for c in api.calls if c[0] == "tree"]
    assert all(c[2] is True and c[3] is False for c in trees)          # recursive, no expand
    assert len(trees) == len({c[1] for c in trees}) == 3                 # shared base listed once
    assert sum(c[0] == "refs" for c in api.calls) == 1
    assert hub.file_sizes(["KRRvkqq.hm"], prs[0].head) == {"KRRvkqq.hm": 700}
    assert len([c for c in api.calls if c[0] == "tree"]) == 3            # sizes from the cache
    assert hub.file_sizes([], "refs/pr/2") == {}
    assert hub.file_sizes(["KRRvkqq.hm"], "refs/pr/2") == {"KRRvkqq.hm": 700}  # not a sha: asks


def test_pr_head_is_fetched_fresh():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)
    hub = Hub("o/d", api=api)
    first = hub.pull_request(2).head
    api.prs[2]["oids"].append(_sha(99))
    api.commits[_sha(99)] = (first, dict(api.commits[first][1]))
    assert hub.pr_head(2) == _sha(99)


def test_main_files_carry_lfs_sha_without_expand():
    api = FakeApi(MAIN)
    files = Hub("o/d", api=api).main_files()
    assert files["KQvk.hm"].sha256 == "aa" and files["KQvk.stats.json"].sha256 is None
    assert all(c[3] is False for c in api.calls if c[0] == "tree")


def test_open_pull_requests_skips_a_pr_without_a_base_and_warns(capsys):
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)
    api.open_pr(3, KRR)
    api.prs[3]["oids"] = []                                   # an empty PR: no commit events
    hub = Hub("o/d", api=api)
    assert [p.num for p in hub.open_pull_requests()] == [2]
    err = capsys.readouterr().err
    assert "#3" in err and "skipping" in err and len(err.strip().splitlines()) == 1
    with pytest.raises(ValueError, match="base"):             # the direct path still refuses
        hub.pull_request(3)


def test_open_pull_requests_still_propagates_other_errors():
    api = FakeApi(MAIN)
    api.open_pr(2, KRR)

    def boom(*a, **k):
        raise ConnectionError("network down")
    api.list_repo_commits = boom
    with pytest.raises(ConnectionError):
        Hub("o/d", api=api).open_pull_requests()


# --- merge conflicts and the server-side copy fallback ---

class ConflictApi(FakeApi):
    """Main has moved on with its own `.gitattributes`, so merging a PR that also
    touched it is refused the way the Hub refuses it (BadRequestError + filesWithConflicts)."""

    def __init__(self, main_tree, conflicting=(".gitattributes",)):
        super().__init__(main_tree)
        self.conflicting = list(conflicting) if isinstance(conflicting, (list, tuple)) else conflicting
        self.status_changes = []
        self.commit_ops = []

    def merge_pull_request(self, repo, num, repo_type=None, comment=None):
        self.calls.append(("merge", num))
        raise _bad_request("Bad request for merge endpoint: There are merge conflicts, cannot proceed")

    def get_discussion_details(self, repo, num, repo_type=None):
        d = super().get_discussion_details(repo, num, repo_type=repo_type)
        d.conflicting_files = self.conflicting
        return d

    def create_commit(self, repo_id, operations, *, commit_message, repo_type=None, **kw):
        from huggingface_hub import CommitOperationCopy
        ops = list(operations)
        self.commit_ops.append((commit_message, ops))
        tree = dict(self.commits[self.main][1])
        changed = False
        for op in ops:
            assert isinstance(op, CommitOperationCopy)
            src = self.commits[self._rev(op.src_revision)][1][op.src_path_in_repo]
            changed |= tree.get(op.path_in_repo) != src   # huggingface_hub drops no-op copies
            tree[op.path_in_repo] = src
        if changed:                                     # all dropped: no commit, main's head returned
            self.main = self._new(self.main, tree)
        return type("CI", (), {"oid": self.main,
                               "commit_url": f"https://hf.example/commit/{self.main}"})()

    def repo_info(self, repo_id, repo_type=None, revision=None, **kw):
        return type("Info", (), {"sha": self._rev(revision)})()

    def change_discussion_status(self, repo_id, discussion_num, new_status, *, comment=None,
                                 repo_type=None, token=None):
        self.status_changes.append((discussion_num, new_status, comment, repo_type))
        self.prs[discussion_num]["status"] = new_status


def _conflicting(conflicting=(".gitattributes",)):
    api = ConflictApi(MAIN, conflicting)
    api.open_pr(2, {**KRR, ".gitattributes": (11, None, "g-pr")})
    api.commit_main(add={".gitattributes": (12, None, "g-main")})
    return api


def test_merge_conflict_carries_the_conflicting_files():
    from helpmate_server.contrib.hf import MergeConflict
    api = _conflicting()
    with pytest.raises(MergeConflict) as exc:
        Hub("o/d", api=api).merge(2)
    assert exc.value.files == [".gitattributes"]


def test_merge_conflict_without_a_file_list_is_never_empty():
    """The Hub may say `True` (conflicts, list unavailable): never an empty list, which
    would look like a subset of anything."""
    from helpmate_server.contrib.hf import MergeConflict
    api = _conflicting(conflicting=True)
    with pytest.raises(MergeConflict) as exc:
        Hub("o/d", api=api).merge(2)
    assert exc.value.files and exc.value.files != [".gitattributes"]


def test_other_merge_errors_propagate_unchanged():
    from huggingface_hub.errors import BadRequestError
    api = _conflicting()

    def refuse(*a, **k):
        raise _bad_request("Bad request: you are not allowed to merge")
    api.merge_pull_request = refuse
    with pytest.raises(BadRequestError, match="not allowed"):
        Hub("o/d", api=api).merge(2)


def test_merge_by_copy_copies_server_side_verifies_and_closes():
    from huggingface_hub import CommitOperationCopy
    api = _conflicting()
    head = api.prs[2]["oids"][-1]
    seen = []
    url = Hub("o/d", api=api).merge_by_copy(
        2, head, ["KRRvkqq.hm", "KRRvkqq.stats.json"], message="Add KRRvkqq",
        comment=_comment, on_commit=lambda ref, already: seen.append((ref, already)))
    (msg, ops), = api.commit_ops
    assert msg == "Add KRRvkqq"
    assert [(o.src_path_in_repo, o.path_in_repo, o.src_revision) for o in ops] == [
        ("KRRvkqq.hm", "KRRvkqq.hm", head), ("KRRvkqq.stats.json", "KRRvkqq.stats.json", head)]
    assert all(isinstance(o, CommitOperationCopy) for o in ops)
    main = api.commits[api.main][1]
    assert main["KRRvkqq.hm"] == KRR["KRRvkqq.hm"] and main[".gitattributes"] == (12, None, "g-main")
    assert url == f"https://hf.example/commit/{api.main}" and seen == [(url, False)]
    assert api.status_changes == [(2, "closed", f"Merged as {url}. Thank you!", "dataset")]


def _comment(ref, already):
    return f"Already on main as of {ref}." if already else f"Merged as {ref}. Thank you!"


def test_merge_by_copy_of_files_already_on_main_makes_no_commit_and_says_so():
    """huggingface_hub drops copies whose destination already equals the source; with all of
    them dropped it makes no commit and returns main's head: never claim "Merged as"."""
    api = _conflicting()
    head = api.prs[2]["oids"][-1]
    api.commit_main(add=KRR)                       # e.g. landed by hand meanwhile
    before, seen = api.main, []
    ref = Hub("o/d", api=api).merge_by_copy(2, head, ["KRRvkqq.hm", "KRRvkqq.stats.json"],
                                            message="m", comment=_comment,
                                            on_commit=lambda r, a: seen.append((r, a)))
    assert api.main == before and ref == before and seen == [(before, True)]
    ((num, status, text, _),) = api.status_changes
    assert status == "closed" and text == f"Already on main as of {before}." and "Merged as" not in text


def test_merge_by_copy_refuses_to_close_when_main_does_not_match_the_head():
    api = _conflicting()
    head = api.prs[2]["oids"][-1]
    real = api.create_commit

    def lossy(*a, **k):
        info = real(*a, **k)
        api.commits[api.main][1]["KRRvkqq.hm"] = (699, "bad", "b9")   # a truncated copy
        return info
    api.create_commit = lossy
    seen = []
    with pytest.raises(RuntimeError, match="KRRvkqq.hm"):
        Hub("o/d", api=api).merge_by_copy(2, head, ["KRRvkqq.hm", "KRRvkqq.stats.json"],
                                          message="m", comment=_comment,
                                          on_commit=lambda r, a: seen.append(r))
    assert api.status_changes == [] and seen == []


def test_close_and_status_of_a_pr():
    api = _conflicting()
    hub = Hub("o/d", api=api)
    assert hub.pr_status(2) == "open"
    hub.close_pr(2, "done")
    assert api.status_changes == [(2, "closed", "done", "dataset")] and hub.pr_status(2) == "closed"

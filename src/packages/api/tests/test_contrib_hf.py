"""Hub against a fake HfApi that models commits, trees, refs and discussions
the way the Hub serves them (checked live on osick/helpmate-tables, PRs #1/#2):
a PR's commits are listed as `commit` events, `list_repo_commits(revision=head)`
walks from the head back through main's history, and refs/pr/N stays after a merge."""
import pytest

from helpmate_server.contrib.hf import Hub


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

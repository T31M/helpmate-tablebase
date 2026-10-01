# src/packages/api/tests/fakes.py
"""In-memory stand-ins for the dataset (Hub) and GitHub, recording every
write so tests can assert what would have been posted, merged or pushed."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from helpmate_server.contrib.hf import FileMeta, PullRequest


class FakeHub:
    """Like the real Hub, a PR's files are the diff between the main it branched
    from (a snapshot taken by add_pr) and its own tree, so main moving on or the
    PR being merged does not change them."""

    def __init__(self, main: dict[str, bytes] | None = None):
        self.repo = "osick/helpmate-tables"
        self.main: dict[str, bytes] = dict(main or {})
        self.prs: dict[int, tuple[PullRequest, dict[str, bytes]]] = {}
        self.bases: dict[int, dict[str, bytes]] = {}
        self.deletes: dict[int, list[str]] = {}
        self.comments: list[tuple[int, str]] = []
        self.merged: list[int] = []
        self.commits: list[tuple[str, dict[str, bytes]]] = []
        self.downloads: list[str] = []
        self.pr_fetches: list[int] = []
        self.conflicts: dict[int, list[str]] = {}   # PR -> files the Hub reports as conflicting
        self.copies: list[dict] = []                 # merge_by_copy calls, in order
        self.closed: list[tuple[int, str]] = []      # (PR, comment)

    def add_pr(self, num, files: dict[str, bytes], *, author="popeye37", description="",
               head="h1", status="open", delete=()):
        pr = PullRequest(num, f"Add {num}", author, status, description, [], head,
                         f"https://hf.example/discussions/{num}")
        self.prs[num] = (pr, dict(files))
        self.bases[num] = dict(self.main)
        self.deletes[num] = list(delete)

    def _pr_tree(self, num) -> dict[str, bytes]:
        tree = {**self.bases[num], **self.prs[num][1]}
        for p in self.deletes[num]:
            tree.pop(p, None)
        return tree

    def pull_request(self, num):
        self.pr_fetches.append(num)
        meta, _ = self.prs[num]
        base, tip = self.bases[num], self._pr_tree(num)
        files = sorted(p for p, v in tip.items() if p != ".gitattributes" and base.get(p) != v)
        deleted = sorted(p for p in base if p != ".gitattributes" and p not in tip)
        return dataclasses.replace(meta, files=files, deleted=deleted)

    def pr_head(self, num):
        return self.prs[num][0].head

    def open_pull_requests(self):
        return [self.pull_request(n) for n, (p, _) in self.prs.items() if p.status == "open"]

    def _num(self, revision):
        if revision.startswith("refs/pr/"):
            return int(revision.rsplit("/", 1)[1])
        return next(n for n, (p, _) in self.prs.items() if p.head == revision)

    def file_sizes(self, files, revision):
        tree = self._pr_tree(self._num(revision))
        return {f: len(tree[f]) for f in files if f in tree}

    def download(self, filename, revision, dest: Path) -> Path:
        num = self._num(revision)
        self.downloads.append(filename)
        dest.mkdir(parents=True, exist_ok=True)
        (dest / filename).write_bytes(self._pr_tree(num)[filename])
        return dest / filename

    def comment(self, num, text):
        self.comments.append((num, text))

    def merge(self, num):
        from helpmate_server.contrib.hf import MergeConflict
        if num in self.conflicts:
            raise MergeConflict(num, list(self.conflicts[num]))
        pr, files = self.prs[num]
        self.main.update(files)
        for p in self.deletes[num]:
            self.main.pop(p, None)
        pr.status = "merged"
        self.merged.append(num)

    def pr_status(self, num):
        return self.prs[num][0].status

    def close_pr(self, num, comment):
        self.closed.append((num, comment))
        self.prs[num][0].status = "closed"

    def merge_by_copy(self, num, head, files, message, comment, on_commit=None):
        """Copies `files` from the PR's tree into main, then closes the PR. If main already
        has them all, no commit is made and the ref is main's head ("main-sha")."""
        assert head == self.prs[num][0].head, "copy from a head that is not the PR's"
        tree = self._pr_tree(num)
        already = all(self.main.get(f) == tree[f] for f in files)
        self.main.update({f: tree[f] for f in files})
        ref = "main-sha" if already else f"https://hf.example/commit/copy-{len(self.copies) + 1}"
        self.copies.append({"num": num, "head": head, "files": list(files), "message": message,
                            "already": already})
        if on_commit is not None:
            on_commit(ref, already)
        self.close_pr(num, comment(ref, already))
        return ref

    def main_files(self):
        import hashlib
        return {k: FileMeta(k, len(v), hashlib.sha256(v).hexdigest()) for k, v in self.main.items()}

    def read_bytes(self, filename, revision="main"):
        return self.main[filename]

    def fetch_manifest(self):
        return json.loads(self.main.get("manifest.json", b'{"schema":1,"files":{}}'))

    def commit(self, files, message):
        self.commits.append((message, dict(files)))
        self.main.update(files)


class FakeGitHub:
    def __init__(self, issues: list[dict] | None = None):
        self.issues = {i["number"]: i for i in (issues or [])}
        self.posted: list[tuple[int, str]] = []
        self.edited: list[tuple[int, str]] = []
        self.labels: dict[int, set[str]] = {n: set(i.get("labels", [])) for n, i in self.issues.items()}
        self.closed: list[int] = []
        self.issue_comments: dict[int, list[dict]] = {n: [] for n in self.issues}

    def comment(self, issue, body):
        self.posted.append((issue, body))
        self.issue_comments.setdefault(issue, []).append(
            {"id": len(self.posted), "body": body, "user": "github-actions[bot]",
             "created_at": "2026-09-30T00:00:00Z"})

    def issue(self, num):
        return self.issues[num]

    def claim_issues(self):
        return [i for i in self.issues.values()
                if i.get("state", "open") == "open" and i["title"].lower().startswith("claim")]

    def comments(self, issue):
        return list(self.issue_comments.get(issue, []))

    def edit_comment(self, comment_id, body):
        self.edited.append((comment_id, body))
        for cs in self.issue_comments.values():
            for c in cs:
                if c["id"] == comment_id:
                    c["body"] = body

    def add_labels(self, issue, labels):
        self.labels.setdefault(issue, set()).update(labels)

    def remove_label(self, issue, label):
        self.labels.setdefault(issue, set()).discard(label)

    def close(self, issue, comment):
        self.comment(issue, comment)
        self.closed.append(issue)
        self.issues[issue]["state"] = "closed"

    def user_id(self, login):
        return 1000 + len(login)

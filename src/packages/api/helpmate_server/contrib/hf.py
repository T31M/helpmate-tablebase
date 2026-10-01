"""The dataset side: pull requests, their files, comments, merges, commits."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_SHA = re.compile(r"[0-9a-f]{40}")


class BaseUnknown(ValueError):
    """A PR's base commit (hence its files) cannot be determined."""


@dataclass
class PullRequest:
    num: int
    title: str
    author: str
    status: str            # "open" | "merged" | "closed" | "draft"
    description: str
    files: list[str] = field(default_factory=list)
    head: str | None = None
    url: str = ""
    deleted: list[str] = field(default_factory=list)

    @property
    def materials(self) -> list[str]:
        return sorted({f[: -len(".hm")] for f in self.files if f.endswith(".hm")})


@dataclass(frozen=True)
class FileMeta:
    path: str
    size: int
    sha256: str | None     # None for non-LFS files: hash their bytes


class Hub:
    def __init__(self, repo_id: str, api=None):
        from huggingface_hub import HfApi

        self.repo = repo_id
        self.api = api or HfApi()
        self._trees: dict[str, dict[str, tuple]] = {}   # commit sha -> {path: (size, identity)}
        self._refs: dict[str, str] | None = None

    def _url(self, num: int) -> str:
        return f"https://huggingface.co/datasets/{self.repo}/discussions/{num}"

    def _pr_refs(self, fresh: bool = False) -> dict[str, str]:
        refs = self._refs
        if fresh or refs is None:
            listing = self.api.list_repo_refs(self.repo, repo_type="dataset", include_pull_requests=True)
            refs = self._refs = {r.ref: r.target_commit for r in listing.pull_requests or []}
        return refs

    def pr_head(self, num: int) -> str | None:
        """The PR's head commit as the Hub has it now (never cached)."""
        return self._pr_refs(fresh=True).get(f"refs/pr/{num}")

    def pull_request(self, num: int) -> PullRequest:
        d = self.api.get_discussion_details(self.repo, num, repo_type="dataset")
        if not d.is_pull_request:
            raise ValueError(f"#{num} on {self.repo} is a discussion, not a pull request")
        desc = next((getattr(e, "content", "") for e in d.events
                     if getattr(e, "type", "") == "comment"), "")
        oids = [e.oid for e in d.events if getattr(e, "type", "") == "commit"]
        head = self._pr_refs().get(f"refs/pr/{num}") or (oids[-1] if oids else None)
        files, deleted = self._changed_files(num, head, set(oids))
        return PullRequest(num, d.title, d.author, d.status, desc, files, head, self._url(num), deleted)

    def _base(self, num: int, head: str | None, pr_commits: set[str]) -> str:
        """The commit the PR branched from: the first commit behind its head that is not
        one of the PR's own. Works after a merge too (refs/pr/N and its commits stay)."""
        if head is None or not pr_commits:
            raise BaseUnknown(f"PR #{num}: cannot determine its base commit (no commits listed)")
        history = [c.commit_id for c in self.api.list_repo_commits(self.repo, repo_type="dataset",
                                                                   revision=head)]
        if not history or history[0] not in pr_commits:
            raise BaseUnknown(f"PR #{num}: cannot determine its base commit "
                             f"(head {head} is not one of the PR's commits)")
        base = next((c for c in history if c not in pr_commits), None)
        if base is None:
            raise BaseUnknown(f"PR #{num}: cannot determine its base commit (no parent outside the PR)")
        return base

    def _tree(self, revision: str) -> dict[str, tuple]:
        """{path: (size, lfs sha256 or blob id)} for every file, subdirectories included.
        The plain listing already carries LFS sha256 and size: no `expand`."""
        from huggingface_hub.hf_api import RepoFile

        if revision in self._trees:
            return self._trees[revision]
        tree = {f.path: (f.size, f.lfs.sha256 if f.lfs else f.blob_id)
                for f in self.api.list_repo_tree(self.repo, repo_type="dataset",
                                                 revision=revision, recursive=True)
                if isinstance(f, RepoFile)}
        if _SHA.fullmatch(revision):          # a commit never changes; a branch name does
            self._trees[revision] = tree
        return tree

    def _changed_files(self, num: int, head: str | None, pr_commits: set[str]
                       ) -> tuple[list[str], list[str]]:
        """(added or changed, deleted) between the PR's base and its head.
        `.gitattributes` is maintained by the Hub itself, not contributed."""
        base = self._tree(self._base(num, head, pr_commits))
        tip = self._tree(head)  # type: ignore[arg-type]  # _base raised if head is None
        changed = sorted(p for p, ident in tip.items() if p != ".gitattributes" and base.get(p) != ident)
        deleted = sorted(p for p in base if p != ".gitattributes" and p not in tip)
        return changed, deleted

    def open_pull_requests(self) -> list[PullRequest]:
        ds = self.api.get_repo_discussions(self.repo, repo_type="dataset",
                                           discussion_type="pull_request",
                                           discussion_status="open")
        out = []
        for d in ds:
            try:
                out.append(self.pull_request(d.num))
            except BaseUnknown as e:  # one broken PR must not stop the bot, status or docs sync
                print(f"warning: skipping open PR #{d.num}: {e}", file=sys.stderr)
        return out

    def file_sizes(self, files: list[str], revision: str) -> dict[str, int]:
        if not files:
            return {}
        if revision in self._trees:
            tree = self._trees[revision]
            return {f: tree[f][0] for f in files if f in tree}
        infos = self.api.get_paths_info(self.repo, files, revision=revision, repo_type="dataset")
        return {i.path: i.size for i in infos}

    def download(self, filename: str, revision: str, dest: Path) -> Path:
        from huggingface_hub import hf_hub_download

        return Path(hf_hub_download(self.repo, filename, repo_type="dataset",
                                    revision=revision, local_dir=dest))

    def comment(self, num: int, text: str) -> None:
        self.api.comment_discussion(self.repo, num, text, repo_type="dataset")

    def merge(self, num: int) -> None:
        self.api.merge_pull_request(self.repo, num, repo_type="dataset")

    def main_files(self) -> dict[str, FileMeta]:
        from huggingface_hub.hf_api import RepoFile

        out = {}
        for f in self.api.list_repo_tree(self.repo, repo_type="dataset", recursive=True):
            if isinstance(f, RepoFile):
                out[f.path] = FileMeta(f.path, f.size, f.lfs.sha256 if f.lfs else None)
        return out

    def read_bytes(self, filename: str, revision: str = "main") -> bytes:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            return self.download(filename, revision, Path(tmp)).read_bytes()

    def fetch_manifest(self) -> dict:
        import json

        return json.loads(self.read_bytes("manifest.json"))

    def commit(self, files: dict[str, bytes], message: str) -> None:
        from huggingface_hub import CommitOperationAdd

        ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=v) for k, v in files.items()]
        self.api.create_commit(repo_id=self.repo, repo_type="dataset", operations=ops,
                               commit_message=message)

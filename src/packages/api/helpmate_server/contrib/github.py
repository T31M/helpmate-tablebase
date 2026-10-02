"""GitHub REST over urllib: the Action has GITHUB_TOKEN, the maintainer has
`gh auth token`. No third-party client, so the Action installs nothing."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from typing import Any, Callable


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    try:
        return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                              check=True).stdout.strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


class GitHub:
    def __init__(self, repo: str, token: str | None = None,
                 opener: Callable[..., Any] | None = None):
        self.repo = repo
        self.token = token if token is not None else _token()
        self._open = opener or urllib.request.urlopen

    def _req(self, method: str, path: str, body: Any = None) -> Any:
        url = path if path.startswith("https://") else f"https://api.github.com{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Accept", "application/vnd.github+json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        with self._open(req, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def comment(self, issue: int, body: str) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{issue}/comments", {"body": body})

    def issue(self, num: int) -> dict:
        return self._req("GET", f"/repos/{self.repo}/issues/{num}")

    def _pages(self, path: str) -> list[dict]:
        """Every item of a paginated listing."""
        out: list[dict] = []
        page, sep = 1, "&" if "?" in path else "?"
        while True:
            batch = self._req("GET", f"{path}{sep}per_page=100&page={page}")
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    def claim_issues(self) -> list[dict]:
        return [i for i in self._pages(f"/repos/{self.repo}/issues?state=open")
                if "pull_request" not in i
                and (i["title"].lower().startswith("claim")
                     or any(lb["name"] == "claim" for lb in i.get("labels", [])))]

    def comments(self, issue: int) -> list[dict]:
        cs = self._pages(f"/repos/{self.repo}/issues/{issue}/comments")
        return [{"id": c["id"], "body": c["body"], "user": c["user"]["login"],
                 "created_at": c["created_at"]} for c in cs]

    def edit_comment(self, comment_id: int, body: str) -> None:
        self._req("PATCH", f"/repos/{self.repo}/issues/comments/{comment_id}", {"body": body})

    def add_labels(self, issue: int, labels: list[str]) -> None:
        self._req("POST", f"/repos/{self.repo}/issues/{issue}/labels", {"labels": labels})

    def remove_label(self, issue: int, label: str) -> None:
        import urllib.error
        try:
            self._req("DELETE", f"/repos/{self.repo}/issues/{issue}/labels/{label}")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise

    def close(self, issue: int, comment: str) -> None:
        self.comment(issue, comment)
        self._req("PATCH", f"/repos/{self.repo}/issues/{issue}",
                  {"state": "closed", "state_reason": "completed"})

    def user_id(self, login: str) -> int:
        return int(self._req("GET", f"/users/{login}")["id"])

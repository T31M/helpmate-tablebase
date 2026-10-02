"""The two lines that tie a dataset PR to GitHub: which claim, which person.
HF and GitHub share no identity, so these lines are the only link."""
from __future__ import annotations

import re

from . import GITHUB_REPO

_CLAIM = re.compile(r"(?im)^\s*claim:\s*(?:" + re.escape(GITHUB_REPO) + r")?#(\d+)")
_ISSUE_URL = re.compile(r"github\.com/" + re.escape(GITHUB_REPO) + r"/issues/(\d+)")
_GITHUB = re.compile(r"(?im)^\s*github:\s*@?([A-Za-z0-9-]+)")


def format_links(claim: int | None, github: str | None) -> str:
    lines = []
    if claim is not None:
        lines.append(f"Claim: {GITHUB_REPO}#{claim}")
    if github:
        lines.append(f"GitHub: @{github.lstrip('@')}")
    return "\n".join(lines)


def parse_links(text: str) -> tuple[int | None, str | None]:
    m = _CLAIM.search(text or "") or _ISSUE_URL.search(text or "")
    g = _GITHUB.search(text or "")
    return (int(m.group(1)) if m else None), (g.group(1) if g else None)

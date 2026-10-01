"""Claim issues: what they claim, what state each material is in, and the
one status comment the bot keeps up to date on each claim."""
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime

from .links import parse_links
from .materials import canonical, expand, universe

_NAME = re.compile(r"(?<![A-Za-z])K[QRBNP?]*vk[qrbnp?]*(?![A-Za-z?])")
_STRUCK = re.compile(r"~~(.*?)~~", re.S)
_MARKER = re.compile(r"<!-- contrib-status body-sha=(\w+) seen=(\d{4}-\d{2}-\d{2}) -->")
_SECTION = re.compile(r"^###[ \t]+(.+?)[ \t]*$", re.M)
_ANON = re.compile(r"^\s*-\s*\[[xX]\]\s*Do not name me", re.M)
_NO_RESPONSE = "_No response_"
STALE_DAYS = 21
BOT_NOTE = ("*Updated automatically from the dataset and the other claims — "
            "you no longer need to keep a status list in the issue by hand.*")


def _names(text: str) -> list[str]:
    out: list[str] = []
    for tok in _NAME.findall(text):
        out += expand(tok) if "?" in tok else ([tok] if canonical(tok) == tok else [])
    return out


def _ordered(names) -> list[str]:
    want = set(names)
    return [m.name for m in universe() if m.name in want]


def parse_claim(text: str) -> tuple[list[str], list[str]]:
    released = _names(" ".join(_STRUCK.findall(text or "")))
    claimed = set(_names(_STRUCK.sub(" ", text or ""))) - set(released)
    return _ordered(claimed), _ordered(released)


def _sections(body: str) -> dict[str, str]:
    """`### Label` sections of a GitHub issue-form body -> their text."""
    parts = _SECTION.split(body or "")
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def parse_form(body: str) -> tuple[str | None, str | None, bool]:
    """(Hugging Face username, name to credit, anonymous) from the claim form.
    A free-text claim has no sections and yields the defaults."""
    sec = _sections(body)

    def value(label: str) -> str | None:
        v = sec.get(label, "")
        return None if not v or v == _NO_RESPONSE else v

    hf = value("Hugging Face username")
    hf = (hf.split()[0].lstrip("@") or None) if hf else None
    anonymous = bool(_ANON.search(sec.get("Credit", "")))
    return hf, value("Name to credit"), anonymous


@dataclass
class Claim:
    issue: int
    author: str
    created_at: str
    materials: list[str]
    released: list[str] = field(default_factory=list)
    body: str = ""
    hf: str | None = None          # the claim form's fields; None / False on a free-text claim
    credit: str | None = None
    anonymous: bool = False


class ClaimIndex:
    def __init__(self, claims: list[Claim]):
        self.claims = sorted(claims, key=lambda c: c.issue)
        self._first: dict[str, Claim] = {}
        for c in self.claims:
            for m in c.materials:
                self._first.setdefault(m, c)

    def claim_for(self, material: str) -> Claim | None:
        return self._first.get(material)


def load_index(gh) -> ClaimIndex:
    """Every open claim issue, parsed: materials, releases and the form's fields."""
    out = []
    for i in gh.claim_issues():
        body = i.get("body") or ""
        mats, rel = parse_claim(f"{i['title']}\n{body}")
        out.append(Claim(i["number"], i["user"]["login"], i["created_at"], mats, rel, body,
                         *parse_form(body)))
    return ClaimIndex(out)


@dataclass
class Status:
    state: str
    hf_pr: int | None = None
    claim: int | None = None
    contributor: str | None = None


def material_status(done: set[str], in_review: dict, index: ClaimIndex, registry) -> dict[str, Status]:
    out = {}
    for m in universe():
        name = m.name
        who = registry.tables.get(name, {}).get("contributor")
        c = index.claim_for(name)
        if name in done:
            out[name] = Status("done", registry.tables.get(name, {}).get("hf_pr"), None, who)
        elif name in in_review:
            out[name] = Status("in review", in_review[name].num, c.issue if c else None,
                               in_review[name].author)
        elif m.bare_king:
            out[name] = Status("not needed")
        elif c:
            out[name] = Status("claimed", None, c.issue, c.author)
        else:
            out[name] = Status("open")
    return out


ICON = {"done": "✅ done", "in review": "🔍 in review", "claimed": "🚧 claimed",
        "open": "⬜ open", "not needed": "➖ not needed"}


def status_comment(claim: Claim, statuses: dict[str, Status], conflicts: list[str],
                   stale: bool, body_sha: str, seen: str, hf_url: str) -> str:
    rows = []
    for m in claim.materials:
        s = statuses[m]
        extra = f" — [HF PR #{s.hf_pr}]({hf_url}/discussions/{s.hf_pr})" if s.state == "in review" else ""
        rows.append(f"| {m} | {ICON[s.state]}{extra} |")
    parts = [f"<!-- contrib-status body-sha={body_sha} seen={seen} -->",
             f"**Claim status** — {sum(statuses[m].state == 'done' for m in claim.materials)} "
             f"of {len(claim.materials)} done", "", BOT_NOTE, "",
             "| material | status |", "|---|---|", *rows]
    if conflicts:
        parts += ["", "**Conflicts** (the earlier claim or the finished table wins; "
                      "strike a name through with `~~name~~` to release it):", "",
                  *[f"- {c}" for c in conflicts]]
    if stale:
        parts += ["", f"⏳ No activity by @{claim.author} for {STALE_DAYS} days. "
                      "Claims lapse after three weeks of silence — a short comment keeps it."]
    return "\n".join(parts) + "\n"


def _day(ts: str) -> date:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()


def ownership_conflict(pr, claim: Claim, registry) -> str | None:
    """Why the PR's identity clues point at someone other than the claim's author, or None.
    The claims bot and accept both ask this, so they agree on who owns a PR."""
    num, login = parse_links(pr.description)
    if num is not None and num != claim.issue:
        return f"the PR names claim #{num}, but its material is claimed in #{claim.issue}"
    if login is not None and login.lower() != claim.author.lower():
        return f"the PR names GitHub user {login}, but #{claim.issue} is by {claim.author}"
    known = registry.by_hf(pr.author)
    if known and known.github and known.github.lower() != claim.author.lower():
        return (f"HF user {pr.author} is {known.github} on GitHub, but #{claim.issue} "
                f"is by {claim.author}")
    return None


def run_claims(hub, gh, registry, today: date) -> int:
    index = load_index(gh)
    done = {f[:-3] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}
    in_review = {m: pr for pr in hub.open_pull_requests() for m in pr.materials}
    statuses = material_status(done, in_review, index, registry)
    hf_url = f"https://huggingface.co/datasets/{hub.repo}"
    failed = []
    for c in index.claims:
        try:
            _update_claim(c, index, statuses, in_review, registry, gh, today, hf_url)
        except (OSError, ValueError) as exc:  # urllib's HTTPError/URLError are OSErrors
            print(f"claim #{c.issue}: {exc}", file=sys.stderr)
            failed.append(c.issue)
    return 1 if failed else 0


def _update_claim(c: Claim, index: ClaimIndex, statuses: dict[str, Status], in_review: dict,
                  registry, gh, today: date, hf_url: str) -> None:
    """The status comment and labels of one claim issue."""
    conflicts = []
    for m in c.materials:
        first = index.claim_for(m)
        if first and first.issue != c.issue:
            conflicts.append(f"{m} is already claimed in #{first.issue}")
        s = statuses[m]
        if s.state == "done":
            entry = registry.tables.get(m)
            if entry is None:
                conflicts.append(f"{m} is already in the dataset")
            else:
                person = registry.contributors.get(entry.get("contributor"))
                login = person.github if person else None
                if (login or "").lower() != c.author.lower():
                    conflicts.append(f"{m} is already done")
        elif s.state == "in review" and ownership_conflict(in_review[m], c, registry):
            conflicts.append(f"{m} is in review by someone else (HF PR #{in_review[m].num})")
    comments = gh.comments(c.issue)
    mine = next((x for x in comments if x["user"].endswith("[bot]")
                 and _MARKER.search(x["body"])), None)
    body_sha = hashlib.sha256(c.body.encode()).hexdigest()[:12]
    seen = today.isoformat()
    marker = _MARKER.search(mine["body"]) if mine else None
    if marker and marker.group(1) == body_sha:
        seen = marker.group(2)
    activity = max([_day(c.created_at), date.fromisoformat(seen)]
                   + [_day(x["created_at"]) for x in comments if x["user"] == c.author])
    stale = (today - activity).days >= STALE_DAYS
    text = status_comment(c, statuses, conflicts, stale, body_sha, seen, hf_url)
    if mine is None:
        gh.comment(c.issue, text)
    elif mine["body"] != text:
        gh.edit_comment(mine["id"], text)
    gh.add_labels(c.issue, ["claim"])
    for label, on in (("claim-conflict", bool(conflicts)), ("claim-stale", stale)):
        if on:
            gh.add_labels(c.issue, [label])
        else:
            gh.remove_label(c.issue, label)

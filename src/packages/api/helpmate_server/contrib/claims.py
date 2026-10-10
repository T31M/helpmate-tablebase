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
_CONFIRM = re.compile(r"\s*confirm:", re.I)
_NO_RESPONSE = "_No response_"
STALE_DAYS = 21
BOT_NOTE = ("*Updated automatically from the dataset and the other claims — "
            "you no longer need to keep a status list in the issue by hand.*")


def _names(text: str, explicit_only: bool = False) -> list[str]:
    out: list[str] = []
    for tok in _NAME.findall(text):
        if "?" in tok:
            out += [] if explicit_only else expand(tok)
        elif canonical(tok) == tok:
            out.append(tok)
    return out


def _ordered(names) -> list[str]:
    want = set(names)
    return [m.name for m in universe() if m.name in want]


def parse_claim(text: str) -> tuple[list[str], list[str]]:
    released = _names(" ".join(_STRUCK.findall(text or "")))
    claimed = set(_names(_STRUCK.sub(" ", text or ""))) - set(released)
    return _ordered(claimed), _ordered(released)


def explicit_names(text: str) -> set[str]:
    """The claimed materials named as a plain canonical name, not via a `?` wildcard."""
    released = set(_names(" ".join(_STRUCK.findall(text or ""))))
    return set(_names(_STRUCK.sub(" ", text or ""), explicit_only=True)) - released


def _sections(body: str) -> dict[str, str]:
    """`### Label` sections of a GitHub issue-form body -> their text."""
    parts = _SECTION.split(body or "")
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def is_confirm(body: str) -> bool:
    """A confirmation claim: its Materials section (issue form) or, on a free-text claim, the
    first non-empty line of the body starts with `confirm:`."""
    sec = _sections(body)
    if "Materials" in sec:
        text = sec["Materials"]
    else:
        text = next((ln for ln in (body or "").splitlines() if ln.strip()), "")
    return bool(_CONFIRM.match(text))


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
    explicit: set[str] = field(default_factory=set)   # named plainly, not only via a `?` wildcard
    confirm: bool = False          # a deliberate reproduction: never holds, never conflicts


class ClaimIndex:
    def __init__(self, claims: list[Claim]):
        self.claims = sorted(claims, key=lambda c: c.issue)
        self._first: dict[str, Claim] = {}
        for c in self.claims:
            if c.confirm:
                continue        # expected overlap: holds nothing, blocks nobody
            for m in c.materials:
                if m not in c.released:
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
                         *parse_form(body), explicit=explicit_names(f"{i['title']}\n{body}"),
                         confirm=is_confirm(body)))
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


def _names_of(keys: list[str], registry) -> str:
    out = []
    for k in keys:
        c = registry.contributors.get(k)
        out.append("maintainer" if k == "maintainer" and c is None else k if c is None
                   else "an anonymous contributor" if c.anonymous else c.display)
    return out[0] if len(out) == 1 else ", ".join(out[:-1]) + " and " + out[-1]


def status_comment(claim: Claim, statuses: dict[str, Status], conflicts: list[str],
                   stale: bool, body_sha: str, seen: str, hf_url: str, *,
                   excluded: dict[str, Claim] | None = None,
                   notes: dict[str, str] | None = None) -> str:
    """`excluded`: materials an earlier claim holds (shown, not counted); `notes`: extra row text
    (producers, held for)."""
    excluded, notes = excluded or {}, notes or {}
    rows = []
    for m in claim.materials:
        s = statuses[m]
        extra = f" — [HF PR #{s.hf_pr}]({hf_url}/discussions/{s.hf_pr})" if s.state == "in review" else ""
        if m in excluded:
            e = excluded[m]
            text = f"claimed in #{e.issue} by @{e.author}" + (" — ✅ done" if s.state == "done" else "")
        else:
            text = ICON[s.state]
        rows.append(f"| {m} | {text}{extra}{notes.get(m, '')} |")
    covered = [m for m in claim.materials if m not in excluded]
    head = (f"**Claim status** — {sum(statuses[m].state == 'done' for m in covered)} of {len(covered)} done")
    if excluded:
        head += (f" — covers {len(covered)} materials ({len(excluded)} excluded: "
                 "claimed earlier by others)")
    if claim.confirm:
        head += " — confirming (independent reproduction of tables that may already exist)"
    parts = [f"<!-- contrib-status body-sha={body_sha} seen={seen} -->", head, "", BOT_NOTE, "",
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
    conflicts: list[str] = []
    excluded: dict[str, Claim] = {}
    notes: dict[str, str] = {}
    for m in c.materials:
        s = statuses[m]
        first = index.claim_for(m)
        holder = first if first is not None and first.issue != c.issue else None
        if holder is not None and not c.confirm:
            if m in c.explicit:
                conflicts.append(f"{m} is already claimed in #{holder.issue}")
            else:
                excluded[m] = holder        # a wildcard never fights an earlier claim
        if s.state == "done":
            producers = registry.producers_of(m)
            if len(producers) >= 2:
                notes[m] = f" — produced by {_names_of(producers, registry)}"
            if c.confirm or m not in c.explicit:
                continue        # only covered by a wildcard: listed as done, not a conflict
            if m not in registry.tables:
                conflicts.append(f"{m} is already in the dataset")
            else:   # a producer (published file or a credited reproduction) holds it rightly
                logins = {person.github.lower() for k in producers
                          if (person := registry.contributors.get(k)) is not None and person.github}
                if c.author.lower() not in logins:
                    conflicts.append(f"{m} is already done")
        elif s.state == "in review" and first is not None:
            pr = in_review[m]
            if ownership_conflict(pr, first, registry):     # held for the claim holder (rule 4)
                notes[m] = (f" — delivered by {pr.author}, held for you" if first.issue == c.issue
                            else f" — held for claim #{first.issue}")
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
    text = status_comment(c, statuses, conflicts, stale, body_sha, seen, hf_url,
                          excluded=excluded, notes=notes)
    if mine is None:
        gh.comment(c.issue, text)
    elif mine["body"] != text:
        gh.edit_comment(mine["id"], text)
    _overlap_notices(c, index, comments, gh)
    gh.add_labels(c.issue, ["claim"])
    for label, on in (("claim-conflict", bool(conflicts)), ("claim-stale", stale)):
        if on:
            gh.add_labels(c.issue, [label])
        else:
            gh.remove_label(c.issue, label)


def _overlap_notices(c: Claim, index: ClaimIndex, comments: list[dict], gh) -> None:
    """Once per (this claim, earlier claim) pair: tell both authors that materials overlap.
    Never on a confirmation claim (its overlaps are deliberate), never for an earlier one, never
    between two claims of the same author; materials the earlier claim released do not count."""
    if c.confirm:
        return
    done = {x["body"] for x in comments if x["user"].endswith("[bot]")}
    for e in index.claims:
        if e.issue >= c.issue or e.confirm or e.author.lower() == c.author.lower():
            continue
        shared = [m for m in c.materials if m in set(e.materials) - set(e.released)]
        marker = f"<!-- contrib-overlap e={e.issue} -->"
        if not shared or any(marker in b for b in done):
            continue
        listed = ", ".join(shared[:10]) + (f" and {len(shared) - 10} more" if len(shared) > 10 else "")
        gh.comment(c.issue, f"{marker}@{c.author} @{e.author} — these materials are also claimed in "
                            f"#{e.issue}: {listed}. The earlier claim holds them; identical deliveries "
                            "are credited to both.")

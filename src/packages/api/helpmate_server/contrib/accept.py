"""accept: merge verified dataset PRs and land the bookkeeping.

Each step is recorded in a state file as it completes, so a rerun after a
failure (network, CI) resumes where it stopped and never merges twice.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from . import SITE_MATERIALS_URL
from .claims import load_index, material_status, ownership_conflict
from .docs_sync import CorpusFacts, SyncError, close_finished_claims, sync
from .hf import MergeConflict as HubConflict
from .hf import PullRequest
from .links import parse_links
from .materials import canonical
from .registry import Contributor, Registry, resolve_contributor
from .site_data import write_site_data

STEPS = ("merge", "manifest", "local", "docs", "card", "claims")
# Every file the docs step writes (site/data/material is a directory: one page per material);
# anything else dirty in the checkout is not ours to touch.
DOCS_PATHS = ("CHANGELOG.md", "data/contributions.json", "README.md", "docs/CONTRIBUTING-TABLES.md",
              "docs/COOPERATIVE-TABLEBASE.md", "docs/hf-dataset-card.md", "site/data/materials.json",
              "site/data/corpus.json", "site/data/stats.json", ".all-contributorsrc", "site/data/material",
              "site/data/index.json", "site/data/themes.json")
_NO_CHECKS = "no checks reported"
MAINTAINER = "maintainer"   # producer key of the published tables that are not contributions
_NO_GLOBAL = {"GIT_CONFIG_GLOBAL": "/dev/null"}   # the global config rewrites HTTPS to SSH
_GH_CREDENTIALS = "credential.helper=!gh auth git-credential"


def under(path: str, paths: tuple[str, ...] = DOCS_PATHS) -> bool:
    """True if `path` is one of `paths` or lies inside one of them (a directory entry)."""
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in paths)


def build_material_pages(materials: list[str], *, checkout: Path, tables: Path, binary: str,
                         runner=subprocess.run) -> None:
    """Mine the site's page data for `materials` (site/data/material/<M>.json, merged into
    index.json and themes.json). Output is not captured: one line per material."""
    cmd = [sys.executable, str(checkout / "tools" / "build_problems.py"), "--tables", str(tables),
           "--binary", binary, "--out", str(checkout / "site" / "data")]
    for m in materials:
        cmd += ["--material", m]
    runner(cmd, cwd=checkout, check=True)
    missing = [m for m in materials if not (checkout / "site" / "data" / "material" / f"{m}.json").exists()]
    if missing:  # build_problems exits 0 when it skips a material
        raise RuntimeError(f"no page built for {', '.join(missing)}; build_problems skipped it — check "
                           "that the table and sidecar are in --tables and done in materials.json")


def manifest_from_hub(hub, generator_version: str) -> dict:
    files = {}
    for path, meta in sorted(hub.main_files().items()):
        if not path.endswith((".hm", ".stats.json")):
            continue
        sha = meta.sha256 or hashlib.sha256(hub.read_bytes(path)).hexdigest()
        files[path] = {"sha256": sha, "size": meta.size}
    return {"schema": 1, "generator_version": generator_version, "files": files}


def add_changelog_data(text: str, line: str) -> str:
    m = re.search(r"^## \[Unreleased\]\n", text, re.M)
    if not m:
        raise ValueError("CHANGELOG.md has no '## [Unreleased]' section")
    nxt = re.search(r"^## \[", text[m.end():], re.M)
    end = m.end() + (nxt.start() if nxt else len(text) - m.end())
    section = text[m.end():end]
    if "### Data\n" in section:
        i = m.end() + section.index("### Data\n") + len("### Data\n")
        return text[:i] + line + "\n" + text[i:]
    return text[:m.end()] + "\n### Data\n" + line + "\n" + text[m.end():]


class MergeConflict(Exception):
    """The docs PR cannot be merged: main changed underneath it."""


class Git:
    """git and gh as the maintainer runs them (see Global Constraints: pushes
    bypass the global config that rewrites HTTPS to SSH)."""

    def __init__(self, checkout: Path, runner=subprocess.run, sleep=time.sleep):
        self.cwd = checkout
        self._runner = runner
        self._sleep = sleep

    def _run(self, *args: str, env: dict | None = None, check: bool = True, text: bool = True):
        return self._runner(list(args), cwd=self.cwd, check=check, capture_output=True, text=text,
                            # English messages: accept matches "remote ref does not exist" and friends,
                            # which a German locale translates
                            env={**os.environ, "LC_ALL": "C", "LANGUAGE": "C", **(env or {})})

    def _out(self, *args: str, env: dict | None = None) -> str:
        return self._run(*args, env=env).stdout.strip()

    def clean(self) -> bool:
        return self._out("git", "status", "--porcelain") == ""

    def dirty_paths(self) -> list[str]:
        return [line[3:].strip().strip('"') for line in  # -uall: files, not an untracked directory
                self._run("git", "status", "--porcelain", "--no-renames", "-uall").stdout.splitlines()
                if line.strip()]

    def current(self) -> str:
        return self._out("git", "rev-parse", "--abbrev-ref", "HEAD")

    def reset_to_origin_main(self, branch: str, paths: tuple[str, ...] = DOCS_PATHS) -> None:
        """A fresh branch from origin/main. Only `paths` (what accept generates; files or
        directories) are restored to HEAD, in index and worktree, or removed if not in HEAD:
        nothing else is touched. Files are compared one by one, so a directory entry keeps
        its committed files and loses only what accept added to it."""
        in_head = set(self._out("git", "ls-tree", "-r", "--name-only", "HEAD", "--", *paths).splitlines())
        if in_head:
            self._run("git", "restore", "--staged", "--worktree", "--source=HEAD", "--", *sorted(in_head))
        staged_new = set(self._out("git", "ls-files", "--", *paths).splitlines()) - in_head
        if staged_new:  # added to the index by a failed attempt, not in HEAD
            self._run("git", "rm", "-f", "-q", "--", *sorted(staged_new))
        self._run("git", "clean", "-fd", "--", *paths)
        self._run("git", "fetch", "origin", "main", env=_NO_GLOBAL)
        self._run("git", "switch", "-C", branch, "origin/main")

    def main_file(self, path: str) -> bytes:
        """`path` as origin/main has it right now (fetched first), byte for byte."""
        self._run("git", "fetch", "origin", "main", env=_NO_GLOBAL)
        return self._run("git", "show", f"origin/main:{path}", text=False).stdout

    def commit_all(self, message: str) -> None:
        self._run("git", "add", "-A")
        self._run("git", "commit", "-m", message)

    def push(self, branch: str) -> None:
        self._run("git", "-c", "credential.helper=", "-c", _GH_CREDENTIALS,
                  "push", "--force-with-lease", "-u", "origin", branch, env=_NO_GLOBAL)

    def open_pr(self, title: str, body: str, branch: str | None = None) -> str:
        if branch:
            existing = json.loads(self._out("gh", "pr", "list", "--head", branch, "--state", "open",
                                            "--json", "url") or "[]")
            if existing:
                return existing[0]["url"]
        args = ["gh", "pr", "create", "--base", "main", "--title", title, "--body", body]
        if branch:
            args += ["--head", branch]
        return self._out(*args)

    def _view(self, url: str) -> dict:
        """The PR's state and mergeability; GitHub computes the latter lazily (UNKNOWN)."""
        for _ in range(6):
            v = json.loads(self._out("gh", "pr", "view", url, "--json", "state,mergeable"))
            if v.get("state") == "MERGED" or v.get("mergeable") != "UNKNOWN":
                return v
            self._sleep(5)
        return v

    def _conflicting(self, url: str) -> bool:
        return self._view(url).get("mergeable") == "CONFLICTING"

    def wait_and_merge(self, url: str, branch: str) -> None:
        """Wait for the checks, squash-merge, then delete the branch on origin and here.
        Run from the maintainer's own branch: never merge while the data branch is checked out.
        Raises MergeConflict when the PR cannot be merged because main has moved on."""
        v = self._view(url)
        if v.get("state") != "MERGED":
            if v.get("mergeable") == "CONFLICTING":
                raise MergeConflict(url)
            for _ in range(12):  # right after `pr create`, GitHub has not registered the checks yet
                r = self._run("gh", "pr", "checks", url, check=False)
                if _NO_CHECKS not in (r.stdout + r.stderr).lower():
                    break
                self._sleep(10)
            else:
                if self._conflicting(url):  # CI does not run on a PR that conflicts
                    raise MergeConflict(url)
                raise RuntimeError(f"no checks were reported for {url} after 2 minutes")
            # not captured: the maintainer watches CI progress in the terminal
            self._runner(["gh", "pr", "checks", url, "--watch", "--fail-fast"], cwd=self.cwd, check=True)
            try:
                self._run("gh", "pr", "merge", url, "--squash", env=_NO_GLOBAL)
            except subprocess.CalledProcessError as exc:
                if self._conflicting(url):
                    raise MergeConflict(url) from exc
                raise
        self._delete_branch(branch)

    def close_pr(self, url: str) -> None:
        self._run("gh", "pr", "close", url, "--comment",
                  "Conflicts with main; `helpmate-tables accept` is redoing this from the current main.")

    def _delete_branch(self, branch: str) -> None:
        for args, gone in ((("git", "-c", "credential.helper=", "-c", _GH_CREDENTIALS,
                             "push", "origin", "--delete", branch), "remote ref does not exist"),
                           (("git", "branch", "-D", branch), "not found")):
            r = self._run(*args, env=_NO_GLOBAL, check=False)
            if r.returncode != 0 and gone not in r.stderr:
                raise subprocess.CalledProcessError(r.returncode, list(args), r.stdout, r.stderr)

    def back(self, ref: str) -> None:
        self._run("git", "switch", ref)


def _statistics(hub, git, tables: Path) -> dict[str, bytes] | str:
    """The Parquet statistics for the card commit, or why they are skipped. Never raises
    for an incomplete corpus or a missing pyarrow: statistics must not fail an accept."""
    from .corpus_stats import collect, completeness, parquet_files, require_pyarrow
    try:
        require_pyarrow()
    except ImportError as exc:
        return str(exc)
    ts = collect(tables)
    missing, extra = completeness(ts, hub.fetch_manifest())
    if missing or extra:
        return (f"{len(missing)} tables missing locally, {len(extra)} not published "
                f"({', '.join((missing + extra)[:5])})")
    reg = Registry(Path("data/contributions.json"), json.loads(git.main_file("data/contributions.json")))
    return parquet_files(ts, reg)


def _err(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 2


def _copy_comment(ref: str, head: str, already: bool) -> str:
    if already:  # every file was on main already: huggingface_hub made no commit
        return (f"Already on main as of {ref} (copied from this PR's verified head {head}, byte for "
                "byte; the only conflict was `.gitattributes`, Hub bookkeeping). Thank you!")
    return (f"Merged as {ref}: the only conflict was `.gitattributes` (Hub bookkeeping, one LFS "
            f"line per table). The files are copied server-side from this PR's verified head {head}, "
            "byte for byte. Thank you!")


def _missing_staged(hub, names: list[str], files_dir: Path, head: str | None) -> list[str]:
    """Those of `names` (table files of the PR at `head`) that are not staged locally at
    the size the PR has."""
    if not names:
        return []
    sizes = hub.file_sizes(names, head)
    return [f for f in names
            if not (files_dir / f).exists() or (files_dir / f).stat().st_size != sizes.get(f)]


@dataclass
class Decision:
    """What accept does with one material of the run (spec section 3)."""
    kind: Literal["new", "reproduction", "held", "conflict"]
    publish_from: int | None      # the PR whose file is published, None if nothing is
    producers: list[int]          # the PRs credited as producers, in delivery order
    held_for: int | None          # the claim a held material waits for
    reason: str


def _nums(ns: list[int]) -> str:
    out = [f"#{n}" for n in ns]
    return out[0] if len(out) == 1 else ", ".join(out[:-1]) + " and " + out[-1]


def _payload(reports: dict, n: int, m: str) -> str | None:
    return ((reports.get(n) or {}).get("tables") or {}).get(m, {}).get("payload_sha256")


def decide(prs, reports: dict, manifest: dict, hashes, index, logins: dict, release) -> dict[str, Decision]:
    """One decision per material delivered by `prs` (taken in ascending PR number = delivery
    order). `reports`: PR -> its verification report; `manifest`: the published manifest;
    `hashes.get(m)`: the published table's payload hash; `index`: the open claims;
    `logins`: PR -> its contributor's GitHub login (or None); `release`: materials whose
    claim the maintainer overrides. Pure apart from `hashes.get`."""
    published = manifest.get("files", {})
    deliveries: dict[str, list[int]] = {}
    for pr in sorted(prs, key=lambda p: p.num):
        for m in pr.materials:
            deliveries.setdefault(m, []).append(pr.num)
    out = {}
    for m, ns in deliveries.items():
        pays = {n: _payload(reports, n, m) for n in ns}
        is_published = f"{m}.hm" in published
        if is_published or len(ns) > 1:
            missing = [n for n in ns if not pays[n]]
            if missing:
                out[m] = Decision("conflict", None, [], None,
                                  f"the report of HF PR {_nums(missing)} has no payload hash to compare "
                                  "(verified by an older helpmate-tables); run verify --pr N again")
                continue
        if is_published:
            ref = hashes.get(m)
            differ = [n for n in ns if pays[n] != ref]
            out[m] = (Decision("conflict", None, [], None,
                               f"content differs from the published table in HF PR {_nums(differ)}")
                      if differ else
                      Decision("reproduction", None, list(ns), None, "identical to the published table"))
            continue
        if len(set(pays.values())) > 1:
            out[m] = Decision("conflict", None, [], None, f"content differs between HF PRs {_nums(ns)}")
            continue
        claim = index.claim_for(m) if index is not None else None
        holder = claim.author.lower() if claim else None
        by_holder = [n for n in ns if holder and (logins.get(n) or "").lower() == holder]
        if claim is not None and not by_holder and m not in release:
            out[m] = Decision("held", None, [], claim.issue,
                              f"held for claim #{claim.issue} by @{claim.author}")
            continue
        src = by_holder[0] if by_holder else ns[0]
        why = ("the claim holder's delivery" if by_holder else
               "released by the maintainer" if claim is not None else "the earliest delivery")
        out[m] = Decision("new", src, list(ns), None, f"published from HF PR #{src}: {why}")
    return out


def _identity_claim(pr, index, reg: Registry):
    """The claim that speaks for the PR's identity: the one it names; else the one by its own
    GitHub login (description or registry) that covers its materials; with no login at all,
    the first claim on its material unless that claim's form names another HF user.
    Someone else's claim never speaks for a PR whose login is known."""
    num, login = parse_links(pr.description)
    if num is not None:
        return next((c for c in index.claims if c.issue == num), None)
    if login is None:
        known = reg.by_hf(pr.author)
        login = known.github if known else None
    if login is not None:
        return next((c for c in index.claims if c.author.lower() == login.lower()
                     and set(c.materials) & set(pr.materials)), None)
    first = index.claim_for(pr.materials[0]) if pr.materials else None
    if first is not None and (first.hf is None or first.hf.lower() == pr.author.lower()):
        return first
    return None


def _notes(credited: list[str], held: list[str], decisions: dict[str, Decision],
           own: list[str] | None = None) -> list[str]:
    """`own`: materials this PR's delivery is already in the dataset and credited for (an
    earlier run of a PR that stayed open for held material)."""
    out = []
    if own:
        out.append(f"{', '.join(own)}: already in the dataset from this PR.")
    if credited:
        out.append(f"{', '.join(credited)}: identical to the published table — credited as co-producer.")
    for m in held:
        out.append(f"{m}: {decisions[m].reason}; it will be published when the claim holder delivers "
                   "or releases it.")
    if held:
        out.append("This PR stays open for the held material.")
    return out


def _partial_comment(ref: str, head: str, already: bool, published: list[str], notes: list[str]) -> str:
    mats = ", ".join(published)
    first = (f"{mats}: already on main as of {ref} (copied from this PR's verified head {head}, byte "
             "for byte)." if already else
             f"{mats}: merged as {ref}, copied server-side from this PR's verified head {head}, byte "
             "for byte.")
    return "\n\n".join([first, *notes, "Thank you!"])


def _own_deliveries(regs: list[Registry], pulls: dict[int, PullRequest]) -> dict[str, list[str]]:
    """PR -> its materials that a registry already credits to this very PR (published from it,
    or listed among the producers with its number): a rerun of a PR that stayed open for held
    material must not credit it again for its own file. `regs`: origin/main's registry (the
    earlier run's docs PR landed there) and the checkout's."""
    out = {}
    for n, pr in pulls.items():
        out[str(n)] = [m for m in pr.materials if any(
            (entry := reg.tables.get(m)) is not None and (entry.get("published_from") == n or any(
                p.get("hf_pr") == n for p in entry.get("producers", [])))
            for reg in regs)]
    return out


def _manifest_key(manifest: dict, materials) -> str:
    """A hash of what the manifest publishes for `materials`: decisions taken under another
    manifest (another run published one of them meanwhile) are taken again."""
    files = manifest.get("files", {})
    rows = sorted((m, (files.get(f"{m}.hm") or {}).get("sha256")) for m in set(materials))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def _decisions(state: dict) -> dict[str, Decision] | None:
    raw = state.get("decisions")
    return None if raw is None else {m: Decision(**d) for m, d in raw.items()}


def accept(prs: list[int], *, hub, gh, git, checkout: Path, tables: Path, staging: Path,
           contributor: str | None, today: str, binary: str | None,
           build_pages=subprocess.run, release: list[str] | None = None,
           no_pages: bool = False) -> int:
    """`binary`: the helpmate binary the material pages are mined with; `build_pages`
    runs tools/build_problems.py (subprocess.run's signature); `release`: materials
    published even though someone else's claim holds them (accept --release); `no_pages`: skip the page build
    (helpmate-tables pages builds them later)."""
    if not binary or not Path(binary).is_file():
        return _err(f"no helpmate binary {'at ' + binary if binary else 'on PATH'}: "
                    "the material pages need one; pass --binary PATH")
    if contributor and len(prs) > 1:
        return _err("--contributor applies to every PR of a run; accept the PR that needs it on "
                    "its own with --contributor LOGIN")
    release = list(release or [])
    not_materials = [m for m in release if canonical(m) != m]
    if not_materials:
        return _err(f"--release takes material names, not {', '.join(not_materials)}")
    state_path = staging / f"accept-{'-'.join(map(str, sorted(prs)))}.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {"done": []}

    def save() -> None:
        state_path.write_text(json.dumps(state, indent=2))

    def mark(step: str, **extra) -> None:
        state["done"].append(step)
        state.update(extra)
        save()

    def sub(name: str) -> bool:
        """True if this sub-step of the docs step is recorded; call sub_done to record it."""
        return name in state.get("sub", [])

    def sub_done(name: str) -> None:
        state.setdefault("sub", []).append(name)
        save()

    reg_path = checkout / "data" / "contributions.json"
    # What each PR contained, as validated: after the merge the Hub is never asked again.
    stored: dict[str, dict] = state.setdefault("pulls", {})

    def fix(n: int) -> str:
        """How to name the PR's contributor: --contributor holds for the whole run."""
        return ("pass --contributor LOGIN" if len(prs) == 1 else
                f"accept PR #{n} on its own with --contributor LOGIN")

    if "merge" not in state["done"]:
        index = load_index(gh)
        if not git.clean():
            return _err(f"{checkout} has uncommitted changes")
        reg = Registry.load(reg_path)
        manifest = hub.fetch_manifest()
        try:  # sync needs every published sidecar locally; find out before merging
            CorpusFacts.from_manifest(manifest, tables)
        except SyncError as exc:
            return _err(str(exc))
        people: dict[int, dict[str, Any]] = {int(k): v for k, v in state.get("people", {}).items()}
        seen_keys: dict[str, str | None] = {}
        merged = state.setdefault("merged", [])
        # PR -> {"ref": copy commit URL or main's sha, "already": no commit was needed} (merge_by_copy);
        # a copy of only the published files adds "partial": True and "close": False if the PR stays open
        copied: dict[str, dict | str] = state.setdefault("copied", {})
        for n in prs:
            if n in merged or str(n) in copied:  # merged by an earlier, interrupted run; validated then
                seen_keys[people[n]["key"]] = people[n]["github"]
                continue
            pr = hub.pull_request(n)
            rep_path = staging / f"pr-{n}" / "report.json"
            if not rep_path.exists():
                return _err(f"PR #{n} has no verification report; run verify --pr {n}")
            rep = json.loads(rep_path.read_text())
            if rep["result"] != "pass":
                return _err(f"PR #{n}: the last verification failed")
            if pr.status != "open":
                return _err(f"PR #{n} is {pr.status}")
            if rep.get("head") != pr.head:
                return _err(f"PR #{n} changed after verification (verified {rep.get('head')}, "
                            f"now {pr.head}); run verify --pr {n} again")
            claim = _identity_claim(pr, index, reg)
            why = ownership_conflict(pr, claim, reg) if claim and not contributor else None
            if why:
                return _err(f"PR #{n}: {why} (the claims bot shows this as a conflict); {fix(n)}")
            who = resolve_contributor(reg, pr, claim, contributor)
            if who is None:
                return _err(f"PR #{n} by HF user {pr.author}: no GitHub identity found; {fix(n)}")
            known = reg.contributors.get(who.key)
            other = known.github if known else seen_keys.get(who.key)
            if (known or who.key in seen_keys) and (other or "").lower() != (who.github or "").lower():
                return _err(f"PR #{n}: registry key {who.key!r} already belongs to GitHub user "
                            f"{other!r}, not {who.github!r}; {fix(n)} with the right login "
                            "or fix data/contributions.json")
            seen_keys[who.key] = who.github
            # Anonymity is per person and permanent: an anonymous claim form by this person
            # hides them from now on, even if they were registered under their name before.
            asks_anonymity = bool(claim and claim.anonymous and who.github
                                  and claim.author.lower() == who.github.lower())
            people[n] = {"key": who.key, "github": who.github, "hf": who.hf,
                         "display": who.display, "anonymous": who.anonymous or asks_anonymity,
                         "claim": claim.issue if claim else None}
            stored[str(n)] = {k: v for k, v in asdict(pr).items() if k != "num"}
        state["people"] = {str(k): v for k, v in people.items()}
        save()
        # The preflight: every material is decided before anything is written to the Hub.
        decisions = _decisions(state)
        heads: dict[str, str | None] = {str(n): stored[str(n)]["head"] for n in prs}
        heads["manifest"] = _manifest_key(manifest, [m for n in prs
                                                     for m in PullRequest(n, **stored[str(n)]).materials])
        if decisions is not None and (release or state.get("decision_heads") != heads):
            # a PR was revised (and verified again) since the decisions, another run published
            # one of the materials, or the maintainer overrides a claim now: decide again
            decisions = None
            state.pop("decisions", None)
        if decisions is None:
            from .checks import MissingPublished
            from .verify import PublishedHashes
            reports = {}
            for n in prs:
                try:
                    reports[n] = json.loads((staging / f"pr-{n}" / "report.json").read_text())
                except (OSError, ValueError):
                    reports[n] = {}
            try:
                decisions = decide([PullRequest(n, **stored[str(n)]) for n in prs], reports, manifest,
                                   PublishedHashes(tables, manifest.get("files", {})), index,
                                   {n: people[n]["github"] for n in prs}, set(release))
            except MissingPublished as exc:
                return _err(f"{exc.material} is published but {exc.material}.hm is missing from "
                            f"{tables}; point --tables at a complete corpus")
            conflicts = [f"{m}: {d.reason}" for m, d in sorted(decisions.items()) if d.kind == "conflict"]
            if conflicts:
                return _err("; ".join(conflicts) + "; nothing merged")
            on_main = Registry(reg_path, json.loads(git.main_file("data/contributions.json")))
            state["own"] = _own_deliveries([on_main, reg],
                                           {n: PullRequest(n, **stored[str(n)]) for n in prs})
            for m in release:
                c = index.claim_for(m)
                print(f"--release {m}: " + (f"overrides claim #{c.issue} by {c.author}" if c else
                                            "not claimed by anyone, nothing to override"), file=sys.stderr)
        for n in prs:
            if n in merged or str(n) in copied:
                continue
            pr = PullRequest(n, **stored[str(n)])
            names = [f for m in pr.materials if decisions[m].publish_from == n
                     for f in (f"{m}.hm", f"{m}.stats.json") if f in pr.files]
            missing = _missing_staged(hub, names, staging / f"pr-{n}" / "files", pr.head)
            if missing:
                return _err(f"PR #{n}: staged files missing or of the wrong size: {', '.join(missing)}; "
                            f"run verify --pr {n} again")
        if "decisions" not in state:
            state["decisions"] = {m: asdict(d) for m, d in decisions.items()}
            state["decision_heads"] = heads
            save()
        decided: dict[str, Decision] = decisions
        owned: dict[str, list[str]] = state.get("own", {})

        def plan(n: int) -> tuple[PullRequest, list[str], list[str], list[str], list[str]]:
            """(the PR, materials published from it, held, credited as co-producer, already
            credited to this PR by an earlier run)"""
            pr = PullRequest(n, **stored[str(n)])
            own = owned.get(str(n), [])
            pub = [m for m in pr.materials if decided[m].publish_from == n]
            held = [m for m in pr.materials if decided[m].kind == "held"]
            return pr, pub, held, [m for m in pr.materials if m not in pub + held + own], own

        # PRs that publish go first: no "credited as co-producer" before the published file landed
        for n in sorted(prs, key=lambda n: (not plan(n)[1], n)):
            if n in merged:
                continue
            pr, pub, held, credited, own = plan(n)
            verified = stored[str(n)]["head"]
            p = people[n]
            credit = "an anonymous contributor" if p.get("anonymous") else p["display"]
            notes = _notes(credited, held, decided, own)

            def record(ref: str, already: bool, n: int = n, partial: bool = True,
                       close: bool = not held) -> None:
                copied[str(n)] = ({"ref": ref, "already": already, "partial": True, "close": close}
                                  if partial else {"ref": ref, "already": already})
                save()

            if str(n) in copied:  # copied by an interrupted run: only the close or comment may be missing
                prior = copied[str(n)]
                if isinstance(prior, str):  # state written before {ref, already}: a commit URL
                    prior = {"ref": prior, "already": False}
                text = (_partial_comment(prior["ref"], verified, prior["already"], pub, notes)
                        if prior.get("partial") else _copy_comment(prior["ref"], verified, prior["already"]))
                if not prior.get("close", True):
                    hub.comment(n, text)
                elif hub.pr_status(n) == "open":
                    hub.close_pr(n, text)
            else:
                now = hub.pr_head(n)
                if now != verified:  # a push between validation and this merge
                    return _err(f"PR #{n} changed after verification (verified {verified}, "
                                f"now {now}); run verify --pr {n} again")
                if pub and not held and not credited and not own:  # everything new, published from here
                    try:
                        hub.merge(n)
                    except HubConflict as exc:
                        if not exc.files or not set(exc.files) <= {".gitattributes"}:
                            return _err(f"PR #{n} conflicts with main in {', '.join(exc.files)}; "
                                        "resolve that on the Hub, then rerun accept")
                        hub.merge_by_copy(n, verified, pr.files,
                                          message=f"Add {', '.join(pr.materials)} from dataset PR #{n} by {credit}",
                                          comment=lambda ref, already, head=verified:
                                              _copy_comment(ref, head, already),
                                          on_commit=lambda ref, already, n=n: record(ref, already, n, False))
                elif pub:
                    copy_files = [f for m in pub for f in (f"{m}.hm", f"{m}.stats.json") if f in pr.files]
                    hub.merge_by_copy(n, verified, copy_files,
                                      message=f"Add {', '.join(pub)} from dataset PR #{n} by {credit}",
                                      comment=lambda ref, already, head=verified, pub=pub, notes=notes:
                                          _partial_comment(ref, head, already, pub, notes),
                                      close=not held, on_commit=record)
                elif held:
                    hub.comment(n, "\n\n".join([*notes, "Thank you!"]))
                else:
                    hub.close_pr(n, "\n\n".join([*notes, "Thank you!"]))
            merged.append(n)
            save()
        mark("merge")

    people = {int(k): v for k, v in state["people"].items()}
    pulls = {n: PullRequest(n, **stored[str(n)]) for n in prs}
    # A state from before decisions finished its merge step under the old rules: all new.
    decisions = _decisions(state) or {m: Decision("new", n, [n], None, "")
                                      for n, pr in pulls.items() for m in pr.materials}
    published = {n: [m for m in pr.materials if decisions[m].publish_from == n] for n, pr in pulls.items()}
    # a PR's own earlier delivery (published from it or credited) is not recorded again
    own = state.get("own", {})
    recorded = {n: [m for m in pr.materials if decisions[m].kind in ("new", "reproduction")
                    and m not in own.get(str(n), [])]
                for n, pr in pulls.items()}
    mats = [m for n in prs for m in published[n]]
    if not any(recorded.values()):  # everything held: nothing changed on main or in the credits
        state_path.unlink()
        return 0

    if "manifest" not in state["done"]:
        if mats:  # reproductions alone change no file on main
            old = hub.fetch_manifest()
            man = manifest_from_hub(hub, old.get("generator_version", "unknown"))
            hub.commit({"manifest.json": json.dumps(man, indent=2, sort_keys=True).encode()},
                       f"Manifest after merging PR(s) {', '.join(f'#{n}' for n in prs)}")
        mark("manifest")

    if "local" not in state["done"]:
        for n in prs:  # only the published files; the other deliveries stay in staging
            for m in published[n]:
                for f in (f"{m}.hm", f"{m}.stats.json"):
                    src = staging / f"pr-{n}" / "files" / f
                    if src.exists():
                        shutil.move(str(src), tables / f)
        mark("local")

    if "docs" not in state["done"]:
        branch = "data/accept-" + "-".join(map(str, sorted(prs)))
        reproduced = sorted({m for ms in recorded.values() for m in ms if len(decisions[m].producers) > 1
                             or decisions[m].kind == "reproduction"})
        title = (f"Data: {len(mats)} table(s)" + (f", {len(reproduced)} reproduction(s)" if reproduced else "")
                 + f" from dataset PR(s) {', '.join(f'#{n}' for n in prs)}")

        def name_of(reg: Registry, key: str) -> str:
            c = reg.contributors.get(key)
            return key if c is None else "an anonymous contributor" if c.anonymous else c.display

        def update_registry(reg: Registry) -> list[str]:
            """Credit this run's deliveries; returns the docs lines for what changed."""
            before = {m: reg.producers_of(m) for ms in recorded.values() for m in ms}
            for n, pr in pulls.items():
                p = people[n]
                if not recorded[n]:
                    continue
                if p["key"] not in reg.contributors:
                    reg.add_contributor(Contributor(p["key"], p["github"], p["hf"], p["display"],
                                                    anonymous=p.get("anonymous", False)))
                elif p.get("anonymous"):  # never set back to False automatically
                    reg.contributors[p["key"]].anonymous = True
                rep = json.loads((staging / f"pr-{n}" / "report.json").read_text())
                for m in published[n]:
                    sc = json.loads((tables / f"{m}.stats.json").read_text())
                    reg.record_table(m, contributor=p["key"], hf_pr=n, claim=p["claim"],
                                     merged=today, generator_version=sc.get("generator_version", ""),
                                     verification={"tool": rep.get("tool"), "head": rep.get("head"),
                                                   "date": rep.get("date"),
                                                   "samples": rep.get("samples"),
                                                   "seed": rep.get("seed"), "result": rep["result"]})
            for n in prs:  # after record_table: a co-delivery may come before the published one
                for m in recorded[n]:
                    if m in published[n]:
                        continue
                    if m not in reg.tables:  # one of the maintainer's own tables: credit both
                        try:
                            gv = json.loads((tables / f"{m}.stats.json").read_text()).get(
                                "generator_version", "")
                        except (OSError, ValueError):
                            gv = ""
                        reg.tables[m] = {"contributor": MAINTAINER, "hf_pr": None, "claim": None,
                                         "merged": None, "generator_version": gv, "verification": None,
                                         "producers": [{"contributor": MAINTAINER, "hf_pr": None,
                                                        "date": None, "generator_version": gv}],
                                         "published_from": None}
                    sc_path = staging / f"pr-{n}" / "files" / f"{m}.stats.json"
                    try:
                        gv = json.loads(sc_path.read_text()).get("generator_version", "")
                    except (OSError, ValueError):
                        gv = ""
                    reg.add_producer(m, contributor=people[n]["key"], hf_pr=n, date=today,
                                     generator_version=gv)
            lines = []
            for n in prs:
                if published[n]:
                    p = people[n]
                    credited = "an anonymous contributor" if p.get("anonymous") else p["display"]
                    lines.append(f"- {', '.join(published[n])} contributed by {credited} "
                                 f"(dataset PR #{n}" + (f", claim #{p['claim']}" if p["claim"] else "") + ").")
            for m in sorted(before):
                now = reg.producers_of(m)
                if len(now) >= 2 and now != before[m]:
                    names = [name_of(reg, k) for k in now]
                    lines.append(f"- {m} (independently reproduced by "
                                 f"{', '.join(names[:-1])} and {names[-1]}).")
            return lines

        def attempt() -> int | None:
            if not sub("committed"):
                outside = [d for d in git.dirty_paths() if not under(d)]
                if outside:
                    return _err(f"{checkout} has uncommitted changes outside what accept writes: "
                                f"{', '.join(outside)}")
                if not state.get("docs_started"):
                    if not git.clean():
                        return _err(f"{checkout} has uncommitted changes; commit or stash them first")
                    state["docs_started"] = True  # from here on, leftovers in DOCS_PATHS are ours
                    save()
                if "original" not in state:  # first attempt only: later ones may start on the data branch
                    state["original"] = git.current()
                    save()
                git.reset_to_origin_main(branch, DOCS_PATHS)
                reg = Registry.load(reg_path)
                lines = update_registry(reg)
                if not lines:  # every delivery was credited already (a rerun): nothing to commit
                    git.back(state["original"])
                    state["docs_empty"] = True
                    save()
                    return None
                reg.save()
                cl = checkout / "CHANGELOG.md"
                text = cl.read_text()
                for line in lines:
                    text = add_changelog_data(text, line)
                cl.write_text(text)
                sync(checkout, hub, gh, reg, tables, close_claims=False)
                # After sync: build_problems skips a material materials.json does not list as done.
                # A docs-PR conflict retry runs this again (minutes per six-piece table).
                if mats and not no_pages:
                    build_material_pages(mats, checkout=checkout, tables=tables, binary=binary,
                                         runner=build_pages)
                write_site_data(checkout / "site" / "data", tables)  # the page flags, now true
                trailers = sorted({f"Co-authored-by: {p['github']} <{gh.user_id(p['github'])}+"
                                   f"{p['github']}@users.noreply.github.com>"
                                   for n, p in people.items()
                                   if recorded.get(n) and p["github"]
                                   and not reg.contributors[p["key"]].anonymous})
                git.commit_all(title + "\n\n" + "\n".join(lines) + "\n\n" + "\n".join(trailers))
                state["lines"] = lines
                sub_done("committed")
            if "docs_pr" not in state:
                if not sub("pushed"):
                    git.push(branch)
                    sub_done("pushed")
                state["docs_pr"] = git.open_pr(title, "\n".join(state.get("lines", [])), branch)
                save()
            git.back(state.get("original", "main"))  # before the merge deletes the data branch
            if not sub("docs_merged"):
                git.wait_and_merge(state["docs_pr"], branch)
                sub_done("docs_merged")
            return None

        def conflicts_again(url: object) -> int:
            return _err(f"the docs PR {url} conflicts with main again; resolve it by hand "
                        "(or close it), then rerun accept")

        try:
            rc = attempt()
        except MergeConflict as first:
            if state.get("docs_retried"):
                return conflicts_again(first)
            print(f"the docs PR {first} conflicts with main; closing it and redoing the docs "
                  "from the current main (once)", file=sys.stderr)
            git.close_pr(state["docs_pr"])
            state["docs_retried"] = True  # at most one retry, across reruns too
            state["sub"] = []             # committed, pushed: all redone from origin/main
            del state["docs_pr"]
            save()
            try:
                rc = attempt()
            except MergeConflict as second:
                return conflicts_again(second)
        if rc is not None:
            return rc
        mark("docs")

    if state.get("docs_empty"):  # a rerun that credited nothing new: card and claims are as they were
        state["done"] += [s for s in ("card", "claims") if s not in state["done"]]
    if "card" not in state["done"]:  # only now: the public card must not credit a failed docs PR
        # main's card, not a copy from this run's docs step: a later accept run may have published a newer one
        card = git.main_file("docs/hf-dataset-card.md")
        files, note = {"README.md": card}, _statistics(hub, git, tables)
        if isinstance(note, dict):
            files.update(note)
            hub.commit(files, "Dataset card and statistics")
            from .stats_push import check
            problems = check(hub)
            if problems:
                return _err("statistics on the dataset do not match the manifest after the upload: "
                            + "; ".join(problems) + " — rerun this accept to retry")
            print(f"statistics uploaded: {len(note)} files", file=sys.stderr)
        else:
            hub.commit(files, "Dataset card: contributors and counts")
            print(f"statistics not uploaded: {note}; run helpmate-tables stats-push --tables DIR "
                  "after syncing", file=sys.stderr)
        mark("card")

    if "claims" not in state["done"]:
        for n, pr in pulls.items():
            c = people[n]["claim"]
            if c is not None and recorded[n] and n not in state.setdefault("commented", []):
                repro = [m for m in recorded[n] if decisions[m].kind == "reproduction"
                         or len(decisions[m].producers) > 1]
                gh.comment(c, f"Accepted: {', '.join(recorded[n])} ([HF PR #{n}]({pr.url})) — "
                              f"now in the dataset and credited on {SITE_MATERIALS_URL}. Thank you!"
                              + (f" {', '.join(repro)}: independently reproduced — credited to both."
                                 if repro else ""))
                state["commented"].append(n)
                save()
        reg = Registry.load(reg_path)
        done = {f[:-3] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}
        idx = load_index(gh)
        close_finished_claims(gh, idx, material_status(done, {}, idx, reg))
        mark("claims")
    state_path.unlink()
    return 0

def status(hub, gh, registry, staging: Path, checkout: Path) -> str:
    index = load_index(gh)
    rows = ["| HF PR | author | materials | claim | verification | |", "|---|---|---|---|---|---|"]
    for pr in hub.open_pull_requests():
        rep_path = staging / f"pr-{pr.num}" / "report.json"
        if rep_path.exists():
            rep = json.loads(rep_path.read_text())
            ver = rep["result"] + ("" if rep.get("head") == pr.head else " (stale: PR changed)")
        else:
            ver = "not verified"
        first = index.claim_for(pr.materials[0]) if pr.materials else None
        c = parse_links(pr.description)[0] or (first.issue if first else None)
        rows.append(f"| #{pr.num} | {pr.author} | {', '.join(pr.materials)} | "
                    f"{'#' + str(c) if c else '—'} | {ver} | |")
    try:
        last = subprocess.run(["git", "log", "-1", "--format=%cs", "--", "docs/DEEPEST.json"],
                              cwd=checkout, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        last = ""
    newer = sum(1 for t in registry.tables.values() if last and (t.get("merged") or "") > last)
    rows += ["", f"{newer} contributed table(s) merged since the last DEEPEST refresh ({last or '?'})."]
    return "\n".join(rows)

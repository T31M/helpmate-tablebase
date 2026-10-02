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
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import SITE_MATERIALS_URL
from .claims import load_index, material_status, ownership_conflict
from .docs_sync import CorpusFacts, SyncError, close_finished_claims, sync
from .hf import MergeConflict as HubConflict
from .hf import PullRequest
from .links import parse_links
from .registry import Contributor, Registry, resolve_contributor
from .site_data import write_site_data

STEPS = ("merge", "manifest", "local", "docs", "card", "claims")
# Every file the docs step writes (site/data/material is a directory: one page per material);
# anything else dirty in the checkout is not ours to touch.
DOCS_PATHS = ("CHANGELOG.md", "data/contributions.json", "README.md", "docs/CONTRIBUTING-TABLES.md",
              "docs/COOPERATIVE-TABLEBASE.md", "docs/hf-dataset-card.md", "site/data/materials.json",
              "site/data/corpus.json", ".all-contributorsrc", "site/data/material",
              "site/data/index.json", "site/data/themes.json")
_NO_CHECKS = "no checks reported"
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
                            env={**os.environ, **(env or {})})

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


def _missing_staged(hub, pr, files_dir: Path) -> list[str]:
    """Table files of the PR that are not staged locally at the size the PR has."""
    names = [f for f in pr.files if f.endswith((".hm", ".stats.json"))]
    sizes = hub.file_sizes(names, pr.head)
    return [f for f in names
            if not (files_dir / f).exists() or (files_dir / f).stat().st_size != sizes.get(f)]


def accept(prs: list[int], *, hub, gh, git, checkout: Path, tables: Path, staging: Path,
           contributor: str | None, today: str, binary: str | None,
           build_pages=subprocess.run) -> int:
    """`binary`: the helpmate binary the material pages are mined with; `build_pages`
    runs tools/build_problems.py (subprocess.run's signature)."""
    if not binary or not Path(binary).is_file():
        return _err(f"no helpmate binary {'at ' + binary if binary else 'on PATH'}: "
                    "the material pages need one; pass --binary PATH")
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
        published = manifest.get("files", {})
        people: dict[int, dict[str, Any]] = {int(k): v for k, v in state.get("people", {}).items()}
        seen_keys: dict[str, str | None] = {}
        merged = state.setdefault("merged", [])
        # PR -> {"ref": copy commit URL or main's sha, "already": no commit was needed} (merge_by_copy)
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
            already = [m for m in pr.materials if f"{m}.hm" in published]
            if already:
                return _err(f"PR #{n}: {', '.join(already)} already in the dataset")
            missing = _missing_staged(hub, pr, staging / f"pr-{n}" / "files")
            if missing:
                return _err(f"PR #{n}: staged files missing or of the wrong size: {', '.join(missing)}; "
                            f"run verify --pr {n} again")
            claim_no = parse_links(pr.description)[0]
            claim = next((c for c in index.claims if c.issue == claim_no), None) \
                or (index.claim_for(pr.materials[0]) if pr.materials else None)
            why = ownership_conflict(pr, claim, reg) if claim and not contributor else None
            if why:
                return _err(f"PR #{n}: {why} (the claims bot shows this as a conflict); "
                            "pass --contributor LOGIN")
            who = resolve_contributor(reg, pr, claim, contributor)
            if who is None:
                return _err(f"PR #{n} by HF user {pr.author}: no GitHub identity found; "
                            "pass --contributor LOGIN")
            known = reg.contributors.get(who.key)
            other = known.github if known else seen_keys.get(who.key)
            if (known or who.key in seen_keys) and (other or "").lower() != (who.github or "").lower():
                return _err(f"PR #{n}: registry key {who.key!r} already belongs to GitHub user "
                            f"{other!r}, not {who.github!r}; pass --contributor with the right login "
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
        owner: dict[str, int] = {}
        for n in prs:
            for m in PullRequest(n, **stored[str(n)]).materials:
                if m in owner:
                    return _err(f"{m} is in both PR #{owner[m]} and PR #{n}; accept one of them")
                owner[m] = n
        state["people"] = {str(k): v for k, v in people.items()}
        save()
        for n in prs:
            if n in merged:
                continue
            verified = stored[str(n)]["head"]
            if str(n) in copied:  # copied by an interrupted run: only the close may be missing
                if hub.pr_status(n) == "open":
                    c = copied[str(n)]
                    if isinstance(c, str):  # state written before {ref, already}: a commit URL
                        c = {"ref": c, "already": False}
                    hub.close_pr(n, _copy_comment(c["ref"], verified, c["already"]))
            else:
                now = hub.pr_head(n)
                if now != verified:  # a push between validation and this merge
                    return _err(f"PR #{n} changed after verification (verified {verified}, "
                                f"now {now}); run verify --pr {n} again")
                try:
                    hub.merge(n)
                except HubConflict as exc:
                    if not exc.files or not set(exc.files) <= {".gitattributes"}:
                        return _err(f"PR #{n} conflicts with main in {', '.join(exc.files)}; "
                                    "resolve that on the Hub, then rerun accept")
                    pr = PullRequest(n, **stored[str(n)])
                    p = people[n]
                    credit = "an anonymous contributor" if p.get("anonymous") else p["display"]

                    def record(ref: str, already: bool, n: int = n) -> None:
                        copied[str(n)] = {"ref": ref, "already": already}
                        save()
                    hub.merge_by_copy(n, verified, pr.files,
                                      message=f"Add {', '.join(pr.materials)} from dataset PR #{n} by {credit}",
                                      comment=lambda ref, already, head=verified:
                                          _copy_comment(ref, head, already),
                                      on_commit=record)
            merged.append(n)
            save()
        mark("merge")

    people = {int(k): v for k, v in state["people"].items()}
    pulls = {n: PullRequest(n, **stored[str(n)]) for n in prs}

    if "manifest" not in state["done"]:
        old = hub.fetch_manifest()
        man = manifest_from_hub(hub, old.get("generator_version", "unknown"))
        hub.commit({"manifest.json": json.dumps(man, indent=2, sort_keys=True).encode()},
                   f"Manifest after merging PR(s) {', '.join(f'#{n}' for n in prs)}")
        mark("manifest")

    if "local" not in state["done"]:
        for n, pr in pulls.items():
            for f in pr.files:
                src = staging / f"pr-{n}" / "files" / f
                if f.endswith((".hm", ".stats.json")) and src.exists():
                    shutil.move(str(src), tables / f)
        mark("local")

    if "docs" not in state["done"]:
        branch = "data/accept-" + "-".join(map(str, sorted(prs)))
        lines = []
        for n, pr in pulls.items():
            p = people[n]
            credited = "an anonymous contributor" if p.get("anonymous") else p["display"]
            lines.append(f"- {', '.join(pr.materials)} contributed by {credited} "
                         f"(dataset PR #{n}" + (f", claim #{p['claim']}" if p["claim"] else "") + ").")
        mats = [m for pr in pulls.values() for m in pr.materials]
        title = f"Data: {len(mats)} table(s) from dataset PR(s) {', '.join(f'#{n}' for n in prs)}"

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
                for n, pr in pulls.items():
                    p = people[n]
                    if p["key"] not in reg.contributors:
                        reg.add_contributor(Contributor(p["key"], p["github"], p["hf"], p["display"],
                                                        anonymous=p.get("anonymous", False)))
                    elif p.get("anonymous"):  # never set back to False automatically
                        reg.contributors[p["key"]].anonymous = True
                    rep = json.loads((staging / f"pr-{n}" / "report.json").read_text())
                    for m in pr.materials:
                        sc = json.loads((tables / f"{m}.stats.json").read_text())
                        reg.record_table(m, contributor=p["key"], hf_pr=n, claim=p["claim"],
                                         merged=today, generator_version=sc.get("generator_version", ""),
                                         verification={"tool": rep.get("tool"), "head": rep.get("head"),
                                                       "date": rep.get("date"),
                                                       "samples": rep.get("samples"),
                                                       "seed": rep.get("seed"), "result": rep["result"]})
                reg.save()
                cl = checkout / "CHANGELOG.md"
                text = cl.read_text()
                for line in lines:
                    text = add_changelog_data(text, line)
                cl.write_text(text)
                sync(checkout, hub, gh, reg, tables, close_claims=False)
                # After sync: build_problems skips a material materials.json does not list as done.
                # A docs-PR conflict retry runs this again (minutes per six-piece table).
                build_material_pages(mats, checkout=checkout, tables=tables, binary=binary,
                                     runner=build_pages)
                write_site_data(checkout / "site" / "data", tables)  # the page flags, now true
                trailers = sorted({f"Co-authored-by: {p['github']} <{gh.user_id(p['github'])}+"
                                   f"{p['github']}@users.noreply.github.com>"
                                   for p in people.values()
                                   if p["github"] and not reg.contributors[p["key"]].anonymous})
                git.commit_all(title + "\n\n" + "\n".join(lines) + "\n\n" + "\n".join(trailers))
                sub_done("committed")
            if "docs_pr" not in state:
                if not sub("pushed"):
                    git.push(branch)
                    sub_done("pushed")
                state["docs_pr"] = git.open_pr(title, "\n".join(lines), branch)
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

    if "card" not in state["done"]:  # only now: the public card must not credit a failed docs PR
        # main's card, not a copy from this run's docs step: a later accept run may have published a newer one
        hub.commit({"README.md": git.main_file("docs/hf-dataset-card.md")}, "Dataset card: contributors and counts")
        mark("card")

    if "claims" not in state["done"]:
        for n, pr in pulls.items():
            c = people[n]["claim"]
            if c is not None and n not in state.setdefault("commented", []):
                gh.comment(c, f"Accepted: {', '.join(pr.materials)} ([HF PR #{n}]({pr.url})) — "
                              f"now in the dataset and credited on {SITE_MATERIALS_URL}. Thank you!")
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
    newer = sum(1 for t in registry.tables.values() if last and t["merged"] > last)
    rows += ["", f"{newer} contributed table(s) merged since the last DEEPEST refresh ({last or '?'})."]
    return "\n".join(rows)

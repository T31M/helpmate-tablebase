"""verify: run V2-V7 on tables in a directory; V1 and downloading for PRs."""
from __future__ import annotations

import json
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .checks import (
    Check, TableReport, check_block_integrity, check_deepest, check_header, check_sidecar,
)
from .consistency import check_consistency
from .links import parse_links
from .materials import canonical
from .oracle import check_oracle
from .report import render_markdown, report_json
from .tablefile import read_header


@dataclass
class VerifyOptions:
    samples: int = 2000
    oracle_samples: int = 20
    oracle_plies: int = 3
    seed: int | None = None

    def resolved_seed(self) -> int:
        if self.seed is None:
            self.seed = secrets.randbelow(2**31)
        return self.seed

    def settings(self) -> dict:
        """What a report records about how it sampled, and when."""
        from datetime import datetime, timezone
        return {"samples": self.samples, "oracle_samples": self.oracle_samples,
                "oracle_plies": self.oracle_plies,
                "date": datetime.now(timezone.utc).date().isoformat()}


def verify_table(material: str, tables: Path, opts: VerifyOptions,
                 installed_version: str) -> TableReport:
    rep = TableReport(material)
    path = tables / f"{material}.hm"
    if not path.exists():
        rep.checks.append(Check("V2", "header and identity", "fail", f"{path} not found"))
        return rep
    for check in (lambda: check_header(path, installed_version),
                  lambda: check_block_integrity(path)):
        rep.checks.append(check())
        if not rep.passed:
            return rep  # later checks would only restate a structural failure
    rep.checks.append(check_sidecar(path))
    rep.checks.append(check_deepest(path, tables))
    if read_header(path).marker:
        rep.checks.append(Check("V6", "local consistency", "skip", "marker table"))
        rep.checks.append(Check("V7", "independent solver", "skip", "marker table"))
        return rep
    if not rep.passed:
        why = "an earlier check failed"
        rep.checks.append(Check("V6", "local consistency", "skip", why))
        rep.checks.append(Check("V7", "independent solver", "skip", why))
        return rep
    seed = opts.resolved_seed()
    try:
        sc = json.loads(path.with_name(f"{material}.stats.json").read_text())
        extra = list(sc.get("deepest", [])) + list(sc.get("deepest_unique", []))
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        why = f"sidecar unreadable: {exc}"
        rep.checks.append(Check("V6", "local consistency", "skip", why))
        rep.checks.append(Check("V7", "independent solver", "skip", why))
        return rep
    v6, fens = check_consistency(material, tables, opts.samples, seed, extra)
    rep.checks.append(v6)
    rep.checks.append(check_oracle(material, tables, samples=opts.oracle_samples,
                                   max_plies=opts.oracle_plies, seed=seed, others=fens))
    return rep


def check_pr_hygiene(pr, manifest_files: dict) -> Check:
    title = "only canonical table + sidecar pairs, nothing already published"
    problems: list[str] = []
    hms = {f[:-3] for f in pr.files if f.endswith(".hm")}
    sidecars = {f[: -len(".stats.json")] for f in pr.files if f.endswith(".stats.json")}
    for f in pr.files:
        if _unsafe(f):
            problems.append(f"unsafe file name {f!r}")
        elif not (f.endswith(".hm") or f.endswith(".stats.json")):
            problems.append(f"unexpected file {f}")
    for stem in sorted(hms | sidecars):
        if canonical(stem) != stem:
            problems.append(f"{stem} is not a canonical material name")
    for stem in sorted(hms ^ sidecars):
        problems.append(f"{stem}: table and sidecar must come together")
    if not hms:
        problems.append("no tables in this PR")
    for f in pr.deleted:
        problems.append(f"PR deletes {f}")
    for f in pr.files:
        if f in manifest_files:
            problems.append(f"{f} is already published "
                            f"(sha256 {manifest_files[f]['sha256'][:12]}…)")
    if problems:
        return Check("V1", title, "fail", "; ".join(problems))
    if parse_links(pr.description)[0] is None:
        return Check("V1", title, "warn", f"{len(hms)} table(s); no `Claim:` line in the "
                     "description (push with --claim N next time)")
    return Check("V1", title, "pass", f"{len(hms)} table(s)")


def _build_overlay(tables: Path, files_dir: Path, overlay: Path) -> None:
    if overlay.exists():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True)
    for src in (tables, files_dir):
        for p in src.iterdir():
            if p.name.endswith((".hm", ".stats.json")):
                link = overlay / p.name
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(p.resolve())


def _unsafe(name: str) -> bool:
    return "/" in name or "\\" in name or name.startswith(".")


def _staged_ok(have: Path, head: str | None, name: str, size: int) -> bool:
    marker = have / ".head"
    if head is not None and (not marker.exists() or marker.read_text() != head):
        return False
    return (have / name).exists() and (have / name).stat().st_size == size


def _stage(hub, pr, files_dir: Path) -> None:
    """Download what is missing or the wrong size, bound to the PR's head."""
    marker = files_dir / ".head"
    if pr.head is not None and files_dir.exists() and (
            not marker.exists() or marker.read_text() != pr.head):
        shutil.rmtree(files_dir)  # staged from another revision
    files_dir.mkdir(parents=True, exist_ok=True)
    if pr.head is not None:
        marker.write_text(pr.head)  # before downloading: an interrupted run resumes
    revision = pr.head or f"refs/pr/{pr.num}"
    sizes = hub.file_sizes(pr.files, revision)
    for f in pr.files:
        p = files_dir / f
        if not (p.exists() and p.stat().st_size == sizes[f]):
            p.unlink(missing_ok=True)
            hub.download(f, revision, files_dir)


def _gib(n: int) -> str:
    return f"{n / 2**30:.2f} GiB"


def verify_prs(a, opts: VerifyOptions, version: str, tool: str, hub_factory, gh_factory) -> int:
    from .cli import UsageError
    from .consistency import MissingSubtable
    from .github import GitHub
    from .hf import Hub

    hub = (hub_factory or Hub)(a.repo)
    tables = Path(a.tables).expanduser()
    staging = Path(a.staging).expanduser()
    staging.mkdir(parents=True, exist_ok=True)
    prs, total = [], 0
    for num in a.pr:
        pr = hub.pull_request(num)
        if pr.status != "open":
            print(f"error: PR #{num} is {pr.status}", file=sys.stderr)
            return 2
        sizes = hub.file_sizes([f for f in pr.files if not _unsafe(f)], pr.head or f"refs/pr/{num}")
        have = staging / f"pr-{num}" / "files"
        todo = {f: s for f, s in sizes.items() if not _staged_ok(have, pr.head, f, s)}
        if any(_unsafe(f) for f in pr.files):
            print(f"  unsafe file names in PR #{num}: nothing will be downloaded")
        total += sum(todo.values())
        print(f"PR #{num} by {pr.author}: {', '.join(pr.materials) or '(no tables)'}")
        for f, s in sorted(sizes.items()):
            print(f"  {f:28} {_gib(s):>12}{'' if f in todo else '  (already downloaded)'}")
        prs.append(pr)
    free = shutil.disk_usage(staging).free
    print(f"to download: {_gib(total)}; free in {staging}: {_gib(free)}")
    if total > free * 0.95:
        print("error: not enough disk space in the staging directory", file=sys.stderr)
        return 2
    if a.plan_only:
        return 0
    if total and not a.yes and input(f"download {_gib(total)}? [y/N] ").strip().lower() != "y":
        return 2
    manifest_files = hub.fetch_manifest().get("files", {})
    gh = None if a.no_post else (gh_factory or GitHub)(a.github_repo)
    rc = 0
    for pr in prs:
        d = staging / f"pr-{pr.num}"
        files_dir = d / "files"
        d.mkdir(parents=True, exist_ok=True)
        v1 = check_pr_hygiene(pr, manifest_files)
        reports: list = []
        try:
            if not any(_unsafe(f) for f in pr.files):
                _stage(hub, pr, files_dir)
                _build_overlay(tables, files_dir, d / "overlay")
                reports = [verify_table(m, d / "overlay", opts, version) for m in pr.materials]
        except MissingSubtable as exc:
            # Our corpus is incomplete, not the PR's fault: post nothing.
            raise UsageError(str(exc)) from exc
        seed = opts.resolved_seed()
        md = render_markdown(reports, heading=f"Verification of PR #{pr.num}", seed=seed,
                             tool=tool, pr_checks=[v1])
        js = report_json(reports, seed=seed, tool=tool, head=pr.head, pr=pr.num, pr_checks=[v1],
                         settings=opts.settings())
        (d / "report.md").write_text(md)
        (d / "report.json").write_text(json.dumps(js, indent=2))
        print(md)
        if js["result"] != "pass":
            rc = 1
        if gh is not None:
            hub.comment(pr.num, md)
            claim, _ = parse_links(pr.description)
            if claim is not None:
                verdict = "passed ✅" if js["result"] == "pass" else "FAILED ❌"
                gh.comment(claim, f"Verification of [HF PR #{pr.num}]({pr.url}) "
                                  f"({', '.join(pr.materials)}): {verdict}. "
                                  "Full report on the pull request.")
    return rc

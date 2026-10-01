"""verify: run V2-V7 on tables in a directory; V1 and downloading for PRs."""
from __future__ import annotations

import json
import re
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
from .materials import Material, canonical
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


def _build_overlay(tables: Path, files_dir: Path, overlay: Path,
                   others: dict[int, Path] | None = None) -> list[int]:
    """Link `others` (PR number -> staged files of another verified PR), then `tables`
    (published data wins over staged), then the PR's own files into `overlay`; a later source
    wins a name clash. Returns the PRs of `others` that still supply a link."""
    if overlay.exists():
        shutil.rmtree(overlay)
    overlay.mkdir(parents=True)
    source: dict[str, int | None] = {}
    for num, src in [*(others or {}).items(), (None, tables), (None, files_dir)]:
        for p in src.iterdir():
            if p.name.endswith((".hm", ".stats.json")):
                link = overlay / p.name
                if link.is_symlink():
                    link.unlink()
                link.symlink_to(p.resolve())
                source[p.name] = num
    return sorted({n for n in source.values() if n is not None})


def _passed_report(d: Path) -> dict | None:
    """`d/report.json` if it says pass, else None."""
    try:
        rep = json.loads((d / "report.json").read_text())
    except (OSError, ValueError):
        return None
    return rep if isinstance(rep, dict) and rep.get("result") == "pass" else None


def _verified_files(staging: Path, exclude: int, open_heads: dict[int, str | None]) -> dict[int, Path]:
    """Staged files of other PRs that are still open and passed verification at their current
    head, which is also the head staged there."""
    out = {}
    for num, head in sorted(open_heads.items()):
        d = staging / f"pr-{num}"
        if num == exclude or head is None:
            continue
        rep, marker = _passed_report(d), d / "files" / ".head"
        if rep is not None and rep.get("head") == head and marker.exists() and marker.read_text() == head:
            out[num] = d / "files"
    return out


def _flip(material: str) -> str:
    m = Material(material)
    return f"K{m.black.upper()}vk{m.white.lower()}"


def _who_has(exc: Exception, open_prs: list, staging: Path) -> str:
    """The MissingSubtable message, plus which PR has the missing table if one is known."""
    m = re.search(r"no table for (\w+) nor its color flip", str(exc))
    if not m:
        return str(exc)
    names = {m.group(1)} | ({_flip(m.group(1))} if "v" in m.group(1) else set())
    for pr in open_prs:
        found = names & set(pr.materials)
        if found:
            rep = _passed_report(staging / f"pr-{pr.num}")
            state = ("verified, not yet accepted" if rep is not None and rep.get("head") == pr.head
                     else "not verified yet — verify it first")
            return f"{exc}; {found.pop()} is in PR #{pr.num} ({state})"
    open_nums = {pr.num for pr in open_prs}
    for d in sorted(staging.glob("pr-*")):
        num = d.name[len("pr-"):]
        if not num.isdigit() or int(num) in open_nums:
            continue
        for name in sorted(names):
            if (d / "files" / f"{name}.hm").exists():
                return (f"{exc}; {name} is staged from PR #{num}, which is no longer open "
                        "(if it was accepted, pull the published corpus)")
    return str(exc)


def _batch_order(pr) -> tuple[int, int, int]:
    """Sub-tables before the tables that need them: a promotion has one pawn fewer, a capture
    one man fewer and no more pawns."""
    mats = [Material(m) for m in pr.materials if canonical(m) == m]
    return (max((m.pawns for m in mats), default=0), max((m.pieces for m in mats), default=0), pr.num)


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
    open_prs = hub.open_pull_requests()
    open_heads = {p.num: p.head for p in open_prs}
    for pr in sorted(prs, key=_batch_order):
        d = staging / f"pr-{pr.num}"
        files_dir = d / "files"
        d.mkdir(parents=True, exist_ok=True)
        v1 = check_pr_hygiene(pr, manifest_files)
        reports: list = []
        subtables_from: list[int] = []
        try:
            if not any(_unsafe(f) for f in pr.files):
                _stage(hub, pr, files_dir)
                subtables_from = _build_overlay(tables, files_dir, d / "overlay",
                                                _verified_files(staging, pr.num, open_heads))
                reports = [verify_table(m, d / "overlay", opts, version) for m in pr.materials]
        except MissingSubtable as exc:
            # Our corpus is incomplete, not the PR's fault: post nothing.
            raise UsageError(_who_has(exc, open_prs, staging)) from exc
        seed = opts.resolved_seed()
        md = render_markdown(reports, heading=f"Verification of PR #{pr.num}", seed=seed,
                             tool=tool, pr_checks=[v1], subtables_from=subtables_from)
        js = report_json(reports, seed=seed, tool=tool, head=pr.head, pr=pr.num, pr_checks=[v1],
                         settings=opts.settings(), subtables_from=subtables_from)
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

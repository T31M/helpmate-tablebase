"""verify: run V2-V7 on tables in a directory; V1 and downloading for PRs."""
from __future__ import annotations

import json
import re
import secrets
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .checks import (
    Check, MissingPublished, TableReport, check_block_integrity, check_deepest, check_header,
    check_identical, check_sidecar,
)
from .claims import ClaimIndex, load_index
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


class PublishedHashes:
    """Payload hashes of published tables, from the local corpus copy, cached per manifest sha."""

    def __init__(self, tables: Path, manifest_files: dict):
        self.tables, self.files = Path(tables), manifest_files
        self.path = self.tables / ".payload-sha256.json"
        try:
            self.cache: dict = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.cache = {}

    def get(self, material: str) -> str:
        from .tablefile import payload_sha256
        sha = self.files.get(f"{material}.hm", {}).get("sha256")
        hit = self.cache.get(material)
        if hit and hit.get("hm_sha256") == sha:
            return hit["payload"]
        hm = self.tables / f"{material}.hm"
        if not hm.exists():
            raise MissingPublished(material)
        payload = payload_sha256(hm)
        self.cache[material] = {"hm_sha256": sha, "payload": payload}
        self.path.write_text(json.dumps(self.cache, indent=1, sort_keys=True))
        return payload


REUSE_SETTINGS = ("samples", "oracle_samples", "oracle_plies")


def reusable(prev: dict | None, material: str, shas: tuple[str, str], tool: str,
             settings: dict, source_payload: str | None = None,
             needs_deepest: bool = False) -> dict | None:
    """The table entry of the previous report if its result may be taken over: same tool and
    sampling, the table passed, its files are unchanged, and it was compared against the same
    source (the published table, an earlier delivery, or none) as it would be now.
    `needs_deepest`: the entry must have run V5 (a duplicate of an earlier delivery of the same
    run; an entry from before that rule skipped V5 as an independent reproduction)."""
    if not prev or prev.get("tool") != tool:
        return None
    if any(prev.get(k) != settings.get(k) for k in REUSE_SETTINGS):
        return None
    entry = prev.get("tables", {}).get(material)
    if not entry or not entry.get("passed") or None in shas:
        return None
    if (entry.get("hm_sha256"), entry.get("stats_sha256")) != shas:
        return None
    if entry.get("source_payload") != source_payload:
        return None
    if needs_deepest:
        v5 = next((c for c in entry.get("checks", []) if c.get("id") == "V5"), None)
        if v5 is None or str(v5.get("detail", "")).startswith("independent reproduction"):
            return None
    return entry


def verify_table(material: str, tables: Path, opts: VerifyOptions,
                 installed_version: str, *, published: str | None = None,
                 source: str = "the published table", probe_deepest: bool = False,
                 progress: Callable[[str], None] | None = None) -> TableReport:
    """`published`: the payload hash a duplicate must equal (V8), from `source`. A duplicate
    skips V5 to V7, or with `probe_deepest` (a duplicate of an earlier delivery of the same run,
    whose sidecar may be the one published) only V6 and V7."""
    rep = TableReport(material)
    path = tables / f"{material}.hm"
    t0 = time.monotonic()

    def note(check: Check) -> Check:
        nonlocal t0
        rep.checks.append(check)
        if progress is not None:
            now = time.monotonic()
            progress(f"{material} {check.id} {check.title} … {check.status} ({now - t0:.1f}s)")
            t0 = now
        return check

    if not path.exists():
        note(Check("V2", "header and identity", "fail", f"{path} not found"))
        return rep
    for check in (lambda: check_header(path, installed_version),
                  lambda: check_block_integrity(path)):
        note(check())
        if not rep.passed:
            return rep  # later checks would only restate a structural failure
    v4, payload = check_sidecar(path)
    note(v4)
    rep.payload_sha256 = payload
    if published is not None:
        note(check_identical(rep.payload_sha256, published, source))
        skipped = [("V6", "local consistency"), ("V7", "independent solver")]
        if probe_deepest and rep.passed:
            note(check_deepest(path, tables))
        else:
            skipped.insert(0, ("V5", "deepest positions probe as recorded"))
        why = (f"independent reproduction: identical to {source}" if rep.passed
               else "an earlier check failed")
        for cid, title in skipped:
            note(Check(cid, title, "skip", why))
        return rep
    note(check_deepest(path, tables))
    if read_header(path).marker:
        note(Check("V6", "local consistency", "skip", "marker table"))
        note(Check("V7", "independent solver", "skip", "marker table"))
        return rep
    if not rep.passed:
        why = "an earlier check failed"
        note(Check("V6", "local consistency", "skip", why))
        note(Check("V7", "independent solver", "skip", why))
        return rep
    seed = opts.resolved_seed()
    try:
        sc = json.loads(path.with_name(f"{material}.stats.json").read_text())
        extra = list(sc.get("deepest", [])) + list(sc.get("deepest_unique", []))
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        why = f"sidecar unreadable: {exc}"
        note(Check("V6", "local consistency", "skip", why))
        note(Check("V7", "independent solver", "skip", why))
        return rep
    v6, fens = check_consistency(material, tables, opts.samples, seed, extra)
    note(v6)
    note(check_oracle(material, tables, samples=opts.oracle_samples,
                      max_plies=opts.oracle_plies, seed=seed, others=fens))
    return rep


def check_pr_hygiene(pr, manifest_files: dict) -> tuple[Check, set[str]]:
    """The V1 check, and the materials of the PR that are already published."""
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
    dups = {f[:-3] for f in pr.files if f.endswith(".hm") and f in manifest_files}
    for f in pr.files:
        if f in manifest_files and f.split(".")[0] not in dups:
            problems.append(f"{f} is already published "
                            f"(sha256 {manifest_files[f]['sha256'][:12]}…)")
    if problems:
        return Check("V1", title, "fail", "; ".join(problems)), dups
    detail = f"{len(hms)} table(s)"
    if dups:
        detail += f"; duplicates of published tables: {', '.join(sorted(dups))}"
    if parse_links(pr.description)[0] is None:
        return Check("V1", title, "warn", f"{detail}; no `Claim:` line in the "
                     "description (push with --claim N next time)"), dups
    return Check("V1", title, "pass", detail), dups


def classify(pr, manifest_files: dict, index: ClaimIndex | None, earlier: dict[str, int],
             login: str | None) -> dict[str, str]:
    """One label per material of the PR: published, delivered by an earlier PR of this run,
    held for someone else's claim, or new."""
    out = {}
    for m in pr.materials:
        claim = index.claim_for(m) if index is not None else None
        if f"{m}.hm" in manifest_files:
            out[m] = "duplicate of published"
        elif m in earlier:
            out[m] = f"duplicate of HF PR #{earlier[m]}"
        elif claim is not None and (login is None or claim.author.lower() != login.lower()):
            out[m] = f"held for claim #{claim.issue}"
        else:
            out[m] = "new"
    return out


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
        rep = _passed_report(d)
        if rep is not None and rep.get("head") == head and _is_staged_for(d / "files", head):
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


def _files_record(files_dir: Path) -> dict:
    try:
        rec = json.loads((files_dir / ".files.json").read_text())
        if isinstance(rec, dict) and isinstance(rec.get("files"), dict):
            return rec
    except (OSError, ValueError):
        pass
    return {"head": None, "files": {}}


def _is_staged_for(files_dir: Path, head: str | None) -> bool:
    return head is not None and _files_record(files_dir).get("head") == head


def _staged_ok(files_dir: Path, name: str, want: tuple[int, str]) -> bool:
    p = files_dir / name
    rec = _files_record(files_dir)["files"].get(name)
    return p.exists() and p.stat().st_size == want[0] and rec is not None and rec.get("sha256") == want[1]


def _sha256_file(p: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def _stage(hub, pr, files_dir: Path) -> list[str]:
    """Download what is missing or changed at the PR's head; keep unchanged files.
    Returns the names actually downloaded."""
    files_dir.mkdir(parents=True, exist_ok=True)
    revision = pr.head or f"refs/pr/{pr.num}"
    tree = hub._tree(revision)
    want = {f: tree[f] for f in pr.files}
    rec = _files_record(files_dir)
    legacy = files_dir / ".head"
    if legacy.exists() and not (files_dir / ".files.json").exists():
        rec = {"head": None, "files": {
            f.name: {"sha256": _sha256_file(f), "size": f.stat().st_size}
            for f in files_dir.iterdir() if f.is_file() and not f.name.startswith(".")}}
    legacy.unlink(missing_ok=True)
    for f in files_dir.iterdir():
        if f.is_file() and not f.name.startswith(".") and f.name not in want:
            f.unlink()
            rec["files"].pop(f.name, None)
    rec["head"] = pr.head

    def save() -> None:
        (files_dir / ".files.json").write_text(json.dumps(rec, indent=1, sort_keys=True))

    save()  # before downloading: an interrupted run resumes
    fetched = []
    for name, (size, sha) in sorted(want.items()):
        p = files_dir / name
        if p.exists() and p.stat().st_size == size and rec["files"].get(name, {}).get("sha256") == sha:
            continue
        p.unlink(missing_ok=True)
        hub.download(name, revision, files_dir)
        rec["files"][name] = {"sha256": sha, "size": size}
        save()
        fetched.append(name)
    return fetched


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
        tree = hub._tree(pr.head or f"refs/pr/{num}")
        sizes = {f: tree[f][0] for f in pr.files if not _unsafe(f)}
        have = staging / f"pr-{num}" / "files"
        # staged before .files.json: a file of the right size is probably kept (_stage checks its sha)
        legacy = (have / ".head").exists() and not (have / ".files.json").exists()
        unsure = {f for f in sizes if legacy and (have / f).is_file() and (have / f).stat().st_size == sizes[f]}
        todo = {f: tree[f][0] for f in sizes if f not in unsure and not _staged_ok(have, f, tree[f])}
        if any(_unsafe(f) for f in pr.files):
            print(f"  unsafe file names in PR #{num}: nothing will be downloaded")
        total += sum(todo.values())
        print(f"PR #{num} by {pr.author}: {', '.join(pr.materials) or '(no tables)'}")
        for f, s in sorted(sizes.items()):
            note = ("" if f in todo else "  (already downloaded, will be checked)" if f in unsure
                    else "  (already downloaded)")
            print(f"  {f:28} {_gib(s):>12}{note}")
        prs.append(pr)
    free = shutil.disk_usage(staging).free
    print(f"to download: {_gib(total)}; free in {staging}: {_gib(free)}")
    if total > free * 0.95:
        print("error: not enough disk space in the staging directory", file=sys.stderr)
        return 2
    if a.plan_only:
        return 0
    if total and not a.yes:
        if not sys.stdin.isatty():
            raise UsageError(f"{_gib(total)} to download and nobody to ask: run with --yes when "
                             "not interactive")
        if input(f"download {_gib(total)}? [y/N] ").strip().lower() != "y":
            return 2
    manifest_files = hub.fetch_manifest().get("files", {})
    gh = None if a.no_post else (gh_factory or GitHub)(a.github_repo)
    index, claims_note = None, ""
    try:
        index = load_index(gh if gh is not None else (gh_factory or GitHub)(a.github_repo))
    except Exception:  # noqa: BLE001 - claims are advisory; verification goes on without them
        claims_note = "; claims unavailable"
    hashes = PublishedHashes(tables, manifest_files)
    delivered: dict[str, tuple[int, str | None]] = {}   # material -> (PR, payload if it passed)
    rc = 0
    open_prs = hub.open_pull_requests()
    open_heads = {p.num: p.head for p in open_prs}
    for pr in sorted(prs, key=_batch_order):
        pr_login = parse_links(pr.description)[1]
        d = staging / f"pr-{pr.num}"
        files_dir = d / "files"
        d.mkdir(parents=True, exist_ok=True)
        v1, dups = check_pr_hygiene(pr, manifest_files)
        earlier = {m: n for m, (n, _) in delivered.items() if n < pr.num}
        labels = classify(pr, manifest_files, index, earlier, pr_login)
        notes = [f"{m}: {label}" for m, label in labels.items() if label != "new"]
        if notes or claims_note:
            v1.detail += ("; " + ", ".join(notes) if notes else "") + claims_note
        reports: list = []
        table_meta: dict[str, dict] = {}
        subtables_from: list[int] = []
        sources: list[dict] = []
        if not getattr(a, "full", False):
            for name in ("report.json", "report.partial.json"):
                try:
                    src_rep = json.loads((d / name).read_text())
                except (OSError, ValueError):
                    continue
                if isinstance(src_rep, dict) and src_rep.get("head"):
                    sources.append(src_rep)
        n = len(pr.materials)
        try:
            if not any(_unsafe(f) for f in pr.files):
                _stage(hub, pr, files_dir)
                subtables_from = _build_overlay(tables, files_dir, d / "overlay",
                                                _verified_files(staging, pr.num, open_heads))
                recorded = _files_record(files_dir)["files"]
                for i, m in enumerate(pr.materials, 1):
                    prior = delivered.get(m)
                    same_run = False   # a duplicate of an earlier delivery: V5 too (R19)
                    if m in dups:
                        pub, src = hashes.get(m), "the published table"
                    elif prior and prior[1] and prior[0] < pr.num:
                        pub, src, same_run = prior[1], f"HF PR #{prior[0]}", True
                    else:
                        pub, src = None, "the published table"
                    shas = (recorded.get(f"{m}.hm", {}).get("sha256"),
                            recorded.get(f"{m}.stats.json", {}).get("sha256"))
                    entry, verified = None, ""
                    for src_rep in sources:
                        entry = reusable(src_rep, m, shas, tool, opts.settings(), pub, needs_deepest=same_run)
                        if entry is not None:
                            verified = str(entry.get("verified_head") or src_rep["head"])
                            break
                    if entry is not None:
                        head = verified
                        reports.append(TableReport.from_json(m, entry, head))
                        seed_used = entry.get("seed")
                        print(f"[{i}/{n}] {m} reused from {head[:7]}", flush=True)
                    else:
                        def show(line: str, i: int = i) -> None:
                            print(f"[{i}/{n}] {line}", flush=True)

                        reports.append(verify_table(m, d / "overlay", opts, version,
                                                    published=pub, source=src,
                                                    probe_deepest=same_run, progress=show))
                        seed_used = opts.resolved_seed()
                        head = pr.head or ""
                    table_meta[m] = {"hm_sha256": shas[0], "stats_sha256": shas[1],
                                     "seed": seed_used, "source_payload": pub,
                                     "verified_head": head}
                    (d / "report.partial.json").write_text(json.dumps(report_json(
                        reports, seed=opts.resolved_seed(), tool=tool, head=pr.head, pr=pr.num,
                        settings=opts.settings(), table_meta=table_meta), indent=2))
        except MissingPublished as exc:
            raise UsageError(f"{exc.material} is published but not in {tables}; "
                             "sync the corpus first") from exc
        except MissingSubtable as exc:
            # Our corpus is incomplete, not the PR's fault: post nothing.
            raise UsageError(_who_has(exc, open_prs, staging)) from exc
        for rep in reports:
            if rep.passed and rep.payload_sha256:
                delivered.setdefault(rep.material, (pr.num, rep.payload_sha256))
        seed = opts.resolved_seed()
        md = render_markdown(reports, heading=f"Verification of PR #{pr.num}", seed=seed,
                             tool=tool, pr_checks=[v1], subtables_from=subtables_from)
        js = report_json(reports, seed=seed, tool=tool, head=pr.head, pr=pr.num, pr_checks=[v1],
                         settings=opts.settings(), subtables_from=subtables_from,
                         table_meta=table_meta)
        (d / "report.md").write_text(md)
        if (d / "report.json").exists():
            (d / "report.json").replace(d / "report.prev.json")
        (d / "report.json").write_text(json.dumps(js, indent=2))
        (d / "report.partial.json").unlink(missing_ok=True)
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

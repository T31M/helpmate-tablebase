"""Argument wiring for the contribution subcommands of helpmate-tables.
Module level stays import-light: see tables_cli's constraint."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import DATASET_REPO, DEFAULT_STAGING, GITHUB_REPO

CONTRIB_COMMANDS = {"verify", "status", "accept", "sync", "claims", "site-status"}


class UsageError(Exception):
    pass


def add_parsers(sub) -> None:
    v = sub.add_parser("verify", help="check tables (yours before a PR, or a dataset PR)")
    v.add_argument("--tables", required=True, metavar="DIR",
                   help="directory holding the table and every published sub-table")
    what = v.add_mutually_exclusive_group(required=True)
    what.add_argument("--material", action="extend", nargs="+", metavar="M")
    what.add_argument("--pr", action="extend", nargs="+", type=int, metavar="N",
                      help="maintainer: verify a pull request on the dataset")
    v.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    v.add_argument("--github-repo", default=GITHUB_REPO)
    v.add_argument("--samples", type=int, default=2000)
    v.add_argument("--oracle-samples", type=int, default=20,
                   help="V7: positions re-solved by the python-chess search, per depth")
    v.add_argument("--oracle-plies", type=int, default=3,
                   help="V7: deepest DTM (plies) re-solved; each extra ply costs a lot more time")
    v.add_argument("--seed", type=int)
    v.add_argument("--report", metavar="FILE", help="also write the JSON report here")
    v.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    v.add_argument("--plan-only", action="store_true", help="--pr: list files and sizes, then stop")
    v.add_argument("--yes", action="store_true", help="--pr: download without asking")
    v.add_argument("--no-post", action="store_true", help="--pr: do not comment anywhere")
    s = sub.add_parser("sync", help="(maintainer) regenerate the site's materials data, credits and counts")
    s.add_argument("--tables", required=True, metavar="DIR")
    s.add_argument("--checkout", type=Path, default=Path("."))
    s.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    s.add_argument("--github-repo", default=GITHUB_REPO)
    s.add_argument("--no-close", action="store_true", help="do not close finished claims")
    ac = sub.add_parser("accept", help="(maintainer) merge verified dataset PRs and credit them")
    ac.add_argument("pr", type=int, nargs="+")
    ac.add_argument("--tables", required=True, metavar="DIR")
    ac.add_argument("--contributor", metavar="GITHUB_LOGIN")
    ac.add_argument("--checkout", type=Path, default=Path("."))
    ac.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    ac.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    ac.add_argument("--github-repo", default=GITHUB_REPO)
    ac.add_argument("--binary", metavar="PATH",
                    help="helpmate binary for the material pages (default: helpmate on PATH)")
    st = sub.add_parser("status", help="(maintainer) open dataset PRs, claims, verification")
    st.add_argument("--checkout", type=Path, default=Path("."))
    st.add_argument("--staging", type=Path, default=DEFAULT_STAGING)
    st.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    st.add_argument("--github-repo", default=GITHUB_REPO)
    c = sub.add_parser("claims", help="(CI) update the status comment on every claim issue")
    c.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    c.add_argument("--github-repo", default=GITHUB_REPO)
    c.add_argument("--registry", type=Path, default=Path("data/contributions.json"))
    ss = sub.add_parser("site-status", help="(CI) write the site's status.json: state and contributors")
    ss.add_argument("--out", required=True, type=Path)
    ss.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    ss.add_argument("--github-repo", default=GITHUB_REPO)
    ss.add_argument("--registry", type=Path, default=Path("data/contributions.json"))


def _absolute_binary(given: str | None) -> str | None:
    """--binary, else helpmate on PATH; absolute, since build_problems runs with cwd=checkout."""
    found = given or shutil.which("helpmate")
    return str(Path(found).expanduser().resolve()) if found else None


def _installed_version() -> str:
    try:
        import helpmate
        return helpmate.__version__
    except ImportError as exc:
        raise UsageError("verify needs the helpmate bindings: run `make install`") from exc


def _require_verify_deps() -> None:
    try:
        import chess  # noqa: F401
        import numpy  # noqa: F401
        import zstandard  # noqa: F401
    except ImportError as exc:
        raise UsageError("verify needs its extra: pip install './src/packages/api[verify]' "
                         f"(missing: {exc.name})") from exc


def _tool() -> str:
    from .. import __version__
    return f"helpmate-tables {__version__}"


def run(a: argparse.Namespace, hub_factory=None, gh_factory=None) -> int:
    try:
        if a.cmd == "verify":
            return _verify(a, hub_factory, gh_factory)
        if a.cmd == "claims":
            from datetime import date
            from .claims import run_claims
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            return run_claims((hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                              Registry.load(a.registry), date.today())
        if a.cmd == "site-status":
            from datetime import datetime, timezone
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            from .site_status import build_status
            payload = build_status((hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                                  Registry.load(a.registry), datetime.now(timezone.utc))
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(payload, separators=(",", ":")))
            print(f"wrote {a.out}: {len(payload['materials'])} non-open materials")
            return 0
        if a.cmd == "sync":
            from .docs_sync import SyncError, sync
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            checkout = Path(a.checkout)
            if not (checkout / "data" / "contributions.json").exists():
                raise UsageError(f"{checkout} is not a helpmate-tablebase checkout")
            try:
                written = sync(checkout, (hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                               Registry.load(checkout / "data" / "contributions.json"),
                               Path(a.tables).expanduser(), close_claims=not a.no_close)
            except SyncError as exc:
                raise UsageError(str(exc)) from exc
            for p in written:
                print(f"wrote {p}")
            return 0
        if a.cmd in ("accept", "status"):
            from datetime import date
            from .accept import Git, accept, status
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            checkout = Path(a.checkout).resolve()
            if not (checkout / "data" / "contributions.json").exists():
                raise UsageError(f"{checkout} is not a helpmate-tablebase checkout")
            hub = (hub_factory or Hub)(a.repo)
            gh = (gh_factory or GitHub)(a.github_repo)
            if a.cmd == "status":
                print(status(hub, gh, Registry.load(checkout / "data" / "contributions.json"),
                             Path(a.staging).expanduser(), checkout))
                return 0
            return accept(a.pr, hub=hub, gh=gh, git=Git(checkout), checkout=checkout,
                          tables=Path(a.tables).expanduser(), staging=Path(a.staging).expanduser(),
                          contributor=a.contributor, today=date.today().isoformat(),
                          binary=_absolute_binary(a.binary))
        raise UsageError(f"{a.cmd}: not implemented yet")
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _verify(a, hub_factory, gh_factory) -> int:
    from .consistency import MissingSubtable
    from .materials import canonical
    from .report import render_markdown, report_json
    from .verify import VerifyOptions, verify_table

    _require_verify_deps()
    version = _installed_version()
    opts = VerifyOptions(samples=a.samples, oracle_samples=a.oracle_samples,
                         oracle_plies=a.oracle_plies, seed=a.seed)
    if a.pr:
        from .verify import verify_prs
        return verify_prs(a, opts, version, _tool(), hub_factory, gh_factory)
    tables = Path(a.tables).expanduser()
    for m in a.material:
        if canonical(m) != m:
            raise UsageError(f"{m!r} is not a canonical material name"
                             + (f" (did you mean {canonical(m)}?)" if canonical(m) else ""))
    try:
        reports = [verify_table(m, tables, opts, version) for m in a.material]
    except MissingSubtable as exc:
        # An incomplete tables directory, not a defect in the table.
        raise UsageError(str(exc)) from exc
    seed = opts.resolved_seed()
    print(render_markdown(reports, heading="Verification", seed=seed, tool=_tool()))
    if a.report:
        Path(a.report).write_text(json.dumps(
            report_json(reports, seed=seed, tool=_tool(), head=None, pr=None,
                        settings=opts.settings()), indent=2))
    return 0 if all(r.passed for r in reports) else 1

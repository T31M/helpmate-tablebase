"""Verification reports: markdown for humans (HF / GitHub comments), JSON
for accept (which checks the result and the PR head it was made for)."""
from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .checks import Check, TableReport

ICON = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "➖"}


def _rows(checks: Iterable[Check]) -> list[str]:
    return [f"| {ICON[c.status]} | {c.id} | {c.title} | {c.detail.replace('|', '/')} |"
            for c in checks]


def render_markdown(reports: list[TableReport], *, heading: str, seed: int, tool: str,
                    pr_checks: Iterable[Check] = ()) -> str:
    pr_checks = list(pr_checks)
    ok = all(r.passed for r in reports) and all(c.status != "fail" for c in pr_checks)
    lines = [f"## {heading}: {'passed ✅' if ok else 'FAILED ❌'}", "",
             f"{tool}, seed {seed}.", ""]
    if pr_checks:
        lines += ["| | | pull request | |", "|---|---|---|---|", *_rows(pr_checks), ""]
    for r in reports:
        lines += [f"### {r.material} {'✅' if r.passed else '❌'}", "",
                  "| | | check | detail |", "|---|---|---|---|", *_rows(r.checks), ""]
    if not ok:
        lines += ["Please push a corrected table to the same pull request; it will be "
                  "verified again. Nothing has been merged or closed."]
    return "\n".join(lines) + "\n"


def report_json(reports: list[TableReport], *, seed: int, tool: str, head: str | None,
                pr: int | None, pr_checks: Iterable[Check] = (),
                settings: dict | None = None) -> dict:
    """`settings`: what was sampled (samples, oracle_samples, oracle_plies) and the date."""
    pr_checks = list(pr_checks)
    ok = all(r.passed for r in reports) and all(c.status != "fail" for c in pr_checks)
    return {"result": "pass" if ok else "fail", "seed": seed, "tool": tool,
            "head": head, "pr": pr, **(settings or {}), "pr_checks": [asdict(c) for c in pr_checks],
            "tables": {r.material: {"passed": r.passed, "checks": [asdict(c) for c in r.checks]}
                       for r in reports}}

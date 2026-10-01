"""Everything the docs say about the corpus and its contributors, generated.

Prose stays hand-written; the numbers and credit lists inside it live in
<!-- contrib:KEY -->...<!-- /contrib --> spans that `sync` rewrites.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import SITE_MATERIALS_URL
from .materials import universe
from .site_data import write_site_data

SPAN = re.compile(r"(<!-- contrib:([\w-]+) -->)(.*?)(<!-- /contrib -->)", re.S)
SPAN_FILES = ["README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md",
              "docs/hf-dataset-card.md"]
HF_USER = "https://huggingface.co/"
GH_USER = "https://github.com/"


class SyncError(Exception):
    """The inputs cannot produce trustworthy docs; nothing is written."""


def replace_spans(text: str, values: dict[str, str]) -> str:
    def sub(m: re.Match) -> str:
        return m.group(1) + values[m.group(2)] + m.group(4)
    return SPAN.sub(sub, text)


@dataclass
class CorpusFacts:
    files: dict[str, dict]
    max_dtm: int
    cells: int

    @classmethod
    def from_manifest(cls, manifest: dict, tables: Path) -> "CorpusFacts":
        files = manifest.get("files", {})
        max_dtm, cells = 0, 0
        sidecars = [n for n in files if n.endswith(".stats.json")]
        missing = [n for n in sidecars if not (tables / n).exists()]
        if missing:
            raise SyncError(f"{len(missing)} of {len(sidecars)} sidecars listed in the manifest are "
                            f"missing from {tables} (first: {', '.join(missing[:3])}); "
                            "point --tables at a complete corpus")
        for name in sidecars:
            sc = json.loads((tables / name).read_text())
            cells += 2 * int(sc["plane_size"])
            if sc["max_dtm"] < 253:
                max_dtm = max(max_dtm, int(sc["max_dtm"]))
        return cls(files, max_dtm, cells)

    def done(self) -> set[str]:
        return {f[:-3] for f in self.files if f.endswith(".hm")}

    def values(self) -> dict[str, str]:
        done = self.done()
        six_real = [m for m in universe() if m.pieces == 6 and not m.bare_king]
        missing = [m for m in six_real if m.name not in done]
        v = {"tables": str(len(done)),
             "gib": f"{sum(x['size'] for x in self.files.values()) / 2**30:.1f}",
             "cells-billion": f"{self.cells / 1e9:.1f}",
             # 34 plies = h#17 (Black starts); 33 plies = h#16.5 (White starts)
             "deepest": f"h#{self.max_dtm // 2}" + (".5" if self.max_dtm % 2 else ""),
             "six-done": str(len(six_real) - len(missing)),
             "six-open": str(len(missing))}
        for p in range(5):
            v[f"six-open-p{p}"] = str(sum(m.pawns == p for m in missing))
        return v


PR_URL = "https://huggingface.co/datasets/osick/helpmate-tables/discussions"


def render_contributors(reg, statuses: dict) -> str:
    rows = ["", "| contributor | tables | notes |", "| --- | --- | --- |"]
    for key, c in sorted(reg.contributors.items(), key=lambda kv: -len(reg.tables_of(kv[0]))):
        mats = [m for m in reg.tables_of(key) if statuses.get(m) and statuses[m].state == "done"]
        if not mats:
            continue
        prs = sorted({reg.tables[m]["hf_pr"] for m in mats})
        name = "anonymous" if c.anonymous else (
            f"[**{c.display}**]({HF_USER}{c.hf})" if c.hf else f"**{c.display}**")
        links = ", ".join(f"[PR #{p}]({PR_URL}/{p})" for p in prs)
        rows.append(f"| {name} | {len(mats)}: {', '.join(mats)} | {links}: {c.note} |")
    return "\n".join(rows) + "\n"


def all_contributors_rc(reg, gh) -> dict:
    people = []
    for key, c in sorted(reg.contributors.items()):
        if c.anonymous or not c.github or not reg.tables_of(key):
            continue
        people.append({"login": c.github, "name": c.display,
                       "avatar_url": f"https://avatars.githubusercontent.com/u/{gh.user_id(c.github)}?v=4",
                       "profile": f"{GH_USER}{c.github}", "contributions": ["data"]})
    return {"projectName": "helpmate-tablebase", "projectOwner": "osick", "repoType": "github",
            "files": ["README.md"], "contributorsPerLine": 7, "contributors": people}


def close_finished_claims(gh, index, statuses: dict) -> list[int]:
    closed = []
    for c in index.claims:
        if c.materials and all(statuses[m].state in ("done", "not needed") for m in c.materials):
            gh.close(c.issue, f"All {len(c.materials)} claimed tables are in the dataset. "
                              f"Thank you! The credits are on {SITE_MATERIALS_URL}")
            closed.append(c.issue)
    return closed


def sync(checkout: Path, hub, gh, reg, tables: Path, *, close_claims: bool = True) -> list[Path]:
    from .claims import load_index, material_status

    facts = CorpusFacts.from_manifest(hub.fetch_manifest(), tables)
    index = load_index(gh)
    in_review = {m: pr for pr in hub.open_pull_requests() for m in pr.materials}
    statuses = material_status(facts.done(), in_review, index, reg)
    values = facts.values()
    values["contributors-table"] = render_contributors(reg, statuses)
    written = []
    for rel_path in SPAN_FILES:
        p = checkout / rel_path
        old = p.read_text()
        new = replace_spans(old, values)
        if new != old:
            p.write_text(new)
            written.append(p)
    written += write_site_data(checkout / "site" / "data", tables)
    rc = checkout / ".all-contributorsrc"
    text = json.dumps(all_contributors_rc(reg, gh), indent=2) + "\n"
    if not rc.exists() or rc.read_text() != text:
        rc.write_text(text)
        written.append(rc)
    if close_claims:
        close_finished_claims(gh, index, statuses)
    return written

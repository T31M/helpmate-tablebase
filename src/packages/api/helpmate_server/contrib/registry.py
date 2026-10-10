"""data/contributions.json: who contributed which table. The one hand-owned
record; every credit list is generated from it."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .links import parse_links

if TYPE_CHECKING:
    from .claims import Claim

REGISTRY_PATH = Path("data/contributions.json")


@dataclass
class Contributor:
    key: str
    github: str | None
    hf: str | None
    display: str
    anonymous: bool = False
    note: str = ""


class Registry:
    def __init__(self, path: Path, data: dict):
        self.path = Path(path)
        self.contributors = {k: Contributor(k, **v) for k, v in data.get("contributors", {}).items()}
        self.tables: dict[str, dict] = {m: _migrated(t) for m, t in data.get("tables", {}).items()}

    @classmethod
    def load(cls, path: Path) -> "Registry":
        return cls(path, json.loads(Path(path).read_text()))

    def save(self) -> None:
        data = {"schema": 1,
                "contributors": {k: {f: v for f, v in asdict(c).items() if f != "key"}
                                 for k, c in sorted(self.contributors.items())},
                "tables": dict(sorted(self.tables.items()))}
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def by_github(self, login: str) -> Contributor | None:
        return next((c for c in self.contributors.values()
                     if c.github and c.github.lower() == login.lower()), None)

    def by_hf(self, user: str) -> Contributor | None:
        return next((c for c in self.contributors.values()
                     if c.hf and c.hf.lower() == user.lower()), None)

    def add_contributor(self, c: Contributor) -> None:
        self.contributors[c.key] = c

    def record_table(self, material: str, *, contributor: str, hf_pr: int, claim: int | None,
                     merged: str, generator_version: str, verification: dict | None) -> None:
        """The published file's delivery (top-level fields, `published_from`), also a producer."""
        producers = list(self.tables.get(material, {}).get("producers", []))
        self.tables[material] = {"contributor": contributor, "hf_pr": hf_pr, "claim": claim,
                                 "merged": merged, "generator_version": generator_version,
                                 "verification": verification, "producers": producers,
                                 "published_from": hf_pr}
        self.add_producer(material, contributor=contributor, hf_pr=hf_pr, date=merged,
                          generator_version=generator_version)

    def add_producer(self, material: str, *, contributor: str, hf_pr: int, date: str,
                     generator_version: str) -> None:
        """Credit a delivery of `material` (which must be recorded) that passed and matched;
        the same (contributor, hf_pr) is credited once. Kept in delivery order (HF PR number)."""
        producers = self.tables[material].setdefault("producers", [])
        if any(p["contributor"] == contributor and p["hf_pr"] == hf_pr for p in producers):
            return
        producers.append({"contributor": contributor, "hf_pr": hf_pr, "date": date,
                          "generator_version": generator_version})
        # delivery order; the maintainer's own table (hf_pr None) came first
        producers.sort(key=lambda p: (p["hf_pr"] is not None, p["hf_pr"] or 0))

    def producers_of(self, material: str) -> list[str]:
        """Contributor keys of every producer of `material`, in delivery order."""
        entry = self.tables.get(material)
        if entry is None:
            return []
        return [p["contributor"] for p in _migrated(entry)["producers"]]

    def tables_of(self, key: str) -> list[str]:
        """The materials `key` produced (published from their file or reproduced)."""
        return sorted(m for m in self.tables if key in self.producers_of(m))

    def reproduced_of(self, key: str) -> list[str]:
        """The materials `key` produced that have more than one producer."""
        return [m for m in self.tables_of(key) if len(self.producers_of(m)) >= 2]


def _migrated(entry: dict) -> dict:
    """An entry from before producers: its one contributor is the only producer and the
    published file is theirs."""
    t = dict(entry)
    if "producers" not in t:
        t["producers"] = [{"contributor": t.get("contributor"), "hf_pr": t.get("hf_pr"),
                           "date": t.get("merged"), "generator_version": t.get("generator_version")}]
        t.setdefault("published_from", t.get("hf_pr"))
    return t


def resolve_contributor(registry: Registry, pr, claim: Claim | None,
                        override: str | None) -> Contributor | None:
    """override > 'GitHub: @' line > claim issue author > registry by HF user.
    A new contributor who is the claim's author gets the claim form's fields."""
    login = override or parse_links(pr.description)[1] or (claim.author if claim else None)
    if login:
        known = registry.by_github(login)
        if known:
            return known
        form = claim if claim and claim.author.lower() == login.lower() else None
        return Contributor(login, login, (form.hf if form else None) or pr.author,
                           (form.credit if form else None) or login,
                           anonymous=bool(form and form.anonymous))
    return registry.by_hf(pr.author)

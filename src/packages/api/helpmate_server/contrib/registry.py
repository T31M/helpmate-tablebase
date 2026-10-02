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
        self.tables: dict[str, dict] = dict(data.get("tables", {}))

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
        self.tables[material] = {"contributor": contributor, "hf_pr": hf_pr, "claim": claim,
                                 "merged": merged, "generator_version": generator_version,
                                 "verification": verification}

    def tables_of(self, key: str) -> list[str]:
        return sorted(m for m, t in self.tables.items() if t["contributor"] == key)


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

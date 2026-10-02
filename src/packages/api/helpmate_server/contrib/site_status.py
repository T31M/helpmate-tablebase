"""status.json for the site: the state of every material and who computed
what, built at deploy time (never committed). Names are returned raw; the
site escapes them."""
from __future__ import annotations

from datetime import datetime

from .claims import Claim, load_index, material_status
from .materials import Material, universe

STATES = ("done", "in review", "claimed", "open", "not needed")


def _claimant(c: Claim | None) -> str | None:
    if c is None:
        return None
    return "anonymous" if c.anonymous else (c.credit or c.author)


def _claim_who(claim: Claim | None, registry) -> str | None:
    """A claimant's name; anonymous when the claim's box is ticked or the registry says the
    claim's author is anonymous (anonymity is per person, permanent)."""
    if claim is None:
        return None
    person = registry.by_github(claim.author)
    return "anonymous" if claim.anonymous or (person and person.anonymous) else _claimant(claim)


def _hidden_by_claim(person, claim: Claim | None) -> bool:
    """The open claim's form asks for anonymity and its author is this (possibly unregistered)
    person; used while a table is claimed or in review, before accept records it."""
    if claim is None or not claim.anonymous:
        return False
    return person is None or bool(person.github and person.github.lower() == claim.author.lower())


def _registered(registry, key: str | None) -> str | None:
    """A done table's credit: the registry alone decides (anonymity is per person, permanent)."""
    c = registry.contributors.get(key) if key else None
    if c is None:
        return None
    return "anonymous" if c.anonymous else c.display


def build_status(hub, gh, registry, now: datetime) -> dict:
    done = {f[: -len(".hm")] for f in hub.fetch_manifest().get("files", {}) if f.endswith(".hm")}
    index = load_index(gh)
    in_review = {m: pr for pr in hub.open_pull_requests() for m in pr.materials}
    statuses = material_status(done, in_review, index, registry)
    materials: dict[str, dict] = {}
    counts = {"six": dict.fromkeys(STATES, 0), "all": dict.fromkeys(STATES, 0)}
    for m in universe():
        s = statuses[m.name]
        counts["all"][s.state] += 1
        if m.pieces == 6:
            counts["six"][s.state] += 1
        if s.state == "open":
            continue
        claim = index.claim_for(m.name)
        entry: dict
        if s.state == "done":
            table = registry.tables.get(m.name, {})
            entry = {"state": "done", "contributor": _registered(registry, table.get("contributor")),
                     "hf_pr": table.get("hf_pr"), "claim": None}
        elif s.state == "in review":
            pr = in_review[m.name]
            known = registry.by_hf(pr.author)
            if known:
                who = "anonymous" if known.anonymous or _hidden_by_claim(known, claim) else known.display
            else:
                who = _claim_who(claim, registry) or pr.author
            entry = {"state": "in review", "contributor": who, "hf_pr": pr.num,
                     "claim": claim.issue if claim else None}
        elif s.state == "claimed":
            entry = {"state": "claimed", "contributor": _claim_who(claim, registry), "hf_pr": None,
                     "claim": claim.issue if claim else None}
        else:
            entry = {"state": s.state, "contributor": None, "hf_pr": None, "claim": None}
        materials[m.name] = entry
    people = []
    hidden: dict = {"display": "anonymous", "hf": None, "github": None, "anonymous": True,
                    "tables": 0, "six": 0, "materials": []}
    for key, c in registry.contributors.items():
        mats = [m.name for m in universe()
                if registry.tables.get(m.name, {}).get("contributor") == key and m.name in done]
        if not mats:
            continue
        six = sum(Material(x).pieces == 6 for x in mats)
        if c.anonymous:
            hidden["tables"] += len(mats)
            hidden["six"] += six
            continue
        people.append({"display": c.display, "hf": c.hf, "github": c.github, "anonymous": False,
                       "tables": len(mats), "six": six, "materials": mats})
    people.sort(key=lambda p: (-p["tables"], p["display"].lower()))
    if hidden["tables"]:
        people.append(hidden)
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%MZ"), "materials": materials,
            "contributors": people, "counts": counts}

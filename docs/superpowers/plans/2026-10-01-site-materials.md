# Materials and Contributors on the Site — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `docs/MATERIALS.md` with the site's Materials page — all 1000 materials with priority, state and contributor, filterable — and add a contributor section to the site's front page, with state refreshed daily at deploy.

**Architecture:** `helpmate_server/contrib/site_data.py` builds `site/data/materials.json` (committed; static facts + stats of done tables) and `corpus.json`; `helpmate-tables sync` writes them, `tools/build_site_data.py` reuses them. A new `helpmate-tables site-status` writes `site/data/status.json` (never committed) inside the Pages workflow, daily. The browser merges the two files; pure logic sits in `site/js/lib/materials.js` with node tests.

**Tech Stack:** Python ≥ 3.9 (package `helpmate-api`), vanilla ES modules (no build step), `node --test`, GitHub Actions Pages workflow, pytest + Playwright (Python, headless Chromium `--no-sandbox`).

**Spec:** `docs/superpowers/specs/2026-10-01-site-materials-design.md` (builds on `docs/superpowers/specs/2026-09-30-contribution-pipeline-design.md`)

## Global Constraints

- Branch `feature/contribution-pipeline` (PR #47, unmerged). Commit there; never push, never touch the real HF dataset or GitHub except read-only calls.
- Priority = number of White non-king pieces (1–4), displayed `P1`–`P4`; bare White king (`Kvk…`) → priority `null`, state "not needed".
- States, exactly: `done`, `in review`, `claimed`, `open`, `not needed` — derived by `claims.material_status`.
- `site/data/materials.json`: one row per universe material (1000) plus corpus tables outside the universe (`Kvk`), keys `material, pieces, pawns, ram_gib, priority, done, page, max_dtm, solvable, unique, size_bytes`; the last four `null` unless done; `ram_gib` only for 6 pieces (else `null`). Done rows keep the old row values exactly (`build_problems.py` reads them).
- `site/data/corpus.json` keeps its current shape and values, computed over done rows only.
- `site/data/status.json` is never committed (git-ignored); the site must render correctly without it.
- The browser fetches only the site's own files; no cookies, no localStorage/sessionStorage; filter state lives in the URL hash.
- `tables_cli` stays importable without the C++ bindings, numpy, zstandard, chess, huggingface_hub at module level.
- Site URL constant: `https://osick.github.io/helpmate-tablebase/#/materials`.
- Anonymous contributors: shown as `anonymous`, no profile links, anywhere on the site.
- Lint/type: `ruff check`, `mypy src/packages/api/helpmate_server/contrib`; site gate `make test-site`.

## Review Focus

1. **Site loaded without `status.json`** (local `make serve-site`, failed CI step): both pages must render, Materials shows done/open/not needed from `materials.json` and says state is unavailable. Pinned in Task 4 (lib test) and Task 7 (Playwright).
2. **Hash with a query string** (`#/materials?state=open`): must open the Materials screen, apply the filter, and a filter change must update the hash without re-initialising the screen. Pinned in Task 4 (router test) and Task 7 (Playwright).
3. **HTML in contributor names** (registry `display` or claim-form credit): must be escaped on both pages. Pinned in Task 6.
4. **Phone width (390 px)**: the long table must not cause page-level horizontal scroll; it scrolls inside its own container. Pinned in Task 7.
5. **`build_problems.py` reading the new `materials.json`**: open rows have `null` stats; build_problems only looks up materials that have sidecars, so done rows must be unchanged. Pinned in Task 1.

---

## File Structure

```
src/packages/api/helpmate_server/contrib/
  __init__.py            MODIFY  SITE_MATERIALS_URL
  site_data.py           CREATE  priority, stats_row, material_rows, corpus_summary, write_site_data
  site_status.py         CREATE  build_status(hub, gh, registry, now) -> dict
  cli.py                 MODIFY  `site-status` subcommand; sync help text
  docs_sync.py           MODIFY  sync writes site files; render_materials removed; close message
  accept.py              MODIFY  DOCS_PATHS; accept comment text
tools/build_site_data.py MODIFY  reuse site_data (material_row/corpus_summary re-exported)
site/js/lib/materials.js CREATE  pure logic
site/js/materials.js     REWRITE page
site/js/front.js         MODIFY  contributor section
site/js/app.js           MODIFY  hash query, optional data, showMaterials
site/index.html          MODIFY  materials controls + columns; front contributor section
site/css/site.css        MODIFY  table wrapper, cards
site/tests/materials.test.js CREATE
tests/repo/test_site_ui.py   CREATE  Playwright
.github/workflows/pages.yml  MODIFY  schedule, issues: read, site-status step
.gitignore                   MODIFY  site/data/status.json
docs/MATERIALS.md            DELETE
.github/ISSUE_TEMPLATE/claim.yml, docs/CONTRIBUTING-TABLES.md, CHANGELOG.md  MODIFY links
```

Run commands from the repository root. helpmate-api is installed editable (`pip install -e './src/packages/api[dev,verify]'`).

---

### Task 1: `site_data` — rows, priority, corpus summary

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/site_data.py`
- Modify: `tools/build_site_data.py` (materials + corpus block in `main`, and `material_row`/`corpus_summary` become re-exports)
- Test: `src/packages/api/tests/test_contrib_site_data.py`; existing `tests/repo/test_build_site_data.py` must pass unchanged

**Interfaces:**
- Consumes: `materials.Material`, `materials.universe`.
- Produces: `priority(m: Material) -> int | None`; `stats_row(stats: dict, size_bytes: int) -> dict` (identical to the old `material_row`); `material_rows(tables: Path, pages: Path | None) -> list[dict]`; `corpus_summary(rows) -> dict` (rows without a `done` key count as done); `write_site_data(out_dir: Path, tables: Path) -> list[Path]` (writes `materials.json` compact and `corpus.json` with `indent=1`, only if changed; `pages = out_dir / "material"`).

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_site_data.py
import importlib.util
import json
from pathlib import Path

from helpmate_server.contrib.materials import Material
from helpmate_server.contrib.site_data import (
    corpus_summary, material_rows, priority, stats_row, write_site_data,
)

ROOT = Path(__file__).resolve().parents[4]


def _old_tool():
    spec = importlib.util.spec_from_file_location("bsd_old", ROOT / "tools" / "build_site_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_priority_counts_white_pieces():
    assert priority(Material("KQvkqbb")) == 1
    assert priority(Material("KRRvkbp")) == 2
    assert priority(Material("KRBNvkq")) == 3
    assert priority(Material("KQRBNvk")) == 4
    assert priority(Material("Kvkqqqq")) is None


def test_rows_cover_the_universe_plus_kvk(compressed_tables, tmp_path):
    pages = tmp_path / "material"
    pages.mkdir()
    (pages / "KQvk.json").write_text("{}")
    rows = material_rows(compressed_tables, pages)
    by = {r["material"]: r for r in rows}
    assert len(rows) == 1001 and "Kvk" in by
    assert by["KQvk"]["done"] and by["KQvk"]["page"] and by["KQvk"]["max_dtm"] == 14
    assert by["KPvk"]["done"] and not by["KPvk"]["page"]
    assert by["KRBvkqq"] == {"material": "KRBvkqq", "pieces": 6, "pawns": 0, "ram_gib": 32,
                             "priority": 2, "done": False, "page": False, "max_dtm": None,
                             "solvable": None, "unique": None, "size_bytes": None}
    assert by["KQvk"]["ram_gib"] is None and by["Kvkqqqq"]["priority"] is None


def test_done_rows_and_summary_equal_the_old_tool(compressed_tables):
    old = _old_tool()
    old_rows = []
    for sc in sorted(compressed_tables.glob("*.stats.json")):
        hm = sc.with_name(sc.name[: -len(".stats.json")] + ".hm")
        old_rows.append(old.material_row(json.loads(sc.read_text()), hm.stat().st_size))
    new = {r["material"]: r for r in material_rows(compressed_tables, None) if r["done"]}
    for r in old_rows:
        assert {k: new[r["material"]][k] for k in r} == r
    assert corpus_summary(list(new.values())) == old.corpus_summary(old_rows)


def test_write_site_data_only_rewrites_on_change(compressed_tables, tmp_path):
    first = write_site_data(tmp_path, compressed_tables)
    assert {p.name for p in first} == {"materials.json", "corpus.json"}
    assert write_site_data(tmp_path, compressed_tables) == []
    assert json.loads((tmp_path / "corpus.json").read_text())["tables"] == \
        len(list(compressed_tables.glob("*.stats.json")))


def test_stats_row_matches_the_documented_example():
    real = {"material": "KQvk", "plane_size": 100, "max_dtm": 14,
            "cells": {"invalid": {"wtm": 10, "btm": 10}, "unsolvable": {"wtm": 5, "btm": 5}},
            "uniqueness": {"wtm": {"2": {"1": 3, "2": 9}}, "btm": {"1": {"1": 4}}}}
    assert stats_row(real, 1000) == {"material": "KQvk", "pieces": 3, "max_dtm": 14,
                                     "solvable": 170, "unique": 7, "size_bytes": 1000}
```

Note: `_old_tool()` must load the ORIGINAL `tools/build_site_data.py`. Run this test once BEFORE Step 5 changes that file (it is the reference); after Step 5 the re-exports make it compare the new code with itself, which is why Step 2 records the passing reference run.

- [ ] **Step 2: Run to verify failure; record the reference**

Run: `python -m pytest src/packages/api/tests/test_contrib_site_data.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.site_data`. Then save the old tool's output for the fixture as a JSON file under `src/packages/api/tests/data/site_rows_reference.json` (done rows + summary, produced with `_old_tool()` on the `compressed_tables` fixture via a small throwaway pytest run), and change `test_done_rows_and_summary_equal_the_old_tool` to compare against that file instead of `_old_tool()`, so the comparison survives Step 5.

- [ ] **Step 3: Implement**

```python
# src/packages/api/helpmate_server/contrib/site_data.py
"""Data for the site: one row per material for the Materials page, and the
corpus summary on the front page. Stats come from the tables' sidecars."""
from __future__ import annotations

import json
from pathlib import Path

from .materials import Material, universe


def priority(m: Material) -> int | None:
    """Fewer White pieces → typically longer, deeper helpmates → higher
    priority (1 is highest). A bare White king has no helpmate at all."""
    return None if m.bare_king else len(m.white)


def stats_row(stats: dict, size_bytes: int) -> dict:
    cells = stats.get("cells", {})
    total = 2 * int(stats["plane_size"])
    invalid = sum(int(v) for v in cells.get("invalid", {}).values())
    unsolvable = sum(int(v) for v in cells.get("unsolvable", {}).values())
    unique = sum(int(by_count.get("1", 0))
                 for side in stats.get("uniqueness", {}).values() for by_count in side.values())
    marker = bool(stats.get("all_unsolvable")) or int(stats.get("max_dtm", 255)) >= 255
    return {"material": stats["material"], "pieces": Material(stats["material"]).pieces,
            "max_dtm": None if marker else int(stats["max_dtm"]),
            "solvable": 0 if marker else total - invalid - unsolvable,
            "unique": 0 if marker else unique, "size_bytes": size_bytes}


def material_rows(tables: Path, pages: Path | None) -> list[dict]:
    present: dict[str, dict] = {}
    for sc in sorted(Path(tables).glob("*.stats.json")):
        hm = sc.with_name(sc.name[: -len(".stats.json")] + ".hm")
        if hm.exists():
            row = stats_row(json.loads(sc.read_text()), hm.stat().st_size)
            present[row["material"]] = row
    names = [m.name for m in universe()]
    names += sorted(set(present) - set(names), key=lambda n: (Material(n).pieces, n))
    rows = []
    for name in names:
        m = Material(name)
        done = present.get(name)
        rows.append({"material": name, "pieces": m.pieces, "pawns": m.pawns,
                     "ram_gib": m.ram_tier_gib if m.pieces == 6 else None,
                     "priority": priority(m), "done": done is not None,
                     "page": bool(pages and (Path(pages) / f"{name}.json").exists()),
                     "max_dtm": done["max_dtm"] if done else None,
                     "solvable": done["solvable"] if done else None,
                     "unique": done["unique"] if done else None,
                     "size_bytes": done["size_bytes"] if done else None})
    return rows


def corpus_summary(rows: list[dict]) -> dict:
    done = [r for r in rows if r.get("done", True)]
    by_pieces: dict[str, int] = {}
    for r in done:
        by_pieces[str(r["pieces"])] = by_pieces.get(str(r["pieces"]), 0) + 1
    real = [r for r in done if r["max_dtm"] is not None]
    deepest = max(real, key=lambda r: r["max_dtm"]) if real else None
    return {"tables": len(done), "markers": len(done) - len(real),
            "size_bytes": sum(r["size_bytes"] for r in done),
            "solvable": sum(r["solvable"] for r in done),
            "unique": sum(r["unique"] for r in done), "by_pieces": by_pieces,
            "deepest": {"material": deepest["material"], "dtm": deepest["max_dtm"]}
            if deepest else None}


def write_site_data(out_dir: Path, tables: Path) -> list[Path]:
    out_dir = Path(out_dir)
    rows = material_rows(tables, out_dir / "material")
    written = []
    for name, text in (("materials.json", json.dumps(rows, separators=(",", ":"))),
                       ("corpus.json", json.dumps(corpus_summary(rows), indent=1))):
        p = out_dir / name
        if not p.exists() or p.read_text() != text:
            p.write_text(text)
            written.append(p)
    return written
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_site_data.py -v`
Expected: PASS (5 tests). If `corpus_summary` differs from the reference on key order only, compare dicts, not strings.

- [ ] **Step 5: `tools/build_site_data.py` reuses the package**

Replace the bodies of `material_row` and `corpus_summary` by re-exports and the
materials/corpus block of `main` by one call:

```python
try:
    from helpmate_server.contrib.site_data import corpus_summary, write_site_data
    from helpmate_server.contrib.site_data import stats_row as material_row
except ImportError:  # running from a checkout without helpmate-api installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "packages" / "api"))
    from helpmate_server.contrib.site_data import corpus_summary, write_site_data
    from helpmate_server.contrib.site_data import stats_row as material_row
```

and in `main`, instead of building `rows` by hand:

```python
    # materials + corpus: the same rows `helpmate-tables sync` writes
    for p in write_site_data(out, tables):
        print(f"wrote {p.name}", file=sys.stderr)
```

Keep `material_row` and `corpus_summary` importable from the tool (the existing repo test uses them).

Run: `python -m pytest tests/repo/test_build_site_data.py tests/repo/test_build_problems.py src/packages/api/tests/test_contrib_site_data.py -q`
Expected: PASS, existing tests unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/site_data.py tools/build_site_data.py \
        src/packages/api/tests/test_contrib_site_data.py src/packages/api/tests/data/site_rows_reference.json
git commit -m "site data: one row per material (1000 + Kvk) with priority; corpus summary over done tables"
```

---

### Task 2: `helpmate-tables site-status`

**Files:**
- Create: `src/packages/api/helpmate_server/contrib/site_status.py`
- Modify: `src/packages/api/helpmate_server/contrib/cli.py` (parser + dispatch)
- Test: `src/packages/api/tests/test_contrib_site_status.py`

**Interfaces:**
- Consumes: `claims.load_index(gh)`, `claims.material_status(done, in_review, index, registry)` (→ `{name: Status(state, hf_pr, claim, contributor)}`), `Registry` (`.tables`, `.contributors`, `.by_hf`), `hub.fetch_manifest()`, `hub.open_pull_requests()`, `Claim` (`.author`, `.credit`, `.anonymous`).
- Produces: `build_status(hub, gh, registry, now: datetime) -> dict` with keys `generated_at` (`"YYYY-MM-DDTHH:MMZ"`), `materials` (`{name: {state, contributor, hf_pr, claim}}` for every material whose state is not `open`), `contributors` (list of `{display, hf, github, anonymous, tables, six, materials}` for contributors with ≥ 1 done table, most tables first), `counts` (`{"six": {state: n}, "all": {state: n}}` over every universe material, all five states present).

- [ ] **Step 1: Write the failing test**

```python
# src/packages/api/tests/test_contrib_site_status.py
import json
from datetime import datetime, timezone

from fakes import FakeGitHub, FakeHub
from helpmate_server import tables_cli
from helpmate_server.contrib.registry import Registry
from helpmate_server.contrib.site_status import build_status

NOW = datetime(2026, 10, 1, 5, 17, tzinfo=timezone.utc)
FORM = ("### Materials\n\nKRRvk??\n\n### Hugging Face username\n\npopeye37\n\n"
        "### Name to credit\n\n<b>Pop</b>\n\n### Credit\n\n- [ ] Do not name me in the credits.\n")


def _reg(tmp_path):
    return Registry(tmp_path / "c.json", {
        "contributors": {"T31M": {"github": "T31M", "hf": "T31M", "display": "T31M"},
                         "shy": {"github": "shy", "hf": "shy", "display": "Shy", "anonymous": True}},
        "tables": {"KRBvkqq": {"contributor": "T31M", "hf_pr": 1, "claim": 41, "merged": "x",
                               "generator_version": "0.19.0", "verification": None},
                   "KRBvkqr": {"contributor": "shy", "hf_pr": 9, "claim": None, "merged": "x",
                               "generator_version": "0.19.0", "verification": None}}})


def _setup(tmp_path):
    manifest = {"schema": 1, "files": {f"{m}.hm": {"sha256": "a", "size": 1}
                                       for m in ("KRBvkqq", "KRBvkqr", "KQvk")}}
    hub = FakeHub({"manifest.json": json.dumps(manifest).encode()})
    hub.add_pr(3, {"KRRvkqr.hm": b"x", "KRRvkqr.stats.json": b"{}"}, author="popeye37")
    gh = FakeGitHub([{"number": 39, "title": "claim: KRR", "body": FORM,
                      "user": {"login": "popeye37"}, "created_at": "2026-09-20T00:00:00Z",
                      "labels": [], "state": "open"}])
    return hub, gh, _reg(tmp_path)


def test_states_contributors_and_counts(tmp_path):
    hub, gh, reg = _setup(tmp_path)
    s = build_status(hub, gh, reg, NOW)
    assert s["generated_at"] == "2026-10-01T05:17Z"
    m = s["materials"]
    assert m["KRBvkqq"] == {"state": "done", "contributor": "T31M", "hf_pr": 1, "claim": None}
    assert m["KRBvkqr"]["contributor"] == "anonymous"
    assert m["KQvk"]["state"] == "done" and m["KQvk"]["contributor"] is None
    assert m["KRRvkqr"]["state"] == "in review" and m["KRRvkqr"]["hf_pr"] == 3
    assert m["KRRvkqr"]["contributor"] == "<b>Pop</b>"          # escaped by the site, not here
    assert m["KRRvkrr"] == {"state": "claimed", "contributor": "<b>Pop</b>", "hf_pr": None, "claim": 39}
    assert m["Kvkqqqq"]["state"] == "not needed"
    assert "KQRvkqq" not in m                                   # open → omitted
    assert sum(s["counts"]["all"].values()) == 1000
    assert sum(s["counts"]["six"].values()) == 715 and s["counts"]["six"]["not needed"] == 70
    names = [c["display"] for c in s["contributors"]]
    assert names == ["T31M", "anonymous"]
    anon = s["contributors"][1]
    assert anon["hf"] is None and anon["github"] is None and anon["anonymous"]
    assert s["contributors"][0] == {"display": "T31M", "hf": "T31M", "github": "T31M",
                                    "anonymous": False, "tables": 1, "six": 1,
                                    "materials": ["KRBvkqq"]}


def test_anonymous_claim_form_hides_the_claimant(tmp_path):
    hub, gh, reg = _setup(tmp_path)
    gh.issues[39]["body"] = FORM.replace("- [ ] Do not", "- [X] Do not")
    s = build_status(hub, gh, reg, NOW)
    assert s["materials"]["KRRvkrr"]["contributor"] == "anonymous"


def test_cli_writes_the_file(tmp_path):
    hub, gh, reg = _setup(tmp_path)
    reg.save()
    out = tmp_path / "status.json"
    rc = tables_cli.main(["site-status", "--out", str(out), "--registry", str(reg.path)],
                         hub_factory=lambda r: hub, gh_factory=lambda r: gh)
    assert rc == 0 and json.loads(out.read_text())["materials"]["KRBvkqq"]["state"] == "done"
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest src/packages/api/tests/test_contrib_site_status.py -v`
Expected: FAIL — `ModuleNotFoundError: ...contrib.site_status`

- [ ] **Step 3: Implement**

```python
# src/packages/api/helpmate_server/contrib/site_status.py
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


def _registered(registry, key: str | None) -> str | None:
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
        if s.state == "done":
            who = _registered(registry, registry.tables.get(m.name, {}).get("contributor"))
            entry = {"state": "done", "contributor": who,
                     "hf_pr": registry.tables.get(m.name, {}).get("hf_pr"), "claim": None}
        elif s.state == "in review":
            pr = in_review[m.name]
            known = registry.by_hf(pr.author)
            who = (("anonymous" if known.anonymous else known.display) if known
                   else _claimant(claim) or pr.author)
            entry = {"state": "in review", "contributor": who, "hf_pr": pr.num,
                     "claim": claim.issue if claim else None}
        elif s.state == "claimed":
            entry = {"state": "claimed", "contributor": _claimant(claim), "hf_pr": None,
                     "claim": claim.issue if claim else None}
        else:
            entry = {"state": s.state, "contributor": None, "hf_pr": None, "claim": None}
        materials[m.name] = entry
    people = []
    for key, c in registry.contributors.items():
        mats = [m.name for m in universe()
                if registry.tables.get(m.name, {}).get("contributor") == key and m.name in done]
        if not mats:
            continue
        people.append({"display": "anonymous" if c.anonymous else c.display,
                       "hf": None if c.anonymous else c.hf,
                       "github": None if c.anonymous else c.github,
                       "anonymous": c.anonymous, "tables": len(mats),
                       "six": sum(Material(x).pieces == 6 for x in mats), "materials": mats})
    people.sort(key=lambda p: (-p["tables"], p["display"].lower()))
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%MZ"), "materials": materials,
            "contributors": people, "counts": counts}
```

(`material_status` already maps bare White king materials to "not needed" and done before in-review before claimed; check its actual precedence in `claims.py` and keep it.)

- [ ] **Step 4: Wire the CLI**

In `cli.add_parsers`:

```python
    ss = sub.add_parser("site-status", help="(CI) write the site's status.json: state and contributors")
    ss.add_argument("--out", required=True, type=Path)
    ss.add_argument("--repo", default=DATASET_REPO, metavar="USER/DATASET")
    ss.add_argument("--github-repo", default=GITHUB_REPO)
    ss.add_argument("--registry", type=Path, default=Path("data/contributions.json"))
```

Add `"site-status"` to `CONTRIB_COMMANDS`, and in `run`:

```python
        if a.cmd == "site-status":
            from datetime import datetime, timezone
            from .github import GitHub
            from .hf import Hub
            from .registry import Registry
            from .site_status import build_status
            status = build_status((hub_factory or Hub)(a.repo), (gh_factory or GitHub)(a.github_repo),
                                  Registry.load(a.registry), datetime.now(timezone.utc))
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(json.dumps(status, separators=(",", ":")))
            print(f"wrote {a.out}: {len(status['materials'])} non-open materials")
            return 0
```

- [ ] **Step 5: Run tests**

Run: `python -m pytest src/packages/api/tests/test_contrib_site_status.py src/packages/api/tests/test_contrib_verify.py -q`
Expected: PASS (incl. the existing "tables_cli imports nothing heavy" test).

- [ ] **Step 6: Live read-only check**

Run: `helpmate-tables site-status --out /tmp/claude-1000/status-check.json && python -c "import json;s=json.load(open('/tmp/claude-1000/status-check.json'));print(s['counts']['six'], [c['display'] for c in s['contributors']])"`
Expected: six-piece counts summing to 715 with `done` 31 (or more if PRs were merged), contributors `['T31M']` at least.

- [ ] **Step 7: Commit**

```bash
git add src/packages/api/helpmate_server/contrib/{site_status,cli}.py src/packages/api/tests/test_contrib_site_status.py
git commit -m "helpmate-tables site-status: the site's status.json (state, contributors, counts)"
```

---

### Task 3: `sync`/`accept` write the site files; `docs/MATERIALS.md` goes

**Files:**
- Modify: `src/packages/api/helpmate_server/contrib/__init__.py` (`SITE_MATERIALS_URL`), `docs_sync.py`, `accept.py`, `cli.py` (sync help), `materials.py` (docstring)
- Delete: `docs/MATERIALS.md`
- Modify: `.github/ISSUE_TEMPLATE/claim.yml`, `docs/CONTRIBUTING-TABLES.md`, `CHANGELOG.md`, `.gitignore`
- Test: `src/packages/api/tests/test_contrib_docs_sync.py`, `src/packages/api/tests/test_contrib_accept.py`

**Interfaces:**
- Consumes: `site_data.write_site_data(out_dir, tables)`.
- Produces: `SITE_MATERIALS_URL = "https://osick.github.io/helpmate-tablebase/#/materials"`; `sync()` returns written paths including `site/data/materials.json` and `site/data/corpus.json`, never `docs/MATERIALS.md`; `accept.DOCS_PATHS` = `("CHANGELOG.md", "data/contributions.json", "README.md", "docs/CONTRIBUTING-TABLES.md", "docs/COOPERATIVE-TABLEBASE.md", "docs/hf-dataset-card.md", "site/data/materials.json", "site/data/corpus.json", ".all-contributorsrc")`.

- [ ] **Step 1: Change the tests first**

In `test_contrib_docs_sync.py`: replace `render_materials` tests with an assertion that `sync` writes `site/data/materials.json` and `site/data/corpus.json` (create `site/data/` in the fixture checkout), that no `docs/MATERIALS.md` is created, and that the refusal test (missing sidecars) leaves `site/data/` untouched. In `test_contrib_accept.py`: every `docs/MATERIALS.md` path becomes `site/data/materials.json` (create `site/data` in the fixture checkout and the real-git clone fixture); the anonymity test drops its MATERIALS.md assertion (anonymity on the site is covered by Task 2's tests) and keeps the README/card/trailer assertions; add `assert SITE_MATERIALS_URL in body` for the claim "Accepted" comment.

Run: `python -m pytest src/packages/api/tests/test_contrib_docs_sync.py src/packages/api/tests/test_contrib_accept.py -q`
Expected: FAIL (sync still writes MATERIALS.md; DOCS_PATHS unchanged).

- [ ] **Step 2: Implement**

- `contrib/__init__.py`: add `SITE_MATERIALS_URL = "https://osick.github.io/helpmate-tablebase/#/materials"`.
- `docs_sync.sync`: replace the `docs/MATERIALS.md` entry of the write loop with
  `written += write_site_data(checkout / "site" / "data", tables)` (import from `.site_data`); keep `.all-contributorsrc`. Delete `render_materials` and the helpers only it used. `close_finished_claims` message: `f"... Thank you! The credits are on {SITE_MATERIALS_URL}"`.
- `accept.py`: `DOCS_PATHS` as in Interfaces; the claim comment says `credited on {SITE_MATERIALS_URL}`.
- `cli.py` sync help: `"(maintainer) regenerate the site's materials data, credits and counts"`.
- `materials.py` docstring: "the claim list and the site's Materials page start at three".
- `git rm docs/MATERIALS.md`.
- `.gitignore`: add `site/data/status.json` (built at deploy, never committed).
- `claim.yml`: link `https://osick.github.io/helpmate-tablebase/#/materials` instead of `docs/MATERIALS.md`.
- `docs/CONTRIBUTING-TABLES.md`: every `MATERIALS.md` mention → the site page (wording: "the [materials list](https://osick.github.io/helpmate-tablebase/#/materials) on the site, filterable, with priority, state and contributor"); in the maintainer section, `sync` regenerates "the site's materials data (site/data/materials.json, corpus.json)"; mention priority (P1 = one White piece besides the king — the longest, deepest problems; start there).
- `CHANGELOG.md` `[Unreleased]`: replace the `docs/MATERIALS.md` bullet with the site Materials page (all materials, priority, state, contributor, filters; state refreshed daily at deploy) and the front-page contributor section.

- [ ] **Step 3: Run tests**

Run: `python -m pytest src/packages/api/tests tests/repo -q` and `grep -rn "MATERIALS.md" --include=*.py --include=*.yml --include=*.md . | grep -v "docs/superpowers\|\.superpowers"`
Expected: all pass; the grep prints nothing (history in specs/plans is left alone).

- [ ] **Step 4: Commit**

```bash
git add -A src/packages/api docs/CONTRIBUTING-TABLES.md CHANGELOG.md .gitignore .github/ISSUE_TEMPLATE/claim.yml
git commit -m "sync/accept write the site's materials data; docs/MATERIALS.md moves to the site"
```

---

### Task 4: Site logic library and router

**Files:**
- Create: `site/js/lib/materials.js`
- Modify: `site/js/app.js`
- Test: `site/tests/materials.test.js`

**Interfaces:**
- Produces (all pure, exported from `site/js/lib/materials.js`):
  - `STATES` = `["open", "claimed", "in review", "done", "not needed"]` (default order)
  - `priorityLabel(p) -> "P1".."P4" | "—"`
  - `wildcardMatch(name, pattern) -> bool` (empty → true; no `?` → case-insensitive substring; with `?` → `K…vk…` shape, each side same length, fixed pieces matched as a multiset, `?` = any piece of that side)
  - `mergeStatus(rows, status) -> rows` adding `state, contributor, hf_pr, claim` (status wins; fallback: `done` → "done", `priority === null` → "not needed", else "open")
  - `filterRows(rows, f)` with `f = {pieces, state, prio, pawns, contributor, q}`, `"all"`/`""`/undefined = no filter; `contributor` matches the row's `contributor` exactly
  - `defaultOrder(rows)`: by `STATES` index, then priority (null last), then pawns, then material
  - `parseQuery(hash) -> object`, `toQuery(obj) -> string` (omits empty/"all"; stable key order)
  - `esc(s) -> string` HTML-escapes `& < > " '`
- `app.js`: route splits `?` off before choosing the screen; `status` is an optional data file (non-OK or invalid JSON → `null`, logged with `console.warn`); materials screen gets `["materials", "corpus", "status"]`, front gets `["corpus", "deepest", "status"]`; on every `show()` of the materials screen call `showMaterials()`.

- [ ] **Step 1: Write the failing test**

```js
// site/tests/materials.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { STATES, priorityLabel, wildcardMatch, mergeStatus, filterRows, defaultOrder,
  parseQuery, toQuery, esc } from "../js/lib/materials.js";

const row = (material, o = {}) => ({ material, pieces: 6, pawns: 0, priority: 1, done: false, ...o });

test("priority labels", () => {
  assert.equal(priorityLabel(1), "P1");
  assert.equal(priorityLabel(4), "P4");
  assert.equal(priorityLabel(null), "—");
});

test("wildcards match per side, as multisets", () => {
  assert.ok(wildcardMatch("KQvkqbb", "KQvk???"));
  assert.ok(wildcardMatch("KQvkqbb", "KQvkb??"));
  assert.ok(!wildcardMatch("KQvkqbb", "KRvk???"));
  assert.ok(!wildcardMatch("KQvkqb", "KQvk???"));
  assert.ok(wildcardMatch("KRRvkbp", "K??vkbp"));
  assert.ok(wildcardMatch("KRRvkbp", "rrv"));          // plain substring, any case
  assert.ok(wildcardMatch("KRRvkbp", ""));
});

test("merge: status wins, fallback without status", () => {
  const rows = [row("KQvkqbb"), row("KRBvkqq", { done: true, priority: 2 }), row("Kvkqqqq", { priority: null })];
  const none = mergeStatus(rows, null);
  assert.deepEqual(none.map((r) => r.state), ["open", "done", "not needed"]);
  const st = { materials: { KQvkqbb: { state: "claimed", contributor: "popeye37", hf_pr: null, claim: 40 } } };
  const m = mergeStatus(rows, st);
  assert.equal(m[0].state, "claimed");
  assert.equal(m[0].contributor, "popeye37");
  assert.equal(m[1].state, "done");
});

test("filters combine; 'all' and '' mean no filter", () => {
  const rows = mergeStatus([row("KQvkqbb"), row("KQvkqbp", { pawns: 1 }), row("KRRvkbb", { priority: 2 }),
    row("KRBvkqq", { done: true, priority: 2 })], null);
  assert.equal(filterRows(rows, { state: "open" }).length, 3);
  assert.equal(filterRows(rows, { state: "open", prio: "1" }).length, 2);
  assert.equal(filterRows(rows, { prio: "1", pawns: "0" }).length, 1);
  assert.equal(filterRows(rows, { q: "KQvk???", state: "all", pieces: "6" }).length, 2);
  assert.equal(filterRows(rows, {}).length, 4);
});

test("default order: open first, then priority, pawns, name", () => {
  const rows = mergeStatus([row("KRBvkqq", { done: true, priority: 2 }), row("KRRvkbb", { priority: 2 }),
    row("KQvkqbp", { pawns: 1 }), row("KQvkqbb"), row("Kvkqqqq", { priority: null })], null);
  assert.deepEqual(defaultOrder(rows).map((r) => r.material),
    ["KQvkqbb", "KQvkqbp", "KRRvkbb", "KRBvkqq", "Kvkqqqq"]);
  assert.deepEqual(STATES, ["open", "claimed", "in review", "done", "not needed"]);
});

test("hash query round trip", () => {
  const q = parseQuery("#/materials?state=open&prio=1&q=KQvk%3F%3F%3F");
  assert.deepEqual(q, { state: "open", prio: "1", q: "KQvk???" });
  assert.equal(toQuery({ prio: "1", state: "open", pieces: "all", q: "" }), "state=open&prio=1");
  assert.deepEqual(parseQuery("#/materials"), {});
});

test("esc escapes markup", () => {
  assert.equal(esc(`<b>"x" & 'y'</b>`), "&lt;b&gt;&quot;x&quot; &amp; &#39;y&#39;&lt;/b&gt;");
  assert.equal(esc(null), "");
});
```

- [ ] **Step 2: Run to verify failure**

Run: `node --test site/tests/materials.test.js`
Expected: FAIL — cannot find module `../js/lib/materials.js`

- [ ] **Step 3: Implement**

```js
// site/js/lib/materials.js
// Pure logic for the Materials page and the front page's contributor block.
export const STATES = ["open", "claimed", "in review", "done", "not needed"];
const KEYS = ["pieces", "state", "prio", "pawns", "contributor", "q"];

export function priorityLabel(p) { return p ? `P${p}` : "—"; }

function sides(s) {
  const m = /^K([QRBNP?]*)vk([qrbnp?]*)$/.exec(s);
  return m ? [m[1], m[2]] : null;
}
function sideMatch(have, pat) {
  if (have.length !== pat.length) return false;
  const rest = [...have];
  for (const c of pat) {
    if (c === "?") continue;
    const i = rest.indexOf(c);
    if (i < 0) return false;
    rest.splice(i, 1);
  }
  return true;
}
export function wildcardMatch(name, pattern) {
  const p = (pattern || "").trim();
  if (!p) return true;
  if (!p.includes("?")) return name.toLowerCase().includes(p.toLowerCase());
  const n = sides(name), q = sides(p);
  return !!(n && q && sideMatch(n[0], q[0]) && sideMatch(n[1], q[1]));
}

export function mergeStatus(rows, status) {
  const st = status && status.materials ? status.materials : {};
  return rows.map((r) => {
    const s = st[r.material];
    const state = s ? s.state : r.done ? "done" : r.priority === null ? "not needed" : "open";
    return { ...r, state, contributor: s ? s.contributor : null,
      hf_pr: s ? s.hf_pr : null, claim: s ? s.claim : null };
  });
}

const on = (v) => v !== undefined && v !== "" && v !== "all";
export function filterRows(rows, f) {
  return rows.filter((r) =>
    (!on(f.pieces) || String(r.pieces) === String(f.pieces)) &&
    (!on(f.state) || r.state === f.state) &&
    (!on(f.prio) || String(r.priority) === String(f.prio)) &&
    (!on(f.pawns) || String(r.pawns) === String(f.pawns)) &&
    (!on(f.contributor) || r.contributor === f.contributor) &&
    wildcardMatch(r.material, f.q));
}

export function defaultOrder(rows) {
  const rank = (r) => STATES.indexOf(r.state);
  const pr = (r) => (r.priority === null || r.priority === undefined ? 99 : r.priority);
  return [...rows].sort((a, b) => rank(a) - rank(b) || pr(a) - pr(b) || a.pawns - b.pawns ||
    (a.material < b.material ? -1 : a.material > b.material ? 1 : 0));
}

export function parseQuery(hash) {
  const i = (hash || "").indexOf("?");
  if (i < 0) return {};
  const out = {};
  for (const [k, v] of new URLSearchParams(hash.slice(i + 1))) if (KEYS.includes(k)) out[k] = v;
  return out;
}
export function toQuery(obj) {
  const p = new URLSearchParams();
  for (const k of KEYS) if (on(obj[k])) p.set(k, obj[k]);
  return p.toString();
}

export function esc(s) {
  if (s === null || s === undefined) return "";
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}
```

Note: `toQuery` uses `URLSearchParams`, which encodes `?` as `%3F`; the test expects `"state=open&prio=1"` (no `q`), consistent.

- [ ] **Step 4: Router changes in `app.js`**

- `route()`: `const hash = location.hash.replace(/^#\/?/, "").split("?")[0];`
- data: `const OPTIONAL = new Set(["status"]);` and in `data(name)`: for optional names, `.then(r => r.ok ? r.json() : null).catch(e => { console.warn(`${name}.json unavailable: ${e.message}`); return null; })`.
- screens: `front: { init: initFront, data: ["corpus", "deepest", "status"] }`, `materials: { init: initMaterials, data: ["materials", "corpus", "status"] }`.
- import `showMaterials` from `./materials.js`; after `await loaded[name];` add `if (name === "materials") showMaterials();`.

(`showMaterials` is created in Task 5; until then export a no-op `export function showMaterials() {}` from `site/js/materials.js` so the site keeps working between tasks.)

- [ ] **Step 5: Run tests**

Run: `make test-site`
Expected: all node tests pass (old + 7 new), every JS file passes `node --check`.

- [ ] **Step 6: Commit**

```bash
git add site/js/lib/materials.js site/tests/materials.test.js site/js/app.js site/js/materials.js
git commit -m "site: materials logic library (priority, wildcards, filters, order, hash query); router reads ?query"
```

---

### Task 5: The Materials page

**Files:**
- Modify: `site/index.html` (`#screen-materials`), `site/css/site.css`
- Rewrite: `site/js/materials.js`

**Interfaces:**
- Consumes: Task 4's library; data `{materials, corpus, status}` (`status` may be `null`).
- Produces: `initMaterials({materials, corpus, status})`, `showMaterials()` (re-reads the hash query into the controls and re-renders).

- [ ] **Step 1: Markup** — replace the body of `<section id="screen-materials">` with:

```html
    <h1>Every material, three to six men</h1>
    <p class="lede" id="materials-lede"></p>
    <p class="status-line" id="materials-asof"></p>
    <div class="controls" id="materials-controls">
      <label>Men <select data-f="pieces"><option value="all">all</option><option>3</option><option>4</option><option>5</option><option>6</option></select></label>
      <label>State <select data-f="state"><option value="all">all</option><option>open</option><option>claimed</option><option>in review</option><option>done</option><option>not needed</option></select></label>
      <label>Priority <select data-f="prio"><option value="all">all</option><option value="1">P1</option><option value="2">P2</option><option value="3">P3</option><option value="4">P4</option></select></label>
      <label>Pawns <select data-f="pawns"><option value="all">all</option><option>0</option><option>1</option><option>2</option><option>3</option><option>4</option></select></label>
      <label>Contributor <select data-f="contributor"><option value="all">all</option></select></label>
      <label>Name <input data-f="q" type="search" placeholder="KQvk???" size="10" spellcheck="false"></label>
      <span class="count" id="materials-count"></span>
    </div>
    <div class="table-scroll">
    <table class="data sortable" id="materials-table">
      <thead><tr>
        <th data-key="material">material</th><th data-key="pieces">men</th>
        <th data-key="priority">priority</th><th data-key="state">state</th>
        <th data-key="contributor">contributor</th><th data-key="ram_gib">RAM</th>
        <th data-key="max_dtm">longest mate</th><th data-key="solvable">positions with a helpmate</th>
        <th data-key="unique">with a unique one</th><th data-key="size_bytes">table</th>
      </tr></thead>
      <tbody></tbody>
    </table>
    </div>
```

CSS (append to `site.css`):

```css
.table-scroll { overflow-x: auto; max-width: 100%; }
.status-line { font-size: var(--f0); color: var(--ink-faint); margin: .25rem 0; }
table.data td.state-open { color: var(--ink); font-weight: 600; }
table.data td.state-claimed, table.data td.state-in-review { color: var(--ink-soft); }
table.data tr.state-not-needed td { color: var(--ink-faint); }
```

- [ ] **Step 2: Page code**

```js
// site/js/materials.js
import { stipulation, sortRows, humanBytes } from "./lib/solution.js";
import { mergeStatus, filterRows, defaultOrder, parseQuery, toQuery, priorityLabel, esc } from "./lib/materials.js";

const fmt = (n) => Number(n).toLocaleString("en-US");
let rows = [], key = null, dir = "asc";
const controls = () => [...document.querySelectorAll("#materials-controls [data-f]")];

export function initMaterials({ materials, corpus, status }) {
  rows = mergeStatus(materials, status);
  const six = status && status.counts ? status.counts.six : null;
  document.getElementById("materials-lede").textContent = six
    ? `${corpus.tables} tables published. Six men: ${six.done} done, ${six["in review"]} in review, ` +
      `${six.claimed} claimed, ${six.open} open. Priority P1 has one White piece besides the king — ` +
      `typically the longest, deepest helpmates — so start there.`
    : `${corpus.tables} tables published. Priority P1 has one White piece besides the king — start there.`;
  document.getElementById("materials-asof").textContent = status
    ? `State as of ${status.generated_at.replace("T", " ").replace("Z", " UTC")}.`
    : "State unavailable — showing done from the last build; everything else as open.";
  const who = document.querySelector('#materials-controls [data-f="contributor"]');
  const names = [...new Set(rows.map((r) => r.contributor).filter(Boolean))].sort();
  who.insertAdjacentHTML("beforeend", names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join(""));
  for (const el of controls()) el.addEventListener(el.tagName === "INPUT" ? "input" : "change", onChange);
  document.querySelectorAll("#materials-table th").forEach((th) => th.addEventListener("click", () => {
    if (key === th.dataset.key) dir = dir === "asc" ? "desc" : "asc";
    else { key = th.dataset.key; dir = "asc"; }
    render();
  }));
}

export function showMaterials() {
  const q = parseQuery(location.hash);
  for (const el of controls()) el.value = q[el.dataset.f] ?? (el.tagName === "INPUT" ? "" : "all");
  render();
}

function current() {
  const f = {};
  for (const el of controls()) f[el.dataset.f] = el.value;
  return f;
}

function onChange() {
  const q = toQuery(current());
  history.replaceState(null, "", `#/materials${q ? `?${q}` : ""}`);   // no hashchange: no re-route
  render();
}

function render() {
  const shown0 = filterRows(rows, current());
  const shown = key ? sortRows(shown0, key, dir) : defaultOrder(shown0);
  document.getElementById("materials-count").textContent = `${shown.length} of ${rows.length}`;
  document.querySelectorAll("#materials-table th").forEach((th) => {
    th.classList.toggle("sorted", th.dataset.key === key);
    th.classList.toggle("asc", th.dataset.key === key && dir === "asc");
  });
  document.querySelector("#materials-table tbody").innerHTML = shown.map((r) => {
    const cls = r.state.replace(" ", "-");
    const name = r.page ? `<a href="material/${esc(r.material)}.html">${esc(r.material)}</a>` : esc(r.material);
    const state = r.state === "in review" && r.hf_pr
      ? `<a href="https://huggingface.co/datasets/osick/helpmate-tables/discussions/${r.hf_pr}">in review</a>`
      : r.state === "claimed" && r.claim
        ? `<a href="https://github.com/osick/helpmate-tablebase/issues/${r.claim}">claimed</a>` : r.state;
    const marker = r.done && r.max_dtm === null;
    const stat = (v, f) => (r.done ? f(v) : "");
    return `<tr class="state-${cls}">
      <td class="mono">${name}</td><td class="num">${r.pieces}</td>
      <td class="num">${priorityLabel(r.priority)}</td><td class="state-${cls}">${state}</td>
      <td>${esc(r.contributor || "")}</td><td class="num">${r.ram_gib ? `${r.ram_gib} GiB` : ""}</td>
      <td class="num">${r.done ? (marker ? "—" : stipulation(r.max_dtm)) : ""}</td>
      <td class="num">${stat(r.solvable, fmt)}</td><td class="num">${stat(r.unique, fmt)}</td>
      <td class="num">${stat(r.size_bytes, humanBytes)}</td></tr>`;
  }).join("");
}
```

(Names in `status.json` are raw; every interpolation goes through `esc`. `sortRows` puts `null` last for both directions, which suits open rows' empty stats.)

- [ ] **Step 3: Check it renders**

Run: `make site && (cd site && timeout 20 python3 -m http.server 8650 >/dev/null 2>&1 &) ; sleep 1; curl -s localhost:8650/data/materials.json | head -c 80`
Expected: JSON starts with `[{"material":"KQvk"` (after Task 7 regenerates the data; before it the old 302-row file renders as done rows only). The visual check is Task 7's Playwright test.

- [ ] **Step 4: Run tests and commit**

Run: `make test-site`
Expected: PASS.

```bash
git add site/index.html site/css/site.css site/js/materials.js
git commit -m "site: Materials page lists every material with priority, state and contributor; filters in the hash"
```

---

### Task 6: Front page contributor section

**Files:**
- Modify: `site/index.html` (`#screen-front`), `site/css/site.css`, `site/js/front.js`, `site/js/lib/materials.js` (+ tests)
- Test: `site/tests/materials.test.js` (append)

**Interfaces:**
- Produces: `contributorCards(status) -> string` (HTML, escaped) and `sixProgress(status, corpus) -> string` in `site/js/lib/materials.js`; `initFront` renders them into `#contrib-cards` and `#contrib-progress`.

- [ ] **Step 1: Failing tests** (append to `site/tests/materials.test.js`)

```js
import { contributorCards, sixProgress } from "../js/lib/materials.js";

test("contributor cards escape names and link profiles unless anonymous", () => {
  const status = { contributors: [
    { display: "<b>T</b>", hf: "T31M", github: "T31M", anonymous: false, tables: 30, six: 30, materials: [] },
    { display: "anonymous", hf: null, github: null, anonymous: true, tables: 2, six: 2, materials: [] }] };
  const html = contributorCards(status);
  assert.ok(html.includes("&lt;b&gt;T&lt;/b&gt;") && !html.includes("<b>T</b>"));
  assert.ok(html.includes("https://huggingface.co/T31M") && html.includes("https://github.com/T31M"));
  assert.ok(html.includes(`#/materials?contributor=${encodeURIComponent("<b>T</b>")}`));
  assert.equal((html.match(/huggingface\.co/g) || []).length, 1);            // none for anonymous
  assert.equal(contributorCards(null), "");
});

test("six-piece progress with and without status", () => {
  const status = { counts: { six: { done: 46, "in review": 30, claimed: 50, open: 519, "not needed": 70 } } };
  assert.equal(sixProgress(status, { by_pieces: { 6: 46 } }),
    "Six men: 46 done, 30 in review, 50 claimed, 519 open of 645.");
  assert.equal(sixProgress(null, { by_pieces: { 6: 31 } }), "Six men: 31 of 645 done.");
});
```

Run: `node --test site/tests/materials.test.js`
Expected: FAIL — `contributorCards` not exported.

- [ ] **Step 2: Implement in the library**

```js
export function contributorCards(status) {
  if (!status || !status.contributors || !status.contributors.length) return "";
  return status.contributors.map((c) => {
    const links = c.anonymous ? "" :
      [c.hf ? `<a href="https://huggingface.co/${encodeURIComponent(c.hf)}">Hugging Face</a>` : "",
       c.github ? `<a href="https://github.com/${encodeURIComponent(c.github)}">GitHub</a>` : ""]
        .filter(Boolean).join(" · ");
    return `<div class="card"><strong>${esc(c.display)}</strong>
      <span>${c.tables} table${c.tables === 1 ? "" : "s"}${c.six ? `, ${c.six} with six men` : ""}</span>
      ${links ? `<span>${links}</span>` : ""}
      <a href="#/materials?contributor=${encodeURIComponent(c.display)}">their tables →</a></div>`;
  }).join("");
}

export function sixProgress(status, corpus) {
  const s = status && status.counts ? status.counts.six : null;
  if (!s) return `Six men: ${(corpus.by_pieces || {})[6] || 0} of 645 done.`;
  return `Six men: ${s.done} done, ${s["in review"]} in review, ${s.claimed} claimed, ${s.open} open of 645.`;
}
```

- [ ] **Step 3: Markup, CSS, front.js**

In `#screen-front`, after the closing `</div>` of `.two-col` and before `</section>`:

```html
    <section class="contributors" id="front-contributors">
      <h2>Contributors</h2>
      <p>Six-piece tables are computed by volunteers on their own machines. Thank you.</p>
      <div class="cards" id="contrib-cards"></div>
      <p id="contrib-progress"></p>
      <p class="links">
        <a href="#/materials?state=open&prio=1">Open materials, priority P1 →</a> ·
        <a href="https://github.com/osick/helpmate-tablebase/issues/new?template=claim.yml">Claim a material</a> ·
        <a href="https://github.com/osick/helpmate-tablebase/blob/main/docs/CONTRIBUTING-TABLES.md">How to compute a table</a>
      </p>
    </section>
```

CSS:

```css
.contributors { margin-top: 2rem; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: .75rem; margin: .75rem 0; }
.card { display: flex; flex-direction: column; gap: .25rem; padding: .75rem 1rem; background: var(--panel); border: 1px solid var(--rule); border-radius: 4px; font-size: var(--f1); }
```

`front.js`: `export async function initFront({ corpus, deepest, status })`; after the numbers block add

```js
  document.getElementById("contrib-cards").innerHTML = contributorCards(status);
  document.getElementById("contrib-progress").textContent = sixProgress(status, corpus);
```

(import `contributorCards, sixProgress` from `./lib/materials.js`).

- [ ] **Step 4: Run tests and commit**

Run: `make test-site`
Expected: PASS.

```bash
git add site/index.html site/css/site.css site/js/front.js site/js/lib/materials.js site/tests/materials.test.js
git commit -m "site: contributor section on the front page"
```

---

### Task 7: Deploy-time state, regenerated data, browser check, final verification

**Files:**
- Modify: `.github/workflows/pages.yml`
- Regenerate: `site/data/materials.json`, `site/data/corpus.json`
- Create: `tests/repo/test_site_ui.py`
- Modify: `docs/superpowers/specs/2026-10-01-site-materials-design.md` (status line → implemented)

- [ ] **Step 1: Pages workflow**

In `pages.yml`: add to `on:` `schedule: [{cron: "23 4 * * *"}]`; add `issues: read` under `permissions`; update the header comment (status.json is built here, daily and on every deploy, never committed); before "Assemble and test the site" add:

```yaml
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      # State per material (done / in review / claimed / ...) and the
      # contributors, read from the dataset and the claim issues. If this
      # fails the site still deploys and says the state is unavailable.
      - name: Build the materials state
        continue-on-error: true
        run: |
          python -m pip install "huggingface_hub>=0.23"
          python -m helpmate_server.tables_cli site-status --out site/data/status.json
        env:
          PYTHONPATH: src/packages/api
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

Validate: `python -c "import yaml;yaml.safe_load(open('.github/workflows/pages.yml'))"` → no output.

- [ ] **Step 2: Regenerate the committed site data (no network)**

Run:
```bash
python - <<'EOF'
from pathlib import Path
import os
from helpmate_server.contrib.site_data import write_site_data
print(write_site_data(Path("site/data"), Path(os.path.expanduser("~/tb"))))
EOF
python -c "import json;r=json.load(open('site/data/materials.json'));c=json.load(open('site/data/corpus.json'));print(len(r), c['tables'], c['by_pieces'].get('6'))"
```
Expected: `1001 317 31`. Then `python -m pytest tests/repo/test_build_problems.py -q` still passes.

- [ ] **Step 3: Browser test (Playwright, Python)**

```python
# tests/repo/test_site_ui.py
"""The site's Materials and front pages in a real browser, with and without
status.json, at desktop and phone width."""
import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
ROOT = Path(__file__).resolve().parents[2]
STATUS = {"generated_at": "2026-10-01T05:17Z",
          "materials": {"KQvkqbb": {"state": "claimed", "contributor": "<i>pop</i>", "hf_pr": None, "claim": 40}},
          "contributors": [{"display": "T31M", "hf": "T31M", "github": "T31M", "anonymous": False,
                            "tables": 30, "six": 30, "materials": []}],
          "counts": {"six": {"done": 31, "in review": 0, "claimed": 1, "open": 613, "not needed": 70},
                     "all": {}}}


@pytest.fixture(params=[True, False], ids=["with-status", "without-status"])
def site(request, tmp_path):
    if not (ROOT / "site" / "vendor").exists():
        pytest.skip("run `make site` first")
    d = tmp_path / "site"
    shutil.copytree(ROOT / "site", d)
    (d / "data" / "status.json").unlink(missing_ok=True)
    if request.param:
        (d / "data" / "status.json").write_text(json.dumps(STATUS))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(d))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/", request.param
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--no-sandbox"])
        except Exception as exc:  # no browser installed on this machine
            pytest.skip(f"chromium unavailable: {exc}")
        yield b
        b.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_materials_page(site, browser, width):
    url, has_status = site
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto(url + "#/materials?state=open&prio=1")
    page.wait_for_selector("#materials-table tbody tr")
    assert page.input_value('[data-f="state"]') == "open"
    rows = page.locator("#materials-table tbody tr")
    assert rows.count() > 0
    assert all("P1" in t for t in rows.locator("td:nth-child(3)").all_inner_texts())
    assert ("as of" in page.inner_text("#materials-asof")) == has_status
    page.select_option('[data-f="state"]', "all")
    page.fill('[data-f="q"]', "KQvk???")
    assert "q=KQvk" in page.url
    assert page.locator("#materials-table tbody tr").count() == 35
    if has_status:
        assert page.locator("text=<i>pop</i>").count() == 1               # escaped, shown literally
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.close()


@pytest.mark.parametrize("width", [1280, 390])
def test_front_contributors(site, browser, width):
    url, has_status = site
    page = browser.new_page(viewport={"width": width, "height": 900})
    page.goto(url + "#/")
    page.wait_for_selector("#contrib-progress:not(:empty)")
    assert ("T31M" in page.inner_text("#contrib-cards")) == has_status
    assert "of 645" in page.inner_text("#contrib-progress")
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    page.close()
```

Run: `make site && python -m pytest tests/repo/test_site_ui.py -v`
Expected: 8 passed (2 status variants × 2 widths × 2 tests). If the 390 px scroll-width check fails, fix the CSS (`.table-scroll`, `.controls` wrapping), not the test.

- [ ] **Step 4: Full verification**

```bash
make test-site
python -m pytest src/packages/api/tests tests/repo -q
ruff check src/packages/api tools
mypy src/packages/api/helpmate_server/contrib
python -m pytest src/packages/api/tests -q --cov=helpmate_server.contrib --cov-report=term | tail -3
```
Expected: all green; contrib coverage ≥ 80 %.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/pages.yml site/data/materials.json site/data/corpus.json tests/repo/test_site_ui.py \
        docs/superpowers/specs/2026-10-01-site-materials-design.md
git commit -m "site: daily deploy-time state, regenerated materials data (1001 rows, 317 tables), browser test"
```

Not part of the task (controller with the user): push to PR #47, then after merge one `workflow_dispatch` of Pages to see `status.json` built for real.

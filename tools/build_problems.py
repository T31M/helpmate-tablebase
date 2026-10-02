"""Build the per-material problem data the static site reads.

    python3 tools/build_problems.py --tables ~/tb [--binary ./build/helpmate]
                                    [--out site/data] [--material KQvk ...]

Run by hand against a corpus, like tools/build_site_data.py -- the output is
committed, because the Pages workflow has no tables.

Two classes of problem per material:

  unique  the deepest positions with exactly one optimal solution
  duals   the deepest positions with exactly two, which differ in both their
          first and their last move (starts = ends = count = 2)

The depths come from the sidecar's `uniqueness` map and are exact, so no
scanning is needed to find them. Only the positions themselves are mined.
`mine --jsonl --themes --solutions` returns fen, dtm, count, starts, ends,
themes and the SAN solutions in one call, so a material costs about two
subprocess invocations for mining, plus one `probe` and one `line --all`
re-check per selected problem (see reprobe, reprobe_lines) -- up to twelve
more, since each of up to six selected problems needs both.

Note that the strict dual filter is usually empty at the deepest dual depth --
the two solutions there almost always share a first or a last move -- so the
search walks depths downward and typically lands one ply shallower. Both
depths are recorded; the page states the difference.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT = Path(__file__).resolve().parents[1]

# Sibling tools loaded through load_module, keyed by the name they were
# registered under. Populated lazily; see load_module's docstring.
_MODULES: Dict[str, Any] = {}

# `mine` defaults to --max 10. Ask for enough candidates that the picker has
# room to find three dissimilar ones, without scanning a plane into memory.
CANDIDATE_CAP = 500


def depths_with(stats: dict, count: int) -> List[int]:
    """Every dtm holding a position with exactly `count` optimal solutions,
    deepest first, across both sides to move."""
    key = str(count)
    found = set()
    for side in ("wtm", "btm"):
        for dtm, counts in stats.get("uniqueness", {}).get(side, {}).items():
            if counts.get(key):
                found.add(int(dtm))
    return sorted(found, reverse=True)


def deepest_depth(stats: dict, count: int) -> Optional[int]:
    depths = depths_with(stats, count)
    return depths[0] if depths else None


def _run(binary: str, args: List[str], tables: str, retries: int = 3) -> str:
    """subprocess.run with the checksum-error retry every table read needs.

    Shared by run_jsonl and reprobe -- both talk to the same corpus reader,
    and both can hit the intermittent zstd checksum error the compressed read
    path threw on 2026-08-21, the same guard tools/deepest_showcase.py
    carries. A recurrence is a reason to run tools/verify_corpus.py, not to
    suspect this script."""
    for attempt in range(retries):
        p = subprocess.run([binary, *args, "--tables", tables],
                           capture_output=True, text=True)
        if p.returncode == 0:
            return p.stdout
        if "checksum" not in p.stderr:
            raise RuntimeError(f"{' '.join(args)}: {p.stderr.strip()[:200]}")
        print(f"    retry {attempt + 1} after checksum error", file=sys.stderr)
    raise RuntimeError(f"{' '.join(args)}: failed after {retries} retries")


def run_jsonl(binary: str, args: List[str], tables: str, retries: int = 3) -> List[Dict]:
    """The position records from a `mine --jsonl` run.

    The first line is the filter header and the last is the counts footer;
    neither is a position. A run cut short before its footer is a truncated
    scan, not an empty result, and raises rather than silently shipping fewer
    problems."""
    out = _run(binary, args, tables, retries)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) < 2:
        raise RuntimeError(f"{' '.join(args)}: no footer -- scan was cut short")
    return [json.loads(ln) for ln in lines[1:-1]]


def reprobe(binary: str, tables: str, fen: str, dtm: int, count: int,
           retries: int = 3) -> None:
    """Independently confirm the dtm and count `mine` claimed for a selected
    problem, via `helpmate probe` -- a different code path from `mine`, so
    agreement is a genuine check rather than restating the same computation.
    Raises on disagreement; build_material lets that propagate so the
    material is reported FAILED rather than shipped with an unverified claim.

    `probe` reports only dtm and count -- confirmed, its output is exactly
    `dtm=12 (h#6) count=1` -- so starts and ends are independently confirmed
    separately, by reprobe_lines via `helpmate line --all`. See "Validation
    before writing" in
    docs/superpowers/specs/2026-09-20-deepest-site-expansion-design.md."""
    out = _run(binary, ["probe", fen], tables, retries)
    fields = {}
    for tok in out.split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            fields[k] = v
    if fields.get("dtm") != str(dtm):
        raise RuntimeError(
            f"probe {fen}: claimed dtm={dtm}, probe says dtm={fields.get('dtm')!r}")
    if fields.get("count") != str(count):
        raise RuntimeError(
            f"probe {fen}: claimed count={count}, probe says "
            f"count={fields.get('count')!r}")


def reprobe_lines(binary: str, tables: str, fen: str, count: int, starts: int,
                  ends: int, retries: int = 3) -> None:
    """Independently confirm count, starts and ends via `helpmate line
    --all` -- a different code path from `mine` again, since `line`
    enumerates every optimal line rather than counting them the way `mine`'s
    filter does.

    `--max infinity` is passed explicitly: `line`'s own default cap is 10
    (the same kind of trap `mine`'s default of 10 is), and a truncated list
    would under-count starts/ends and raise a false failure here. Both
    selected classes (unique: count 1; strict dual: count 2) are far below
    any cap regardless, so this is cheap.

    count  = how many optimal lines `line --all` printed
    starts = how many distinct first moves those lines show
    ends   = how many distinct last moves those lines show

    Raises on disagreement, same as reprobe."""
    out = _run(binary, ["line", fen, "--all", "--max", "infinity"], tables, retries)
    lines = [ln.split() for ln in out.splitlines() if ln.strip()]
    if len(lines) != count:
        raise RuntimeError(
            f"line --all {fen}: claimed count={count}, line --all printed "
            f"{len(lines)} line(s)")
    got_starts = len({ln[0] for ln in lines})
    got_ends = len({ln[-1] for ln in lines})
    if got_starts != starts:
        raise RuntimeError(
            f"line --all {fen}: claimed starts={starts}, got {got_starts}")
    if got_ends != ends:
        raise RuntimeError(
            f"line --all {fen}: claimed ends={ends}, got {got_ends}")


def mine(binary: str, tables: str, material: str, dtm: int, count: int,
         strict: bool = False, cap: int = CANDIDATE_CAP) -> List[Dict]:
    """Candidates at one depth. `--max` is passed explicitly: it defaults to 10."""
    args = ["mine", material, "--dtm", str(dtm), "--count", str(count),
            "--max", str(cap), "--themes", "--solutions", "--jsonl"]
    if strict:
        args += ["--starts", "2", "--ends", "2"]
    return run_jsonl(binary, args, tables)


def strict_dual_depth(binary: str, tables: str, material: str, stats: dict):
    """The deepest dtm holding a dual whose solutions differ in both their
    first and their last move, and its candidates.

    Walks downward because the deepest dual depth is almost always empty under
    that filter -- the two solutions there share a first or a last move."""
    for dtm in depths_with(stats, 2):
        rows = mine(binary, tables, material, dtm, 2, strict=True)
        if rows:
            return dtm, rows
    return None, []


def load_module(path: Path, name: str):
    """Import a sibling tool. `tools/` is not a package, so this is the only way
    to reuse code across these scripts -- the same trick tests/repo uses.

    Cached by `name`: a full run calls this twice per problem, and a full
    corpus produces roughly 1,500 problems, so an uncached loader would
    re-execute these sibling modules that many times over for no reason."""
    if name not in _MODULES:
        import importlib.util

        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


def attribution(deepest_rows: List[Dict]) -> Dict[str, Dict]:
    """The published-problem fields from docs/DEEPEST.json, keyed by FEN.

    Output of PRs #30-32. Only 26 of 234 entries are published and problems 2,
    3 and every dual are positions that file has never seen, so most lookups
    miss -- that is expected, not a failure."""
    return {r["fen"]: r for r in deepest_rows}


def stipulation(dtm: int) -> str:
    """`h#n` from a ply distance. Odd dtm means White to move: the .5 case."""
    return f"h#{dtm // 2}" if dtm % 2 == 0 else f"h#{dtm // 2}.5"


def problem_record(binary: str, tables: str, cand: Dict,
                   attrib: Dict[str, Dict]) -> Dict:
    """One problem as the site reads it: independently re-probed, solutions
    expanded ply by ply, themes as mined, attribution carried over, quality
    recomputed.

    Raises if `probe` disagrees with what `mine` claimed for dtm or count
    (see reprobe), if `line --all` disagrees on count, starts or ends (see
    reprobe_lines), or ValueError if a solution is illegal, ambiguous or does
    not mate -- never something to ship silently."""
    reprobe(binary, tables, cand["fen"], cand["dtm"], cand["count"])
    reprobe_lines(binary, tables, cand["fen"], cand["count"], cand["starts"],
                 cand["ends"])

    site_data = load_module(ROOT / "tools/build_site_data.py", "build_site_data")
    published = load_module(ROOT / "tools/published_problems.py", "published_problems")

    solutions = [site_data.expand_solution(cand["fen"], " ".join(line))
                 for line in cand["solutions"]]
    row = attrib.get(cand["fen"], {})
    return {
        "fen": cand["fen"],
        "dtm": cand["dtm"],
        "stipulation": stipulation(cand["dtm"]),
        "count": cand["count"],
        "starts": cand["starts"],
        "ends": cand["ends"],
        "themes": cand["themes"],
        "solutions": solutions,
        "published": row.get("published"),
        "published_by": row.get("published_by"),
        "quality": published.assess(cand["fen"], " ".join(cand["solutions"][0])),
        "alternative": row.get("alternative"),
    }


def saturated_at_max(stats: dict) -> bool:
    """True if every position at max_dtm has a saturated (255+) solution count.

    Ported from tools/deepest_showcase.py rather than imported, so this tool
    keeps no dependency on that one. Takes the SIDECAR stats dict, whose
    max_dtm is 255 for a marker material -- not the materials.json row, whose
    max_dtm is None for one. The `bool(keys) and` guard makes an empty
    `uniqueness` (a marker) safely False, so this is fine to call before the
    marker early-return in build_material."""
    md = str(stats.get("max_dtm"))
    keys = set()
    for side in ("wtm", "btm"):
        keys |= set(stats.get("uniqueness", {}).get(side, {}).get(md, {}))
    return bool(keys) and keys == {"255"}


def build_material(binary: str, tables: str, material: str, stats: dict,
                   row: dict, attrib: Dict[str, Dict]) -> Dict:
    """The document for one material: statistics, both problem classes, notes.

    A marker material -- one provably holding no helpmate at all -- is not an
    error and is not mined. 68 of the 302 tables are markers."""
    picker = load_module(ROOT / "tools/problem_picker.py", "problem_picker")

    unique_dtm = deepest_depth(stats, 1)
    doc = {
        "material": material,
        "pieces": row["pieces"],
        "stats": {
            "max_dtm": row["max_dtm"],
            "deepest_unique_dtm": unique_dtm,
            "unique_at_depth": 0,
            "deepest_dual_dtm": deepest_depth(stats, 2),
            "strict_dual_dtm": None,
            "plane_size": stats.get("plane_size"),
            "solvable": row["solvable"],
            "unique": row["unique"],
            "size_bytes": row["size_bytes"],
            "saturated_at_max": saturated_at_max(stats),
            "dtm_histogram": stats.get("dtm_histogram", {}),
        },
        "unique": [], "duals": [], "notes": [],
        "candidates_considered": 0, "candidates_total": 0,
    }

    if row["solvable"] == 0:
        doc["notes"].append("No helpmate exists in this material.")
        return doc

    cands = mine(binary, tables, material, unique_dtm, 1)
    doc["candidates_considered"] = len(cands)
    doc["candidates_total"] = sum(
        int(stats["uniqueness"][s].get(str(unique_dtm), {}).get("1", 0))
        for s in ("wtm", "btm"))
    doc["stats"]["unique_at_depth"] = doc["candidates_total"]

    seed = next((f for f in attrib if any(c["fen"] == f for c in cands)), None)
    chosen, notes = picker.pick(cands, limit=3, seed_fen=seed)
    doc["unique"] = [problem_record(binary, tables, c, attrib) for c in chosen]
    doc["notes"] += notes

    dual_dtm, dual_cands = strict_dual_depth(binary, tables, material, stats)
    doc["stats"]["strict_dual_dtm"] = dual_dtm
    chosen, notes = picker.pick(dual_cands, limit=3)
    doc["duals"] = [problem_record(binary, tables, c, attrib) for c in chosen]
    doc["notes"] += notes
    return doc


def merge_index(existing: List[Dict], new_rows: List[Dict], processed: Set[str]) -> List[Dict]:
    """This run's index rows folded into whatever index.json already held.

    Every row for a material this run processed is dropped from `existing`
    first (so a re-run replaces rather than duplicates it), then `new_rows`
    is added. Every other material's row -- one this run never touched --
    passes through untouched. Sorted stably by (pieces, material) so a
    scoped run's output is indistinguishable in order from a full run's."""
    kept = [r for r in existing if r["material"] not in processed]
    merged = kept + new_rows
    merged.sort(key=lambda r: (r["pieces"], r["material"]))
    return merged


def merge_themes(existing: Dict[str, Dict], new_entries: Dict[str, List[Dict]],
                 processed: Set[str]) -> Dict[str, Dict]:
    """This run's theme entries folded into whatever themes.json already held.

    Every problem entry belonging to a material this run processed is
    dropped from `existing` first -- whether or not that material ends up
    contributing a new entry for that theme -- then this run's entries are
    added. `count` is recomputed from the final list. A theme left holding
    no problems disappears rather than lingering at count 0."""
    merged: Dict[str, List[Dict]] = {}
    for t, info in existing.items():
        kept = [p for p in info.get("problems", []) if p["material"] not in processed]
        if kept:
            merged[t] = kept
    for t, ps in new_entries.items():
        merged.setdefault(t, [])
        merged[t] += ps
    return {t: {"count": len(ps), "problems": ps}
            for t, ps in sorted(merged.items()) if ps}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser("build_problems")
    ap.add_argument("--tables", required=True)
    ap.add_argument("--binary", default="./build/helpmate")
    ap.add_argument("--out", default="site/data")
    ap.add_argument("--material", action="append", default=[],
                    help="restrict to these materials (repeatable)")
    a = ap.parse_args(argv)

    out = Path(a.out)
    (out / "material").mkdir(parents=True, exist_ok=True)

    deepest_rows = json.loads((ROOT / "docs/DEEPEST.json").read_text())
    attrib = attribution(deepest_rows)
    rows = {r["material"]: r
            for r in json.loads((out / "materials.json").read_text())}

    index: List[Dict] = []
    themes: Dict[str, List[Dict]] = {}
    processed: Set[str] = set()
    failures = 0
    for sc in sorted(Path(a.tables).glob("*.stats.json")):
        material = sc.name[: -len(".stats.json")]
        if a.material and material not in a.material:
            continue
        if material not in rows:
            print(f"  {material}: not in materials.json, skipped", file=sys.stderr)
            continue
        if not rows[material].get("done", True):     # rows from old data have no `done`
            print(f"  {material}: not done in materials.json, skipped", file=sys.stderr)
            continue
        try:
            doc = build_material(a.binary, a.tables, material,
                                 json.loads(sc.read_text()), rows[material], attrib)
        except Exception as exc:                        # reported per material, not hidden
            print(f"  {material}: FAILED -- {exc}", file=sys.stderr)
            failures += 1
            continue

        processed.add(material)
        (out / "material" / f"{material}.json").write_text(json.dumps(doc, indent=1))
        for kind in ("unique", "duals"):
            for p in doc[kind]:
                for t in p["themes"]:
                    themes.setdefault(t, []).append({
                        "material": material, "fen": p["fen"], "dtm": p["dtm"],
                        "stipulation": p["stipulation"],
                        "kind": "unique" if kind == "unique" else "dual"})
        index.append({
            "material": material, "pieces": doc["pieces"],
            "stipulation": (stipulation(doc["stats"]["deepest_unique_dtm"])
                            if doc["stats"]["deepest_unique_dtm"] else None),
            "unique": len(doc["unique"]), "duals": len(doc["duals"]),
            # All 302 materials have a table; this is whether one actually
            # holds a helpmate (row["solvable"] != 0), not whether a table
            # exists -- see build_material's marker guard.
            "has_helpmate": doc["stats"]["solvable"] != 0,
        })
        print(f"  {material}: {len(doc['unique'])} unique, {len(doc['duals'])} dual",
              file=sys.stderr)

    # A scoped run (--material) must not wipe out every other material's
    # entry in the committed index/theme files -- merge in place of them.
    index_path = out / "index.json"
    existing_index = json.loads(index_path.read_text()) if index_path.exists() else []
    merged_index = merge_index(existing_index, index, processed)

    themes_path = out / "themes.json"
    existing_themes = json.loads(themes_path.read_text()) if themes_path.exists() else {}
    merged_themes = merge_themes(existing_themes, themes, processed)

    themes_path.write_text(json.dumps(merged_themes, indent=1))
    index_path.write_text(json.dumps(merged_index, indent=1))
    print(f"wrote {len(merged_index)} materials, {len(merged_themes)} themes, "
          f"{failures} failure(s)", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

# src/packages/api/helpmate_server/contrib/checks.py
"""V2-V5: checks that need only the file, its sidecar and a few probes."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .materials import Material, canonical
from .tablefile import (
    DTM_INVALID, DTM_UNSET, DTM_UNSOLVABLE, BlockReader, TableFormatError,
    check_blocks, read_header, read_meta,
)


@dataclass
class Check:
    id: str
    title: str
    status: str  # "pass" | "fail" | "warn" | "skip"
    detail: str = ""


@dataclass
class TableReport:
    material: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.status != "fail" for c in self.checks)


def _stem(path: Path) -> str:
    return path.name[: -len(".hm")]


def _sidecar(path: Path) -> Path:
    return path.with_name(_stem(path) + ".stats.json")


def _load_sidecar(path: Path) -> tuple[dict | None, str]:
    """The sidecar as a dict, or (None, reason) when missing or malformed."""
    sc_path = _sidecar(path)
    if not sc_path.exists():
        return None, "no .stats.json sidecar next to the table"
    try:
        sc = json.loads(sc_path.read_text())
    except (ValueError, OSError) as exc:
        return None, f"sidecar is not readable JSON: {exc}"
    if not isinstance(sc, dict):
        return None, "sidecar is not a JSON object"
    return sc, ""


def _version(v: str) -> tuple[int, ...] | None:
    try:
        return tuple(int(x) for x in v.split("."))
    except ValueError:
        return None


def check_header(path: Path, installed_version: str) -> Check:
    title = "header and identity"
    stem = _stem(path)
    try:
        h = read_header(path)
        meta = read_meta(path, h)
    except TableFormatError as exc:
        return Check("V2", title, "fail", str(exc))
    except ValueError as exc:
        return Check("V2", title, "fail", f"embedded metadata is not JSON: {exc}")
    problems: list[str] = []
    canon = canonical(stem)
    if canon != stem:
        problems.append(f"file name {stem!r} is not a canonical material"
                        + (f" (canonical: {canon})" if canon else ""))
    if h.material != stem:
        problems.append(f"header says {h.material!r}, file name says {stem!r}")
    if canon:
        m = Material(canon)
        if h.plane_size != m.plane_size:
            problems.append(f"plane_size {h.plane_size}, index size for {canon} is {m.plane_size}")
        if h.symmetry != (0 if m.pawns else 1):
            problems.append(f"symmetry byte {h.symmetry} is wrong for this material")
    if h.marker:
        if h.version != 2:
            problems.append(f"marker with format version {h.version}, expected 2")
    elif not (h.version == 3 and h.encoding == 2 and h.codec == 1 and h.block_size):
        problems.append(f"format version {h.version}, encoding {h.encoding}: the dataset "
                        "serves only block-compressed tables (gen --compress, or "
                        "helpmate compact --compress)")
    sc, why = _load_sidecar(path)
    if sc is None:
        problems.append(why)
    else:
        if sc != meta:
            problems.append("sidecar differs from the metadata embedded in the table")
        gv = str(sc.get("generator_version", ""))
        got, inst = _version(gv), _version(installed_version)
        if got is None:
            problems.append(f"generator_version {gv!r} is not a version")
        elif inst is not None and got > inst:
            problems.append(f"generated with {gv}, newer than the installed helpmate "
                            f"{installed_version}; upgrade before verifying")
    if problems:
        return Check("V2", title, "fail", "; ".join(problems))
    return Check("V2", title, "pass",
                 f"{h.material}, plane_size {h.plane_size:,}, format v{h.version}")


def check_block_integrity(path: Path) -> Check:
    verdict, nb = check_blocks(path)
    if verdict.startswith("skip"):
        return Check("V3", "block integrity", "skip", verdict)
    if verdict == "OK":
        return Check("V3", "block integrity", "pass", f"{nb:,} blocks decoded, checksums match")
    return Check("V3", "block integrity", "fail", verdict)


def recompute_stats(reader: BlockReader) -> dict:
    """The sidecar's statistics, recomputed from the payload the way
    SliceGen::stats_json computes them (src/core/generator/generator.cpp)."""
    import numpy as np

    out: dict = {"cells": {"invalid": {}, "unsolvable": {}},
                 "dtm_histogram": {}, "uniqueness": {}, "unset": 0}
    max_dtm = -1
    for s, stm in ((0, "wtm"), (1, "btm")):
        joint = np.zeros(65536, dtype=np.uint64)
        for d, c in zip(reader.plane_chunks(s), reader.plane_chunks(2 + s)):
            dv = np.frombuffer(d, dtype=np.uint8).astype(np.uint32)
            cv = np.frombuffer(c, dtype=np.uint8).astype(np.uint32)
            joint += np.bincount(dv * 256 + cv, minlength=65536).astype(np.uint64)
        grid = joint.reshape(256, 256)
        per = grid.sum(axis=1)
        out["cells"]["invalid"][stm] = int(per[DTM_INVALID])
        out["cells"]["unsolvable"][stm] = int(per[DTM_UNSOLVABLE])
        out["unset"] += int(per[DTM_UNSET])
        depths = [d for d in range(DTM_UNSET) if per[d]]
        out["dtm_histogram"][stm] = {str(d): int(per[d]) for d in depths}
        out["uniqueness"][stm] = {
            str(d): {str(int(c)): int(grid[d, c]) for c in np.nonzero(grid[d])[0]}
            for d in depths}
        if depths:
            max_dtm = max(max_dtm, depths[-1])
    out["max_dtm"] = max_dtm if max_dtm >= 0 else DTM_UNSOLVABLE
    return out


def check_sidecar(path: Path) -> Check:
    title = "sidecar recomputed from the payload"
    try:
        h = read_header(path)
    except TableFormatError as exc:
        return Check("V4", title, "fail", str(exc))
    if h.marker:
        return Check("V4", title, "skip", "marker table: no payload")
    sc, why = _load_sidecar(path)
    if sc is None:
        return Check("V4", title, "fail", why)
    try:
        with BlockReader(path) as r:
            got = recompute_stats(r)
    except TableFormatError as exc:
        return Check("V4", title, "fail", str(exc))
    diffs = [k for k in ("cells", "dtm_histogram", "uniqueness", "max_dtm") if sc.get(k) != got[k]]
    if got["unset"]:
        diffs.append(f"{got['unset']} cells still DTM_UNSET")
    if h.max_dtm != got["max_dtm"]:
        diffs.append(f"header max_dtm {h.max_dtm}, payload {got['max_dtm']}")
    if diffs:
        return Check("V4", title, "fail", "differs: " + ", ".join(diffs))
    return Check("V4", title, "pass", f"{2 * h.plane_size:,} cells, max_dtm {got['max_dtm']}")


def check_deepest(path: Path, tables: Path) -> Check:
    """Probe the sidecar's deepest positions through the C++ reader. This is
    also where the reader's own identity check (material, plane_size) runs."""
    import helpmate

    title = "deepest positions probe as recorded"
    sc, why = _load_sidecar(path)
    if sc is None:
        return Check("V5", title, "fail", why)
    if sc.get("max_dtm") == DTM_UNSOLVABLE:
        return Check("V5", title, "skip", "no solvable cell")
    bad: list[str] = []
    try:
        tb = helpmate.Tablebase(str(tables))
        for fen in sc.get("deepest", []):
            p = tb.probe(fen)
            if p is None or p[0] != sc["max_dtm"]:
                bad.append(f"deepest {fen}: probe {p}, max_dtm {sc['max_dtm']}")
        uniq = sc.get("deepest_unique", [])
        depth = None
        for fen in uniq:
            p = tb.probe(fen)
            if p is None or p[1] != 1 or (depth is not None and p[0] != depth):
                bad.append(f"deepest_unique {fen}: probe {p}")
            elif depth is None:
                depth = p[0]
        if depth is not None:
            for stm, by_depth in sc["uniqueness"].items():
                for d, counts in by_depth.items():
                    if int(d) > depth and "1" in counts:
                        bad.append(f"uniqueness has unique {stm} cells at {d} > {depth}")
    except Exception as exc:  # the reader refusing the file is the finding
        return Check("V5", title, "fail", f"reader error: {exc}")
    if bad:
        return Check("V5", title, "fail", "; ".join(bad[:10]))
    return Check("V5", title, "pass",
                 f"{len(sc.get('deepest', []))} deepest + {len(uniq)} deepest-unique positions")

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

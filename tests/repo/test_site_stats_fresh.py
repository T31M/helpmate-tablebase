"""The Statistics screen's data must describe exactly the corpus the Materials page
shows. Every docs PR that adds tables (helpmate-tables accept / sync) rewrites both;
this test makes a PR that updates one without the other unmergeable."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "site" / "data"


def test_stats_json_matches_the_materials_list():
    materials = json.loads((DATA / "materials.json").read_text())
    stats = json.loads((DATA / "stats.json").read_text())["materials"]
    done = {r["material"]: r for r in materials if r["done"]}
    assert sorted(stats) == sorted(done), (
        "site/data/stats.json is stale (missing %s, extra %s): run helpmate-tables sync --tables DIR"
        % (sorted(set(done) - set(stats)), sorted(set(stats) - set(done))))
    for name, r in done.items():
        assert stats[name]["max_dtm"] == r["max_dtm"], name
        rows = [t for stm in ("wtm", "btm") for t in stats[name][stm]]
        assert sum(c for _, c, _ in rows) == r["solvable"], name
        unique = sum(u for _, _, u in rows)
        assert unique == r["unique"], name


def test_stats_json_stays_small():
    assert (DATA / "stats.json").stat().st_size < 1_000_000

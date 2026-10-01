"""tools/build_problems.py: mining the problems the site shows.

The sidecar arithmetic is exact and testable without a corpus, so it is
tested here; the mining itself is driven through a fake binary in Task 5.
"""

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# The shape of a real sidecar, cut down to what this tool reads. `uniqueness`
# maps side -> dtm -> solution count -> how many positions.
STATS = {
    "material": "KQvk",
    "max_dtm": 14,
    "plane_size": 29568,
    "uniqueness": {
        "wtm": {"7": {"2": 3}, "13": {"255": 2}},
        "btm": {"10": {"2": 4}, "12": {"1": 3}, "14": {"255": 4}},
    },
}


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_problems", ROOT / "tools/build_problems.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_problems"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_deepest_depth_with_a_unique_solution():
    m = _load()
    assert m.deepest_depth(STATS, 1) == 12


def test_deepest_depth_spans_both_sides_to_move():
    m = _load()
    # count=2 appears at btm 10 and wtm 7; the deeper one wins.
    assert m.deepest_depth(STATS, 2) == 10


def test_depths_with_are_listed_deepest_first():
    m = _load()
    assert m.depths_with(STATS, 2) == [10, 7]


def test_deepest_depth_is_none_when_the_count_never_occurs():
    m = _load()
    assert m.deepest_depth(STATS, 3) is None
    assert m.depths_with(STATS, 3) == []


def _fake_run(outputs):
    """Stand in for subprocess.run, returning canned stdout per invocation.

    `outputs` is a list of stdout strings, consumed in order. The argv of each
    call is recorded so the test can assert what was asked of the binary."""
    calls = []

    def run(argv, capture_output=True, text=True, **kw):
        calls.append(argv)
        out = outputs.pop(0) if outputs else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")

    run.calls = calls
    return run


def _fake_run_with_codes(responses):
    """Stand in for subprocess.run, returning canned (returncode, stdout, stderr).

    `responses` is a list of (returncode, stdout, stderr) tuples, consumed in
    order. The argv of each call is recorded so the test can assert what was
    asked of the binary."""
    calls = []

    def run(argv, capture_output=True, text=True, **kw):
        calls.append(argv)
        if responses:
            code, out, err = responses.pop(0)
        else:
            code, out, err = 0, "", ""
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)

    run.calls = calls
    return run


HEADER = '{"material":"KQvk","filter":{},"max":500}'
FOOTER = '{"positions":1,"skipped_saturated":0}'
ROW = ('{"fen":"8/8/7k/6Q1/8/8/8/K7 b - - 0 1","dtm":12,"count":1,'
       '"themes":["pure","model"],"starts":1,"ends":1,'
       '"solutions":[["Kh7","Kb2","Kh8","Qg7#"]]}')


def test_run_jsonl_drops_the_header_and_footer(monkeypatch):
    m = _load()
    monkeypatch.setattr(subprocess, "run", _fake_run(["\n".join([HEADER, ROW, FOOTER])]))
    rows = m.run_jsonl("./build/helpmate", ["mine", "KQvk"], "/tb")
    assert len(rows) == 1
    assert rows[0]["fen"].startswith("8/8/7k/6Q1")
    assert rows[0]["themes"] == ["pure", "model"]


def test_mine_passes_max_explicitly_because_the_default_is_ten(monkeypatch):
    m = _load()
    fake = _fake_run(["\n".join([HEADER, ROW, FOOTER])])
    monkeypatch.setattr(subprocess, "run", fake)
    m.mine("./build/helpmate", "/tb", "KQvk", 12, 1)
    argv = fake.calls[0]
    assert "--max" in argv and argv[argv.index("--max") + 1] == "500"
    assert "--themes" in argv and "--solutions" in argv and "--jsonl" in argv
    assert "--starts" not in argv


def test_mine_adds_the_strict_filter_when_asked(monkeypatch):
    m = _load()
    fake = _fake_run(["\n".join([HEADER, FOOTER])])
    monkeypatch.setattr(subprocess, "run", fake)
    m.mine("./build/helpmate", "/tb", "KQvk", 10, 2, strict=True)
    argv = fake.calls[0]
    assert argv[argv.index("--starts") + 1] == "2"
    assert argv[argv.index("--ends") + 1] == "2"


def test_strict_dual_depth_walks_downward_until_a_depth_yields(monkeypatch):
    """The deepest dual depth is almost always empty under starts=ends=2."""
    m = _load()
    empty = "\n".join([HEADER, FOOTER])
    hit = "\n".join([HEADER, ROW, FOOTER])
    fake = _fake_run([empty, hit])          # depth 10 empty, depth 7 yields
    monkeypatch.setattr(subprocess, "run", fake)
    depth, rows = m.strict_dual_depth("./build/helpmate", "/tb", "KQvk", STATS)
    assert depth == 7
    assert len(rows) == 1
    assert [c[c.index("--dtm") + 1] for c in fake.calls] == ["10", "7"]


def test_strict_dual_depth_returns_none_when_no_depth_yields(monkeypatch):
    m = _load()
    empty = "\n".join([HEADER, FOOTER])
    monkeypatch.setattr(subprocess, "run", _fake_run([empty, empty]))
    depth, rows = m.strict_dual_depth("./build/helpmate", "/tb", "KQvk", STATS)
    assert depth is None and rows == []


def test_run_jsonl_raises_on_nonzero_return_without_checksum_error(monkeypatch):
    """Non-zero return code with non-checksum error fails immediately."""
    m = _load()
    import pytest
    fake = _fake_run_with_codes([(1, "", "some other error")])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="some other error"):
        m.run_jsonl("./build/helpmate", ["mine", "KQvk"], "/tb")
    assert len(fake.calls) == 1


def test_run_jsonl_raises_when_output_has_no_footer(monkeypatch):
    """Header without footer (single line) indicates truncated scan."""
    m = _load()
    import pytest
    fake = _fake_run_with_codes([(0, HEADER, "")])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="cut short"):
        m.run_jsonl("./build/helpmate", ["mine", "KQvk"], "/tb")


def test_run_jsonl_retries_on_checksum_and_raises_after_limit(monkeypatch):
    """Checksum errors are retried; gives up after exhausting retries."""
    m = _load()
    import pytest
    responses = [
        (1, "", "checksum error: ..."),
        (1, "", "checksum error: ..."),
        (1, "", "checksum error: ..."),
    ]
    fake = _fake_run_with_codes(responses)
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="failed after 3 retries"):
        m.run_jsonl("./build/helpmate", ["mine", "KQvk"], "/tb")
    assert len(fake.calls) == 3


pytest.importorskip("chess")

PROBE_OUT = "dtm=13 (h#6.5) count=1\n"
LINE_OUT = ("e3 Kf7 e4 Ke6 e5 Kd5 e6 Kc4 e7 Kb3 e8=Q Ka2 Qa4#\n")


def _fake_probe_and_line(probe_out, line_out):
    """Stand in for subprocess.run during problem_record: the first call is
    `probe`, the second `line --all`."""
    outputs = [probe_out, line_out]

    def run(argv, capture_output=True, text=True, **kw):
        out = outputs.pop(0) if outputs else ""
        return types.SimpleNamespace(returncode=0, stdout=out, stderr="")
    return run


DEEPEST_ROW = {
    "material": "KPvk",
    "fen": "6k1/8/8/8/8/8/4P3/2K5 w - - 0 1",
    "published": [{"id": "P0530828", "author": "Niemann, John",
                   "sources": ["Schachmatt, No. 427, 13/07/1947"]}],
    "published_by": "Niemann (1947)",
    "quality": {"capture_first": False, "check": False, "legal": True},
    "alternative": None,
}


def test_attribution_is_keyed_by_fen():
    m = _load()
    a = m.attribution([DEEPEST_ROW])
    assert a["6k1/8/8/8/8/8/4P3/2K5 w - - 0 1"]["published_by"] == "Niemann (1947)"


def test_problem_record_carries_attribution_over_by_fen(monkeypatch):
    m = _load()
    monkeypatch.setattr(subprocess, "run", _fake_probe_and_line(PROBE_OUT, LINE_OUT))
    cand = {"fen": DEEPEST_ROW["fen"], "dtm": 13, "count": 1, "starts": 1, "ends": 1,
            "themes": ["model"],
            "solutions": [["e3", "Kf7", "e4", "Ke6", "e5", "Kd5", "e6", "Kc4",
                           "e7", "Kb3", "e8=Q", "Ka2", "Qa4#"]]}
    rec = m.problem_record("./build/helpmate", "/tb", cand, m.attribution([DEEPEST_ROW]))
    assert rec["published_by"] == "Niemann (1947)"
    assert rec["stipulation"] == "h#6.5"
    assert rec["solutions"][0][0] == {"san": "e3", "uci": "e2e3",
                                      "fen": "6k1/8/8/8/8/4P3/8/2K5 b - - 0 1"}


def test_problem_record_recomputes_quality_for_a_new_position(monkeypatch):
    """Most problems have no DEEPEST.json row to carry quality from."""
    m = _load()
    monkeypatch.setattr(subprocess, "run", _fake_probe_and_line(PROBE_OUT, LINE_OUT))
    cand = {"fen": DEEPEST_ROW["fen"], "dtm": 13, "count": 1, "starts": 1, "ends": 1,
            "themes": [],
            "solutions": [["e3", "Kf7", "e4", "Ke6", "e5", "Kd5", "e6", "Kc4",
                           "e7", "Kb3", "e8=Q", "Ka2", "Qa4#"]]}
    rec = m.problem_record("./build/helpmate", "/tb", cand, {})   # no attribution at all
    assert rec["published"] is None and rec["published_by"] is None
    assert rec["quality"] == {"capture_first": False, "check": False, "legal": True}


def test_problem_record_rejects_a_line_that_does_not_mate(monkeypatch):
    m = _load()
    # Reprobe must agree with the (bogus) claim so the mate check is what fails.
    monkeypatch.setattr(subprocess, "run", _fake_probe_and_line(
        "dtm=2 (h#1) count=1\n", "Kh6 Qg5\n"))
    cand = {"fen": "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", "dtm": 2, "count": 1,
            "starts": 1, "ends": 1, "themes": [], "solutions": [["Kh6", "Qg5"]]}
    with pytest.raises(ValueError, match="does not end in checkmate"):
        m.problem_record("./build/helpmate", "/tb", cand, {})


def test_reprobe_passes_when_probe_agrees(monkeypatch):
    m = _load()
    fake = _fake_run(["dtm=12 (h#6) count=1\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    m.reprobe("./build/helpmate", "/tb", "fen", 12, 1)          # does not raise


def test_reprobe_raises_when_dtm_disagrees(monkeypatch):
    m = _load()
    fake = _fake_run(["dtm=11 (h#5.5) count=1\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="dtm"):
        m.reprobe("./build/helpmate", "/tb", "fen", 12, 1)


def test_reprobe_raises_when_count_disagrees(monkeypatch):
    m = _load()
    fake = _fake_run(["dtm=12 (h#6) count=2\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="count"):
        m.reprobe("./build/helpmate", "/tb", "fen", 12, 1)


def test_reprobe_lines_passes_when_line_all_agrees(monkeypatch):
    m = _load()
    fake = _fake_run(["Qa2 Kf3 Kb2 Ke2 Kc3+ Kd1 Qd2#\nQc4 Kf2 Kb2 Ke1 Kc3 Kd1 Qf1#\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    m.reprobe_lines("./build/helpmate", "/tb", "fen", 2, 2, 2)  # does not raise
    argv = fake.calls[0]
    assert argv[1:4] == ["line", "fen", "--all"]
    assert "--max" in argv and argv[argv.index("--max") + 1] == "infinity"


def test_reprobe_lines_raises_on_starts_mismatch(monkeypatch):
    """Both lines start with the same move, so starts is really 1, not 2."""
    m = _load()
    fake = _fake_run(["Qa2 Kf3 Kb2 Ke2 Kc3+ Kd1 Qd2#\nQa2 Kf2 Kb2 Ke1 Kc3 Kd1 Qf1#\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="starts"):
        m.reprobe_lines("./build/helpmate", "/tb", "fen", 2, 2, 2)


def test_reprobe_lines_raises_on_ends_mismatch(monkeypatch):
    """Both lines end with the same move, so ends is really 1, not 2."""
    m = _load()
    fake = _fake_run(["Qa2 Kf3 Kb2 Ke2 Kc3+ Kd1 Qd2#\nQc4 Kf2 Kb2 Ke1 Kc3 Kd1 Qd2#\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="ends"):
        m.reprobe_lines("./build/helpmate", "/tb", "fen", 2, 2, 2)


def test_reprobe_lines_raises_on_count_mismatch(monkeypatch):
    """mine claimed count=2 but line --all printed only one line."""
    m = _load()
    fake = _fake_run(["Qa2 Kf3 Kb2 Ke2 Kc3+ Kd1 Qd2#\n"])
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(RuntimeError, match="count"):
        m.reprobe_lines("./build/helpmate", "/tb", "fen", 2, 2, 2)


def test_saturated_at_max_is_false_for_a_marker():
    m = _load()
    assert m.saturated_at_max(MARKER_STATS) is False


def test_saturated_at_max_is_true_when_the_max_bucket_is_only_255():
    m = _load()
    stats = {"max_dtm": 14, "uniqueness": {
        "wtm": {"14": {"255": 2}}, "btm": {"14": {"255": 4}},
    }}
    assert m.saturated_at_max(stats) is True


MARKER_STATS = {"material": "Kvk", "max_dtm": 255, "plane_size": 462, "uniqueness": {}}
MATERIAL_ROW = {"material": "KQvk", "pieces": 3, "max_dtm": 14,
                "solvable": 45723, "unique": 3064, "size_bytes": 71647}


def test_build_material_on_a_marker_reports_no_helpmate_without_mining(monkeypatch):
    m = _load()
    def explode(*a, **k):
        raise AssertionError("a marker material must not be mined")
    monkeypatch.setattr(m, "mine", explode)
    doc = m.build_material("./build/helpmate", "/tb", "Kvk", MARKER_STATS,
                           {"material": "Kvk", "pieces": 2, "max_dtm": None,
                            "solvable": 0, "unique": 0, "size_bytes": 466}, {})
    assert doc["unique"] == [] and doc["duals"] == []
    assert doc["notes"] == ["No helpmate exists in this material."]
    assert doc["stats"]["deepest_unique_dtm"] is None


def test_build_material_does_not_claim_no_helpmate_when_solvable_is_nonzero(monkeypatch):
    """The marker note is derived from row['solvable'], not from
    deepest_unique_dtm being None. A material with helpmates but no unique
    solution anywhere must not falsely publish 'No helpmate exists'."""
    m = _load()
    stats_no_unique = {"material": "KQvk", "max_dtm": 14, "plane_size": 29568,
                       "uniqueness": {"wtm": {"7": {"2": 3}}, "btm": {"10": {"2": 4}}}}
    row = {"material": "KQvk", "pieces": 3, "max_dtm": 14,
          "solvable": 45723, "unique": 0, "size_bytes": 71647}
    monkeypatch.setattr(m, "mine", lambda *a, **k: [])
    monkeypatch.setattr(m, "strict_dual_depth", lambda *a, **k: (None, []))
    doc = m.build_material("./build/helpmate", "/tb", "KQvk", stats_no_unique, row, {})
    assert doc["notes"] != ["No helpmate exists in this material."]
    assert doc["stats"]["deepest_unique_dtm"] is None      # still true and still reported
    assert doc["stats"]["solvable"] == 45723


def test_build_material_records_both_dual_depths(monkeypatch):
    m = _load()
    cand = {"fen": "8/8/7k/6Q1/8/8/8/K7 b - - 0 1", "dtm": 12, "count": 1,
            "starts": 1, "ends": 1, "themes": [],
            "solutions": [["Kh7", "Kb2", "Kh8", "Qg7#"]]}
    dual = {"fen": "8/5Q2/8/8/8/6k1/8/K7 w - - 0 1", "dtm": 7, "count": 2,
            "starts": 2, "ends": 2, "themes": [],
            "solutions": [["Qf3", "Kh4", "Qh3#"], ["Qg7", "Kh4", "Qh6#"]]}
    monkeypatch.setattr(m, "mine", lambda *a, **k: [cand])
    monkeypatch.setattr(m, "strict_dual_depth", lambda *a, **k: (7, [dual]))
    monkeypatch.setattr(m, "problem_record", lambda b, t, c, a: dict(c, stipulation="x"))
    doc = m.build_material("./build/helpmate", "/tb", "KQvk", STATS, MATERIAL_ROW, {})
    assert doc["stats"]["deepest_unique_dtm"] == 12
    assert doc["stats"]["deepest_dual_dtm"] == 10      # from the sidecar
    assert doc["stats"]["strict_dual_dtm"] == 7        # what the filter found
    assert doc["stats"]["solvable"] == 45723
    assert len(doc["unique"]) == 1 and len(doc["duals"]) == 1


def test_build_material_carries_the_pickers_notes(monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "mine", lambda *a, **k: [])
    monkeypatch.setattr(m, "strict_dual_depth", lambda *a, **k: (None, []))
    doc = m.build_material("./build/helpmate", "/tb", "KQvk", STATS, MATERIAL_ROW, {})
    assert "No position at this depth satisfies the filter." in doc["notes"]


def test_merge_index_replaces_processed_rows_and_keeps_others():
    m = _load()
    existing = [
        {"material": "KPvk", "pieces": 3, "stipulation": "h#6.5",
         "unique": 1, "duals": 1, "has_helpmate": True},
        {"material": "KQvk", "pieces": 3, "stipulation": "h#2.5",
         "unique": 3, "duals": 2, "has_helpmate": True},          # stale
    ]
    fresh = [{"material": "KQvk", "pieces": 3, "stipulation": "h#6",
              "unique": 1, "duals": 1, "has_helpmate": True}]
    merged = m.merge_index(existing, fresh, {"KQvk"})
    assert [r["material"] for r in merged] == ["KPvk", "KQvk"]     # sorted, no dupes
    kqvk = next(r for r in merged if r["material"] == "KQvk")
    assert kqvk["stipulation"] == "h#6"                            # replaced, not appended
    kpvk = next(r for r in merged if r["material"] == "KPvk")
    assert kpvk["unique"] == 1 and kpvk["duals"] == 1              # untouched


def test_merge_themes_drops_stale_entries_and_removes_a_theme_left_empty():
    m = _load()
    existing = {
        "model": {"count": 2, "problems": [
            {"material": "KPvk", "fen": "kpvk-fen", "dtm": 13,
             "stipulation": "h#6.5", "kind": "unique"},
            {"material": "KQvk", "fen": "stale-fen", "dtm": 5,
             "stipulation": "h#2.5", "kind": "unique"},
        ]},
        "capture": {"count": 1, "problems": [
            {"material": "KQvk", "fen": "stale-fen", "dtm": 5,
             "stipulation": "h#2.5", "kind": "unique"},
        ]},
    }
    new_entries = {"model": [
        {"material": "KQvk", "fen": "new-fen", "dtm": 12,
         "stipulation": "h#6", "kind": "unique"},
    ]}
    merged = m.merge_themes(existing, new_entries, {"KQvk"})
    assert "capture" not in merged            # its only entry was for KQvk: gone, not count 0
    assert merged["model"]["count"] == 2
    fens = {p["fen"] for p in merged["model"]["problems"]}
    assert fens == {"kpvk-fen", "new-fen"}     # stale KQvk entry replaced, KPvk untouched


def test_main_merges_a_scoped_run_into_an_existing_index_and_themes(tmp_path, monkeypatch):
    """A run scoped to one material must not disturb another material's rows,
    and must replace -- not duplicate -- its own. Uses tmp_path throughout,
    never site/data."""
    m = _load()
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "KQvk.stats.json").write_text(json.dumps(STATS))

    out = tmp_path / "out"
    out.mkdir()
    (out / "materials.json").write_text(json.dumps([MATERIAL_ROW]))
    (out / "index.json").write_text(json.dumps([
        {"material": "KPvk", "pieces": 3, "stipulation": "h#6.5",
         "unique": 1, "duals": 1, "has_helpmate": True},
        {"material": "KQvk", "pieces": 3, "stipulation": "h#2.5",
         "unique": 3, "duals": 2, "has_helpmate": True},          # stale, must be replaced
    ]))
    (out / "themes.json").write_text(json.dumps({
        "model": {"count": 2, "problems": [
            {"material": "KPvk", "fen": "kpvk-fen", "dtm": 13,
             "stipulation": "h#6.5", "kind": "unique"},
            {"material": "KQvk", "fen": "stale-fen", "dtm": 5,
             "stipulation": "h#2.5", "kind": "unique"},
        ]},
    }))

    fake_doc = {
        "material": "KQvk", "pieces": 3,
        "stats": {"deepest_unique_dtm": 12, "unique_at_depth": 1,
                  "deepest_dual_dtm": 10, "strict_dual_dtm": 7,
                  "max_dtm": 14, "plane_size": 29568, "solvable": 45723,
                  "unique": 3064, "size_bytes": 71647,
                  "saturated_at_max": True, "dtm_histogram": {}},
        "unique": [{"fen": "new-fen", "dtm": 12, "themes": ["model"],
                    "stipulation": "h#6"}],
        "duals": [], "notes": [],
        "candidates_considered": 1, "candidates_total": 1,
    }
    monkeypatch.setattr(m, "build_material", lambda *a, **k: fake_doc)

    rc = m.main(["--tables", str(tables), "--binary", "x", "--out", str(out),
                "--material", "KQvk"])
    assert rc == 0

    index = json.loads((out / "index.json").read_text())
    assert {r["material"] for r in index} == {"KPvk", "KQvk"}
    kqvk = next(r for r in index if r["material"] == "KQvk")
    assert kqvk["stipulation"] == "h#6"                 # replaced, not duplicated
    kpvk = next(r for r in index if r["material"] == "KPvk")
    assert kpvk["stipulation"] == "h#6.5"               # untouched

    themes = json.loads((out / "themes.json").read_text())
    fens = {p["fen"] for p in themes["model"]["problems"]}
    assert fens == {"kpvk-fen", "new-fen"}
    assert themes["model"]["count"] == 2


def test_main_skips_materials_whose_row_is_not_done(tmp_path, monkeypatch):
    """A sidecar for a material materials.json lists as not done (a table being
    verified, say) gets no page; rows without a `done` key (old data) count as done."""
    bp = _load()
    tables, out = tmp_path / "tb", tmp_path / "out"
    tables.mkdir()
    out.mkdir()
    for m in ("KQvk", "KRvk", "KBvk"):
        (tables / f"{m}.stats.json").write_text(json.dumps({**STATS, "material": m}))
    (out / "materials.json").write_text(json.dumps([
        {"material": "KQvk", "done": True}, {"material": "KRvk", "done": False},
        {"material": "KBvk"}]))
    built = []

    def fake_build(binary, tables_dir, material, sc, row, attrib):
        built.append(material)
        return {"pieces": 3, "unique": [], "duals": [],
                "stats": {"deepest_unique_dtm": None, "solvable": 0}}

    monkeypatch.setattr(bp, "build_material", fake_build)
    assert bp.main(["--tables", str(tables), "--out", str(out)]) == 0
    assert built == ["KBvk", "KQvk"]
    assert not (out / "material" / "KRvk.json").exists()

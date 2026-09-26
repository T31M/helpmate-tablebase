"""tools/render_site.py: the static pages built from the committed JSON.

These pages are generated from data the site owns, but material and author
names still reach HTML as text, so escaping is tested rather than assumed.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "render_site", ROOT / "tools/render_site.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["render_site"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_page_is_a_complete_document_with_the_title():
    m = _load()
    html = m.page("KQvk", "<p>hi</p>")
    assert html.startswith("<!doctype html>")
    assert "<title>KQvk" in html
    assert "<p>hi</p>" in html
    assert html.rstrip().endswith("</html>")


def test_page_at_depth_one_reaches_assets_with_dotdot():
    m = _load()
    top = m.page("Themes", "", depth=0)
    nested = m.page("KQvk", "", depth=1)
    assert 'href="css/site.css"' in top
    assert 'href="../css/site.css"' in nested
    assert 'href="index.html"' in top
    assert 'href="../index.html"' in nested


def test_esc_neutralizes_markup_and_quotes():
    m = _load()
    assert m.esc('<b>"x"</b>') == "&lt;b&gt;&quot;x&quot;&lt;/b&gt;"
    assert m.esc(None) == ""
    assert m.esc(12) == "12"


def test_page_carries_the_description_when_given_one():
    m = _load()
    assert 'name="description" content="Deepest helpmates in KQvk"' in m.page(
        "KQvk", "", description="Deepest helpmates in KQvk")


PROBLEM = {
    "fen": "8/8/7k/6Q1/8/8/8/K7 b - - 0 1",
    "dtm": 12, "stipulation": "h#6", "count": 1, "starts": 1, "ends": 1,
    "themes": ["pure", "model", "single-piece:black"],
    "solutions": [[
        {"san": "Kh7", "uci": "h6h7", "fen": "8/7k/8/6Q1/8/8/8/K7 w - - 1 2"},
        {"san": "Qg7#", "uci": "g5g7", "fen": "8/6Qk/8/8/8/8/8/K7 b - - 2 2"},
    ]],
    "published": None, "published_by": None,
    "quality": {"capture_first": False, "check": False, "legal": True},
    "alternative": None,
}

DUAL = dict(PROBLEM, count=2, starts=2, ends=2, solutions=[
    PROBLEM["solutions"][0],
    [{"san": "Kh5", "uci": "h6h5", "fen": "8/8/8/6Qk/8/8/8/K7 w - - 1 2"},
     {"san": "Qg6#", "uci": "g5g6", "fen": "8/8/6Q1/7k/8/8/8/K7 b - - 2 2"}],
])

PUBLISHED = dict(PROBLEM,
                 published=[{"id": "P0530828", "author": "Niemann, John",
                             "sources": ["Schachmatt, No. 427, 13/07/1947"]}],
                 published_by="Niemann (1947)")

FLAWED = dict(PROBLEM, quality={"capture_first": True, "check": False, "legal": True})


def test_problem_html_carries_the_fen_and_the_stipulation():
    m = _load()
    out = m.problem_html(PROBLEM, 1)
    assert 'data-fen="8/8/7k/6Q1/8/8/8/K7 b - - 0 1"' in out
    assert "h#6" in out


def test_problem_html_lists_every_theme_linked_to_the_theme_index():
    m = _load()
    out = m.problem_html(PROBLEM, 1)
    assert '../themes.html#single-piece:black' in out
    assert ">pure<" in out and ">model<" in out


def test_problem_html_renders_both_solutions_of_a_dual():
    m = _load()
    out = m.problem_html(DUAL, 1)
    assert out.count('class="solution"') == 2
    assert "Qg7#" in out and "Qg6#" in out


def test_problem_html_embeds_the_plies_as_escaped_json_for_the_board():
    """The JSON rides in an HTML attribute, so its quotes are entity-escaped.

    Asserting the raw `"uci": "g5g7"` here would fail, and the tempting way to
    make that pass is to drop the escaping — which is exactly the bug. The
    browser unescapes `&quot;` when it reads `dataset.plies`, so what must hold
    is that the values survive and the attribute is escaped."""
    m = _load()
    out = m.problem_html(PROBLEM, 1)
    assert "data-plies='" in out
    assert "g5g7" in out and "Qg7#" in out
    assert "&quot;uci&quot;" in out
    # And it must round-trip the way the browser will read it.
    import html as html_mod
    import json as json_mod
    attr = out.split("data-plies='")[1].split("'")[0]
    assert json_mod.loads(html_mod.unescape(attr))[0][1]["uci"] == "g5g7"


def test_attribution_names_the_author_and_source_when_published():
    m = _load()
    out = m.attribution_html(PUBLISHED)
    assert "Niemann (1947)" in out
    assert "Schachmatt, No. 427, 13/07/1947" in out


def test_attribution_is_empty_for_an_unpublished_problem():
    m = _load()
    assert m.attribution_html(PROBLEM).strip() == ""


def test_a_flawed_problem_says_what_is_wrong():
    m = _load()
    out = m.problem_html(FLAWED, 1)
    assert "the solution begins with a capture" in out


# --- FIX 5: _quality_note is a deliberate clone of published_problems's
# quality_note (see its docstring) -- untested branches would drift silently.

def test_quality_note_illegal_diagram():
    m = _load()
    note = m._quality_note({"legal": False, "check": True, "capture_first": True})
    assert note == "the diagram has no legal last move, so it cannot arise in a game"


def test_quality_note_check_only():
    m = _load()
    note = m._quality_note({"legal": True, "check": True, "capture_first": False})
    assert note == "the side to move is in check in the diagram"


def test_quality_note_both_check_and_capture_first():
    m = _load()
    note = m._quality_note({"legal": True, "check": True, "capture_first": True})
    assert note == ("the side to move is in check in the diagram; "
                    "the solution begins with a capture")


def test_quality_note_none_or_missing_quality():
    m = _load()
    assert m._quality_note(None) == ""
    assert m._quality_note({}) == ""


def test_author_names_are_escaped():
    m = _load()
    nasty = dict(PROBLEM, published_by='<script>alert(1)</script>',
                 published=[{"id": "x", "author": "a", "sources": ["s"]}])
    assert "<script>" not in m.attribution_html(nasty)
    assert "&lt;script&gt;" in m.attribution_html(nasty)


DOC = {
    "material": "KQvk", "pieces": 3,
    "stats": {"max_dtm": 14, "deepest_unique_dtm": 12, "unique_at_depth": 3,
              "deepest_dual_dtm": 10, "strict_dual_dtm": 7, "plane_size": 29568,
              "solvable": 45723, "unique": 3064, "size_bytes": 71647,
              "saturated_at_max": True, "dtm_histogram": {}},
    "unique": [PROBLEM], "duals": [DUAL],
    "notes": ["Only one distinct idea exists at this depth: 3 positions share a solution."],
    "candidates_considered": 3, "candidates_total": 3,
}

MARKER = {
    "material": "Kvk", "pieces": 2,
    "stats": {"max_dtm": None, "deepest_unique_dtm": None, "unique_at_depth": 0,
              "deepest_dual_dtm": None, "strict_dual_dtm": None, "plane_size": 462,
              "solvable": 0, "unique": 0, "size_bytes": 466,
              "saturated_at_max": False, "dtm_histogram": {}},
    "unique": [], "duals": [],
    "notes": ["No helpmate exists in this material."],
    "candidates_considered": 0, "candidates_total": 0,
}

DOC_EQUAL_DUALS = {
    "material": "KQvk", "pieces": 3,
    "stats": {"max_dtm": 10, "deepest_unique_dtm": 8, "unique_at_depth": 2,
              "deepest_dual_dtm": 10, "strict_dual_dtm": 10, "plane_size": 29568,
              "solvable": 45723, "unique": 3064, "size_bytes": 71647,
              "saturated_at_max": True, "dtm_histogram": {}},
    "unique": [PROBLEM], "duals": [DUAL],
    "notes": [],
    "candidates_considered": 3, "candidates_total": 3,
}


def test_material_page_shows_both_problem_classes():
    m = _load()
    out = m.material_page(DOC)
    assert "KQvk" in out
    assert "Deepest unique" in out and "Deepest dual" in out
    assert out.count('class="problem"') == 2


def test_material_page_prints_the_notes_verbatim():
    m = _load()
    out = m.material_page(DOC)
    assert "Only one distinct idea exists at this depth" in out


def test_material_page_states_both_dual_depths_because_they_differ():
    """The strict dual is usually shallower than the deepest dual; say so."""
    m = _load()
    out = m.material_page(DOC)
    # Check that the explanatory note is present, explaining the distinction.
    assert "where the two solutions share a first or a last move" in out


def test_material_page_omits_dual_explanation_when_depths_are_equal():
    """When strict and deepest dual depths match, no explanation is needed."""
    m = _load()
    out = m.material_page(DOC_EQUAL_DUALS)
    # The explanatory note should NOT appear when the depths are equal.
    assert "where the two solutions share a first or a last move" not in out


def test_marker_material_gets_a_page_saying_no_helpmate_exists():
    m = _load()
    out = m.material_page(MARKER)
    assert "No helpmate exists in this material." in out
    assert 'class="problem"' not in out
    assert out.startswith("<!doctype html>")


def test_stats_html_formats_numbers_with_separators():
    m = _load()
    out = m.stats_html(DOC)
    assert "45,723" in out
    assert "3,064" in out


def test_material_page_links_back_to_the_materials_directory():
    m = _load()
    assert "../index.html#/materials" in m.material_page(DOC)


# --- FIX 1: attributing doc["notes"] to the section each one describes ----
#
# pick() emits at most one note per call, and only when it returned fewer
# than 3 problems -- verified against all 302 committed documents. So the
# first note belongs to the unique section iff len(unique) < 3, and the last
# belongs to the dual section iff len(duals) < 3.

DOC_TWO_NOTES = dict(DOC, notes=["unique section note text",
                                 "dual section note text"])

DOC_ONLY_DUAL_SHORT = dict(
    DOC, unique=[PROBLEM, PROBLEM, PROBLEM], duals=[DUAL],
    notes=["the only note, for the dual section"])

DOC_ONLY_UNIQUE_SHORT = dict(
    DOC, unique=[PROBLEM], duals=[DUAL, DUAL, DUAL],
    notes=["the only note, for the unique section"])

DOC_NOTE_COUNT_MISMATCH = dict(
    DOC, unique=[PROBLEM], duals=[DUAL, DUAL, DUAL],
    notes=["stray note one", "stray note two"])   # expected 1, got 2


def _section_of(html, title):
    """The markup of one named <section>, so a note can be located precisely.

    Stronger than asserting the note directly follows the <h2>: that only
    proves adjacency and breaks when a section legitimately carries a second
    note, while this proves the note is inside THAT section and, paired with
    the negative assertions, nowhere near the other one."""
    for m in re.finditer(r"<section>.*?</section>", html, re.S):
        if f"<h2>{title}</h2>" in m.group(0):
            return m.group(0)
    raise AssertionError(f"no section titled {title!r} in the page")


def test_material_page_splits_two_notes_across_the_two_sections():
    m = _load()
    out = m.material_page(DOC_TWO_NOTES)
    uniq = _section_of(out, "Deepest unique problems")
    dual = _section_of(out, "Deepest dual problems")
    assert "unique section note text" in uniq
    assert "unique section note text" not in dual
    assert "dual section note text" in dual
    assert "dual section note text" not in uniq


def test_material_page_attributes_the_single_note_to_the_short_dual_section():
    m = _load()
    out = m.material_page(DOC_ONLY_DUAL_SHORT)
    assert ("the only note, for the dual section"
            in _section_of(out, "Deepest dual problems"))
    assert 'class="note"' not in _section_of(out, "Deepest unique problems")


def test_material_page_attributes_the_single_note_to_the_short_unique_section():
    m = _load()
    out = m.material_page(DOC_ONLY_UNIQUE_SHORT)
    assert ("the only note, for the unique section"
            in _section_of(out, "Deepest unique problems"))
    dual = _section_of(out, "Deepest dual problems")
    assert "the only note, for the unique section" not in dual


def test_material_page_falls_back_to_floating_notes_on_a_count_mismatch():
    """A wrong label is worse than an unlabelled one: when the note count
    does not match the invariant, print them together, as before, rather
    than mis-attributing one to a section."""
    m = _load()
    out = m.material_page(DOC_NOTE_COUNT_MISMATCH)
    assert "stray note one" in out and "stray note two" in out
    # Neither stray note may be adopted by a section. Asserting on the
    # sections' own markup rather than on adjacency to the <h2>, because a
    # section may legitimately carry a depth note of its own.
    for title in ("Deepest unique problems", "Deepest dual problems"):
        sec = _section_of(out, title)
        assert "stray note one" not in sec
        assert "stray note two" not in sec
    # Floating, above both sections -- same place today's code puts it.
    assert out.index("stray note one") < out.index("<section>")


def test_marker_material_floats_its_single_note_above_the_sections():
    """A marker has exactly one note and no sections to attribute it to."""
    m = _load()
    out = m.material_page(MARKER)
    assert out.index("No helpmate exists in this material.") < out.index("<section>")


THEMES = {
    "model": {"count": 2, "problems": [
        {"material": "KQvk", "fen": "8/8/7k/6Q1/8/8/8/K7 b - - 0 1",
         "dtm": 12, "stipulation": "h#6", "kind": "unique"},
        {"material": "KRvk", "fen": "8/8/8/8/8/8/8/K1R2k2 b - - 0 1",
         "dtm": 10, "stipulation": "h#5", "kind": "dual"},
    ]},
    "single-piece:black": {"count": 1, "problems": [
        {"material": "KQvk", "fen": "8/8/7k/6Q1/8/8/8/K7 b - - 0 1",
         "dtm": 12, "stipulation": "h#6", "kind": "unique"},
    ]},
}
INDEX = [
    {"material": "KQvk", "pieces": 3, "stipulation": "h#6",
     "unique": 1, "duals": 1, "has_helpmate": True},
    {"material": "Kvk", "pieces": 2, "stipulation": None,
     "unique": 0, "duals": 0, "has_helpmate": False},
]


def test_themes_page_lists_every_theme_with_its_count():
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert ">model<" in out and "2 problems" in out
    assert "single-piece:black" in out and "1 problem<" in out


def test_each_theme_is_an_anchor_a_problem_can_link_to():
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert 'id="model"' in out
    assert 'id="single-piece:black"' in out


def test_theme_entries_link_to_the_material_page():
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert 'href="material/KQvk.html"' in out
    assert 'href="material/KRvk.html"' in out


def test_themes_page_distinguishes_unique_from_dual_problems():
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert "unique" in out and "dual" in out


def test_themes_page_says_how_many_themes_the_engine_implements():
    """Three different numbers, none of which may be confused for another:
    how many themes this site's problems show (2, from THEMES), how many the
    engine's registry can detect (28), and how many the glossary names (295).
    The old wording claimed the engine "detects directly from the tables"
    only the ones shown here, which is false -- 24 is how many the selected
    problems happen to exhibit, not the engine's ceiling."""
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert "2 themes" in out           # this site's problems
    assert "28 themes" in out          # the engine's registry
    assert "295" in out                # the glossary
    assert "33 registry entries" in out



def test_engine_theme_counts_match_usage():
    """The constants are copied by hand from docs/USAGE.md, which states them
    in words; a new theme that updates USAGE but not render_site.py drifted
    once already (30/26 after the registry grew to 33/28)."""
    import re
    words = {w: i for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve "
        "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
    tens = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}

    def number(w):
        head, _, unit = w.lower().partition("-")
        return tens[head] + (words[unit] if unit else 0) if head in tens else words[head]

    usage = (ROOT / "docs" / "USAGE.md").read_text()
    found = re.search(r"([A-Z][a-z-]+) registry entries cover ([a-z-]+) themes", usage)
    assert found, "USAGE.md no longer states the registry size"
    m = _load()
    assert (m.ENGINE_THEME_ENTRIES, m.ENGINE_THEMES) == (
        number(found.group(1)), number(found.group(2)))

def test_themes_page_uses_the_actual_problem_count_not_the_stored_one():
    """entry["count"] can drift from len(entry["problems"]) if something
    upstream is wrong; the page must render what it is actually listing."""
    m = _load()
    themes = {"model": {"count": 99, "problems": [
        {"material": "KQvk", "fen": "8/8/7k/6Q1/8/8/8/K7 b - - 0 1",
         "dtm": 12, "stipulation": "h#6", "kind": "unique"},
    ]}}
    out = m.themes_page(themes, INDEX)
    assert "1 problem<" in out
    assert "99" not in out


def test_themes_page_counts_the_materials_it_covers():
    m = _load()
    out = m.themes_page(THEMES, INDEX)
    assert "2 materials" in out


def test_main_writes_a_page_per_material_and_the_theme_index(tmp_path):
    m = _load()
    data = tmp_path / "data"
    (data / "material").mkdir(parents=True)
    (data / "material" / "KQvk.json").write_text(json.dumps(DOC))
    (data / "material" / "Kvk.json").write_text(json.dumps(MARKER))
    (data / "themes.json").write_text(json.dumps(THEMES))
    (data / "index.json").write_text(json.dumps(INDEX))
    out = tmp_path / "site"
    out.mkdir()

    assert m.main(["--data", str(data), "--out", str(out)]) == 0
    assert (out / "material" / "KQvk.html").exists()
    assert (out / "material" / "Kvk.html").exists()
    assert (out / "themes.html").exists()
    assert "KQvk" in (out / "material" / "KQvk.html").read_text()
    assert "No helpmate exists" in (out / "material" / "Kvk.html").read_text()


def test_main_is_idempotent(tmp_path):
    """make site runs this on every build; a rerun must not append or differ."""
    m = _load()
    data = tmp_path / "data"
    (data / "material").mkdir(parents=True)
    (data / "material" / "KQvk.json").write_text(json.dumps(DOC))
    (data / "themes.json").write_text(json.dumps(THEMES))
    (data / "index.json").write_text(json.dumps(INDEX))
    out = tmp_path / "site"
    out.mkdir()
    m.main(["--data", str(data), "--out", str(out)])
    first = (out / "material" / "KQvk.html").read_text()
    m.main(["--data", str(data), "--out", str(out)])
    assert (out / "material" / "KQvk.html").read_text() == first


def test_main_reports_missing_data_instead_of_writing_half_a_site(tmp_path):
    m = _load()
    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "site"
    out.mkdir()
    assert m.main(["--data", str(data), "--out", str(out)]) == 1

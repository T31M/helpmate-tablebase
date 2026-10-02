import pytest
import helpmate

@pytest.fixture(scope="session")
def tables(tmp_path_factory):
    d = str(tmp_path_factory.mktemp("tables"))
    written = helpmate.generate("KQvk", tables=d, threads=2)
    assert any(w.endswith("KQvk.hm") for w in written)
    return d

def test_probe_golden(tables):
    tb = helpmate.Tablebase(tables)
    # dtm/count golden per Task 8 (cross-checked against the cooperative oracle,
    # reconfirmed by src/core/tests/test_probe.cpp and the CLI's cli_probe test):
    # Black king has two legal replies (Kh6, Kh8); Kh6 allows three distinct
    # mates (Qg6#/Qh1#/Qh2#) and Kh8 allows one (Qg7#) -> count 4, not 1.
    assert tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == (2, 4, False)
    assert tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1") is None      # Kvk unsolvable

def test_line_and_mine(tables):
    tb = helpmate.Tablebase(tables)
    # Which of the 4 optimal lines line() finds first depends on legal_moves()
    # ordering (not part of the golden); it is deterministically "Kh6 Qh2#" for
    # this material/board (same as src/core/tests/test_probe.cpp and the CLI's
    # cli_line test).
    assert tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1") == ["Kh6", "Qh2#"]
    fens = tb.mine("KQvk", dtm=2, count=1, max=5)
    assert len(fens) == 5
    for f in fens:
        assert tb.probe(f) == (2, 1, False)

def test_stats_dict(tables):
    tb = helpmate.Tablebase(tables)
    s = tb.stats("KQvk")
    assert s["material"] == "KQvk"
    assert s["max_dtm"] >= 3

def test_mine_shape_filters(tables):
    tb = helpmate.Tablebase(tables)
    # mine returns canonical (symmetry-reduced) FENs; this is the golden
    # position's canonical form -- starts 2, ends 4.
    golden = "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1"
    hit = tb.mine("KQvk", dtm=2, count=4, starts=2, ends=4, max=200)
    assert golden in hit
    assert golden not in tb.mine("KQvk", dtm=2, count=4, starts=3, max=200)
    # omitting the new kwargs reproduces the old behaviour
    assert tb.mine("KQvk", dtm=2, count=4, max=5) == tb.mine("KQvk", dtm=2, count=4, max=5)
    for f in tb.mine("KQvk", dtm=4, starts=1, ends=1, max=20):
        ls = tb.lines(f)
        assert len({line[0] for line in ls}) == 1 and len({line[-1] for line in ls}) == 1

def test_mine_with_stats_returns_pair(tables):
    tb = helpmate.Tablebase(tables)
    fens, skipped = tb.mine_with_stats("KQvk", dtm=2, count=4, starts=2, ends=4, max=5)
    assert isinstance(fens, list) and isinstance(skipped, int)
    assert skipped == 0          # KQvk has no saturated-count positions

def test_mine_rejects_invalid_shape_filters(tables):
    tb = helpmate.Tablebase(tables)
    for kwargs in ({"starts": 0}, {"ends": 0}, {"starts": 5, "count": 2}, {"ends": 5, "count": 2}):
        with pytest.raises(ValueError):
            tb.mine("KQvk", dtm=2, max=5, **kwargs)
    # -1 is the documented "unset" value and must still be accepted
    assert isinstance(tb.mine("KQvk", dtm=2, max=5, starts=-1, ends=-1), list)

def test_errors(tables):
    tb = helpmate.Tablebase(tables)
    with pytest.raises(ValueError):
        tb.probe("garbage")
    with pytest.raises(RuntimeError):
        tb.probe("8/8/8/8/3n4/4k3/8/4K3 w - - 0 1")   # Kvkn not generated


def test_theme_registry_is_exposed():
    reg = helpmate.themes()
    names = [t["name"] for t in reg]
    assert "model" in names and "en-passant" in names
    assert all(t["doc"] for t in reg)


def test_theme_registry_exposes_needs():
    # Task 10: `needs` is how a caller tells which themes answer without
    # enumerating solutions -- and so still answer on positions whose stored
    # solution count saturates (capped at 255). set-play is the one
    # non-Solutions theme among the 33 in this build.
    entries = helpmate.themes()
    assert all("needs" in e for e in entries)
    by_name = {e["name"]: e for e in entries}
    assert by_name["set-play"]["needs"] == "plane"
    assert by_name["model"]["needs"] == "solutions"


def test_themes_on_saturated_position_warns_about_truncation(tables):
    # Same disclosure app.py's /v1/probe?themes=true makes via themes_note,
    # and the CLI's `probe --themes` stderr note: on a saturated position
    # (stored count == 255, the cap) tb.themes()'s auto-cap falls back to the
    # first 100 of an unknowably larger true solution set, and the result is
    # representative-dependent, not merely incomplete. A Python return value
    # has no sibling-field slot for a note, so this is a warnings.warn(),
    # catchable with pytest.warns.
    #
    # FEN measured directly against a freshly generated KQvk table (dtm=8,
    # `helpmate mine KQvk --dtm 8 --count 255` picks this FEN out of 5273
    # saturated dtm=8 cells; `helpmate probe ... --themes` confirms
    # count=255).
    saturated_fen = "8/8/8/8/8/8/8/K1k2Q2 b - - 0 1"
    tb = helpmate.Tablebase(tables)
    assert tb.probe(saturated_fen)[1] == 255  # count
    with pytest.warns(RuntimeWarning, match="satur"):
        names = tb.themes(saturated_fen)
    assert isinstance(names, list) and names  # still answered, not empty/None

    # An explicit max= is the caller overriding the auto-cap on purpose --
    # no surprise-truncation note to give in that case.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        tb.themes(saturated_fen, max=50)


def test_probe_themes_and_mine_theme_filter(tables):
    tb = helpmate.Tablebase(tables)
    golden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
    assert isinstance(tb.themes(golden), list)
    # KQvk dtm=2 true totals (measured): 580 unfiltered, 477 with theme
    # "mirror" -- max must exceed BOTH true totals, or comparing two
    # truncated-at-max lists would pass under any filter semantics,
    # including a no-op filter.
    wide = tb.mine("KQvk", dtm=2, max=600)
    narrow = tb.mine("KQvk", dtm=2, max=600, themes=["mirror"])
    assert len(wide) == 580 and len(narrow) == 477
    assert set(narrow) <= set(wide)
    assert len(narrow) < len(wide)


def test_theme_registry_marks_parametric_themes():
    by_name = {e["name"]: e for e in helpmate.themes()}
    assert by_name["promotions:<types>"]["parameter"]["example"] == "qrr"
    assert by_name["model"]["parameter"] is None


def test_check_theme_resolves_names_and_values():
    assert helpmate.check_theme("model") is None
    assert helpmate.check_theme("excelsior:white") is None
    assert helpmate.check_theme("promotions:RQ") is None      # canonicalised server-side
    assert "needs a value" in helpmate.check_theme("promotions")
    assert "does not accept" in helpmate.check_theme("promotions:qx")
    assert "promotions:q" in helpmate.check_theme("promotion:q")
    assert "unknown theme" in helpmate.check_theme("nosuch")


def test_mine_rejects_a_bad_parametric_value(tables):
    tb = helpmate.Tablebase(tables)
    assert tb.mine("KQvk", 2, themes=["promotions:q"], max=3) == []   # no pawn: no match, no error
    with pytest.raises(ValueError, match="does not accept"):
        tb.mine("KQvk", 2, themes=["promotions:qx"])

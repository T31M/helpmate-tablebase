#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include <set>

#include "themes/registry.h"

using namespace hm;
using namespace hm::themes;

static Solution at(const std::string& fen) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    return Solution{*b, {}};
}

TEST_CASE("the registry holds all thirty-three entries", "[themes][registry]") {
    REQUIRE(theme_registry().size() == 33);
}

TEST_CASE("every entry has a name, a detector or a parameter, and a doc", "[themes][registry]") {
    for (const auto& t : theme_registry()) {
        REQUIRE_FALSE(t.name.empty());
        // Exactly one of the two: a boolean detector, or a parametric family.
        REQUIRE((t.fn != nullptr) != (t.param != nullptr));
        if (t.param) {
            REQUIRE(t.param->canon != nullptr);
            REQUIRE(t.param->eval != nullptr);
            REQUIRE(t.param->values != nullptr);
            REQUIRE_FALSE(t.param->doc.empty());
            REQUIRE(t.param->canon(t.param->example).has_value());  // the example is valid
        }
        REQUIRE_FALSE(t.doc.empty());
    }
}

TEST_CASE("names are unique", "[themes][registry]") {
    std::set<std::string_view> seen;
    for (const auto& t : theme_registry()) REQUIRE(seen.insert(t.name).second);
}

TEST_CASE("every documented theme is findable by name", "[themes][registry]") {
    for (const char* n : {"pure",
                          "model",
                          "ideal",
                          "mirror",
                          "promotion",
                          "underpromotion",
                          "excelsior",
                          "excelsior:white",
                          "excelsior:black",
                          "switchback",
                          "closed-walk",
                          "self-block",
                          "single-piece",
                          "single-piece:white",
                          "single-piece:black",
                          "en-passant",
                          "kniest",
                          "zajic",
                          "phoenix",
                          "schnoebelen",
                          "pendulum",
                          "nocapture",
                          "nocheck",
                          "umnov",
                          "umnov-mate",
                          "klasinc",
                          "zilahi",
                          "allumwandlung",
                          "promotions",
                          "indian",
                          "maslar",
                          "maslar:black-white"})
        REQUIRE(find_theme(n) != nullptr);
}

TEST_CASE("an unknown name is not found", "[themes][registry]") {
    REQUIRE(find_theme("rundlauf") == nullptr);  // the English name is closed-walk
    REQUIRE(find_theme("") == nullptr);
    REQUIRE(find_theme("PURE") == nullptr);  // matching is exact, not case-folded
}

TEST_CASE("detect uses any semantics across solutions", "[themes][registry]") {
    // The back-rank model mate from test_mate_themes.cpp's kBase: black Kg8,
    // white Ra8 + Kg6. The brief's original FEN here (king on f7) is not even
    // checkmate -- h7 is an open, unattacked flight square -- so it was
    // replaced with the verified fixture; see task-5-report.md for the
    // discrepancy writeup.
    auto model_mate = at("R5k1/8/6K1/8/8/8/8/8 b - - 0 1");
    auto not_mate = at("8/8/8/8/8/8/8/K6k w - - 0 1");

    std::vector<Solution> both{not_mate, model_mate};
    ThemeInput both_in{model_mate.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, both};
    auto only_second = detect(both_in);
    REQUIRE(std::find(only_second.begin(), only_second.end(), "model") != only_second.end());

    std::vector<Solution> one{not_mate};
    ThemeInput one_in{not_mate.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, one};
    auto neither = detect(one_in);
    REQUIRE(std::find(neither.begin(), neither.end(), "model") == neither.end());
}

TEST_CASE("detect returns names in registry order", "[themes][registry]") {
    auto mate = at("R5k1/8/6K1/8/8/8/8/8 b - - 0 1");
    std::vector<Solution> sols{mate};
    ThemeInput in{mate.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    auto names = detect(in);
    size_t prev = 0;
    for (const auto& n : names) {
        size_t idx = 0;
        while (theme_registry()[idx].name != n) ++idx;
        REQUIRE(idx >= prev);
        prev = idx;
    }
}

TEST_CASE("detect on an empty solution set finds nothing", "[themes][registry]") {
    auto b = Board::from_fen("8/8/8/8/8/8/8/K6k w - - 0 1");
    REQUIRE(b);
    std::vector<Solution> sols;
    ThemeInput in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    REQUIRE(detect(in).empty());
}

TEST_CASE("any_of finds a theme shown by only ONE of several solutions", "[themes][registry]") {
    // This is the `any` path that any_of<> now owns, so the test must be able
    // to fail if any_of<> is broken. Solution 1 shows nothing; solution 2
    // really promotes -- built from a legal move the engine produced, never a
    // Ply typed by hand.
    auto b = Board::from_fen("8/P6k/8/8/8/8/8/K7 w - - 0 1");
    REQUIRE(b);
    const Move* promo = nullptr;
    auto legal = b->legal_moves();
    for (const auto& m : legal)
        if (m.promotion() == PieceType::Queen) promo = &m;
    REQUIRE(promo != nullptr);  // the fixture FEN really does allow a promotion

    Solution plain{*b, {}};
    Solution promoting{*b, {}};
    Ply p;
    p.piece = {Color::White, PieceType::Pawn};
    p.from = promo->from;
    p.to = promo->to;
    p.promotion = promo->promotion();
    Board after = *b;
    after.make(*promo);
    p.after = after;
    promoting.plies.push_back(p);

    std::vector<Solution> sols{plain, promoting};
    ThemeInput in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE(std::find(names.begin(), names.end(), "promotion") != names.end());
}

// all_of<> is the `every` counterpart of any_of<>, and nocapture/nocheck are
// the only registry entries on it. The fixtures below are built by
// Board::make from legal moves, never from a Ply typed by hand, so the
// `captured`/`is_check` flags are the ones the generator would set.
namespace {
int sq_of(const char* n) { return (n[1] - '1') * 8 + (n[0] - 'a'); }

struct RegMove {
    const char* from;
    const char* to;
    std::optional<PieceType> promo{};
};

Solution play_regs(const std::string& fen, const std::vector<RegMove>& moves) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    Solution s{*b, {}};
    Board cur = *b;
    for (const auto& [from, to, promo] : moves) {
        const Move* found = nullptr;
        auto legal = cur.legal_moves();
        for (const auto& m : legal)
            if ((int)m.from == sq_of(from) && (int)m.to == sq_of(to) && m.promotion() == promo) found = &m;
        REQUIRE(found != nullptr);
        Ply p;
        p.from = found->from;
        p.to = found->to;
        p.promotion = found->promotion();
        p.is_ep = found->is_ep();
        for (const auto& pp : cur.pieces()) {
            if ((int)pp.square == (int)found->from) p.piece = pp.piece;
            else if ((int)pp.square == (int)found->to) p.captured = pp.piece.type;
        }
        cur.make(*found);
        p.is_check = cur.in_check();
        p.after = cur;
        s.plies.push_back(std::move(p));
    }
    return s;
}

bool shows(const std::vector<std::string>& names, const char* n) {
    return std::find(names.begin(), names.end(), n) != names.end();
}
}  // namespace

TEST_CASE("all_of requires EVERY solution to qualify, unlike any_of", "[themes][registry]") {
    // The golden KQvk h#1: black Kh7, white Kf6 + Qg1. 1...Kh8 2.Qg7# is quiet
    // until the mate. A second, made-up line from the same diagram captures
    // nothing either, so the set is capture-free -- and then a third line
    // that takes the queen breaks it.
    const std::string fen = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
    Solution mate = play_regs(fen, {{"h7", "h8"}, {"g1", "g7"}});
    REQUIRE(mate.plies.back().is_check);
    REQUIRE_FALSE(mate.plies.front().is_check);
    Solution quiet = play_regs(fen, {{"h7", "h6"}, {"g1", "g2"}});

    std::vector<Solution> both{mate, quiet};
    ThemeInput both_in{mate.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, both};
    auto names = detect(both_in);
    REQUIRE(shows(names, "nocapture"));
    REQUIRE(shows(names, "nocheck"));

    // Black Kh7 + Bb6, white Kf6 + Qg1: 1...Bxg1 is a capture; 1...Kh8
    // 2.Qg7 is not.
    const std::string fen2 = "8/7k/1b3K2/8/8/8/8/6Q1 b - - 0 1";
    Solution takes = play_regs(fen2, {{"b6", "g1"}});
    REQUIRE(takes.plies.front().captured == PieceType::Queen);
    Solution keeps = play_regs(fen2, {{"h7", "h8"}, {"g1", "g7"}});
    std::vector<Solution> mixed{keeps, takes};
    ThemeInput mixed_in{keeps.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, mixed};
    auto mixed_names = detect(mixed_in);
    REQUIRE_FALSE(shows(mixed_names, "nocapture"));  // one capturing line is enough to break it
    REQUIRE(shows(mixed_names, "nocheck"));          // neither line checks before its last ply

    std::vector<Solution> only_keeps{keeps};
    ThemeInput keeps_in{keeps.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, only_keeps};
    REQUIRE(shows(detect(keeps_in), "nocapture"));
}

TEST_CASE("nocheck breaks on one solution that checks before its mate", "[themes][registry]") {
    // Black Ka8, white Ke2 + Qh1. 1.Qa1+ Kb8 is a check on the first ply;
    // 1.Qh3 Kb8 is quiet (Qh2 would guard b8 and make Kb8 illegal).
    const std::string fen = "k7/8/8/8/8/8/4K3/7Q w - - 0 1";
    Solution checking = play_regs(fen, {{"h1", "a1"}, {"a8", "b8"}});
    REQUIRE(checking.plies.front().is_check);
    Solution quiet = play_regs(fen, {{"h1", "h3"}, {"a8", "b8"}});
    std::vector<Solution> sols{quiet, checking};
    ThemeInput in{quiet.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE_FALSE(shows(names, "nocheck"));
    REQUIRE(shows(names, "nocapture"));

    std::vector<Solution> only_quiet{quiet};
    ThemeInput quiet_in{quiet.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, only_quiet};
    REQUIRE(shows(detect(quiet_in), "nocheck"));
}

TEST_CASE("the set-wide themes are not shown by an empty solution set", "[themes][registry]") {
    // Guarded separately from the generic empty-set test above because
    // all_of<> over nothing is vacuously true unless it refuses an empty set
    // -- and a position whose solutions could not be enumerated must not
    // read as capture-free.
    auto b = Board::from_fen("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    REQUIRE(b);
    std::vector<Solution> none;
    ThemeInput in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, none};
    auto names = detect(in);
    REQUIRE_FALSE(shows(names, "nocapture"));
    REQUIRE_FALSE(shows(names, "nocheck"));
}

TEST_CASE("display_name marks a parametric theme", "[themes][registry]") {
    REQUIRE(display_name(*find_theme("promotions")) == "promotions:<types>");
    REQUIRE(display_name(*find_theme("pure")) == "pure");
    REQUIRE(display_name(*find_theme("excelsior:white")) == "excelsior:white");
}

TEST_CASE("resolve_theme: exact names, parametric values, and every failure mode", "[themes][registry]") {
    std::string err;
    auto pure = resolve_theme("pure", &err);
    REQUIRE(pure);
    REQUIRE(pure->def->name == "pure");
    REQUIRE(pure->name() == "pure");

    // A colour variant is a full registry name, never `excelsior` with a value.
    auto ew = resolve_theme("excelsior:white", &err);
    REQUIRE(ew);
    REQUIRE(ew->def->name == "excelsior:white");
    REQUIRE(ew->value.empty());

    auto qrr = resolve_theme("promotions:RRQ", &err);
    REQUIRE(qrr);
    REQUIRE(qrr->def->name == "promotions");
    REQUIRE(qrr->value == "qrr");  // canonicalised
    REQUIRE(qrr->name() == "promotions:qrr");

    REQUIRE_FALSE(resolve_theme("promotions", &err));  // needs a value
    REQUIRE(err.find("needs a value") != std::string::npos);
    REQUIRE(err.find("promotions:qrr") != std::string::npos);

    REQUIRE_FALSE(resolve_theme("promotions:qx", &err));
    REQUIRE(err.find("does not accept") != std::string::npos);

    // The singular typo must not fall through to the boolean `promotion`.
    REQUIRE_FALSE(resolve_theme("promotion:qrr", &err));
    REQUIRE(err.find("promotions:qrr") != std::string::npos);

    REQUIRE_FALSE(resolve_theme("pure:yes", &err));  // a boolean takes no value
    REQUIRE(err.find("unknown theme") != std::string::npos);
    REQUIRE_FALSE(resolve_theme("nosuch", &err));
    REQUIRE(err.find("unknown theme \"nosuch\"") != std::string::npos);
}

TEST_CASE(
    "detect prints the combined promotion multiset of all solutions, and promotions:<types> "
    "matches any sub-multiset of it",
    "[themes][registry]") {
    auto b = Board::from_fen("k7/6P1/8/8/8/8/8/K7 w - - 0 1");
    REQUIRE(b);
    auto promote = [&](PieceType t) {
        const Move* found = nullptr;
        auto legal = b->legal_moves();
        for (const auto& m : legal)
            if (m.promotion() == t) found = &m;
        REQUIRE(found != nullptr);
        Solution s{*b, {}};
        Ply p;
        p.piece = {Color::White, PieceType::Pawn};
        p.from = found->from;
        p.to = found->to;
        p.promotion = t;
        Board after = *b;
        after.make(*found);
        p.after = after;
        s.plies.push_back(p);
        return s;
    };
    // Four solutions: queen, knight, queen, and one that does not promote.
    // Taken together that is q, q, n -- ONE value, printed once.
    std::vector<Solution> sols{promote(PieceType::Queen), promote(PieceType::Knight),
                               promote(PieceType::Queen), Solution{*b, {}}};
    ThemeInput in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE(shows(names, "promotions:qqn"));
    REQUIRE_FALSE(shows(names, "promotions:q"));  // per-solution values are not printed
    REQUIRE_FALSE(shows(names, "promotions:n"));
    REQUIRE_FALSE(shows(names, "promotions"));  // never printed bare
    REQUIRE_FALSE(shows(names, "allumwandlung"));

    // "At least these": every sub-multiset matches, anything asking for more
    // of a letter than the set has does not.
    auto ok = [&](const char* name) {
        auto t = resolve_theme(name);
        REQUIRE(t);
        return t->eval(in);
    };
    REQUIRE(ok("promotions:q"));
    REQUIRE(ok("promotions:qq"));
    REQUIRE(ok("promotions:n"));
    REQUIRE(ok("promotions:qn"));
    REQUIRE(ok("promotions:nqq"));  // typed order is irrelevant
    REQUIRE(ok("promotions:qqn"));
    REQUIRE_FALSE(ok("promotions:r"));
    REQUIRE_FALSE(ok("promotions:qqq"));  // three queens asked, two present
    REQUIRE_FALSE(ok("promotions:nn"));

    // A set in which nothing promotes prints no promotions entry and matches
    // no pattern at all. (Other names may still appear: a ply-less solution's
    // final board is the diagram, on which e.g. `mirror` reads true.)
    std::vector<Solution> none{Solution{*b, {}}, Solution{*b, {}}};
    ThemeInput none_in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, none};
    for (const auto& n : detect(none_in)) REQUIRE(n.rfind("promotions:", 0) != 0);
    REQUIRE_FALSE(resolve_theme("promotions:q")->eval(none_in));

    // Four lines, one per type: allumwandlung by coverage.
    std::vector<Solution> four{promote(PieceType::Queen), promote(PieceType::Rook),
                               promote(PieceType::Bishop), promote(PieceType::Knight)};
    ThemeInput four_in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, four};
    REQUIRE(shows(detect(four_in), "allumwandlung"));
    std::vector<Solution> three{promote(PieceType::Queen), promote(PieceType::Rook),
                                promote(PieceType::Bishop)};
    ThemeInput three_in{*b, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, three};
    REQUIRE_FALSE(shows(detect(three_in), "allumwandlung"));
}

TEST_CASE("zilahi: the unit that mates in one solution is captured in the other, and vice versa",
          "[themes][registry]") {
    // White Rc1 + Bf4 + Kh2; black Kh8 + Rb1. Line A: the rook is captured and
    // the bishop makes the last move. Line B: the bishop is captured and the
    // rook makes the last move. Neither line need be a real mate for the
    // detector, which reads the last ply's mover. (Kh2, not h1: after Rxc1
    // the black rook would check a king on h1 along the first rank.)
    const std::string fen = "7k/8/8/8/5B2/8/7K/1rR5 b - - 0 1";
    Solution a = play_regs(fen, {{"b1", "c1"}, {"f4", "e5"}});
    Solution b = play_regs(fen, {{"b1", "b4"}, {"h2", "g1"}, {"b4", "f4"}, {"c1", "c8"}});
    REQUIRE(a.plies[0].captured == PieceType::Rook);
    REQUIRE(b.plies[2].captured == PieceType::Bishop);
    std::vector<Solution> both{a, b};
    ThemeInput in{a.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, both};
    REQUIRE(shows(detect(in), "zilahi"));

    // Same bishop moves last in both lines: nothing is exchanged.
    Solution b_bishop = play_regs(fen, {{"b1", "b4"}, {"h2", "g1"}, {"b4", "c4"}, {"f4", "e5"}});
    std::vector<Solution> same{a, b_bishop};
    ThemeInput same_in{a.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, same};
    REQUIRE_FALSE(shows(detect(same_in), "zilahi"));

    // The bishop is captured, but the last mover is the king, not the rook.
    Solution b_king = play_regs(fen, {{"b1", "b4"}, {"h2", "g1"}, {"b4", "f4"}, {"g1", "h1"}});
    std::vector<Solution> king{a, b_king};
    ThemeInput king_in{a.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, king};
    REQUIRE_FALSE(shows(detect(king_in), "zilahi"));

    // One solution alone can never be a Zilahi.
    std::vector<Solution> one{a};
    ThemeInput one_in{a.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, one};
    REQUIRE_FALSE(shows(detect(one_in), "zilahi"));
}

TEST_CASE("promotions:qrr -- q and r in one solution, nothing in a second, r in a third",
          "[themes][registry]") {
    // The owner's worked example. White pawns a7 and g7 against a bare king
    // on h1, white Kc3 (nowhere near the promotion squares): line A promotes
    // both pawns (queen, then rook), line B is a quiet king shuffle, line C
    // promotes one pawn to a rook.
    const std::string fen = "8/P5P1/8/8/8/2K5/8/7k w - - 0 1";
    Solution a =
        play_regs(fen, {{"a7", "a8", PieceType::Queen}, {"h1", "h2"}, {"g7", "g8", PieceType::Rook}});
    Solution b = play_regs(fen, {{"c3", "d3"}, {"h1", "h2"}});
    Solution c = play_regs(fen, {{"g7", "g8", PieceType::Rook}, {"h1", "h2"}});
    std::vector<Solution> sols{a, b, c};
    ThemeInput in{a.start, ValuePair{DTM_UNSOLVABLE, 0}, std::nullopt, sols};
    auto names = detect(in);
    REQUIRE(shows(names, "promotions:qrr"));
    // exactly one promotions:* entry
    REQUIRE(std::count_if(names.begin(), names.end(),
                          [](const std::string& n) { return n.rfind("promotions:", 0) == 0; }) == 1);
    auto ok = [&](const char* name) {
        auto t = resolve_theme(name);
        REQUIRE(t);
        return t->eval(in);
    };
    REQUIRE(ok("promotions:qrr"));
    REQUIRE(ok("promotions:qr"));
    REQUIRE(ok("promotions:rr"));
    REQUIRE(ok("promotions:r"));
    REQUIRE_FALSE(ok("promotions:qrrr"));
    REQUIRE_FALSE(ok("promotions:qq"));
    REQUIRE_FALSE(ok("promotions:b"));
}

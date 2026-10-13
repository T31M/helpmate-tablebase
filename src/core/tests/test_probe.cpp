#include <catch2/catch_test_macros.hpp>
#include "probe/tablebase.h"
#include "generator/generator.h"
#include "format/table_file.h"
#include <algorithm>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <set>
#include <unistd.h>
using namespace hm;
static std::string gen_dir() {                        // one shared generated dir per test binary run
    static std::string dir = [] {
        auto d = std::filesystem::temp_directory_path() / "hm_probe";
        std::filesystem::remove_all(d); std::filesystem::create_directories(d);
        GenOptions opt; opt.tables_dir = d.string();
        generate(*Material::parse("KQvk"), opt);
        generate(*Material::parse("KPvk"), opt);
        return opt.tables_dir;
    }();
    return dir;
}
TEST_CASE("probe goldens with h-notation") {
    Tablebase tb(gen_dir());
    auto p = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    // dtm/count golden per Task 8 (cross-checked there against the cooperative
    // oracle): Black king has two legal replies (Kh6, Kh8); Kh6 allows three
    // distinct mates (Qg6#/Qh1#/Qh2#) and Kh8 allows one (Qg7#) -> count 4.
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 4); CHECK(!p->flipped);
    CHECK(Tablebase::h_notation(2, Color::Black) == "h#1");
    CHECK(Tablebase::h_notation(1, Color::White) == "h#0.5");
    CHECK(Tablebase::h_notation(0, Color::Black) == "h#0");
}
TEST_CASE("probe color-flipped position") {
    Tablebase tb(gen_dir());
    // color-flip of the dtm-2 golden: White king mated by black queen; only KQvk exists
    auto p = tb.probe("6q1/8/8/8/8/5k2/7K/8 w - - 0 1");
    REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->flipped);
}
TEST_CASE("line reconstruction") {
    Tablebase tb(gen_dir());
    auto l = tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    // one of the 4 optimal lines (which one is found first depends on legal_moves()
    // ordering, not part of the golden); every optimal line here is King-then-mate.
    REQUIRE(l.size() == 2);
    CHECK((l[0] == "Kh6" || l[0] == "Kh8"));
    CHECK(l[1].back() == '#');
    std::set<std::string> mates = {"Qg6#", "Qh1#", "Qh2#", "Qg7#"};
    CHECK(mates.count(l[1]) == 1);

    auto all = tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(all.size() == 4);                            // count == 4 (see golden above)
    std::set<std::pair<std::string, std::string>> got;
    for (auto& ln : all) { REQUIRE(ln.size() == 2); got.insert({ln[0], ln[1]}); }
    std::set<std::pair<std::string, std::string>> want = {
        {"Kh6", "Qg6#"}, {"Kh6", "Qh1#"}, {"Kh6", "Qh2#"}, {"Kh8", "Qg7#"}};
    CHECK(got == want);

    auto promo = tb.lines("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    REQUIRE(promo.size() == 2);                        // e8=Q# and e8=R#
    std::set<std::string> promo_moves;
    for (auto& ln : promo) { REQUIRE(ln.size() == 1); promo_moves.insert(ln[0]); }
    CHECK(promo_moves == std::set<std::string>{"e8=Q#", "e8=R#"});
}
TEST_CASE("mine finds unique-solution cells") {
    Tablebase tb(gen_dir());
    int found = 0;
    tb.mine(*Material::parse("KQvk"), MineFilter{.dtm = 2, .count = 1}, [&](const std::string& fen) {
        auto p = tb.probe(fen);
        REQUIRE(p); CHECK(p->dtm == 2); CHECK(p->count == 1);
        return ++found < 10;
    });
    CHECK(found == 10);
}
TEST_CASE("errors") {
    Tablebase tb(gen_dir());
    // Neither material nor its color flip was built: KQvk/KPvk closures only ever
    // give White a single extra piece (KQvk, KRvk, KBvk, KNvk, KPvk, Kvk); a
    // bishop+knight for Black (and its flip, KBNvk for White) is outside that set.
    CHECK_THROWS_AS(tb.probe("8/8/8/6b1/3n4/4k3/8/4K3 w - - 0 1"), MissingTableError);
    CHECK_THROWS_AS(tb.probe("garbage"), std::invalid_argument);
    CHECK_THROWS_AS(tb.stats_json(*Material::parse("KRvkr")), MissingTableError);
}
TEST_CASE("unsolvable probes to nullopt") {
    Tablebase tb(gen_dir());
    CHECK(!tb.probe("8/8/8/8/8/4k3/8/4K3 w - - 0 1"));   // Kvk was built as part of closures
}
TEST_CASE("mine takes a MineFilter and behaves as before for dtm/count") {
    Tablebase tb(gen_dir());
    Material kqvk = *Material::parse("KQvk");

    std::vector<std::string> got;
    tb.mine(kqvk, MineFilter{.dtm = 2, .count = 4}, [&](const std::string& f) {
        got.push_back(f); return got.size() < 50;
    });
    REQUIRE_FALSE(got.empty());
    // every returned position really has dtm 2 and count 4
    for (const auto& f : got) {
        auto p = tb.probe(f);
        REQUIRE(p.has_value());
        CHECK(p->dtm == 2);
        CHECK(p->count == 4);
    }
    // the golden position from the "probe goldens" test above is among them, in its
    // canonical form: mine() emits one canonical representative per symmetry class,
    // while probe() (used above) accepts any of its 8 symmetric-equivalent FENs.
    CHECK(std::find(got.begin(), got.end(),
                    "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1") != got.end());

    // count unset (-1) must not filter
    size_t any_count = 0;
    tb.mine(kqvk, MineFilter{.dtm = 2}, [&](const std::string&) {
        ++any_count; return any_count < 50; });
    CHECK(any_count >= got.size());
}
TEST_CASE("solution_shape counts distinct first and last moves") {
    Tablebase tb(gen_dir());

    // Golden KQvk position: 4 optimal lines -- Kh6 Qh2#, Kh6 Qh1#, Kh6 Qg6#, Kh8 Qg7#
    // => 2 distinct first moves (Kh6, Kh8), 4 distinct mating moves.
    auto sh = tb.solution_shape("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    CHECK(sh.exhaustive);
    CHECK(sh.starts == 2);
    CHECK(sh.ends == 4);

    // A position already mated (dtm 0) has no moves at all.
    auto mated = tb.solution_shape("8/8/8/8/8/8/8/kQK5 b - - 0 1");
    CHECK(mated.exhaustive);
    CHECK(mated.starts == 0);
    CHECK(mated.ends == 0);

    // Unsolvable position: bare kings.
    auto uns = tb.solution_shape("8/8/8/8/8/4k3/8/4K3 w - - 0 1");
    CHECK(uns.exhaustive);
    CHECK(uns.starts == 0);
    CHECK(uns.ends == 0);
}

TEST_CASE("mine filters on distinct starting and mating moves") {
    Tablebase tb(gen_dir());
    Material kqvk = *Material::parse("KQvk");
    // mine emits canonical (symmetry-reduced) FENs -- this is the golden
    // position's canonical form: same 4 solutions, starts 2, ends 4.
    const std::string golden = "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1";

    auto collect = [&](MineFilter f, int cap = 200) {
        std::vector<std::string> out;
        uint64_t skipped = 0;
        tb.mine(kqvk, f, [&](const std::string& s) {
            out.push_back(s); return (int)out.size() < cap; }, &skipped);
        return out;
    };

    // The golden position has starts 2, ends 4 -- it must appear only for those values.
    auto hit = collect(MineFilter{.dtm = 2, .count = 4, .starts = 2, .ends = 4});
    CHECK(std::find(hit.begin(), hit.end(), golden) != hit.end());

    auto miss_starts = collect(MineFilter{.dtm = 2, .count = 4, .starts = 3, .ends = 4});
    CHECK(std::find(miss_starts.begin(), miss_starts.end(), golden) == miss_starts.end());

    auto miss_ends = collect(MineFilter{.dtm = 2, .count = 4, .starts = 2, .ends = 3});
    CHECK(std::find(miss_ends.begin(), miss_ends.end(), golden) == miss_ends.end());

    // Every position returned under a starts/ends filter really has that shape.
    for (const auto& f : collect(MineFilter{.dtm = 4, .starts = 1, .ends = 1}, 40)) {
        auto sh = tb.solution_shape(f);
        CHECK(sh.exhaustive);
        CHECK(sh.starts == 1);
        CHECK(sh.ends == 1);
    }

    // Filtering on only one of the two works.
    for (const auto& f : collect(MineFilter{.dtm = 2, .starts = 1}, 40))
        CHECK(tb.solution_shape(f).starts == 1);
}

TEST_CASE("shape_of reports saturation and counts distinct endpoints") {
    using L = std::vector<std::vector<std::string>>;
    // Saturated: the line set cannot be complete, so no numbers are reported.
    auto sat = shape_of(255, L{{"Kh6", "Qh2#"}});
    CHECK_FALSE(sat.exhaustive);
    CHECK(sat.starts == 0);
    CHECK(sat.ends == 0);
    // The golden shape: 4 lines, 2 distinct first moves, 4 distinct mating moves.
    auto g = shape_of(4, L{{"Kh6","Qh2#"},{"Kh6","Qh1#"},{"Kh6","Qg6#"},{"Kh8","Qg7#"}});
    CHECK(g.exhaustive); CHECK(g.starts == 2); CHECK(g.ends == 4);
    // Already mate: lines() yields one empty line.
    auto m = shape_of(1, L{{}});
    CHECK(m.exhaustive); CHECK(m.starts == 0); CHECK(m.ends == 0);
    // No solutions at all.
    auto n = shape_of(0, L{});
    CHECK(n.exhaustive); CHECK(n.starts == 0); CHECK(n.ends == 0);
}

// Final-review fix: a future-format PRIMARY table must not preempt probe()'s
// color-flip fallback. Reproduces the reviewer's exact case: a valid KQvk
// closure (from gen_dir()) plus a hand-crafted future-version Kvkq.hm -- the
// primary material for the probed FEN -- in the same directory.
namespace {
std::filesystem::path copy_gen_dir_to_scratch(const std::string& tag) {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_probe_future_" + tag + "_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    for (auto& entry : fs::directory_iterator(gen_dir()))
        fs::copy(entry.path(), dir / entry.path().filename(), fs::copy_options::overwrite_existing);
    return dir;
}
void patch_table_version(const std::string& path, uint32_t v) {
    std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
    f.seekp(offsetof(TableHeader, version));
    f.write(reinterpret_cast<const char*>(&v), sizeof(v));
}
}  // namespace

TEST_CASE("probe falls back to color flip past a future-version primary table") {
    namespace fs = std::filesystem;
    Material kvkq = *Material::parse("Kvkq");

    fs::path dir = copy_gen_dir_to_scratch("flip_ok");
    std::string kvkq_path = (dir / "Kvkq.hm").string();
    // Kvkq is never in the KQvk/KPvk closures generated by gen_dir() (no
    // capture/promotion reaches it -- it's KQvk's color flip, not a successor),
    // so this file doesn't already exist; hand-craft it as a future-version table.
    TableWriter::write_unsolvable(kvkq_path, kvkq, SliceIndex(kvkq).size(), "{}");
    patch_table_version(kvkq_path, 99);

    Tablebase tb(dir.string());
    auto p = tb.probe("4k2q/8/8/8/8/8/8/4K3 w - - 0 1");
    REQUIRE(p);
    CHECK(p->dtm == 8);
    CHECK(p->count == 32);
    CHECK(p->flipped);
}

TEST_CASE("probe rethrows UnsupportedTableVersionError when both primary and flip are unusable") {
    namespace fs = std::filesystem;
    Material kvkq = *Material::parse("Kvkq");

    fs::path dir = copy_gen_dir_to_scratch("both_bad");
    std::string kvkq_path = (dir / "Kvkq.hm").string();
    TableWriter::write_unsolvable(kvkq_path, kvkq, SliceIndex(kvkq).size(), "{}");
    patch_table_version(kvkq_path, 99);
    patch_table_version((dir / "KQvk.hm").string(), 99);  // the color flip's table, also future-format

    Tablebase tb(dir.string());
    CHECK_THROWS_AS(tb.probe("4k2q/8/8/8/8/8/8/4K3 w - - 0 1"), UnsupportedTableVersionError);
}

TEST_CASE("moves lists every legal move with the value it leads to") {
    Tablebase tb(gen_dir());
    auto ms = tb.moves("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");

    // Black king on h7, White king f6 covers g6/g7/h6... the black king's legal
    // moves are exactly Kh6 and Kh8 (g8 is covered by nothing, but g7/g6 are).
    std::set<std::string> sans;
    for (const auto& m : ms) sans.insert(m.san);
    CHECK(sans.count("Kh6") == 1);
    CHECK(sans.count("Kh8") == 1);

    // Both are optimal (they lead to dtm 1 from this dtm-2 position).
    for (const auto& m : ms) {
        INFO("move " << m.san);
        if (m.san == "Kh6" || m.san == "Kh8") {
            CHECK(m.optimal);
            CHECK(m.solvable);
            CHECK(m.dtm == 1);
        } else {
            CHECK_FALSE(m.optimal);
        }
        // every entry carries a usable resulting position
        auto after = Board::from_fen(m.fen);
        CHECK(after.has_value());
        CHECK_FALSE(m.uci.empty());
    }
    // the number of optimal moves matches the distinct first moves of the
    // optimal lines (Kh6, Kh8) -- see the golden lines in the plan header
    int opt = 0;
    for (const auto& m : ms) if (m.optimal) ++opt;
    CHECK(opt == 2);
}

TEST_CASE("moves reports unsolvable children instead of hiding them") {
    Tablebase tb(gen_dir());
    // dtm-0 position: Black is already mated, so there are no legal moves.
    CHECK(tb.moves("8/8/8/8/8/8/8/kQK5 b - - 0 1").empty());
    // A position where a capture leads into Kvk (unsolvable): the move must be
    // listed with solvable=false rather than dropped or throwing.
    // Fixture verified with a scratch Board::legal_moves() dump: black king h8,
    // white queen h7, white king a1, black to move -- the only legal move is
    // Kxh7 (a genuine capture; the a1 king defends nothing relevant to h7).
    auto ms = tb.moves("7k/7Q/8/8/8/8/8/K7 b - - 0 1");
    bool saw_capture = false;
    for (const auto& m : ms)
        if (m.san.find('x') != std::string::npos) {
            saw_capture = true;
            CHECK_FALSE(m.optimal);
            CHECK_FALSE(m.solvable);
            CHECK(m.dtm == -1);
        }
    INFO("this FEN must offer at least one capture for the test to mean anything");
    CHECK(saw_capture);
}

TEST_CASE("moves reports a child with no table as unsolvable, without throwing") {
    namespace fs = std::filesystem;
    // A scratch copy of the generated tables with Kvk.hm REMOVED: capturing the
    // queen now leads to material whose table is genuinely absent, which is the
    // only way to exercise moves()'s MissingTableError guard (the KQvk closure
    // always builds Kvk, so an unmodified tables dir cannot reach this path).
    fs::path dir = fs::temp_directory_path() / ("hm_moves_notable_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    for (const auto& e : fs::directory_iterator(gen_dir()))
        fs::copy_file(e.path(), dir / e.path().filename());
    fs::remove(dir / "Kvk.hm");

    Tablebase tb(dir.string());
    auto ms = tb.moves("7k/7Q/8/8/8/8/8/K7 b - - 0 1");   // only legal move: Kxh7 -> Kvk
    REQUIRE(ms.size() == 1);
    CHECK(ms[0].san == "Kxh7");
    CHECK_FALSE(ms[0].solvable);      // no table -> reported, not thrown
    CHECK(ms[0].dtm == -1);
    CHECK_FALSE(ms[0].optimal);
    fs::remove_all(dir);
}

TEST_CASE("moves rejects a bad FEN like probe does") {
    Tablebase tb(gen_dir());
    CHECK_THROWS_AS(tb.moves("garbage"), std::invalid_argument);
}

TEST_CASE("a king capture is reported as valueless, not thrown") {
    // The position editor can build a position where the side NOT to move is
    // already in check; capturing that king is then a "legal move" whose
    // result no tablebase can describe. The move list must stay complete and
    // the request must not fail with an invalid_fen naming a FEN the caller
    // never sent.
    Tablebase tb(gen_dir());
    auto ms = tb.moves("7k/8/8/8/8/8/8/K6Q w - - 0 1");   // Rh1-style check on h8
    REQUIRE_FALSE(ms.empty());
    auto it = std::find_if(ms.begin(), ms.end(),
                           [](const MoveInfo& m) { return m.uci == "h1h8"; });
    REQUIRE(it != ms.end());
    CHECK_FALSE(it->solvable);
    CHECK(it->dtm == -1);
    CHECK_FALSE(it->optimal);
}

TEST_CASE("mine gives the single-threaded FENs and tally on any thread count") {
    Tablebase tb(gen_dir());
    struct Query {
        const char* material;
        MineFilter f;
    };
    // A plain filter, a shape filter, a solutions theme that skips saturated
    // cells (KQvk dtm 8), a sibling-plane theme, and pawn material.
    const std::vector<Query> queries = {
        {"KQvk", MineFilter{.dtm = 2}},
        {"KQvk", MineFilter{.dtm = 4, .starts = 1, .ends = 1}},
        {"KQvk", MineFilter{.dtm = 8, .themes = {"mirror"}}},
        {"KQvk", MineFilter{.dtm = 8, .themes = {"set-play"}}},
        {"KPvk", MineFilter{.dtm = 5}},
    };
    auto run = [&](const Query& q, int threads, int cap) {
        std::vector<std::string> out;
        uint64_t skipped = 0;
        tb.mine(
            *Material::parse(q.material), q.f,
            [&](const std::string& fen) {
                if ((int)out.size() >= cap) return false;
                out.push_back(fen);
                return (int)out.size() < cap;
            },
            &skipped, threads);
        return std::make_pair(out, skipped);
    };
    for (const auto& q : queries) {
        auto full = run(q, 1, 1 << 30);
        REQUIRE_FALSE(full.first.empty());
        // A stop before the first FEN, inside the scan, and after the end.
        for (int cap : {0, 1, 7, (int)full.first.size() / 2 + 1, 1 << 30}) {
            auto one = run(q, 1, cap);
            for (int threads : {2, 3, 8}) {
                INFO(q.material << " dtm " << q.f.dtm << " threads " << threads << " cap " << cap);
                auto many = run(q, threads, cap);
                CHECK(many.first == one.first);
                CHECK(many.second == one.second);
            }
        }
    }
}

TEST_CASE("multi-threaded mine reports a missing table as one thread does") {
    Tablebase tb(gen_dir());
    MineFilter f{.dtm = 2};
    for (int threads : {1, 4})
        CHECK_THROWS_AS(
            tb.mine(
                *Material::parse("KRBvk"), f, [](const std::string&) { return true; }, nullptr, threads),
            MissingTableError);
}

TEST_CASE("mine --starts selects exactly what solution_shape says") {
    // The scan rejects a candidate early when it has fewer optimal root moves
    // than --starts; the selection must still equal the full enumeration's.
    Tablebase tb(gen_dir());
    for (const auto& [material, dtm] :
         std::vector<std::pair<std::string, int>>{{"KQvk", 2}, {"KQvk", 4}, {"KPvk", 3}, {"KPvk", 5}}) {
        auto m = *Material::parse(material);
        std::vector<std::string> all;
        tb.mine(m, MineFilter{.dtm = dtm}, [&](const std::string& f) {
            all.push_back(f);
            return true;
        });
        REQUIRE_FALSE(all.empty());
        std::vector<SolutionShape> shapes;
        for (const auto& f : all) shapes.push_back(tb.solution_shape(f));
        for (int starts : {1, 2, 3}) {
            for (int ends : {-1, 1, 2}) {
                INFO(material << " dtm " << dtm << " starts " << starts << " ends " << ends);
                std::vector<std::string> want;
                for (size_t i = 0; i < all.size(); ++i) {
                    const auto& sh = shapes[i];
                    if (sh.exhaustive && sh.starts == starts && (ends < 0 || sh.ends == ends))
                        want.push_back(all[i]);
                }
                std::vector<std::string> got;
                uint64_t skipped = 0;
                tb.mine(
                    m, MineFilter{.dtm = dtm, .starts = starts, .ends = ends},
                    [&](const std::string& f) {
                        got.push_back(f);
                        return true;
                    },
                    &skipped);
                CHECK(got == want);
            }
        }
    }
}

TEST_CASE("mine on compressed tables with one small shared cache matches the raw tables") {
    // Compressed copies of the same materials; a shared cache of one 64 KiB
    // block makes every table switch evict, at 1 and 4 threads.
    static std::string zdir = [] {
        namespace fs = std::filesystem;
        auto d = fs::temp_directory_path() / "hm_probe_z";
        fs::remove_all(d);
        fs::create_directories(d);
        for (const auto& e : fs::directory_iterator(gen_dir())) {
            if (e.path().extension() != ".hm") continue;
            auto src = TableReader::open(e.path().string());
            REQUIRE(src.has_value());
            if (src->all_unsolvable()) fs::copy_file(e.path(), d / e.path().filename());
            else TableWriter::compress_existing((d / e.path().filename()).string(), *src);
        }
        return d.string();
    }();
    Tablebase raw(gen_dir());
    Tablebase shared(zdir, kDefaultBlockSize);
    const std::vector<std::pair<std::string, MineFilter>> queries = {
        {"KQvk", MineFilter{.dtm = 4, .starts = 1, .ends = 1}},
        {"KQvk", MineFilter{.dtm = 4, .themes = {"mirror"}}},
        {"KPvk", MineFilter{.dtm = 5, .starts = 2}},
    };
    auto run = [](const Tablebase& tb, const std::pair<std::string, MineFilter>& q, int threads) {
        std::vector<std::string> out;
        uint64_t skipped = 0;
        tb.mine(
            *Material::parse(q.first), q.second,
            [&](const std::string& f) {
                out.push_back(f);
                return true;
            },
            &skipped, threads);
        return std::make_pair(out, skipped);
    };
    for (const auto& q : queries) {
        INFO(q.first << " dtm " << q.second.dtm);
        auto want = run(raw, q, 1);
        REQUIRE_FALSE(want.first.empty());
        for (int threads : {1, 4}) CHECK(run(shared, q, threads) == want);
    }
    CHECK(shared.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")->count == 4);
}

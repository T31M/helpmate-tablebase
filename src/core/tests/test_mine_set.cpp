#include <algorithm>
#include <catch2/catch_test_macros.hpp>
#include <climits>
#include <filesystem>
#include <nlohmann/json.hpp>
#include <sstream>

#include "generator/generator.h"
#include "probe/mine_set.h"
#include "themes/registry.h"

using namespace hm;

namespace {
std::string gen_kqvk() {
    static std::string dir;
    if (dir.empty()) {
        dir = (std::filesystem::temp_directory_path() / "hm_mine_set_test").string();
        std::filesystem::create_directories(dir);
        GenOptions opt;
        opt.tables_dir = dir;
        generate(*Material::parse("KQvk"), opt);
    }
    return dir;
}
const char* kGolden = "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1";
const char* kFirst = "8/8/8/8/8/8/8/k1KQ4 b - - 0 1";
const char* kSecond = "8/8/8/8/8/2Q5/8/k1K5 b - - 0 1";

MineSet kqvk_set(const Tablebase& tb, int dtm = 2, int cap = INT_MAX) {
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = dtm}, cap);
    uint64_t skipped = 0;
    tb.mine(
        *Material::parse("KQvk"), MineFilter{.dtm = dtm},
        [&](const std::string& f) {
            s.add(f);
            return (int)s.size() < cap;
        },
        &skipped);
    s.set_skipped_saturated(skipped);
    return s;
}
}  // namespace

TEST_CASE("MineSet::add probes dtm and count", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 10);
    REQUIRE(s.size() == 0);
    s.add(kGolden);
    s.add(kFirst);
    REQUIRE(s.size() == 2);
    REQUIRE(s.hits()[0].fen == kGolden);
    REQUIRE(s.hits()[0].dtm == 2);
    REQUIRE(s.hits()[0].count == 4);
    REQUIRE(s.hits()[1].count == 1);
    REQUIRE_FALSE(s.hits()[0].shape.has_value());  // nothing enriched yet
    REQUIRE(s.max() == 10);
    REQUIRE(s.filter().dtm == 2);
    REQUIRE(s.material().name() == "KQvk");
}

TEST_CASE("MineSet loads a whole scan", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb);
    REQUIRE(s.size() == 580);
    REQUIRE(s.hits()[0].fen == kFirst);
    REQUIRE(s.hits()[1].fen == kSecond);
    REQUIRE(s.skipped_saturated() == 0);
    REQUIRE(s.max() == INT_MAX);
}

TEST_CASE("non_parametric drops parametric entries only", "[mine_set]") {
    std::vector<std::string> in{"mirror", "promotions:q", "single-piece:white", "promotions:qrr"};
    auto out = non_parametric(in);
    REQUIRE(out == std::vector<std::string>{"mirror", "single-piece:white"});
    // Sanity: the registry really has exactly one parametric entry today.
    int parametric = 0;
    for (const auto& t : themes::theme_registry()) parametric += t.param != nullptr;
    REQUIRE(parametric == 1);
}

TEST_CASE("enrichment fills shape, themes and solutions once", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 10);
    s.add(kGolden);
    Hit h = s.hits()[0];
    s.ensure_shape(h);
    REQUIRE(h.shape);
    REQUIRE(h.shape->starts == 2);
    REQUIRE(h.shape->ends == 4);
    s.ensure_solutions(h);
    REQUIRE(h.solutions);
    REQUIRE(h.solutions->size() == 4);
    REQUIRE((*h.solutions)[3] == std::vector<std::string>{"Kh8", "Qg7#"});
    s.ensure_themes(h);
    REQUIRE(h.themes);
    auto& t = *h.themes;
    REQUIRE(std::find(t.begin(), t.end(), "mirror") != t.end());
    for (const auto& n : t) REQUIRE(themes::resolve_theme(n)->def->param == nullptr);
    REQUIRE(h.unavailable.empty());
}

TEST_CASE("ensure_themes_all reports progress and is idempotent", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb, 2, 250);
    REQUIRE(s.size() == 250);
    REQUIRE_FALSE(s.all_have_themes());
    std::vector<std::pair<size_t, size_t>> ticks;
    s.ensure_themes_all([&](size_t d, size_t t) { ticks.emplace_back(d, t); });
    REQUIRE(s.all_have_themes());
    REQUIRE_FALSE(ticks.empty());
    REQUIRE(ticks.back() == std::pair<size_t, size_t>{250, 250});
    ticks.clear();
    s.ensure_themes_all([&](size_t d, size_t t) { ticks.emplace_back(d, t); });
    REQUIRE(ticks.empty());  // nothing left to do: no callback at all
    REQUIRE(s.unavailable_count() == 0);
}

TEST_CASE("a hit whose enrichment needs a missing table is marked, not dropped", "[mine_set]") {
    // A Tablebase over an EMPTY directory: probe/solutions throw MissingTableError.
    auto empty = (std::filesystem::temp_directory_path() / "hm_mine_set_empty").string();
    std::filesystem::create_directories(empty);
    Tablebase tb(empty);
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 10);
    Hit h;
    h.fen = kGolden;
    h.dtm = 2;
    h.count = 4;
    s.add(h);
    Hit copy = s.hits()[0];
    s.ensure_themes(copy);
    REQUIRE_FALSE(copy.themes);
    REQUIRE_FALSE(copy.unavailable.empty());
    s.ensure_solutions(copy);  // skipped: already unavailable, must not throw
    REQUIRE_FALSE(copy.solutions);
    s.ensure_themes_all();
    REQUIRE(s.unavailable_count() == 1);
    // An unavailable hit never matches a theme narrowing -- with OR without
    // negate. "not mirror" must not quietly re-admit what "mirror" dropped.
    REQUIRE(s.with_theme("mirror", false).size() == 0);
    REQUIRE(s.with_theme("mirror", true).size() == 0);
}

TEST_CASE("with_theme narrows, negates, and leaves the source intact", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb);
    auto mirror = s.with_theme("mirror", false);
    auto rest = s.with_theme("mirror", true);
    REQUIRE(s.size() == 580);
    REQUIRE(mirror.size() == 477);
    REQUIRE(rest.size() == 103);
    REQUIRE(mirror.hits()[0].fen == kFirst);
    REQUIRE(rest.hits()[0].fen == kSecond);
    REQUIRE(mirror.material().name() == "KQvk");
    REQUIRE(mirror.max() == INT_MAX);
    // the source was enriched as a side effect, so a second narrowing is free
    REQUIRE(s.all_have_themes());
    REQUIRE_THROWS_AS(s.with_theme("nosuch", false), std::invalid_argument);
}

TEST_CASE("with_theme accepts a parametric name", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb, 2, 20);
    auto promo = s.with_theme("promotions:q", false);  // no pawn in KQvk
    REQUIRE(promo.size() == 0);
    auto nopromo = s.with_theme("promotions:q", true);
    REQUIRE(nopromo.size() == 20);
}

TEST_CASE("count/starts/ends narrowing", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb);
    REQUIRE(s.with_count(1).size() == 356);
    REQUIRE(s.with_theme("mirror", false).with_count(1).size() == 257);
    MineSet g(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 10);
    g.add(kGolden);
    g.add(kFirst);
    REQUIRE(g.with_starts(2).size() == 1);
    REQUIRE(g.with_ends(4).size() == 1);
    REQUIRE(g.with_ends(1).hits()[0].fen == kFirst);
    REQUIRE(g.with_starts(3).size() == 0);
}

TEST_CASE("enrichment on several threads gives the single-threaded results", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto fens = [](const MineSet& s) {
        std::vector<std::string> out;
        for (const auto& h : s.hits()) out.push_back(h.fen);
        return out;
    };
    auto one = kqvk_set(tb, 4);
    auto many = kqvk_set(tb, 4);
    many.set_threads(4);
    REQUIRE(one.size() > 100);

    std::vector<std::pair<size_t, size_t>> ticks;
    auto mirror_many =
        many.with_theme("mirror", false, [&](size_t d, size_t t) { ticks.emplace_back(d, t); });
    REQUIRE_FALSE(ticks.empty());
    REQUIRE(ticks.back() == std::pair<size_t, size_t>{many.size(), many.size()});
    for (const auto& [d, t] : ticks) REQUIRE(d <= t);
    ticks.clear();
    many.ensure_themes_all([&](size_t d, size_t t) { ticks.emplace_back(d, t); });
    REQUIRE(ticks.empty());  // nothing left to do: no callback at all

    CHECK(fens(mirror_many) == fens(one.with_theme("mirror", false)));
    CHECK(fens(many.with_theme("mirror", true)) == fens(one.with_theme("mirror", true)));
    CHECK(fens(many.with_theme("promotions:q", true)) == fens(one.with_theme("promotions:q", true)));
    // A derived set keeps the thread count and the workers.
    CHECK(fens(mirror_many.with_ends(1)) == fens(one.with_theme("mirror", false).with_ends(1)));
    CHECK(fens(many.with_starts(1)) == fens(one.with_starts(1)));
    CHECK(many.theme_histogram() == one.theme_histogram());
    MineSet::Facets all{.themes = true, .solutions = true};
    CHECK(many.to_json(all) == one.to_json(all));

    // A missing table still marks the hit instead of failing the batch.
    auto empty = (std::filesystem::temp_directory_path() / "hm_mine_set_empty_mt").string();
    std::filesystem::create_directories(empty);
    Tablebase none(empty);
    MineSet s(none, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 10);
    for (const char* f : {kGolden, kFirst, kSecond}) {
        Hit h;
        h.fen = f;
        h.dtm = 2;
        h.count = 1;
        s.add(h);
    }
    s.set_threads(3);
    s.ensure_themes_all();
    CHECK(s.unavailable_count() == 3);
    CHECK(s.with_theme("mirror", true).size() == 0);
}

TEST_CASE("theme_histogram lists every non-parametric theme in registry order", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    auto s = kqvk_set(tb, 2, 50);
    auto h = s.theme_histogram();
    std::vector<std::string> expect;
    for (const auto& t : themes::theme_registry())
        if (!t.param) expect.push_back(std::string(t.name));
    REQUIRE(h.size() == expect.size());
    for (size_t i = 0; i < h.size(); ++i) REQUIRE(h[i].first == expect[i]);
    size_t mirror = 0;
    for (const auto& [n, c] : h)
        if (n == "mirror") mirror = c;
    REQUIRE(mirror == s.with_theme("mirror", false).size());
    REQUIRE(mirror > 0);
}

TEST_CASE("to_json has the documented shape", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2, .themes = {"mirror"}}, INT_MAX);
    s.add(kGolden);
    s.add(kFirst);
    auto j = nlohmann::json::parse(s.to_json({.themes = true, .solutions = true}));
    REQUIRE(j["material"] == "KQvk");
    REQUIRE(j["filter"]["dtm"] == 2);
    REQUIRE(j["filter"]["count"] == -1);
    REQUIRE(j["filter"]["themes"] == nlohmann::json::array({"mirror"}));
    REQUIRE(j["max"] == "infinity");
    REQUIRE(j["skipped_saturated"] == 0);
    REQUIRE(j["positions"].size() == 2);
    auto& p = j["positions"][0];
    REQUIRE(p["fen"] == kGolden);
    REQUIRE(p["dtm"] == 2);
    REQUIRE(p["count"] == 4);
    REQUIRE(p["starts"] == 2);
    REQUIRE(p["ends"] == 4);
    REQUIRE(p["solutions"].size() == 4);
    REQUIRE(p["solutions"][3] == nlohmann::json::array({"Kh8", "Qg7#"}));
    REQUIRE(p["themes"].is_array());
    REQUIRE_FALSE(p.contains("unavailable"));
    // Key order is stable: material first, positions last.
    auto text = s.to_json({});
    REQUIRE(text.find("\"material\"") < text.find("\"positions\""));
    REQUIRE(text.back() == '\n');
}

TEST_CASE("to_json without facets is minimal; max as integer", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 7);
    s.add(kFirst);
    auto j = nlohmann::json::parse(s.to_json({}));
    REQUIRE(j["max"] == 7);
    auto& p = j["positions"][0];
    REQUIRE(p.size() == 3);  // fen, dtm, count
    REQUIRE_FALSE(p.contains("themes"));
    REQUIRE_FALSE(p.contains("solutions"));
}

TEST_CASE("unavailable hits serialise with the message and nothing else", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 7);
    Hit h;
    h.fen = kFirst;
    h.dtm = 2;
    h.count = 1;
    h.unavailable = "no table for \"Kvk\"";  // a quote, to prove escaping
    s.add(h);
    auto j = nlohmann::json::parse(s.to_json({.themes = true, .solutions = true}));
    auto& p = j["positions"][0];
    REQUIRE(p["unavailable"] == "no table for \"Kvk\"");
    REQUIRE_FALSE(p.contains("themes"));
    REQUIRE_FALSE(p.contains("solutions"));
    std::ostringstream out;
    s.to_text(out, {.themes = true, .solutions = true});
    REQUIRE(out.str() == std::string(kFirst) + "\n  unavailable: no table for \"Kvk\"\n\n");
}

TEST_CASE("a saturated hit says so instead of faking starts/ends", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 7);
    Hit h;
    h.fen = kFirst;
    h.dtm = 2;
    h.count = (int)COUNT_SAT;
    h.shape = SolutionShape{0, 0, false};           // not exhaustive: nothing countable
    h.themes = std::vector<std::string>{"mirror"};  // pre-set, so nothing is re-probed
    h.solutions = std::vector<std::vector<std::string>>{{"Ka2", "Qa4#"}};  // the capped first 100
    s.add(h);
    auto j = nlohmann::json::parse(s.to_json({.themes = true, .solutions = true}));
    auto& p = j["positions"][0];
    REQUIRE(p["exhaustive"] == false);
    REQUIRE_FALSE(p.contains("starts"));
    REQUIRE_FALSE(p.contains("ends"));
    REQUIRE(p["solutions"].size() == 1);
    std::ostringstream out;
    s.to_text(out, {.solutions = true});
    REQUIRE(out.str() ==
            std::string(kFirst) + "\n  Ka2 Qa4#\n  (solution count saturated: first 100 solutions only)\n\n");
}

TEST_CASE("to_text: bare FENs by default, indented facets otherwise", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 7);
    s.add(kFirst);
    s.add(kSecond);
    std::ostringstream bare;
    s.to_text(bare, {});
    REQUIRE(bare.str() == std::string(kFirst) + "\n" + kSecond + "\n");
    std::ostringstream sol;
    s.to_text(sol, {.solutions = true});
    REQUIRE(sol.str() == std::string(kFirst) + "\n  Ka2 Qa4#\n\n" + kSecond + "\n  Ka2 Qb2#\n\n");
    std::ostringstream both;
    s.to_text(both, {.themes = true, .solutions = true});
    std::string text = both.str();
    REQUIRE(text.rfind(std::string(kFirst) + "\n  themes:", 0) == 0);
    REQUIRE(text.find(" mirror") != std::string::npos);
    REQUIRE(text.find("\n  Ka2 Qa4#\n\n") != std::string::npos);
}

TEST_CASE("to_jsonl: header, one record per hit, footer; records equal to_json's", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2, .themes = {"mirror"}}, INT_MAX);
    s.add(kGolden);
    s.add(kFirst);
    s.set_skipped_saturated(3);
    MineSet::Facets both{.themes = true, .solutions = true};
    std::ostringstream os;
    s.to_jsonl(os, both);
    std::vector<std::string> lines;
    {
        std::istringstream in(os.str());
        for (std::string l; std::getline(in, l);) lines.push_back(l);
    }
    REQUIRE(lines.size() == 4);  // header + 2 records + footer
    REQUIRE(os.str().back() == '\n');
    auto header = nlohmann::json::parse(lines[0]);
    REQUIRE(header["material"] == "KQvk");
    REQUIRE(header["filter"]["themes"] == nlohmann::json::array({"mirror"}));
    REQUIRE(header["max"] == "infinity");
    REQUIRE_FALSE(header.contains("positions"));
    REQUIRE_FALSE(header.contains("skipped_saturated"));
    // Records are byte-for-byte the --json positions[] elements, compacted.
    auto doc = nlohmann::json::parse(s.to_json(both));
    for (size_t i = 0; i < 2; ++i) {
        auto rec = nlohmann::json::parse(lines[i + 1]);
        REQUIRE(rec == doc["positions"][i]);
        REQUIRE(rec.contains("fen"));
    }
    auto footer = nlohmann::json::parse(lines[3]);
    REQUIRE(footer["positions"] == 2);
    REQUIRE(footer["skipped_saturated"] == 3);
    REQUIRE_FALSE(footer.contains("fen"));
    // The streaming building blocks agree with the held-set writer.
    REQUIRE(lines[0] + "\n" == s.jsonl_header());
    REQUIRE(lines[3] + "\n" == s.jsonl_footer(2));
    Hit h = s.make_hit(kGolden);
    REQUIRE(h.count == 4);
    REQUIRE_FALSE(h.themes);
    s.enrich(h, both);
    REQUIRE(h.themes);
    REQUIRE(h.solutions);
    REQUIRE(lines[1] + "\n" == s.jsonl_record(h, both));
    REQUIRE(s.size() == 2);  // make_hit stored nothing
}

TEST_CASE("to_jsonl without facets is minimal and the footer follows an empty set", "[mine_set]") {
    Tablebase tb(gen_kqvk());
    MineSet s(tb, *Material::parse("KQvk"), MineFilter{.dtm = 2}, 7);
    std::ostringstream os;
    s.to_jsonl(os, {});
    std::vector<std::string> lines;
    std::istringstream in(os.str());
    for (std::string l; std::getline(in, l);) lines.push_back(l);
    REQUIRE(lines.size() == 2);
    REQUIRE(nlohmann::json::parse(lines[0])["max"] == 7);
    REQUIRE(nlohmann::json::parse(lines[1]) == nlohmann::json({{"positions", 0}, {"skipped_saturated", 0}}));
}

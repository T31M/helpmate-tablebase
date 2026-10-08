#include <catch2/catch_test_macros.hpp>
#include <filesystem>
#include <fstream>
#include <map>
#include <nlohmann/json.hpp>
#include <string>

#include "chess/board.h"
#include "format/table_file.h"
#include "generator/generator.h"
using namespace hm;
TEST_CASE("stats sidecar is written and consistent") {
    auto d = std::filesystem::temp_directory_path() / "hm_stats";
    std::filesystem::remove_all(d); std::filesystem::create_directories(d);
    GenOptions opt; opt.tables_dir = d.string();
    generate(*Material::parse("KQvk"), opt);
    std::ifstream f(opt.tables_dir + "/KQvk.stats.json"); REQUIRE(f.good());
    auto j = nlohmann::json::parse(f);
    CHECK(j["material"] == "KQvk");
    CHECK(j["plane_size"] == 462ull * 64);
    int maxd = j["max_dtm"];
    CHECK(maxd >= 3);                                  // golden G3 proves >= 3
    // histogram sums must account for every cell
    uint64_t total_b = 0;
    for (auto& [k, v] : j["dtm_histogram"]["btm"].items()) total_b += (uint64_t)v;
    total_b += (uint64_t)j["cells"]["invalid"]["btm"] + (uint64_t)j["cells"]["unsolvable"]["btm"];
    CHECK(total_b == 462ull * 64);
    // deepest FENs probe back to max_dtm
    REQUIRE(!j["deepest"].empty());
    auto b = Board::from_fen(j["deepest"][0]); REQUIRE(b);
    auto r = TableReader::open(opt.tables_dir + "/KQvk.hm");
    SliceIndex idx(*Material::parse("KQvk"));
    CHECK((int)r->get(b->stm(), *idx.encode(b->pieces())).dtm == maxd);
    // embedded meta == sidecar
    CHECK(nlohmann::json::parse(r->meta_json()) == j);
    // uniqueness histogram exists for some depth
    CHECK(j.contains("uniqueness"));
}

namespace {
// The pre-array statistics: one std::map lookup per counted cell. The
// histogram and uniqueness sections of stats_json() must match it exactly.
nlohmann::json reference_counts(const SliceGen& g) {
    static const char* kStm[2] = {"wtm", "btm"};
    nlohmann::json out;
    for (int s = 0; s < 2; ++s) {
        uint64_t invalid = 0, unsolvable = 0;
        std::map<int, uint64_t> hist;
        std::map<int, std::map<int, uint64_t>> uniq;
        const auto& dtm = g.dtm((Color)s);
        const auto& cnt = g.cnt((Color)s);
        for (size_t c = 0; c < dtm.size(); ++c) {
            if (dtm[c] == DTM_INVALID) {
                ++invalid;
                continue;
            }
            if (dtm[c] == DTM_UNSOLVABLE) {
                ++unsolvable;
                continue;
            }
            ++hist[dtm[c]];
            ++uniq[dtm[c]][cnt[c]];
        }
        out["cells"]["invalid"][kStm[s]] = invalid;
        out["cells"]["unsolvable"][kStm[s]] = unsolvable;
        nlohmann::json hj = nlohmann::json::object(), uj = nlohmann::json::object();
        for (auto& [d, n] : hist) hj[std::to_string(d)] = n;
        for (auto& [d, counts] : uniq)
            for (auto& [k, n] : counts) uj[std::to_string(d)][std::to_string(k)] = n;
        out["dtm_histogram"][kStm[s]] = hj;
        out["uniqueness"][kStm[s]] = uj;
    }
    return out;
}
}  // namespace

TEST_CASE("stats_json counts match a per-cell map tally, before and after the UNSET sweep") {
    auto d = std::filesystem::temp_directory_path() / "hm_stats_tally";
    std::filesystem::remove_all(d);
    std::filesystem::create_directories(d);
    GenOptions opt;
    opt.tables_dir = d.string();
    opt.threads = 2;
    generate(*Material::parse("KRvk"), opt);  // predecessors for the SliceGen below
    for (const char* name : {"KQvk", "KRvk"}) {
        SliceGen g(*Material::parse(name), opt);
        g.run_all_passes();  // UNSET cells still present: counted under key 253, as before
        for (int round = 0; round < 2; ++round) {
            auto j = g.stats_json();
            auto want = reference_counts(g);
            INFO(name << " round " << round);
            CHECK(j["cells"] == want["cells"]);
            CHECK(j["dtm_histogram"] == want["dtm_histogram"]);
            CHECK(j["uniqueness"] == want["uniqueness"]);
            if (round == 0) g.finalize_and_write();  // sweeps UNSET to UNSOLVABLE, then compare again
        }
    }
    std::filesystem::remove_all(d);
}

TEST_CASE("stats_json is identical for every thread count, deepest positions included") {
    // Counts are summed per thread range and the deepest positions are found
    // by an ordered search over thread ranges; both must give exactly the
    // single-threaded document.
    auto d = std::filesystem::temp_directory_path() / "hm_stats_threads";
    std::filesystem::remove_all(d);
    std::filesystem::create_directories(d);
    GenOptions opt;
    opt.tables_dir = d.string();
    opt.threads = 4;
    generate(*Material::parse("KBNvk"), opt);  // KBNvk and its predecessors
    for (const char* name : {"KQvk", "KBNvk"}) {
        std::string reference_before, reference_after;
        for (int threads : {1, 3, 8}) {
            GenOptions o = opt;
            o.threads = threads;
            o.tables_dir = (d / ("t" + std::to_string(threads))).string();
            std::filesystem::create_directories(o.tables_dir);
            for (auto& f : std::filesystem::directory_iterator(d))
                if (f.path().extension() == ".hm" && f.path().stem() != name)
                    std::filesystem::copy_file(f.path(), o.tables_dir + "/" + f.path().filename().string(),
                                               std::filesystem::copy_options::overwrite_existing);
            SliceGen g(*Material::parse(name), o);
            g.run_all_passes();
            std::string before = g.stats_json().dump();
            g.finalize_and_write();
            std::string after = g.stats_json().dump();
            INFO(name << " threads " << threads);
            CHECK(!nlohmann::json::parse(after)["deepest"].empty());
            if (threads == 1) {
                reference_before = before;
                reference_after = after;
            } else {
                CHECK(before == reference_before);
                CHECK(after == reference_after);
            }
        }
    }
    std::filesystem::remove_all(d);
}

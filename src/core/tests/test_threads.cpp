#include <catch2/catch_test_macros.hpp>
#include "generator/generator.h"
#include "indexing/material.h"
#include <filesystem>
#include <fstream>
#include <string>
#include <unistd.h>
using namespace hm;
static std::string file_bytes(const std::string& p) {
    std::ifstream f(p, std::ios::binary);
    return std::string(std::istreambuf_iterator<char>(f), {});
}
// Compares without ever handing Catch2 two multi-MB strings to stringify on
// failure: report sizes and the first differing offset instead.
static void check_files_equal(const std::string& name, const std::string& a_path, const std::string& b_path) {
    auto a = file_bytes(a_path), b = file_bytes(b_path);
    REQUIRE(!a.empty());
    INFO(name << ": size_1t=" << a.size() << " size_4t=" << b.size());
    REQUIRE(a.size() == b.size());
    size_t mismatch = a.size();
    for (size_t i = 0; i < a.size(); ++i) if (a[i] != b[i]) { mismatch = i; break; }
    INFO(name << ": first mismatching byte at offset " << mismatch);
    CHECK(mismatch == a.size());
}
// Generates `material`'s full closure with threads=1 and threads=4 into
// unique (PID-suffixed) fresh temp dirs, then checks every slice's table and
// stats are byte-identical between the two runs; cleans up afterward.
static void run_threaded_determinism(const char* material, bool compress = false) {
    auto base = std::filesystem::temp_directory_path();
    std::string tag =
        std::string(compress ? "compressed_" : "raw_") + std::to_string((unsigned long long)getpid());
    std::filesystem::path d1 = base / ("hm_thr1_" + tag);
    std::filesystem::path d4 = base / ("hm_thr4_" + tag);
    for (auto& d : {d1, d4}) { std::filesystem::remove_all(d); std::filesystem::create_directories(d); }
    GenOptions opt1;
    opt1.tables_dir = d1.string();
    opt1.threads = 1;
    opt1.compress = compress;
    generate(*Material::parse(material), opt1);
    GenOptions opt4;
    opt4.tables_dir = d4.string();
    opt4.threads = 4;
    opt4.compress = compress;
    generate(*Material::parse(material), opt4);
    for (auto& m : Material::closure_topo(*Material::parse(material))) {
        std::string n = m.name();
        check_files_equal(n, (d1 / (n + ".hm")).string(), (d4 / (n + ".hm")).string());
        check_files_equal(n + " stats", (d1 / (n + ".stats.json")).string(),
                          (d4 / (n + ".stats.json")).string());
    }
    std::filesystem::remove_all(d1);
    std::filesystem::remove_all(d4);
}
TEST_CASE("4-thread generation is byte-identical to 1-thread") {
    run_threaded_determinism("KPvk");
}
TEST_CASE("compressed 4-thread generation and stats are byte-identical to 1-thread") {
    run_threaded_determinism("KQvk", true);
}
// KPvk has no black pawn, so eval_board's EP branch (the only code path whose
// thread-safety argument rests on a position's material changing mid-lookup,
// via a second cross-slice SubTables lookup after an EP capture) never runs
// there. KPvkp is both the minimal material with pawns on both sides and the
// exact material the pre-fix WIP crashed on (map::at) -- so it is the
// material that actually exercises that path under threads>1. Generation-only
// (no oracle probes) to keep this reasonably fast; still [slow] since it
// builds the full 36-slice closure twice.
TEST_CASE("4-thread KPvkp generation is byte-identical to 1-thread", "[slow]") {
    run_threaded_determinism("KPvkp");
}

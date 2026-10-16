#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include "chess/board.h"
#include "format/table_file.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include <filesystem>
#include <string>
#include <unistd.h>
using namespace hm;
using Catch::Matchers::ContainsSubstring;

// Regression cover for Task 21. Two lookup paths in the generator used to assume their
// inputs instead of checking them:
//   * SubTables::lookup did t_.at(m.name()), which throws a context-free
//     std::out_of_range("map::at") -- the whole of the crash message the user saw; and
//   * both lookup paths did *encode(pp) on a std::optional that is disengaged for any
//     position the slice cannot hold (kings adjacent/equal). That is UB: it reads
//     uninitialised stack, and because vec[i] is *(data() + i) with wrapping arithmetic
//     the resulting address can be anywhere, so the damage surfaced far from its cause
//     (typically a SIGSEGV inside malloc minutes later, or a corrupted std::map).
// These tests pin the behaviour to a typed error that names material, FEN and cell.

namespace {
// Builds the KNvkq sub-tables the generator would load for KNvkqr, in a fresh temp dir.
struct TempTables {
    std::filesystem::path dir;
    TempTables() {
        dir = std::filesystem::temp_directory_path() /
              ("hm_guard_" + std::to_string((unsigned long long)getpid()));
        std::filesystem::remove_all(dir);
        std::filesystem::create_directories(dir);
    }
    ~TempTables() { std::filesystem::remove_all(dir); }
};
}  // namespace

TEST_CASE("SubTables::lookup reports an unloaded material instead of throwing map::at") {
    TempTables tt;
    GenOptions opt; opt.tables_dir = tt.dir.string(); opt.threads = 1;
    generate(*Material::parse("KQvk"), opt);          // writes Kvk.hm and KQvk.hm

    SubTables subs;
    subs.load_for(*Material::parse("KQvk"), opt.tables_dir);   // loads only Kvk

    // A KQvk position: its material is NOT a successor of KQvk, so it is not loaded.
    std::vector<PlacedPiece> pp{
        {{Color::White, PieceType::King}, 4}, {{Color::Black, PieceType::King}, 60},
        {{Color::White, PieceType::Queen}, 0}};
    REQUIRE(Material::of(pp) == *Material::parse("KQvk"));

    REQUIRE_THROWS_AS(subs.lookup(Material::of(pp), pp, Color::White), GeneratorLookupError);
    REQUIRE_THROWS_WITH(subs.lookup(Material::of(pp), pp, Color::White),
                        ContainsSubstring("KQvk") && ContainsSubstring("no sub-table loaded"));
}

TEST_CASE("SubTables::lookup reports an unencodable position instead of dereferencing nullopt") {
    TempTables tt;
    GenOptions opt; opt.tables_dir = tt.dir.string(); opt.threads = 1;
    generate(*Material::parse("KQvk"), opt);

    SubTables subs;
    subs.load_for(*Material::parse("KQvk"), opt.tables_dir);   // loads Kvk

    // Kvk material, but the kings are adjacent -> no transform yields a valid KK index,
    // so SliceIndex::encode() returns nullopt. Pre-fix this was `*e` on a disengaged
    // optional; now it must be a typed error naming the position.
    std::vector<PlacedPiece> pp{{{Color::White, PieceType::King}, 0},
                               {{Color::Black, PieceType::King}, 1}};
    REQUIRE(Material::of(pp) == *Material::parse("Kvk"));
    REQUIRE_FALSE(SliceIndex(*Material::parse("Kvk")).encode(pp).has_value());

    REQUIRE_THROWS_AS(subs.lookup(Material::of(pp), pp, Color::White), GeneratorLookupError);
    REQUIRE_THROWS_WITH(subs.lookup(Material::of(pp), pp, Color::White),
                        ContainsSubstring("not encodable"));

    // The public SubTables API still validates the supplied material against the pieces.
    std::vector<PlacedPiece> mismatched{{{Color::White, PieceType::King}, 4},
                                        {{Color::Black, PieceType::King}, 60},
                                        {{Color::White, PieceType::Queen}, 0}};
    REQUIRE(Material::of(mismatched) == *Material::parse("KQvk"));
    REQUIRE_THROWS_WITH(subs.lookup(*Material::parse("Kvk"), mismatched, Color::White),
                        ContainsSubstring("not encodable"));
}

TEST_CASE("TableReader::get rejects an out-of-range cell") {
    TempTables tt;
    GenOptions opt; opt.tables_dir = tt.dir.string(); opt.threads = 1;
    generate(*Material::parse("KQvk"), opt);

    auto r = TableReader::open(tt.dir.string() + "/Kvk.hm");
    REQUIRE(r);
    REQUIRE_NOTHROW(r->get(Color::White, r->plane_size() - 1));
    REQUIRE_THROWS_AS(r->get(Color::White, r->plane_size()), std::out_of_range);
    // The value that used to walk off the mapping: a wild index.
    REQUIRE_THROWS_AS(r->get(Color::White, ~0ull), std::out_of_range);
}

// The property whose violation would produce the reported crash, checked exhaustively on a
// slice small enough for the fast suite: for every cell and every legal move, the post-move
// position must be answerable -- its material is either the slice's own or one of the loaded
// direct successors, and it must be encodable in whichever slice owns it. 1.89 M cells.
TEST_CASE("KNvkq: every legal move lands on a position the generator can look up", "[slow]") {
    Material root = *Material::parse("KNvkq");
    SliceIndex idx(root);
    std::map<std::string, SliceIndex> subs;
    for (auto& s : root.successors()) subs.emplace(s.name(), SliceIndex(s));

    std::vector<PlacedPiece> pp;
    Board b;
    uint64_t checked = 0;
    for (uint64_t c = 0; c < idx.size(); ++c) {
        if (!idx.decode(c, pp)) continue;
        auto e0 = idx.encode(pp);
        if (!e0 || *e0 != c) continue;                 // non-canonical duplicate
        for (int s = 0; s < 2; ++s) {
            b.reset(pp, (Color)s);
            if (b.opponent_in_check()) continue;       // not a legal cell for this stm
            for (const Move& m : b.legal_moves()) {
                b.make(m);
                auto pp2 = b.pieces();
                Material after = Material::of(pp2);
                if (after == root) {
                    auto e = idx.encode(pp2);
                    INFO("cell " << c << " move " << m.uci() << " -> own slice, fen " << b.fen());
                    REQUIRE(e.has_value());
                    REQUIRE(*e < idx.size());
                } else {
                    auto it = subs.find(after.name());
                    INFO("cell " << c << " move " << m.uci() << " -> material " << after.name()
                                 << ", fen " << b.fen());
                    REQUIRE(it != subs.end());         // else SubTables::lookup would throw
                    auto e = it->second.encode(pp2);
                    REQUIRE(e.has_value());
                    REQUIRE(*e < it->second.size());
                }
                b.unmake(m);
                ++checked;
            }
        }
    }
    REQUIRE(checked > 1000000);
}

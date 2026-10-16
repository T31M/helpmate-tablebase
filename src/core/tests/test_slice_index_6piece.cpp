#include <catch2/catch_test_macros.hpp>
#include "indexing/slice_index.h"
#include "indexing/material.h"
#include <cstdint>
#include <vector>
using namespace hm;

// 6-piece index coverage: pure index math (no table generation), so these run
// in well under a second despite the multi-billion-cell planes. Materials
// chosen to cover distinct shapes: pawnless, multi-pawn, mixed minor pieces,
// and same-piece multiples on both sides.

namespace {

struct Case { const char* name; uint64_t expected_size; };

const Case kCases[] = {
    {"KQRvkqr", 462ull * 64 * 64 * 64 * 64},   // pawnless, 8-fold symmetry
    {"KPPvkpp", 1806ull * 48 * 48 * 48 * 48},  // multi-pawn, mirror symmetry only
    {"KQNvkbn", 462ull * 64 * 64 * 64 * 64},   // mixed piece types
    {"KNNvknn", 462ull * 64 * 64 * 64 * 64},   // same-piece multiples both sides
};

// Deterministic sample: 10k cells spread evenly across [0, size).
constexpr uint64_t kSamples = 10000;

}  // namespace

TEST_CASE("6-piece plane sizes are sane (uint64, no overflow)") {
    for (auto& tc : kCases) {
        auto m = Material::parse(tc.name);
        REQUIRE(m);
        SliceIndex idx(*m);
        INFO(tc.name);
        CHECK(idx.size() == tc.expected_size);
        CHECK(idx.size() > 0);
        CHECK(idx.size() < (1ull << 63));              // far from uint64 overflow
        // size is exactly kk * product of per-piece radices, so it must be
        // divisible by every slot radix (64 pawnless / 48 per pawn).
        CHECK(idx.size() % (m->has_pawns() ? 48 : 64) == 0);
    }
}

TEST_CASE("6-piece encode/decode roundtrip over a deterministic even spread") {
    for (auto& tc : kCases) {
        SliceIndex idx(*Material::parse(tc.name));
        const uint64_t size = idx.size();
        const uint64_t step = size / kSamples;         // >> 1 for all 6-piece planes
        REQUIRE(step > 0);
        std::vector<PlacedPiece> pp, pp2;
        uint64_t decoded = 0, canonical = 0;
        for (uint64_t i = 0; i < kSamples; ++i) {
            uint64_t c = i * step;
            if (!idx.decode(c, pp)) continue;          // overlapping pieces: cell is invalid
            ++decoded;
            auto e = idx.encode(pp);
            REQUIRE(e);                                // decoded cells always re-encode
            CHECK(*e <= c);                            // canonical index is minimal
            if (*e == c) ++canonical;
            // The canonical representative is a fixpoint: decode it and it
            // must encode back to itself exactly.
            REQUIRE(idx.decode(*e, pp2));
            auto e2 = idx.encode(pp2);
            REQUIRE(e2);
            CHECK(*e2 == *e);
        }
        INFO(tc.name);
        // Overlap kills at most a modest fraction of cells for 6 pieces; the
        // sample must be overwhelmingly decodable and contain both canonical
        // and non-canonical cells, or the test is vacuous.
        CHECK(decoded > kSamples / 2);
        CHECK(canonical > 0);
        CHECK(canonical < decoded);
    }
}

TEST_CASE("6-piece boundary cells: 0 and size-1 behave, size decodes false") {
    for (auto& tc : kCases) {
        SliceIndex idx(*Material::parse(tc.name));
        const uint64_t size = idx.size();
        std::vector<PlacedPiece> pp;
        INFO(tc.name);
        CHECK(!idx.decode(size, pp));                  // one past the end: rejected
        CHECK(!idx.decode(size + 1, pp));
        CHECK(!idx.decode(UINT64_MAX, pp));
        for (uint64_t c : {(uint64_t)0, size - 1}) {   // in-range boundaries: no crash,
            if (!idx.decode(c, pp)) continue;          // and if valid, they roundtrip
            auto e = idx.encode(pp);
            REQUIRE(e);
            CHECK(*e <= c);
        }
    }
}

TEST_CASE("6-piece identical multiples: swapped order encodes identically") {
    SliceIndex idx(*Material::parse("KNNvknn"));
    std::vector<PlacedPiece> a = {
        {{Color::White, PieceType::King}, 0},   {{Color::White, PieceType::Knight}, 18},
        {{Color::White, PieceType::Knight}, 45},{{Color::Black, PieceType::King}, 63},
        {{Color::Black, PieceType::Knight}, 27},{{Color::Black, PieceType::Knight}, 36}};
    auto b = a;
    std::swap(b[1], b[2]);                             // white knights
    std::swap(b[4], b[5]);                             // black knights
    auto ea = idx.encode(a);
    REQUIRE(ea);
    CHECK(idx.encode(b) == ea);
    CHECK(*ea == 541775588);  // pre-change on-disk index
}

TEST_CASE("6-piece KRBvkqq canonical numeric index is stable") {
    SliceIndex idx(*Material::parse("KRBvkqq"));
    std::vector<PlacedPiece> pieces = {
        {{Color::White, PieceType::King}, 0},    {{Color::White, PieceType::Rook}, 10},
        {{Color::White, PieceType::Bishop}, 27}, {{Color::Black, PieceType::King}, 18},
        {{Color::Black, PieceType::Queen}, 41},  {{Color::Black, PieceType::Queen}, 55}};
    auto encoded = idx.encode(pieces);
    REQUIRE(encoded);
    CHECK(*encoded == 204061303);
}

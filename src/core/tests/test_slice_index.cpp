#include <catch2/catch_test_macros.hpp>
#include "indexing/slice_index.h"
#include "indexing/material.h"
#include <algorithm>
#include <random>
#include <tuple>
using namespace hm;
TEST_CASE("plane sizes") {
    CHECK(SliceIndex(*Material::parse("Kvk")).size()   == 462);
    CHECK(SliceIndex(*Material::parse("KQvk")).size()  == 462ull * 64);
    CHECK(SliceIndex(*Material::parse("KPvk")).size()  == 1806ull * 48);
    CHECK(SliceIndex(*Material::parse("KQvkq")).size() == 462ull * 64 * 64);
    CHECK(SliceIndex(*Material::parse("KPvkp")).size() == 1806ull * 48 * 48);
}
static std::vector<PlacedPiece> transform_pos(const std::vector<PlacedPiece>& pp, int t) {
    auto out = pp; for (auto& p : out) p.square = (uint8_t)transform_sq(p.square, t); return out;
}
TEST_CASE("all symmetry images share one canonical index (pawnless)") {
    SliceIndex idx(*Material::parse("KQvkr"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 12}, {{Color::White, PieceType::Queen}, 33},
        {{Color::Black, PieceType::King}, 60}, {{Color::Black, PieceType::Rook}, 7}};
    auto base = idx.encode(pp); REQUIRE(base);
    for (int t = 1; t < 8; ++t) CHECK(idx.encode(transform_pos(pp, t)) == base);
}
TEST_CASE("mirror image shares canonical index (pawns)") {
    SliceIndex idx(*Material::parse("KPvkp"));
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 4},  {{Color::White, PieceType::Pawn}, 28},
        {{Color::Black, PieceType::King}, 20}, {{Color::Black, PieceType::Pawn}, 35}};
    auto base = idx.encode(pp); REQUIRE(base);
    CHECK(idx.encode(transform_pos(pp, 1)) == base);
}
TEST_CASE("decode/encode round trip over random cells") {
    for (auto name : {"KQvkr", "KPvkp", "KQQvk"}) {
        SliceIndex idx(*Material::parse(name));
        std::mt19937_64 rng(42);
        std::vector<PlacedPiece> pp;
        int checked = 0;
        while (checked < 2000) {
            uint64_t c = rng() % idx.size();
            if (!idx.decode(c, pp)) continue;         // overlapping cell
            auto e = idx.encode(pp);
            REQUIRE(e);
            CHECK(*e <= c);                           // canonical is minimal
            checked++;
        }
    }
}
TEST_CASE("identical pieces: swapped order encodes identically") {
    SliceIndex idx(*Material::parse("KQQvk"));
    std::vector<PlacedPiece> a = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 10},
        {{Color::White, PieceType::Queen}, 20}, {{Color::Black, PieceType::King}, 63}};
    auto b = a; std::swap(b[1], b[2]);
    CHECK(idx.encode(a) == idx.encode(b));
}
TEST_CASE("encode rejects garbage") {
    SliceIndex idx(*Material::parse("KQvk"));
    std::vector<PlacedPiece> wrong = {
        {{Color::White, PieceType::King}, 0}, {{Color::Black, PieceType::King}, 63}};
    CHECK(!idx.encode(wrong));                        // material mismatch (missing Q)
    std::vector<PlacedPiece> adj = {
        {{Color::White, PieceType::King}, 0}, {{Color::White, PieceType::Queen}, 30},
        {{Color::Black, PieceType::King}, 1}};
    CHECK(!idx.encode(adj));                          // adjacent kings
    adj[0].square = 64;
    CHECK(!idx.encode(adj));                          // malformed square is not a table index
}

TEST_CASE("canonical numeric indices retain the existing table layout") {
    // The a1/c3 kings permit identity and transpose. The queen position makes
    // transpose the lower complete index, so both choices must be considered.
    SliceIndex pawnless(*Material::parse("KQvkr"));
    std::vector<PlacedPiece> two_choices = {
        {{Color::White, PieceType::King}, 0},
        {{Color::White, PieceType::Queen}, 17},
        {{Color::Black, PieceType::King}, 18},
        {{Color::Black, PieceType::Rook}, 41}};
    auto pawnless_index = pawnless.encode(two_choices);
    REQUIRE(pawnless_index);
    CHECK(*pawnless_index == 49805);

    SliceIndex pawns(*Material::parse("KPvkp"));
    std::vector<PlacedPiece> mirrored = {
        {{Color::White, PieceType::King}, 4},
        {{Color::White, PieceType::Pawn}, 28},
        {{Color::Black, PieceType::King}, 20},
        {{Color::Black, PieceType::Pawn}, 35}};
    auto pawn_index = pawns.encode(mirrored);
    REQUIRE(pawn_index);
    CHECK(*pawn_index == 436396);
    CHECK(pawns.encode(transform_pos(mirrored, 1)) == pawn_index);
}
namespace {
// The pre-optimisation encoder, kept verbatim in shape (group by scanning all
// pieces for each run of identical slots, std::sort, min over king choices) as
// an oracle for the current one.
std::optional<uint64_t> reference_encode(const Material& m, const std::vector<PlacedPiece>& pp) {
    if (!(Material::of(pp) == m)) return std::nullopt;
    const KKTable& kk = m.has_pawns() ? KKTable::with_pawns() : KKTable::pawnless();
    std::vector<Slot> slots;
    for (int color = 0; color < 2; ++color)
        for (int t = 1; t < 6; ++t)
            for (int k = 0; k < (color == 0 ? m.white : m.black)[t]; ++k)
                slots.push_back({{(Color)color, (PieceType)t}, t == 5 ? 48 : 64});
    int wk = -1, bk = -1;
    for (auto& p : pp)
        if (p.piece.type == PieceType::King) (p.piece.color == Color::White ? wk : bk) = p.square;
    if (wk < 0 || bk < 0) return std::nullopt;
    uint64_t best = UINT64_MAX;
    for (uint16_t choice : kk.choices_of[wk * 64 + bk]) {
        if (choice == KKTable::kNoChoice) break;
        int t = choice & 7;
        uint64_t idx = choice >> 3;
        bool ok = true;
        for (size_t i = 0; i < slots.size() && ok;) {
            size_t j = i;
            while (j < slots.size() && slots[j].piece == slots[i].piece) j++;
            std::vector<int> sqs;
            for (auto& p : pp)
                if (p.piece == slots[i].piece) sqs.push_back(transform_sq(p.square, t));
            if (sqs.size() != j - i) { ok = false; break; }
            std::sort(sqs.begin(), sqs.end());
            for (size_t k = i; k < j; ++k) {
                int digit = sqs[k - i] - (slots[k].radix == 48 ? 8 : 0);
                if (digit < 0 || digit >= slots[k].radix) { ok = false; break; }
                idx = idx * slots[k].radix + (uint64_t)digit;
            }
            i = j;
        }
        if (ok) best = std::min(best, idx);
    }
    if (best == UINT64_MAX) return std::nullopt;
    return best;
}
}  // namespace

TEST_CASE("encode matches the reference encoder on transformed, shuffled positions") {
    std::mt19937_64 rng(20261002);
    for (const char* name : {"KQvkr", "KRBvkq", "KBBBvk", "KNNvknn", "KQQvkq", "KPPvkpp", "KPPPvk", "KBBvkpp",
                             "KRPvkp"}) {
        Material m = *Material::parse(name);
        SliceIndex idx(m);
        const int transforms = m.has_pawns() ? 2 : 8;
        std::vector<PlacedPiece> pp;
        int compared = 0, encodable = 0;
        for (int trial = 0; trial < 20000; ++trial) {
            if (!idx.decode(rng() % idx.size(), pp)) continue;
            auto pos = transform_pos(pp, (int)(rng() % transforms));
            std::shuffle(pos.begin(), pos.end(), rng);
            auto want = reference_encode(m, pos);
            INFO(name << " trial " << trial);
            REQUIRE(idx.encode(pos) == want);
            ++compared;
            encodable += want.has_value();
        }
        CHECK(compared > 10000);
        CHECK(encodable > compared / 2);
    }
    // Wrong material and adjacent kings still have no index.
    SliceIndex krb(*Material::parse("KRBvkq"));
    std::vector<PlacedPiece> adjacent{{{Color::White, PieceType::King}, 0}, {{Color::Black, PieceType::King}, 1},
                                      {{Color::White, PieceType::Rook}, 20}, {{Color::White, PieceType::Bishop}, 30},
                                      {{Color::Black, PieceType::Queen}, 40}};
    CHECK_FALSE(krb.encode(adjacent).has_value());
    CHECK(reference_encode(*Material::parse("KRBvkq"), adjacent) == std::nullopt);
    adjacent.pop_back();
    CHECK_FALSE(krb.encode(adjacent).has_value());
}

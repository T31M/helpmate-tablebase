#pragma once
#include "chess/types.h"
#include <array>
#include <cstdint>
#include <cstring>
#include <optional>
#include <string>
#include <vector>

namespace hm {

struct Material {
    std::array<uint8_t, 6> white{}, black{};        // counts indexed by PieceType

    static std::optional<Material> parse(const std::string&);  // "KBkqrbp" or "KBvkqrbp"
    static Material of(const std::vector<PlacedPiece>&);

    // Piece counts packed one byte per PieceType (byte t holds the count of
    // type t), indexed by Color -- the form Board::pieces(out, counts) fills.
    // Comparing two of these is two integer compares on registers.
    using Counts = std::array<uint64_t, 2>;
    Counts counts() const;
    static Material from_counts(const Counts&);

    std::string name() const;                       // canonical "KBvkqrbp"
    // Same result as the defaulted member-wise compare, but a fixed 12-byte
    // compare the compiler inlines: std::array's == calls out to memcmp.
    bool operator==(const Material& o) const {
        static_assert(sizeof(Material) == 12, "white and black counts, no padding");
        return std::memcmp(this, &o, sizeof(Material)) == 0;
    }

    bool has_pawns() const;
    int total() const;
    int pawn_count() const;
    // True iff the white (mating) side holds only its king. Such a side can
    // never give check, so the material can contain no mate — and since only
    // black owns pawns here, no promotion can change that.
    bool mating_side_is_bare_king() const;

    std::vector<Material> successors() const;       // capture / promotion / promotion-capture results
    static std::vector<Material> closure_topo(const Material& root); // build order, root last
};

}  // namespace hm

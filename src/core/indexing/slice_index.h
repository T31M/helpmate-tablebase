#pragma once
#include <array>
#include <cstdint>
#include <optional>
#include <utility>
#include <vector>

#include "chess/types.h"
#include "indexing/kk.h"
#include "indexing/material.h"

namespace hm {

class SliceGen;
struct SubTables;

struct Slot { Piece piece; int radix; };  // radix 64; pawns 48 (digit = sq-8)

class SliceIndex {
public:
    explicit SliceIndex(const Material&);
    uint64_t size() const;                            // cells per side-to-move plane
    // canonical index = min over allowed transforms; identical pieces sorted by transformed square.
    // nullopt if pieces don't match the material, kings adjacent/equal, or a pawn off ranks 2-7.
    std::optional<uint64_t> encode(const std::vector<PlacedPiece>&) const;
    // false if idx >= size() or decoded pieces overlap; kings come from the KK table.
    bool decode(uint64_t idx, std::vector<PlacedPiece>& out) const;
    int num_transforms() const;                       // 2 with pawns, 8 without

    // Returned by moved_index when the move needs a full encode.
    static constexpr uint64_t kNoIndex = UINT64_MAX;
    // `pp` is canonical cell `c` exactly as decode() returned it. For a move of
    // the non-king piece on `from` to the empty square `to` that is neither a
    // capture nor a promotion, the successor's canonical index, computed by
    // changing that piece's digit alone: valid when the king pair has a single
    // eligible transform (so `pp` is already in that orientation and the move
    // keeps it) and the piece has no identical twin to re-sort with. kNoIndex
    // otherwise (a king, a twin, a two-choice king pair).
    uint64_t moved_index(uint64_t c, const std::vector<PlacedPiece>& pp, int from, int to) const;

private:
    friend class SliceGen;
    friend struct SubTables;
    friend bool slice_has_any_mate(const Material&);

    // Caller has already established the material, or decoded this slice's own
    // material. Keep the ordinary public encode() path self-validating.
    std::optional<uint64_t> encode_for_material(const std::vector<PlacedPiece>&, const Material&) const;

    Material mat_;
    bool pawns_;
    const KKTable* kk_;
    std::vector<Slot> slots_;
    // Place value of each slot's digit in the index: the product of the radices after it.
    std::vector<uint64_t> slot_weight_;
    // Per piece kind (color * 6 + type): its run of identical slots,
    // [run_first_, run_first_ + run_count_). Kings and absent kinds have count 0.
    std::array<uint8_t, 12> run_first_{}, run_count_{};
    // (first, count) of each run holding two or more identical pieces.
    std::vector<std::pair<uint8_t, uint8_t>> multi_runs_;
    uint64_t size_ = 0;
};

}  // namespace hm

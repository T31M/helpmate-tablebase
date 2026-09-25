#pragma once
#include "chess/types.h"
#include "indexing/material.h"
#include "indexing/kk.h"
#include <cstdint>
#include <optional>
#include <vector>

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
    uint64_t size_ = 0;
};

}  // namespace hm

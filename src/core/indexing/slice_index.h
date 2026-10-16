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
    // the piece on `from` to the empty square `to` that is neither a capture
    // nor a promotion, the successor's canonical index, computed by changing
    // one digit alone (or, for a piece with identical twins, the digits of
    // its re-sorted run). A non-king piece qualifies when the king pair has a
    // single eligible transform (so `pp` is already in that orientation and
    // the move keeps it); a king when its new pair's only eligible transform
    // is the identity. kNoIndex otherwise.
    uint64_t moved_index(uint64_t c, const std::vector<PlacedPiece>& pp, int from, int to) const;

    // The per-cell part of moved_index, built once from a decoded cell so each
    // of its moves costs one table lookup instead of a walk over the pieces.
    struct MoveContext {
        uint64_t c = 0;
        uint64_t kk = 0;  // c's king-pair index
        int wk = 0, bk = 0;
        // Per square: the slot k of a non-king piece (kTwin + k when it has
        // identical twins), kWhiteKing or kBlackKing, or -1 when empty.
        // Pieces stay -1 when the king pair has two eligible transforms.
        std::array<int8_t, 64> slot;
        std::array<uint8_t, 62> digit;  // per slot, for re-sorting a twin's run
    };
    static constexpr int8_t kWhiteKing = -2, kBlackKing = -3, kTwin = 64;
    void prepare_moves(uint64_t c, const std::vector<PlacedPiece>& pp, MoveContext& ctx) const;
    // Same contract as moved_index(c, pp, from, to) for the cell `ctx` was prepared from.
    uint64_t moved_index(const MoveContext& ctx, int from, int to) const {
        const int entry = ctx.slot[from];
        if (entry >= 0) {
            const int k = entry & (kTwin - 1);
            const int digit = to - (slots_[k].radix == 48 ? 8 : 0);
            if ((unsigned)digit >= (unsigned)slots_[k].radix)
                return kNoIndex;  // a pawn reaching its last rank
            if (entry >= kTwin) return twin_moved_index(ctx, k, digit);
            return ctx.c + (uint64_t)(int64_t)(to - from) * slot_weight_[k];
        }
        if (entry == -1) return kNoIndex;
        // A king move keeps every other digit. The cell is canonical, so the
        // pieces are already sorted in the identity orientation; that stays
        // the canonical one if the new pair's only eligible transform is the
        // identity, and then only the king-pair index changes.
        const int w = entry == kWhiteKing ? to : ctx.wk;
        const int b = entry == kWhiteKing ? ctx.bk : to;
        const auto& choice = kk_->choices_of[w * 64 + b];
        if (choice[1] != KKTable::kNoChoice || (choice[0] & 7) != 0) return kNoIndex;  // kNoChoice & 7 != 0
        return ctx.c + ((uint64_t)(choice[0] >> 3) - ctx.kk) * kk_weight_;
    }

private:
    // moved_index for a piece with identical twins: re-sorts its run alone.
    uint64_t twin_moved_index(const MoveContext& ctx, int k, int digit) const;

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
    uint64_t kk_weight_ = 1;  // place value of the king-pair index: the product of all radices
    // Per piece kind (color * 6 + type): its run of identical slots,
    // [run_first_, run_first_ + run_count_). Kings and absent kinds have count 0.
    std::array<uint8_t, 12> run_first_{}, run_count_{};
    // (first, count) of each run holding two or more identical pieces.
    std::vector<std::pair<uint8_t, uint8_t>> multi_runs_;
    // Per slot: the run_first_/run_count_ of its piece kind.
    std::vector<uint8_t> slot_run_first_, slot_run_count_;
    std::vector<int8_t> slot_entry_;  // per slot: its MoveContext::slot entry
    uint64_t size_ = 0;
};

}  // namespace hm

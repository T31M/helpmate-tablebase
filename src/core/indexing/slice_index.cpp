#include "indexing/slice_index.h"

#include <algorithm>
#include <array>
#include <cstdlib>

namespace hm {

SliceIndex::SliceIndex(const Material& m) : mat_(m) {
    pawns_ = m.has_pawns();
    kk_ = pawns_ ? &KKTable::with_pawns() : &KKTable::pawnless();
    for (int color = 0; color < 2; ++color)           // fixed order: white Q,R,B,N,P then black q,r,b,n,p
        for (int t = 1; t < 6; ++t) {
            const auto& cnt = color == 0 ? m.white : m.black;
            for (int k = 0; k < cnt[t]; ++k)
                slots_.push_back({{(Color)color, (PieceType)t}, t == 5 ? 48 : 64});
        }
    size_ = kk_->size;
    for (auto& s : slots_) size_ *= (uint64_t)s.radix;
    slot_weight_.assign(slots_.size(), 1);
    for (int k = (int)slots_.size() - 2; k >= 0; --k)
        slot_weight_[k] = slot_weight_[k + 1] * (uint64_t)slots_[k + 1].radix;
    for (size_t k = 0; k < slots_.size(); ++k) {
        int kind = (int)slots_[k].piece.color * 6 + (int)slots_[k].piece.type;
        if (run_count_[kind] == 0) run_first_[kind] = (uint8_t)k;
        run_count_[kind]++;
    }
    for (int kind = 0; kind < 12; ++kind)
        if (run_count_[kind] > 1) multi_runs_.push_back({run_first_[kind], run_count_[kind]});
}

uint64_t SliceIndex::size() const { return size_; }

int SliceIndex::num_transforms() const { return pawns_ ? 2 : 8; }

std::optional<uint64_t> SliceIndex::encode(const std::vector<PlacedPiece>& pp) const {
    return encode_for_material(pp, Material::of(pp));
}

std::optional<uint64_t> SliceIndex::encode_for_material(const std::vector<PlacedPiece>& pp,
                                                        const Material& material) const {
    if (!(material == mat_)) return std::nullopt;
    int wk = -1, bk = -1;
    for (auto& p : pp) if (p.piece.type == PieceType::King)
        (p.piece.color == Color::White ? wk : bk) = p.square;
    if (wk < 0 || wk >= 64 || bk < 0 || bk >= 64) return std::nullopt;
    const size_t ns = slots_.size();
    uint64_t best = UINT64_MAX;
    for (uint16_t choice : kk_->choices_of[wk * 64 + bk]) {
        if (choice == KKTable::kNoChoice) break;
        int t = choice & 7;
        uint64_t idx = choice >> 3;
        // One pass drops each transformed square straight into its slot run;
        // identical pieces then only need ordering within their run.
        std::array<int, 64> sqs;
        std::array<uint8_t, 12> fill{};
        size_t placed = 0;
        bool ok = true;
        for (auto& p : pp) {
            if (p.piece.type == PieceType::King) continue;
            int kind = (int)p.piece.color * 6 + (int)p.piece.type;
            if (fill[kind] == run_count_[kind]) {
                ok = false;
                break;
            }  // more than the material holds
            sqs[run_first_[kind] + fill[kind]++] = transform_sq(p.square, t);
            ++placed;
        }
        if (!ok || placed != ns) continue;
        // Runs hold a few identical pieces; std::sort's call and introsort
        // setup cost more than the sort itself at that size.
        for (auto [first, count] : multi_runs_)
            for (size_t a = first + 1; a < (size_t)first + count; ++a) {
                int v = sqs[a];
                size_t b = a;
                for (; b > first && sqs[b - 1] > v; --b) sqs[b] = sqs[b - 1];
                sqs[b] = v;
            }
        for (size_t k = 0; k < ns; ++k) {
            int digit = sqs[k] - (slots_[k].radix == 48 ? 8 : 0);
            if (digit < 0 || digit >= slots_[k].radix) {
                ok = false;
                break;
            }
            idx = idx * slots_[k].radix + (uint64_t)digit;
        }
        if (ok) best = std::min(best, idx);
    }
    if (best == UINT64_MAX) return std::nullopt;      // e.g. kings adjacent
    return best;
}

uint64_t SliceIndex::moved_index(uint64_t c, const std::vector<PlacedPiece>& pp, int from, int to) const {
    // decode() lays out both kings first, then one piece per slot in slot order.
    if (pp.size() != slots_.size() + 2) return kNoIndex;
    if (kk_->choices_of[pp[0].square * 64 + pp[1].square][1] != KKTable::kNoChoice) return kNoIndex;
    for (size_t k = 0; k < slots_.size(); ++k) {
        if (pp[k + 2].square != from) continue;
        const Piece piece = slots_[k].piece;
        if (run_count_[(int)piece.color * 6 + (int)piece.type] != 1) return kNoIndex;
        const int base = slots_[k].radix == 48 ? 8 : 0;
        const int digit = to - base;
        if (digit < 0 || digit >= slots_[k].radix) return kNoIndex;  // a pawn reaching its last rank
        return c - (uint64_t)(from - base) * slot_weight_[k] + (uint64_t)digit * slot_weight_[k];
    }
    return kNoIndex;  // `from` holds a king
}

bool SliceIndex::decode(uint64_t idx, std::vector<PlacedPiece>& out) const {
    if (idx >= size_) return false;
    out.clear();
    uint64_t rest = idx;
    // At most 62 non-king pieces fit beside two kings; a stack array avoids a
    // heap allocation on every decoded cell.
    std::array<int, 64> dg;
    for (int i = (int)slots_.size() - 1; i >= 0; --i) { dg[i] = rest % slots_[i].radix; rest /= slots_[i].radix; }
    auto [wk, bk] = kk_->squares_of[rest];            // remaining = kk index
    uint64_t occ = (1ull << wk) | (1ull << bk);
    out.push_back({{Color::White, PieceType::King}, wk});
    out.push_back({{Color::Black, PieceType::King}, bk});
    for (size_t i = 0; i < slots_.size(); ++i) {
        int sq = dg[i] + (slots_[i].radix == 48 ? 8 : 0);
        if (occ & (1ull << sq)) return false;         // overlap -> invalid cell
        occ |= 1ull << sq;
        out.push_back({slots_[i].piece, (uint8_t)sq});
    }
    return true;
}

}  // namespace hm

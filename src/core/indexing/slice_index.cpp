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
    uint64_t best = UINT64_MAX;
    for (uint16_t choice : kk_->choices_of[wk * 64 + bk]) {
        if (choice == KKTable::kNoChoice) break;
        int t = choice & 7;
        uint64_t idx = choice >> 3; bool ok = true;
        size_t i = 0;
        while (i < slots_.size() && ok) {
            size_t j = i;                             // run of identical slots
            while (j < slots_.size() && slots_[j].piece == slots_[i].piece) j++;
            std::array<int, 64> sqs;
            size_t n = 0;
            for (auto& p : pp)
                if (p.piece == slots_[i].piece) {
                    if (n == sqs.size()) return std::nullopt;
                    sqs[n++] = transform_sq(p.square, t);
                }
            if (n != j - i) { ok = false; break; }
            std::sort(sqs.begin(), sqs.begin() + n);
            for (size_t k = i; k < j; ++k) {
                int digit = sqs[k - i] - (slots_[k].radix == 48 ? 8 : 0);
                if (digit < 0 || digit >= slots_[k].radix) { ok = false; break; }
                idx = idx * slots_[k].radix + (uint64_t)digit;
            }
            i = j;
        }
        if (ok) best = std::min(best, idx);
    }
    if (best == UINT64_MAX) return std::nullopt;      // e.g. kings adjacent
    return best;
}

bool SliceIndex::decode(uint64_t idx, std::vector<PlacedPiece>& out) const {
    if (idx >= size_) return false;
    out.clear();
    uint64_t rest = idx;
    std::vector<int> dg(slots_.size());
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

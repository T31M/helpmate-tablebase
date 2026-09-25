#pragma once
#include <array>
#include <vector>
#include <cstdint>
#include <utility>

namespace hm {
// t in [0,8): bit0 = mirror files (a<->h), bit1 = mirror ranks, bit2 = transpose (a1-h8 diag).
// Applied in that order. With pawns only t in {0,1} is allowed.
inline int transform_sq(int sq, int t) {
    if (t & 1) sq ^= 7;
    if (t & 2) sq ^= 56;
    if (t & 4) sq = ((sq & 7) << 3) | (sq >> 3);
    return sq;
}

struct KKTable {
    static constexpr uint16_t kNoChoice = UINT16_MAX;
    int size = 0;
    std::array<int32_t, 4096> index_of;               // wk*64+bk -> kk index, -1 if outside canonical region/illegal
    // Raw wk*64+bk -> up to two eligible (kk index << 3 | transform) choices.
    // Entries follow transform order; unused entries are kNoChoice.
    std::array<std::array<uint16_t, 2>, 4096> choices_of;
    std::vector<std::pair<uint8_t, uint8_t>> squares_of;
    static const KKTable& with_pawns();               // wK on files a-d; size 1806
    static const KKTable& pawnless();                 // wK in a1-d1-d4 triangle; size 462
};

bool kings_adjacent(int a, int b);
}

#include "indexing/material.h"
#include <algorithm>
#include <cctype>
#include <cstring>
#include <tuple>

namespace hm {

static const char WLET[7] = "KQRBNP";

std::optional<Material> Material::parse(const std::string& s) {
    Material m;
    for (char c : s) {
        if (c == 'v') continue;
        const char* p = strchr(WLET, toupper(c));
        if (!p || !*p) return std::nullopt;
        (isupper(c) ? m.white : m.black)[p - WLET]++;
    }
    if (m.white[0] != 1 || m.black[0] != 1) return std::nullopt;
    return m;
}

Material Material::of(const std::vector<PlacedPiece>& pieces) {
    Material m;
    for (const auto& pp : pieces) {
        int type = static_cast<int>(pp.piece.type);
        if (pp.piece.color == Color::White) {
            m.white[type]++;
        } else {
            m.black[type]++;
        }
    }
    return m;
}

Material::Counts Material::counts() const {
    Counts c{0, 0};
    for (int t = 0; t < 6; ++t) {
        c[0] |= (uint64_t)white[t] << (8 * t);
        c[1] |= (uint64_t)black[t] << (8 * t);
    }
    return c;
}

Material Material::from_counts(const Counts& c) {
    Material m;
    for (int t = 0; t < 6; ++t) {
        m.white[t] = (uint8_t)(c[0] >> (8 * t));
        m.black[t] = (uint8_t)(c[1] >> (8 * t));
    }
    return m;
}

std::string Material::name() const {
    std::string out;
    for (int t = 0; t < 6; ++t) out.append(white[t], WLET[t]);
    out += 'v';
    for (int t = 0; t < 6; ++t) out.append(black[t], (char)tolower(WLET[t]));
    return out;
}

bool Material::has_pawns() const {
    return white[5] > 0 || black[5] > 0;
}

int Material::total() const {
    int sum = 0;
    for (int i = 0; i < 6; ++i) {
        sum += white[i] + black[i];
    }
    return sum;
}

int Material::pawn_count() const {
    return white[5] + black[5];
}

bool Material::mating_side_is_bare_king() const {
    for (size_t i = 0; i < white.size(); ++i)
        if (i != (size_t)PieceType::King && white[i] != 0) return false;
    return true;
}

std::vector<Material> Material::successors() const {
    std::vector<Material> out;
    auto add = [&](const Material& m) { if (std::find(out.begin(), out.end(), m) == out.end()) out.push_back(m); };
    for (int t = 1; t < 6; ++t) {                     // captures: either color loses a non-king
        if (white[t]) { Material m = *this; m.white[t]--; add(m); }
        if (black[t]) { Material m = *this; m.black[t]--; add(m); }
    }
    for (int p = 1; p <= 4; ++p) {                    // promotions P -> Q/R/B/N
        if (white[5]) { Material m = *this; m.white[5]--; m.white[p]++; add(m); }
        if (black[5]) { Material m = *this; m.black[5]--; m.black[p]++; add(m); }
        for (int t = 1; t < 6; ++t) {                 // promotion-captures
            if (white[5] && black[t]) { Material m = *this; m.white[5]--; m.white[p]++; m.black[t]--; add(m); }
            if (black[5] && white[t]) { Material m = *this; m.black[5]--; m.black[p]++; m.white[t]--; add(m); }
        }
    }
    return out;
}

std::vector<Material> Material::closure_topo(const Material& root) {
    std::vector<Material> all{root};                  // BFS closure
    for (size_t i = 0; i < all.size(); ++i)
        for (auto& s : all[i].successors())
            if (std::find(all.begin(), all.end(), s) == all.end()) all.push_back(s);
    std::sort(all.begin(), all.end(), [](const Material& a, const Material& b) {
        return std::tuple(a.total(), a.pawn_count(), a.name())
             < std::tuple(b.total(), b.pawn_count(), b.name()); });
    return all;
}

}  // namespace hm

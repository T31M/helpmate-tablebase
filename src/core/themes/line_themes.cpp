#include "themes/line_themes.h"

#include <algorithm>
#include <cstdlib>
#include <set>

#include "themes/attack.h"
#include "themes/trajectory.h"

namespace hm::themes {
namespace {

bool excelsior_for(const Solution& s, std::optional<Color> want) {
    const auto start_pieces = s.start.pieces();
    for (const auto& t : trajectories(s)) {
        if (!t.promoted) continue;
        if (want && t.color != *want) continue;
        const int home = (t.color == Color::White) ? 1 : 6;  // own second rank, 0-indexed
        const uint8_t origin = t.squares.front();
        if (sq_rank(origin) != home) continue;
        // Defensive: a trajectory that promotes can only be a pawn's, so this
        // scan cannot currently reject anything the rank test let through. It
        // states the theme's own definition rather than relying on that.
        for (const auto& p : start_pieces)
            if (p.square == origin && p.piece.color == t.color && p.piece.type == PieceType::Pawn)
                return true;
    }
    return false;
}

bool single_for(const Solution& s, Color c) {
    int n = 0;
    for (const auto& t : trajectories(s))
        if (t.color == c) ++n;
    return n == 1;
}

}  // namespace

bool has_promotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion) return true;
    return false;
}

bool has_underpromotion(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.promotion && *p.promotion != PieceType::Queen) return true;
    return false;
}

bool has_excelsior(const Solution& s) { return excelsior_for(s, std::nullopt); }
bool has_excelsior_white(const Solution& s) { return excelsior_for(s, Color::White); }
bool has_excelsior_black(const Solution& s) { return excelsior_for(s, Color::Black); }

bool has_switchback(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i + 2 < t.squares.size(); ++i)
            if (t.squares[i] == t.squares[i + 2]) return true;
    return false;
}

bool has_closed_walk(const Solution& s) {
    for (const auto& t : trajectories(s))
        for (size_t i = 0; i < t.squares.size(); ++i)
            for (size_t j = i + 3; j < t.squares.size(); ++j) {
                if (t.squares[i] != t.squares[j]) continue;
                std::set<uint8_t> mid(t.squares.begin() + i + 1, t.squares.begin() + j);
                // A path that touches its own start square in between is a
                // sequence of switchbacks, not one circuit. The size test
                // restates the theme's two-square minimum; the j >= i + 3 gap
                // already implies it, since a ply always changes square.
                //
                // mid.size() alone only counts DISTINCT intermediate squares:
                // e1-e2-d2-e2-e1 has mid = {e2, d2}, size 2, yet retraces
                // through e2 twice rather than circulating -- a shuffle, not
                // a Rundlauf. Requiring mid.size() == j - i - 1 (every
                // intermediate ply lands on a square none of the others did)
                // rules that out while leaving a genuine circuit (no repeats
                // at all between i and j) unaffected.
                if (mid.size() == j - i - 1 && mid.count(t.squares[i]) == 0) return true;
            }
    return false;
}

bool has_self_block(const Solution& s) {
    const auto ps = final_board(s).pieces();
    int bk = -1;
    for (const auto& p : ps)
        if (p.piece.type == PieceType::King && p.piece.color == Color::Black) bk = p.square;
    if (bk < 0) return false;

    for (int f : king_field(bk)) {
        const PlacedPiece* occ = nullptr;
        for (const auto& p : ps)
            if ((int)p.square == f) occ = &p;
        // The colour and king tests are untestable by DELETION, not untested:
        // in a real mate a white unit standing on a field square is always
        // attacked, so the attackers_of check below already skips it whether
        // or not this line does, and no king is ever adjacent to itself. But
        // INVERTING either check is caught immediately by the self-block
        // positive fixture, whose blocking square g8 holds a black rook --
        // an inverted colour test would skip that rook, an inverted king
        // test would skip it too.
        if (!occ || occ->piece.color != Color::Black || occ->piece.type == PieceType::King) continue;
        // Same king-removed rule as is_pure: a blocked square that White also
        // attacks is not a self-block, it is double duty.
        if (attackers_of(ps, Color::White, f, Color::Black) != 0) continue;
        // The VERDICT is provably right, but not for the tempting reason. This
        // loop does not identify which ply put the occupant on f: black unit A
        // can arrive on f, leave again, and black unit B arrive later, in which
        // case the first match is A's ply, not B's. It is still a genuine
        // self-block, because B cannot be standing on f without a `to == f`
        // ply of its own -- a unit parked on f from the start would have
        // blocked every other black unit from ever moving there. So the answer
        // is correct; do not reuse this loop to report WHICH ply caused it.
        for (const auto& ply : s.plies)  // did a black unit MOVE there?
            if (ply.piece.color == Color::Black && (int)ply.to == f) return true;
    }
    return false;
}

bool is_single_piece_white(const Solution& s) { return single_for(s, Color::White); }
bool is_single_piece_black(const Solution& s) { return single_for(s, Color::Black); }
bool is_single_piece(const Solution& s) { return is_single_piece_white(s) || is_single_piece_black(s); }

bool has_en_passant(const Solution& s) {
    for (const auto& p : s.plies)
        if (p.is_ep) return true;
    return false;
}

bool has_kniest(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk) return true;
    return false;
}

// A unit is captured on S, a later ply recaptures on S with the black king,
// and the black king is mated standing on S.
bool has_zajic(const Solution& s) {
    const Board& fin = final_board(s);
    int bk = -1;
    for (const auto& pp : fin.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) bk = pp.square;
    if (bk < 0) return false;
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (!s.plies[i].captured || (int)s.plies[i].to != bk) continue;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& r = s.plies[j];
            if (r.captured && (int)r.to == bk && r.piece.type == PieceType::King &&
                r.piece.color == Color::Black)
                return true;
        }
    }
    return false;
}

// A unit of type T belonging to side C is captured, and a LATER ply promotes
// a pawn of side C to type T -- the captured unit is reborn.
bool has_phoenix(const Solution& s) {
    for (size_t i = 0; i < s.plies.size(); ++i) {
        const Ply& cap = s.plies[i];
        if (!cap.captured) continue;
        // The captured unit belongs to the side that did NOT move.
        const Color owner = cap.piece.color == Color::White ? Color::Black : Color::White;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            const Ply& pr = s.plies[j];
            if (pr.promotion && *pr.promotion == *cap.captured && pr.piece.color == owner) return true;
        }
    }
    return false;
}

// A pawn promotes on square S; a later ply captures on S; and no ply in
// between moves a unit FROM S. The promoted unit is captured without ever
// having moved.
bool has_schnoebelen(const Solution& s) {
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (!s.plies[i].promotion) continue;
        const int sq = (int)s.plies[i].to;
        for (size_t j = i + 1; j < s.plies.size(); ++j) {
            if ((int)s.plies[j].from == sq) break;  // it moved: not Schnoebelen
            if (s.plies[j].captured && (int)s.plies[j].to == sq) return true;
        }
    }
    return false;
}

// One unit's trajectory visits exactly two distinct squares and has length
// >= 4 -- A,B,A,B, at least two returns. Deliberately NOT exclusive with
// switchback: a pendulum trajectory contains a switchback (A,B,A), and both
// are reported -- exactly as ideal implies model implies pure already does.
bool has_pendulum(const Solution& s) {
    for (const auto& t : trajectories(s)) {
        if (t.squares.size() < 4) continue;
        std::set<uint8_t> distinct(t.squares.begin(), t.squares.end());
        // `== 2`, not `<= 2`: relaxing this to `<= 2` cannot be killed by any
        // fixture built from real plies, so it is worth being explicit about
        // why. `trajectories()` (trajectory.cpp) pushes p.to for every ply,
        // and a chess move always has p.from != p.to -- there is no null
        // move -- so any two SUCCESSIVE entries in `squares` already differ.
        // With size() >= 4 guaranteed by the guard above, that alone forces
        // distinct.size() >= 2 for every trajectory this loop ever sees:
        // distinct.size() == 1 would need every entry equal, which the
        // successive-differ property rules out. So `<= 2` and `== 2` accept
        // exactly the same trajectories over the whole domain of legal
        // Solutions -- an equivalent mutant, not a weaker check -- and no
        // amount of fixture-writing can tell them apart. `== 2` is kept
        // because it states the theme's own two-square definition directly,
        // the same reasoning excelsior_for's rank check above uses for a
        // defensive-but-unkillable-by-deletion condition.
        if (distinct.size() == 2) return true;
    }
    return false;
}

bool is_capture_free(const Solution& s) {
    if (s.plies.empty()) return false;  // nothing was played, so nothing is shown
    for (const auto& p : s.plies)
        if (p.captured) return false;  // `captured` is set for en-passant too
    return true;
}

bool is_check_free(const Solution& s) {
    if (s.plies.empty()) return false;  // nothing was played, so nothing is shown
    // `is_check` on ply i means the side to move AFTER ply i is in check --
    // i.e. ply i gave check. The last ply is the mate and is skipped.
    for (size_t i = 0; i + 1 < s.plies.size(); ++i)
        if (s.plies[i].is_check) return false;
    return true;
}

bool has_umnov(const Solution& s) {
    for (size_t i = 1; i < s.plies.size(); ++i)
        if (s.plies[i].to == s.plies[i - 1].from) return true;
    return false;
}

bool has_umnov_mate(const Solution& s) {
    const size_t n = s.plies.size();
    return n >= 2 && s.plies[n - 1].to == s.plies[n - 2].from;
}

namespace {

// Does a straight move from `from` to `to` pass strictly over `sq`? True only
// for a rank, file or diagonal move whose interior contains sq; a move that
// ENDS on sq, or a knight's leap, never "passes over" anything.
bool passes_over(int from, int to, int sq) {
    const int df = sq_file(to) - sq_file(from), dr = sq_rank(to) - sq_rank(from);
    if (df == 0 && dr == 0) return false;
    if (df != 0 && dr != 0 && std::abs(df) != std::abs(dr)) return false;  // not a line
    const int sf = (df > 0) - (df < 0), sr = (dr > 0) - (dr < 0);
    int f = sq_file(from) + sf, r = sq_rank(from) + sr;
    while (f != sq_file(to) || r != sq_rank(to)) {
        if (r * 8 + f == sq) return true;
        f += sf;
        r += sr;
    }
    return false;
}

bool is_line_piece(PieceType t) {
    return t == PieceType::Queen || t == PieceType::Rook || t == PieceType::Bishop;
}

// The squares a straight move from `from` to `to` passes strictly over, in
// order; empty for a knight's leap or a one-square step.
std::vector<int> squares_between(int from, int to) {
    std::vector<int> out;
    for (int sq = 0; sq < 64; ++sq)
        if (passes_over(from, to, sq)) out.push_back(sq);
    return out;
}

// Where the king of colour `c` stands on `b`, or -1.
int king_square(const Board& b, Color c) {
    for (const auto& pp : b.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == c) return pp.square;
    return -1;
}

// The unit standing on `sq`, if it has colour `c` and is a line piece.
std::optional<PlacedPiece> line_piece_on(const Board& b, int sq, Color c) {
    for (const auto& pp : b.pieces())
        if (pp.square == sq && pp.piece.color == c && is_line_piece(pp.piece.type)) return pp;
    return std::nullopt;
}

// The skeleton Indian and both Maslars share: a CRITICAL MOVE (ply i, a line
// piece of colour `lc` moving a -> b over square c) followed by an
// INTERFERENCE (ply j > i, a unit of colour `ic` arriving on c) while the
// line piece still stands on b. Calls `finish(i, j, b, c)` for every such
// pair and returns true as soon as it does; `finish` inspects the plies
// after j. The line piece's identity is "the unit on b", which is exact
// because the scan stops at the first ply that moves from b or captures on b.
template <class Finish>
bool critical_then_interference(const Solution& s, Color lc, Color ic, bool interferer_may_be_king,
                                Finish&& finish) {
    const int n = (int)s.plies.size();
    for (int i = 0; i < n; ++i) {
        const Ply& crit = s.plies[i];
        if (crit.piece.color != lc || !is_line_piece(crit.piece.type)) continue;
        const int b = crit.to;
        for (int c : squares_between(crit.from, crit.to)) {
            for (int j = i + 1; j < n; ++j) {
                const Ply& p = s.plies[j];
                if (p.from == b || p.to == b) break;  // the line piece moved or was taken
                if (p.to != c || p.piece.color != ic) continue;
                if (!interferer_may_be_king && p.piece.type == PieceType::King) continue;
                if (finish(i, j, b, c)) return true;
            }
        }
    }
    return false;
}

}  // namespace

bool has_klasinc(const Solution& s) {
    for (const auto& t : trajectories(s)) {
        // squares[k] is where the unit stood before ply plies[k]; it leaves
        // squares[k] by that ply and next stands on squares[k2] == squares[k]
        // after ply plies[k2 - 1] -- the return. Anything strictly between the
        // two plies is the window a line piece may pass through.
        for (size_t k = 0; k < t.plies.size(); ++k) {
            const int a = t.squares[k];
            const int leave = t.plies[k];
            for (size_t k2 = k + 1; k2 < t.squares.size(); ++k2) {
                if (t.squares[k2] != a) continue;
                const int back = t.plies[k2 - 1];
                for (int j = leave + 1; j < back; ++j) {
                    // A promoted unit's later plies already carry its promoted
                    // type: collect_solutions reads the mover off the board.
                    const PieceType ty = s.plies[j].piece.type;
                    if (ty != PieceType::Queen && ty != PieceType::Rook && ty != PieceType::Bishop) continue;
                    if (passes_over(s.plies[j].from, s.plies[j].to, a)) return true;
                }
                break;  // the FIRST return closes this window; later returns open their own
            }
        }
    }
    return false;
}

bool has_indian(const Solution& s) {
    const int n = (int)s.plies.size();
    for (Color lc : {Color::White, Color::Black}) {
        const Color enemy = lc == Color::White ? Color::Black : Color::White;
        // The interferer is of the line piece's own colour; it may be the
        // king (a royal battery is still an Indian).
        auto finish = [&](int, int j, int b, int c) {
            for (int k = j + 1; k < n; ++k) {
                const Ply& p = s.plies[k];
                if (p.from == b || p.to == b) return false;  // the line piece moved or was taken
                if (p.from != c) {
                    if (p.to == c) return false;  // the interferer was captured on c
                    continue;
                }
                // The interferer leaves c. It must uncover a check from the
                // line piece along the line through c -- a check the moving
                // unit gives by itself is not the theme.
                if (!p.is_check) return false;
                const int king = king_square(p.after, enemy);
                const auto lp = line_piece_on(p.after, b, lc);
                return king >= 0 && lp && passes_over(b, king, c) &&
                       piece_attacks(p.after.pieces(), *lp, king);
            }
            return false;
        };
        if (critical_then_interference(s, lc, lc, true, finish)) return true;
    }
    return false;
}

bool has_maslar(const Solution& s) {
    const int n = (int)s.plies.size();
    auto finish = [&](int, int j, int b, int c) {
        bool king_arrived = false;
        for (int k = j + 1; k < n; ++k) {
            const Ply& p = s.plies[k];
            if (p.from == b) {
                // The line piece moves at last: it must capture the
                // interferer on c, giving check along the thematic line to a
                // black king that arrived there after the interference.
                if (p.to != c || !p.captured || !p.is_check || !king_arrived) return false;
                const int king = king_square(p.after, Color::Black);
                const auto lp = line_piece_on(p.after, c, Color::White);
                return king >= 0 && lp && passes_over(b, king, c) &&
                       piece_attacks(p.after.pieces(), *lp, king);
            }
            if (p.to == b || p.from == c || p.to == c) return false;  // line piece or interferer disturbed
            // Beyond c as seen from b: between b and c is impossible, the line
            // piece on b attacks those squares.
            if (p.piece.color == Color::Black && p.piece.type == PieceType::King && passes_over(b, p.to, c))
                king_arrived = true;
        }
        return false;
    };
    return critical_then_interference(s, Color::White, Color::Black, false, finish);
}

bool has_maslar_black_white(const Solution& s) {
    const int n = (int)s.plies.size();
    auto finish = [&](int, int j, int b, int c) {
        for (int k = j + 1; k < n; ++k) {
            const Ply& p = s.plies[k];
            if (p.from == b) return p.to == c && p.captured.has_value();
            if (p.to == b || p.from == c || p.to == c) return false;
        }
        return false;
    };
    return critical_then_interference(s, Color::Black, Color::White, false, finish);
}

namespace {
// The fixed display order of the promotion letters, and the map back.
constexpr std::string_view kPromoOrder = "qrbn";
char promo_letter(PieceType t) {
    switch (t) {
        case PieceType::Queen:
            return 'q';
        case PieceType::Rook:
            return 'r';
        case PieceType::Bishop:
            return 'b';
        case PieceType::Knight:
            return 'n';
        default:
            return '?';
    }
}
}  // namespace

std::string canon_sort_promotions(std::string letters) {
    std::sort(letters.begin(), letters.end(),
              [](char x, char y) { return kPromoOrder.find(x) < kPromoOrder.find(y); });
    return letters;
}

std::string promotion_multiset(const Solution& s) {
    std::string out;
    for (const auto& p : s.plies)
        if (p.promotion) out.push_back(promo_letter(*p.promotion));
    return canon_sort_promotions(std::move(out));
}

std::optional<std::string> canon_promotions(std::string_view raw) {
    if (raw.empty() || raw.size() > 8) return std::nullopt;
    std::string letters;
    for (char c : raw) {
        const char l = (char)std::tolower((unsigned char)c);
        if (kPromoOrder.find(l) == std::string_view::npos) return std::nullopt;
        letters.push_back(l);
    }
    return canon_sort_promotions(std::move(letters));
}

}  // namespace hm::themes

#pragma once
#include "probe/solution.h"

namespace hm::themes {

// Detectors that walk one solution's plies. All share the Detector signature.

bool has_promotion(const Solution& s);       // any ply promotes a pawn
bool has_underpromotion(const Solution& s);  // any ply promotes to R, B or N

// A pawn standing on its OWN second rank at the start of the solution
// promotes during it.
bool has_excelsior(const Solution& s);
bool has_excelsior_white(const Solution& s);
bool has_excelsior_black(const Solution& s);

// A unit leaves a square and returns to it, having visited exactly one
// intermediate square (out and back).
bool has_switchback(const Solution& s);

// Rundlauf: a unit returns to its departure square having visited two or more
// DISTINCT intermediate squares, traversing a circuit rather than retracing
// its path. Mutually exclusive with switchback for a given return event, but
// one solution may show both, by different units.
bool has_closed_walk(const Solution& s);

// A black unit other than the king moves onto a square of the black king's
// field, and in the mating position that square holds that unit and is NOT
// attacked by White.
bool has_self_block(const Solution& s);

// Every move by that side is made by the same unit.
bool is_single_piece_white(const Solution& s);
bool is_single_piece_black(const Solution& s);
bool is_single_piece(const Solution& s);  // either side

bool has_en_passant(const Solution& s);  // any ply is an en-passant capture

// Some ply captures on square S, and in the mating position the black king
// stands on S. S is read as `p.to`, the capture ply's destination square.
// For an en-passant capture the victim actually stands BESIDE `p.to` (see
// trajectory.cpp's `gone` computation), not on it -- this detector does not
// correct for that. Deliberate, not an oversight: `p.to` is where the
// capturing unit ends up, and kniest asks whether the king is later mated on
// that square, which is well-defined for ep captures too. Behaviour is
// unchanged; this is a documented reading, not a bug.
bool has_kniest(const Solution& s);

// A unit is captured on square S, a later ply recaptures on S with the black
// king, and the black king is mated standing on S. Same `p.to`-as-S reading
// as has_kniest above, including for an en-passant first capture: S is the
// capturing pawn's destination square, not the (adjacent) square the ep
// victim actually stood on. Deliberate, not an oversight.
bool has_zajic(const Solution& s);

// A unit of type T belonging to side C is captured, and a LATER ply promotes
// a pawn of side C to type T -- the captured unit is reborn.
bool has_phoenix(const Solution& s);

// A pawn promotes on square S; a later ply captures on S; and no ply in
// between moves a unit FROM S. The promoted unit is captured without ever
// having moved.
bool has_schnoebelen(const Solution& s);

// One unit's trajectory visits exactly two distinct squares and has length
// >= 4 -- A,B,A,B, at least two returns. Deliberately NOT exclusive with
// switchback: a pendulum trajectory contains a switchback (A,B,A), and both
// are reported.
bool has_pendulum(const Solution& s);

// No ply captures anything (en-passant captures included). A solution with
// no plies at all -- the queried position was already mate -- shows neither
// of these two, like every other line theme; see the registry entries for
// how they combine across a position's solution SET (every solution, not
// any).
bool is_capture_free(const Solution& s);

// No ply before the last one gives check. The final ply is exempt: in a
// helpmate it is the mating move, which is always a check, so a rule that
// counted it would never match. Whether the final ply actually checks is not
// examined at all -- the theme is about the play BEFORE the mate.
bool is_check_free(const Solution& s);

// Umnov: a ply lands on the square the immediately preceding ply -- always
// the opponent's, plies alternate -- vacated (plies[i].to == plies[i-1].from).
bool has_umnov(const Solution& s);

// Umnov mate: the mating move lands on the square Black's last move vacated.
// The last-ply case of has_umnov, kept as its own theme the way switchback
// and pendulum are.
bool has_umnov_mate(const Solution& s);

// Klasinc: a unit A leaves square a; later a line piece (queen, rook or
// bishop, either colour; a promoted queen counts, since a ply carries the
// mover's type as it stands) moves along a rank, file or diagonal that passes strictly over a;
// after that A returns to a. "Passes over" excludes a move that ends ON a,
// and A's return must be the next time A stands on a after leaving it.
bool has_klasinc(const Solution& s);

// The three below share one skeleton: a CRITICAL MOVE, in which a line piece
// L (queen, rook or bishop) moves a -> b passing strictly over square c,
// followed by an INTERFERENCE, a unit arriving on c while L still stands on
// b. What must happen next differs. Throughout, L must not move from b or be
// captured there, and the interferer must not leave or be captured on c,
// until the theme's last move.

// Indian (Loveday): the interferer is of L's own colour (the king counts),
// and later it moves off c giving check, with L on b attacking the enemy king
// along the line through c -- a discovered check from the critical line.
// Either colour.
bool has_indian(const Solution& s);

// Maslar: L is white, the interferer a black unit other than the king; after
// the interference the black king arrives on the thematic line beyond c, and
// then L captures the interferer on c giving check along that line.
bool has_maslar(const Solution& s);

// Black-White Maslar: L is black, the interferer a white unit other than the
// king, and L finally captures it on c. The definition asks for no king
// arrival and no check, so none is required.
bool has_maslar_black_white(const Solution& s);

// The solution's promotions as a canonical multiset string: one letter per
// promotion, either colour, sorted in the fixed order q, r, b, n -- "qrr" for
// one queen and two rooks. Empty when nothing promotes. `promotions:<types>`
// concatenates these over the whole solution set (set_themes.cpp).
std::string promotion_multiset(const Solution& s);

// Sorts a string of promotion letters into the canonical q, r, b, n order.
std::string canon_sort_promotions(std::string letters);

// The canonical form of a user-typed promotion multiset: letters q r b n in
// any order and case, one to eight of them, re-sorted to q, r, b, n. nullopt
// for anything else (an empty string, a stray letter, too many letters).
std::optional<std::string> canon_promotions(std::string_view raw);

}  // namespace hm::themes

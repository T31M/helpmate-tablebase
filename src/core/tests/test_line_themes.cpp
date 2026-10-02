#include <catch2/catch_test_macros.hpp>
#include <set>

#include "probe/solution.h"
#include "themes/line_themes.h"
#include "themes/trajectory.h"

using namespace hm;
using namespace hm::themes;

static int sq(const char* n) { return (n[1] - '1') * 8 + (n[0] - 'a'); }

// Build a Solution by playing UCI-ish moves onto a start FEN. Each entry is
// {from, to, promotion}. The boards are produced by Board::make so `after`,
// captures and en passant are real, not asserted. The ply fields are filled the
// same way Tablebase::collect_solutions fills them -- including the en-passant
// rule that the captured pawn is NOT on the destination square -- so a detector
// cannot pass here on a ply shape the generator never produces.
struct MoveSpec {
    const char* from;
    const char* to;
    std::optional<PieceType> promo;
};

static Solution play(const std::string& fen, const std::vector<MoveSpec>& specs) {
    auto b = Board::from_fen(fen);
    REQUIRE(b);
    Solution s{*b, {}};
    Board cur = *b;
    for (const auto& ms : specs) {
        const Move* found = nullptr;
        auto legal = cur.legal_moves();
        for (const auto& m : legal)
            if ((int)m.from == sq(ms.from) && (int)m.to == sq(ms.to) && m.promotion() == ms.promo) found = &m;
        REQUIRE(found != nullptr);  // the fixture asked for an illegal move
        Ply p;
        p.from = found->from;
        p.to = found->to;
        p.promotion = found->promotion();
        p.is_ep = found->is_ep();
        for (const auto& pp : cur.pieces()) {
            if ((int)pp.square == (int)found->from) p.piece = pp.piece;
            else if ((int)pp.square == (int)found->to) p.captured = pp.piece.type;
        }
        if (p.is_ep) p.captured = PieceType::Pawn;
        cur.make(*found);
        p.is_check = cur.in_check();
        p.after = cur;
        s.plies.push_back(std::move(p));
    }
    return s;
}

TEST_CASE("trajectories chain a unit's squares through the solution", "[themes][line]") {
    // White king walks e1-e2-e3; black king shuffles a8-b8.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e3", {}}});
    auto ts = trajectories(s);
    REQUIRE(ts.size() == 2);
    for (const auto& t : ts) {
        if (t.color == Color::White) {
            REQUIRE(t.squares ==
                    std::vector<uint8_t>{(uint8_t)sq("e1"), (uint8_t)sq("e2"), (uint8_t)sq("e3")});
            REQUIRE(t.plies == std::vector<int>{0, 2});
        } else {
            REQUIRE(t.squares.size() == 2);
            REQUIRE(t.plies == std::vector<int>{1});
        }
    }
}

TEST_CASE("a unit arriving on a captured unit's square starts its own trajectory", "[themes][line]") {
    // Black Rd8 and pawn d6, white Rd1, kings h8 and a1. The pawn steps to d5,
    // White takes it (Rd1xd5), then the rook recaptures onto the SAME square
    // (Rd8xd5). Two black units moved, so the arrival must not be chained onto
    // the dead pawn's path.
    auto s =
        play("3r3k/8/3p4/8/8/8/8/K2R4 b - - 0 1", {{"d6", "d5", {}}, {"d1", "d5", {}}, {"d8", "d5", {}}});
    auto ts = trajectories(s);
    REQUIRE(ts.size() == 3);
    REQUIRE(ts[0].color == Color::Black);
    REQUIRE(ts[0].squares == std::vector<uint8_t>{(uint8_t)sq("d6"), (uint8_t)sq("d5")});
    REQUIRE(ts[1].color == Color::White);
    REQUIRE(ts[2].color == Color::Black);
    REQUIRE(ts[2].squares == std::vector<uint8_t>{(uint8_t)sq("d8"), (uint8_t)sq("d5")});
    REQUIRE(s.plies[1].captured == PieceType::Pawn);
    REQUIRE_FALSE(is_single_piece_black(s));
    REQUIRE(is_single_piece_white(s));
}

TEST_CASE("promotion and underpromotion", "[themes][line]") {
    auto queen = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1", {{"g2", "g4", {}},
                                                         {"a8", "b8", {}},
                                                         {"g4", "g5", {}},
                                                         {"b8", "a8", {}},
                                                         {"g5", "g6", {}},
                                                         {"a8", "b8", {}},
                                                         {"g6", "g7", {}},
                                                         {"b8", "a8", {}},
                                                         {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_promotion(queen));
    REQUIRE_FALSE(has_underpromotion(queen));

    auto knight = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1", {{"g2", "g4", {}},
                                                          {"a8", "b8", {}},
                                                          {"g4", "g5", {}},
                                                          {"b8", "a8", {}},
                                                          {"g5", "g6", {}},
                                                          {"a8", "b8", {}},
                                                          {"g6", "g7", {}},
                                                          {"b8", "a8", {}},
                                                          {"g7", "g8", PieceType::Knight}});
    REQUIRE(has_promotion(knight));
    REQUIRE(has_underpromotion(knight));
}

TEST_CASE("excelsior: a pawn from its own second rank promotes", "[themes][line]") {
    auto s = play("k7/8/8/8/8/8/6P1/4K3 w - - 0 1", {{"g2", "g4", {}},
                                                     {"a8", "b8", {}},
                                                     {"g4", "g5", {}},
                                                     {"b8", "a8", {}},
                                                     {"g5", "g6", {}},
                                                     {"a8", "b8", {}},
                                                     {"g6", "g7", {}},
                                                     {"b8", "a8", {}},
                                                     {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_excelsior(s));
    REQUIRE(has_excelsior_white(s));
    REQUIRE_FALSE(has_excelsior_black(s));

    // Near-miss: same promotion, but the pawn starts on g4, not its home rank.
    auto near = play("k7/8/8/8/6P1/8/8/4K3 w - - 0 1", {{"g4", "g5", {}},
                                                        {"a8", "b8", {}},
                                                        {"g5", "g6", {}},
                                                        {"b8", "a8", {}},
                                                        {"g6", "g7", {}},
                                                        {"a8", "b8", {}},
                                                        {"g7", "g8", PieceType::Queen}});
    REQUIRE(has_promotion(near));
    REQUIRE_FALSE(has_excelsior(near));
}

TEST_CASE("excelsior is detected for Black on its own seventh rank", "[themes][line]") {
    // Black Kh8 and a pawn on b7; white Ke1 marks time on e1/e2 while the pawn
    // runs b7-b5-b4-b3-b2-b1=Q. The white king is never in check: the pawn only
    // ever bears on the a- and c-files.
    auto s = play("7k/1p6/8/8/8/8/8/4K3 b - - 0 1", {{"b7", "b5", {}},
                                                     {"e1", "e2", {}},
                                                     {"b5", "b4", {}},
                                                     {"e2", "e1", {}},
                                                     {"b4", "b3", {}},
                                                     {"e1", "e2", {}},
                                                     {"b3", "b2", {}},
                                                     {"e2", "e1", {}},
                                                     {"b2", "b1", PieceType::Queen}});
    REQUIRE(has_excelsior(s));
    REQUIRE(has_excelsior_black(s));
    REQUIRE_FALSE(has_excelsior_white(s));
}

TEST_CASE("a pawn that leaves its home rank without promoting is not excelsior", "[themes][line]") {
    // The black d-pawn starts on d7, its home rank, and moves -- but never
    // reaches the eighth. Excelsior needs the promotion, not just the origin.
    auto s = play("k7/3p4/8/4P3/8/8/8/4K3 b - - 0 1", {{"d7", "d5", {}}, {"e5", "d6", {}}});
    REQUIRE_FALSE(has_excelsior(s));
    REQUIRE_FALSE(has_excelsior_black(s));
}

TEST_CASE("switchback is out-and-back with exactly one intermediate square", "[themes][line]") {
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e1", {}}});
    REQUIRE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
}

TEST_CASE("closed walk is a circuit of two or more intermediate squares", "[themes][line]") {
    // White king e1-e2-d2-d1-e1: three distinct intermediate squares. The black
    // king walks a8-b8-c8-d8 rather than shuffling, so it contributes no
    // return of its own to either verdict.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "d2", {}},
                                                   {"b8", "c8", {}},
                                                   {"d2", "d1", {}},
                                                   {"c8", "d8", {}},
                                                   {"d1", "e1", {}}});
    REQUIRE(has_closed_walk(s));
    REQUIRE_FALSE(has_switchback(s));
}

TEST_CASE("a repeated shuffle is a switchback, not a circuit", "[themes][line]") {
    // White king e1-e2-e1-e2-e1 returns to its origin after four moves, but the
    // squares between the two ends repeat, so this retraces rather than
    // circulates. The black king a8-b8-a8-b8 never returns on an index gap of
    // three or more, so it cannot rescue the closed-walk verdict either.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "e1", {}},
                                                   {"b8", "a8", {}},
                                                   {"e1", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "e1", {}}});
    REQUIRE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
}

TEST_CASE("a shuffle that revisits its own turning square is a switchback, not a closed walk",
          "[themes][line]") {
    // White king e1-e2-d2-e2-e1: it returns to e1 having touched two DISTINCT
    // squares along the way (e2, d2), which naive "count of distinct
    // intermediates >= 2" would call a circuit -- but the path re-enters e2
    // on the way back, so it retraces rather than circulates. This is the
    // same unit under one continuous out-and-back reading: e2-d2-e2 (one
    // intermediate square, d2) is itself a switchback.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "d2", {}},
                                                   {"b8", "a8", {}},
                                                   {"d2", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "e1", {}}});
    REQUIRE_FALSE(has_closed_walk(s));
    REQUIRE(has_switchback(s));
}

TEST_CASE("a unit that never returns shows neither walk theme", "[themes][line]") {
    // White king walks e1-e2-e3-e4-e5 -- a straight climb up the e-file that
    // revisits nothing, four plies so the trajectory reaches five squares and
    // exercises the closed-walk endpoint test's j >= i + 3 gap (e.g. i at e1,
    // j at e4). Black king walks a8-b8-c8-d8-e8 in step, an equally monotonic
    // line with no repeated square, so it cannot rescue either verdict either.
    auto s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}},
                                                   {"a8", "b8", {}},
                                                   {"e2", "e3", {}},
                                                   {"b8", "c8", {}},
                                                   {"e3", "e4", {}},
                                                   {"c8", "d8", {}},
                                                   {"e4", "e5", {}},
                                                   {"d8", "e8", {}}});
    REQUIRE_FALSE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
}

TEST_CASE("single-piece is evaluated per side", "[themes][line]") {
    // White moves only its king; Black moves only its king.
    auto both = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}, {"a8", "b8", {}}, {"e2", "e3", {}}});
    REQUIRE(is_single_piece_white(both));
    REQUIRE(is_single_piece_black(both));
    REQUIRE(is_single_piece(both));

    // White moves king then rook: two white units. The rook stands on h1, not
    // a1, so it does not attack the black king on a8 -- a white rook on the
    // a-file would make this a position with Black already in check and White
    // to move, which is illegal.
    auto two = play("k7/8/8/8/8/8/8/4K2R w - - 0 1", {{"e1", "e2", {}}, {"a8", "b8", {}}, {"h1", "h4", {}}});
    REQUIRE_FALSE(is_single_piece_white(two));
    REQUIRE(is_single_piece_black(two));
    REQUIRE(is_single_piece(two));  // "either side" still holds
}

TEST_CASE("en passant is recognised", "[themes][line]") {
    // White pawn e5, black plays d7-d5, White captures exd6 e.p.
    auto s = play("k7/3p4/8/4P3/8/8/8/4K3 b - - 0 1", {{"d7", "d5", {}}, {"e5", "d6", {}}});
    REQUIRE(s.plies.back().is_ep);
    REQUIRE(has_en_passant(s));
    REQUIRE(s.plies.back().captured == PieceType::Pawn);

    auto quiet = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}});
    REQUIRE_FALSE(has_en_passant(quiet));
    REQUIRE_FALSE(has_promotion(quiet));
}

TEST_CASE("self-block: a black unit steps onto an unattacked flight square", "[themes][line]") {
    // Black Kh8 and Rb8; white Nf5, Rb1, Ka1. The rook swings to g8, beside its
    // own king, and Rb1-h1 mates up the h-file: h7 is denied by the mating rook
    // itself, g7 by the knight, and g8 only by the black rook standing on it --
    // no white unit bears on g8, so the block is the sole reason that flight is
    // gone.
    auto s = play("1r5k/8/8/5N2/8/8/8/KR6 b - - 0 1", {{"b8", "g8", {}}, {"b1", "h1", {}}});
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE(has_self_block(s));
}

TEST_CASE("a self-blocked square White also attacks is not a self-block", "[themes][line]") {
    // The same mate with a white bishop added on b3, whose diagonal
    // b3-c4-d5-e6-f7-g8 bears on the blocking square. g8 is now denied twice
    // over -- double duty, not a self-block.
    auto s = play("1r5k/8/8/5N2/8/1B6/8/KR6 b - - 0 1", {{"b8", "g8", {}}, {"b1", "h1", {}}});
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE_FALSE(has_self_block(s));
}

TEST_CASE("a square attacked only through the mated king is not a self-block", "[themes][line]") {
    // Black Kg8 and Rh7; white Bh6, Ng5, Ra1, Ke1. Black plays Rh7-h8 and
    // Ra1-a8 mates along the eighth (f7 and h7 covered by the knight, g7 by the
    // bishop). The rook on h8 sits on a field square, and with the mated king
    // lifted off g8 the mating rook's ray reaches h8: attacked, so not a
    // self-block. With the king left on the board the ray stops short and this
    // would read as one.
    auto s = play("6k1/7r/7B/6N1/8/8/8/R3K3 b - - 0 1", {{"h7", "h8", {}}, {"a1", "a8", {}}});
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE_FALSE(has_self_block(s));
}

TEST_CASE("a black unit already beside its king is not a self-block", "[themes][line]") {
    // The self-block mate reached WITHOUT the black rook ever moving: it starts
    // on g8, White plays Rb1-h1 and the identical mating position arises. The
    // blocking square is just as unattacked, so only the missing black move
    // separates this from the positive case.
    auto s = play("6rk/8/8/5N2/8/8/8/KR6 w - - 0 1", {{"b1", "h1", {}}});
    REQUIRE(final_board(s).state() == PosState::Checkmate);
    REQUIRE_FALSE(has_self_block(s));
}

TEST_CASE("a position with no black king self-blocks nothing", "[themes][line]") {
    // Board::from_fen insists on one king per side, so build this board
    // directly: white Ke1 and Ra1, White to move, no black king anywhere. The
    // self-block scan must answer false rather than take a king field around a
    // square index of -1.
    Solution s{
        Board::from_pieces({{{Color::White, PieceType::King}, 4}, {{Color::White, PieceType::Rook}, 0}},
                           Color::White, -1),
        {}};
    REQUIRE_FALSE(has_self_block(s));
}

// The black king's square on a board, or -1.
static int bk_of(const Board& b) {
    for (const auto& pp : b.pieces())
        if (pp.piece.type == PieceType::King && pp.piece.color == Color::Black) return pp.square;
    return -1;
}

TEST_CASE("kniest: a capture on the square the king is later mated on", "[themes][line]") {
    // Black Kb8, white Na8 (undefended), white Kb6, white Rh1. Black plays
    // Kb8xa8, capturing the knight; White answers Rh1-h8#. The corner mate is
    // a textbook R+K pattern: Rh8 checks along the rank and covers b8, Kb6
    // covers a7 and b7 -- verified with the real tablebase (material KRNvk):
    // probing the start FEN gives dtm=2 (h#1), and `helpmate line` returns
    // exactly "Kxa8 Rh8#".
    Solution s = play("Nk6/8/1K6/8/8/8/8/7R b - - 0 1", {{"b8", "a8", {}}, {"h1", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);  // it really is mate
    const int bk = bk_of(fin);
    REQUIRE(bk >= 0);
    bool captured_on_bk = false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk) captured_on_bk = true;
    REQUIRE(captured_on_bk);  // the fixture really shows it
    CHECK(has_kniest(s));
}

TEST_CASE("kniest: a capture elsewhere is not kniest", "[themes][line]") {
    // Black Kh8 (never moves), black Na7, white Ke1, white Ra1. White plays
    // Ra1xa7, a capture far from the black king's square. Verified with the
    // real tablebase (material KRvkn): both the start FEN and the FEN after
    // Rxa7 probe to finite, non-error dtm values (9 and 10 respectively), so
    // the position and the move are legal chess, not just accepted by
    // Board::legal_moves() in isolation.
    Solution s = play("7k/n7/8/8/8/8/8/R3K3 w - - 0 1", {{"a1", "a7", {}}});
    const int bk = bk_of(final_board(s));
    bool any_capture = false, on_bk = false;
    for (const auto& p : s.plies) {
        if (p.captured) any_capture = true;
        if (p.captured && (int)p.to == bk) on_bk = true;
    }
    REQUIRE(any_capture);  // a fixture with no capture would pass for the wrong reason
    REQUIRE_FALSE(on_bk);
    CHECK_FALSE(has_kniest(s));
}

TEST_CASE("kniest: the king merely ending on a square is not enough", "[themes][line]") {
    // White king walks e1-e2; black king shuffles a8-b8. No captures at all,
    // the same quiet-walk fixture shape used by the trajectory tests above.
    Solution s = play("k7/8/8/8/8/8/8/4K3 w - - 0 1", {{"e1", "e2", {}}, {"a8", "b8", {}}});
    for (const auto& p : s.plies) REQUIRE_FALSE(p.captured);
    CHECK_FALSE(has_kniest(s));
}

TEST_CASE("zajic: capture on S, king recaptures on S, mated on S", "[themes][line]") {
    // White Kb6, Nc7, Rh1; black Kb8, Ba8; White to move. White plays
    // Nc7xa8, capturing the bishop that started on a8 -- the first capture on
    // S. Black recaptures with the king, Kb8xa8 -- the king's recapture on
    // S. White mates with Rh1-h8#: the same corner pattern as the kniest
    // fixture (rook checks along the eighth, king covers a7/b7), just
    // reached one capture later.
    //
    // Legality comes from `play()`, which REQUIREs each move be found among
    // Board::legal_moves() -- an impossible fixture fails loudly. Mate comes
    // from REQUIRE(fin.state() == PosState::Checkmate) below, computed by
    // the same real Board class the rest of the engine uses, backed by the
    // structural REQUIREs pinning which square each capture lands on.
    //
    // Tablebase cross-verification was NOT performed: this fixture's
    // material is KNRvkb (5 pieces), and three attempts to `helpmate gen`
    // it each exceeded the time budget before the main slice finished --
    // see task-6-report.md.
    Solution s =
        play("bk6/2N5/1K6/8/8/8/8/7R w - - 0 1", {{"c7", "a8", {}}, {"b8", "a8", {}}, {"h1", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);
    const int bk = bk_of(fin);
    REQUIRE(bk == sq("a8"));

    bool first_capture_on_s = false, king_recapture_on_s = false;
    for (size_t i = 0; i < s.plies.size(); ++i) {
        if (s.plies[i].captured && (int)s.plies[i].to == bk) first_capture_on_s = true;
    }
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == bk && p.piece.type == PieceType::King && p.piece.color == Color::Black)
            king_recapture_on_s = true;
    REQUIRE(first_capture_on_s);   // Nxa8: the bishop is captured on S
    REQUIRE(king_recapture_on_s);  // Kxa8: the king recaptures on S
    CHECK(has_zajic(s));
}

TEST_CASE("zajic: the second capture on S is not by the king", "[themes][line]") {
    // White Ke1, Nc7; black Kh8, Ra5, Ba8; White to move. White plays
    // Nc7xa8, capturing the bishop -- same first-capture-on-S shape as the
    // positive fixture. But the recapture on a8 is Ra5xa8, a black ROOK, not
    // the king; the black king (h8) never goes near a8.
    Solution s = play("b6k/2N5/8/r7/8/8/8/4K3 w - - 0 1", {{"c7", "a8", {}}, {"a5", "a8", {}}});
    REQUIRE(s.plies.size() == 2);
    REQUIRE(s.plies[0].captured);             // Nxa8
    REQUIRE((int)s.plies[0].to == sq("a8"));  // ... on S
    const Ply& recapture = s.plies[1];
    REQUIRE(recapture.captured);
    REQUIRE((int)recapture.to == sq("a8"));            // Rxa8: also on S ...
    REQUIRE(recapture.piece.type != PieceType::King);  // ... but not the king
    CHECK_FALSE(has_zajic(s));
}

TEST_CASE("zajic: the king recaptures on S but is mated elsewhere", "[themes][line]") {
    // White Kb6, Nc7, Rh5; black Kb8, Ba8; White to move. White plays
    // Nc7xa8 (capture on S=a8), Black recaptures Kb8xa8 (king recapture on
    // S=a8) -- both halves of the shape are present. But the king does not
    // stay put: White marks time with Rh5-h4, Black walks the king back
    // Ka8-b8, and White mates on b8 with Rh4-h8#, the king's own escort
    // (Kb6 covers a7/b7/c7) sealing every flight square. The mate square
    // (b8) is not S (a8), so this must NOT read as zajic.
    Solution s =
        play("bk6/2N5/1K6/7R/8/8/8/8 w - - 0 1",
             {{"c7", "a8", {}}, {"b8", "a8", {}}, {"h5", "h4", {}}, {"a8", "b8", {}}, {"h4", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);
    const int bk = bk_of(fin);
    REQUIRE(bk != sq("a8"));
    REQUIRE(bk == sq("b8"));

    bool king_recapture_on_a8 = false;
    for (const auto& p : s.plies)
        if (p.captured && (int)p.to == sq("a8") && p.piece.type == PieceType::King &&
            p.piece.color == Color::Black)
            king_recapture_on_a8 = true;
    REQUIRE(king_recapture_on_a8);  // the fixture really shows the king recapturing on S
    CHECK_FALSE(has_zajic(s));
}

TEST_CASE("zajic: the WHITE king capturing on S is not a recapture either", "[themes][line]") {
    // A fourth, non-required case added specifically because the mutation
    // check (dropping `r.piece.color == Color::Black`) survives all three
    // cases the brief asks for: none of them has a WHITE king doing a
    // capture on the square the black king later reaches. Without this
    // fixture, that conjunct is untested by deletion.
    //
    // Black Bg8, white Nd5, white Kc4 (blocked from the bishop's check by
    // its own knight), black Kh1; black to move. Bg8xd5 captures the knight
    // (first capture on S=d5) and opens check on c4 along the same
    // diagonal, so White's only reply, Kc4xd5, captures the bishop on S --
    // a second capture on S by a KING, but the WHITE king, not black's. Both
    // kings then shuffle, alone on the board, back down the same a8-h1
    // diagonal (White retreating d5-c4-b3-a2, Black following
    // h1-g2-f3-e4-d5) until the black king peacefully occupies d5 -- so the
    // black king's FINAL square really is S, same as the wrongly-colored
    // recapture, without the black king ever itself recapturing there.
    Solution s = play("6b1/8/8/3N4/2K5/8/8/7k b - - 0 1", {{"g8", "d5", {}},
                                                           {"c4", "d5", {}},
                                                           {"h1", "g2", {}},
                                                           {"d5", "c4", {}},
                                                           {"g2", "f3", {}},
                                                           {"c4", "b3", {}},
                                                           {"f3", "e4", {}},
                                                           {"b3", "a2", {}},
                                                           {"e4", "d5", {}}});
    REQUIRE(s.plies.size() == 9);
    REQUIRE(s.plies[0].captured);             // Bxd5
    REQUIRE((int)s.plies[0].to == sq("d5"));  // ... on S

    const Ply& wk_recapture = s.plies[1];
    REQUIRE(wk_recapture.captured);                       // Kxd5
    REQUIRE((int)wk_recapture.to == sq("d5"));            // ... on S too
    REQUIRE(wk_recapture.piece.type == PieceType::King);  // a king recaptures ...
    REQUIRE(wk_recapture.piece.color == Color::White);    // ... but the WHITE one

    const int bk = bk_of(final_board(s));
    REQUIRE(bk == sq("d5"));  // the black king really does end up on S, just never captured there
    CHECK_FALSE(has_zajic(s));
}

TEST_CASE("zajic: the king's own capture on S is not also its own recapture", "[themes][line]") {
    // A fifth, non-required case, added for the same reason as the fourth:
    // the mutation check (changing the inner loop's `j = i + 1` to `j = 0`)
    // survives all four cases above, because none of them puts a LONE
    // king-capture on the mating square with nothing captured there before
    // it. With `j = 0` the inner loop revisits ply i itself, so that single
    // capture satisfies both "the earlier capture" and "the recapture" --
    // the same self-match bug, one loop bound over.
    //
    // Reuses the kniest positive fixture's FEN verbatim (already verified
    // against the real tablebase in task-5-report.md: KRNvk, dtm=2, line
    // "Kxa8 Rh8#") but stops after the first half-move, Kb8xa8, so the
    // solution has exactly one ply and no White reply at all.
    Solution s = play("Nk6/8/1K6/8/8/8/8/7R b - - 0 1", {{"b8", "a8", {}}});
    REQUIRE(s.plies.size() == 1);
    const int bk = bk_of(final_board(s));
    REQUIRE(bk == sq("a8"));
    REQUIRE(s.plies[0].captured);       // Kxa8
    REQUIRE((int)s.plies[0].to == bk);  // ... on S, which is also the final bk
    REQUIRE(s.plies[0].piece.type == PieceType::King);
    REQUIRE(s.plies[0].piece.color == Color::Black);
    CHECK_FALSE(has_zajic(s));  // one capture is not a capture AND a later recapture
}

TEST_CASE("phoenix: a captured knight reborn by a black pawn's promotion", "[themes][line]") {
    // White Kb6, Rh1; black Ka8, Nh7, Pb2; White to move. White plays
    // Rh1xh7, capturing the black knight (owner: the side that did NOT
    // move, i.e. Black -- the definition's subtlety). Black promotes
    // b2-b1=N, a LATER ply, a black pawn to the same type just captured.
    // White then plays Rh7-h8#: the same Kb6+R corner mate geometry as the
    // kniest/zajic fixtures (rook checks along the eighth, king covers
    // a7/b7), reached after the capture-then-promotion detour.
    //
    // Material KRvknp (5 men): task 7's own scratch `helpmate gen` attempt
    // under the 180s single-command limit did not complete (see
    // task-7-report.md). But `~/tb` -- a pre-built, read-only 190-table
    // corpus, never written to -- already holds KRvknp.hm, and probing this
    // exact start FEN against it confirms the fixture directly:
    //   $ ./build/helpmate probe "k7/7n/1K6/8/8/8/1p6/7R w - - 0 1" --tables ~/tb
    //   dtm=3 (h#1.5) count=27
    //   $ ./build/helpmate line "k7/7n/1K6/8/8/8/1p6/7R w - - 0 1" --tables ~/tb --all --max 30
    //   ... (27 lines total, including) ...
    //   Rxh7 b1=N Rh8#
    // `Rxh7 b1=N Rh8#` is this fixture's exact three-ply line, and it is one
    // of the 27 optimal (dtm=3) solutions from this position -- not merely
    // legal chess, but a genuine optimal helpmate line. Legality of every
    // move also comes from `play()`, which REQUIREs each move be found
    // among Board::legal_moves() -- an impossible fixture fails loudly.
    // Mate comes from REQUIRE(fin.state() == PosState::Checkmate) below,
    // computed by the same real Board class the rest of the engine uses.
    Solution s = play("k7/7n/1K6/8/8/8/1p6/7R w - - 0 1",
                      {{"h1", "h7", {}}, {"b2", "b1", PieceType::Knight}, {"h7", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);
    REQUIRE(s.plies.size() == 3);
    const Ply& cap = s.plies[0];
    const Ply& promo = s.plies[1];
    REQUIRE(cap.captured);
    REQUIRE(*cap.captured == PieceType::Knight);  // the captured unit really is a knight
    REQUIRE(promo.promotion);
    REQUIRE(*promo.promotion == PieceType::Knight);  // ... and the LATER promotion is to the same type
    REQUIRE(promo.piece.color == Color::Black);      // ... by a black pawn
    CHECK(has_phoenix(s));
}

TEST_CASE("phoenix: promotion to a different type is not phoenix", "[themes][line]") {
    // Same fixture as the positive up to the promotion, but Black promotes
    // to a queen instead of a knight -- the captured type and the promoted
    // type differ. (No third, mating move here: the queen delivers check
    // to White's own king, so Rh7-h8 is no longer legal -- irrelevant to
    // this predicate, which only inspects the capture and promotion plies.)
    Solution s = play("k7/7n/1K6/8/8/8/1p6/7R w - - 0 1", {{"h1", "h7", {}}, {"b2", "b1", PieceType::Queen}});
    REQUIRE(s.plies.size() == 2);
    REQUIRE(s.plies[0].captured);
    REQUIRE(*s.plies[0].captured == PieceType::Knight);
    REQUIRE(s.plies[1].promotion);
    REQUIRE(*s.plies[0].captured != *s.plies[1].promotion);  // knight captured, queen promoted -- differ
    CHECK_FALSE(has_phoenix(s));
}

TEST_CASE("phoenix: the promoting side must be the captured unit's owner, not the capturer",
          "[themes][line]") {
    // White Kb6, Rh1, Pe7; black Ka8, Nh7; White to move. White plays
    // Rh1xh7, capturing the black knight (owner: Black, same shape as the
    // positive). Black plays Ka8-b8, a spacer move so the promotion is a
    // LATER, distinct ply -- but it is not a free choice: the white king on
    // b6 covers both a7 and b7, so b8 is Black's only legal move here. White
    // then promotes its OWN pawn, e7-e8=N -- a knight reborn, but on the WRONG
    // side: the promoter is White, the same side that did the capturing,
    // not Black, the side that lost the knight. A detector that derives
    // owner from the mover's own colour instead of the opponent's would
    // wrongly call this phoenix.
    //
    // Legality of every move verified with `play()`, same as above. Material
    // KRPvkn (5 men) was also killed after exceeding the 180s single-command
    // limit during `helpmate gen`; see task-7-report.md. This fixture does
    // not end in checkmate (White still has a pawn's worth of decisions
    // left to make to actually mate an escaping king from b8), so no
    // REQUIRE(Checkmate) is made here -- the shape assertions below are the
    // evidence, matching kniest's and zajic's negative fixtures.
    Solution s = play("k7/4P2n/1K6/8/8/8/8/7R w - - 0 1",
                      {{"h1", "h7", {}}, {"a8", "b8", {}}, {"e7", "e8", PieceType::Knight}});
    REQUIRE(s.plies.size() == 3);
    const Ply& cap = s.plies[0];
    const Ply& promo = s.plies[2];
    REQUIRE(cap.captured);
    REQUIRE(*cap.captured == PieceType::Knight);
    REQUIRE(promo.promotion);
    REQUIRE(*promo.promotion == PieceType::Knight);
    // The promoter is the side that did the capturing, not the side that lost the unit:
    REQUIRE(promo.piece.color == cap.piece.color);
    CHECK_FALSE(has_phoenix(s));
}

// All three schnoebelen fixtures share one skeleton: White Kb6, Nc2; black
// Ka8, Pa2; black to move. Black's pawn promotes on a1 (S=a1); the knight on
// c2 is placed so it can recapture there (c2-a1 is a legal knight move) once
// the fixture calls for it. The corner geometry (Kb6 covering a7/b7) is the
// same one used by kniest/zajic/phoenix, reused here for the positive
// fixture's mate so the mating pattern is already load-bearing precedent,
// not a new invention.

TEST_CASE("schnoebelen: a promoted queen captured on S without ever having moved", "[themes][line]") {
    // White Kb6, Rh1, Nc2; black Ka8, Pa2; black to move.
    // 1. a2-a1=Q (promotion, S=a1; not check -- a1 shares no file/rank/
    //    diagonal with b6). 2. Rh1-h4 (white filler, does not touch a1).
    // 3. Ka8-b8 (black filler; b8 is not covered by Kb6, so it is legal, not
    //    forced). 4. Nc2xa1 (the knight recaptures on S -- the LATER capture
    //    the theme requires; note the two filler plies in between, ply1 and
    //    ply2, neither of which has from == a1, so this is a genuine
    //    "nothing moved from S in between" case, not just trivial adjacency
    //    of promotion-then-immediate-capture). 5. Kb8-a8 (black returns to
    //    the corner). 6. Rh4-h8# -- the familiar Kb6+R corner mate (rook
    //    checks along the eighth, king covers a7/b7; the knight sitting on
    //    a1 plays no further part).
    //
    // Legality of every move comes from `play()`, which REQUIREs each move
    // be found among Board::legal_moves() -- an impossible fixture fails
    // loudly. Mate comes from REQUIRE(fin.state() == PosState::Checkmate)
    // below, computed by the same real Board class the rest of the engine
    // uses.
    //
    // Tablebase cross-check: `~/tb` already holds KRNvkp.hm (a pre-built,
    // read-only 190-table corpus; never written to). Probing this exact
    // start FEN against it gives:
    //   $ ./build/helpmate probe "k7/8/1K6/8/8/8/p1N5/7R b - - 0 1" --tables ~/tb
    //   dtm=2 (h#1) count=3
    //   $ ./build/helpmate line "k7/8/1K6/8/8/8/p1N5/7R b - - 0 1" --tables ~/tb --all
    //   Kb8 Rh8#
    //   a1=N Rh8#
    //   a1=R Rh8#
    // So the position's real optimal solutions are all h#1 (2 plies: Black
    // has three tying replies, White always mates Rh8# next), none of them
    // this fixture's 6-ply line. That is expected and not a problem: the
    // fixture below is a hand-built LEGAL sequence built to exhibit the
    // schnoebelen shape (a genuine gap between promotion and recapture),
    // not a claim that it is what the engine would actually solve this
    // position with. `has_schnoebelen` is a pure predicate over a
    // `Solution`'s plies; it has no opinion on optimality, and this test
    // does not need one either. The evidence for THIS fixture being legal
    // chess is `play()`'s REQUIREs plus the real Checkmate state below, not
    // the tablebase.
    Solution s = play("k7/8/1K6/8/8/8/p1N5/7R b - - 0 1", {{"a2", "a1", PieceType::Queen},
                                                           {"h1", "h4", {}},
                                                           {"a8", "b8", {}},
                                                           {"c2", "a1", {}},
                                                           {"b8", "a8", {}},
                                                           {"h4", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);
    REQUIRE(s.plies.size() == 6);

    const Ply& promo = s.plies[0];
    REQUIRE(promo.promotion);
    REQUIRE((int)promo.to == sq("a1"));  // promotes on S

    const Ply& recap = s.plies[3];
    REQUIRE(recap.captured);             // Nxa1
    REQUIRE((int)recap.to == sq("a1"));  // ... a LATER capture on S

    for (size_t k = 1; k < 3; ++k) REQUIRE((int)s.plies[k].from != sq("a1"));  // nothing left S first
    CHECK(has_schnoebelen(s));
}

TEST_CASE("schnoebelen: moved away and captured elsewhere is not schnoebelen", "[themes][line]") {
    // Same skeleton, no rook needed since this fixture does not reach mate.
    // 1. a2-a1=Q (promotion, S=a1). 2. Kb6-b5 (white filler). 3. Qa1-a3 (the
    // queen itself leaves S -- `from == a1`). 4. Nc2xa3: White captures the
    // queen, but on a3, not on S (c2-a3 is a legal knight move; c2-a1's
    // sibling). There is no capture on a1 anywhere in this fixture.
    Solution s = play("k7/8/1K6/8/8/8/p1N5/8 b - - 0 1",
                      {{"a2", "a1", PieceType::Queen}, {"b6", "b5", {}}, {"a1", "a3", {}}, {"c2", "a3", {}}});
    REQUIRE(s.plies.size() == 4);
    REQUIRE(s.plies[0].promotion);
    REQUIRE((int)s.plies[0].to == sq("a1"));

    const Ply& leaves = s.plies[2];
    REQUIRE((int)leaves.from == sq("a1"));  // the promoted queen moves away from S

    const Ply& cap = s.plies[3];
    REQUIRE(cap.captured);
    REQUIRE((int)cap.to != sq("a1"));  // ... and is captured elsewhere, not on S
    CHECK_FALSE(has_schnoebelen(s));
}

TEST_CASE("schnoebelen: moved away and back before being captured on S is not schnoebelen",
          "[themes][line]") {
    // The case the "no ply in between moves FROM S" clause exists for. Same
    // skeleton again. 1. a2-a1=Q (promotion, S=a1). 2. Kb6-b5 (filler).
    // 3. Qa1-a4 (the queen leaves S -- `from == a1` -- and this also gives
    // check: a4 and b5 are diagonally adjacent). 4. Kb5-b6 is therefore NOT
    // filler but White's forced reply to that check -- one of several legal
    // responses (White could equally have captured, Kb5xa4, since a4 is
    // undefended); it happens not to touch a1 or a4 either way. 5. Qa4-a1
    // (the queen returns to S -- `to == a1`, but note `from == a4`, NOT
    // `from == a1`, so this ply itself is not a second departure from S).
    // 6. Nc2xa1: the knight recaptures on S, a LATER ply with `captured`
    // and `to == a1`.
    //
    // A naive detector that only checks "promoted on S, later a capture on
    // S" passes this fixture wrongly: ply0 promotes on a1 and ply5 captures
    // on a1, and that is all such a detector looks at. The correct detector
    // must stop scanning the instant it finds ply2 (`from == a1`), well
    // before it ever reaches the capture on ply5, and so must answer false.
    Solution s = play("k7/8/1K6/8/8/8/p1N5/8 b - - 0 1", {{"a2", "a1", PieceType::Queen},
                                                          {"b6", "b5", {}},
                                                          {"a1", "a4", {}},
                                                          {"b5", "b6", {}},
                                                          {"a4", "a1", {}},
                                                          {"c2", "a1", {}}});
    REQUIRE(s.plies.size() == 6);
    REQUIRE(s.plies[0].promotion);
    REQUIRE((int)s.plies[0].to == sq("a1"));

    bool left_s = false;
    for (size_t k = 1; k < s.plies.size(); ++k)
        if ((int)s.plies[k].from == sq("a1")) left_s = true;
    REQUIRE(left_s);  // the promoted queen really does leave S at some point

    const Ply& recap = s.plies[5];
    REQUIRE(recap.captured);
    REQUIRE((int)recap.to == sq("a1"));  // ... and S really is captured on again, later still

    CHECK_FALSE(has_schnoebelen(s));  // but the unit was NOT on S continuously until that capture
}

TEST_CASE("schnoebelen: a promotion with no later capture at all is not schnoebelen", "[themes][line]") {
    // Cheap to add (unlike the KRNvkp-scale skeleton above, this needs no
    // mating material at all), covering the gap the other predicate tests
    // in this file (kniest, zajic, phoenix) also leave: a promotion that is
    // simply never followed by any capture on its square. White Kb1, Pg7;
    // black Ka8. g7-g8=Q, then the position is left as-is -- one ply, no
    // capture anywhere.
    Solution s = play("k7/6P1/8/8/8/8/8/1K6 w - - 0 1", {{"g7", "g8", PieceType::Queen}});
    REQUIRE(s.plies.size() == 1);
    REQUIRE(s.plies[0].promotion);
    REQUIRE_FALSE(s.plies[0].captured);
    CHECK_FALSE(has_schnoebelen(s));
}

// All four pendulum fixtures share one skeleton: White Kb6, Ng1, Rh1; black
// Ka8; White to move. Material KRNvk (4 men) -- `~/tb` (a pre-built,
// read-only 190-table corpus, never written to) already holds KRNvk.hm.
// Probing this exact start FEN against it gives:
//   $ taskset -c 0-3 ./build/helpmate probe "k7/8/1K6/8/8/8/8/6NR w - - 0 1" --tables ~/tb
//   dtm=1 (h#0.5) count=1
//   $ taskset -c 0-3 ./build/helpmate line "k7/8/1K6/8/8/8/8/6NR w - - 0 1" --tables ~/tb --all
//   Rh8#
// Kb6 already covers a7/b7/c7 and Rh1-h8# alone mates along the eighth --
// this position is mate in ONE ply. Every fixture below instead has the
// knight shuffle back and forth (and, in the switchback/pendulum cases, the
// black king shuffle a8-b8 as its only legal replies) for several ply pairs
// before White finally plays the same Rh1-h8# -- legal cooperative chess
// that is NOT among the dtm-optimal lines (which mate immediately), stated
// plainly rather than left implicit. Legality of every move comes from
// `play()`, which REQUIREs each move be found among Board::legal_moves() --
// an impossible fixture fails loudly; genuine mate (where claimed) comes
// from REQUIRE(fin.state() == PosState::Checkmate) via the real Board class.

TEST_CASE("pendulum: a unit oscillating between two squares", "[themes][line]") {
    // Knight g1-f3-g1-f3: two distinct squares, four entries (A,B,A,B).
    // Black's only unit is its king, so its three replies are forced to be
    // king moves; a8-b8-a8-b8 happens to be a pendulum in its own right too
    // (Kb6 covers a7/b7/c7, so b8 stays a safe, non-adjacent reply each
    // time) -- that does not undermine the shape check below, which asks
    // only whether SOME trajectory matches, and the knight's alone already
    // does.
    Solution s = play("k7/8/1K6/8/8/8/8/6NR w - - 0 1", {{"g1", "f3", {}},
                                                         {"a8", "b8", {}},
                                                         {"f3", "g1", {}},
                                                         {"b8", "a8", {}},
                                                         {"g1", "f3", {}},
                                                         {"a8", "b8", {}},
                                                         {"h1", "h8", {}}});
    const Board& fin = final_board(s);
    REQUIRE(fin.state() == PosState::Checkmate);
    // Shape first: one trajectory of exactly two distinct squares, length >= 4.
    bool found = false;
    for (const auto& t : trajectories(s)) {
        std::set<uint8_t> d(t.squares.begin(), t.squares.end());
        if (t.squares.size() >= 4 && d.size() == 2) found = true;
    }
    REQUIRE(found);
    CHECK(has_pendulum(s));
}

TEST_CASE("pendulum: a single out-and-back is a switchback, not a pendulum", "[themes][line]") {
    // Knight g1-f3-g1 only: a single out-and-back, three squares, two
    // distinct -- the shape the brief calls a switchback, not a pendulum.
    // No mating move here; the rook never fires, so this is not checkmate,
    // matching the structural-only negative fixtures already used for
    // zajic/phoenix/schnoebelen in this file.
    Solution s =
        play("k7/8/1K6/8/8/8/8/6NR w - - 0 1", {{"g1", "f3", {}}, {"a8", "b8", {}}, {"f3", "g1", {}}});
    for (const auto& t : trajectories(s)) REQUIRE(t.squares.size() <= 3);
    CHECK(has_pendulum(s) == false);
    CHECK(has_switchback(s));  // the overlap rule, stated in the spec
}

TEST_CASE("pendulum and switchback are NOT exclusive", "[themes][line]") {
    // Spec decision: a pendulum trajectory contains a switchback, and both
    // are reported -- exactly as ideal implies model implies pure. The v0.8
    // closed-walk bug came from leaving an overlap rule unstated. Reuses the
    // full four-move knight oscillation from the positive case above.
    Solution s = play("k7/8/1K6/8/8/8/8/6NR w - - 0 1", {{"g1", "f3", {}},
                                                         {"a8", "b8", {}},
                                                         {"f3", "g1", {}},
                                                         {"b8", "a8", {}},
                                                         {"g1", "f3", {}},
                                                         {"a8", "b8", {}},
                                                         {"h1", "h8", {}}});
    CHECK(has_pendulum(s));
    CHECK(has_switchback(s));
}

TEST_CASE("pendulum: three distinct squares is a walk, not a pendulum", "[themes][line]") {
    // Knight g1-f3-h4-f3: three distinct squares (g1, f3, h4), the shape
    // A,B,C,B -- a walk, not a pendulum. No mating move; the rook never
    // fires, so no checkmate is asserted, same as the case above.
    Solution s =
        play("k7/8/1K6/8/8/8/8/6NR w - - 0 1",
             {{"g1", "f3", {}}, {"a8", "b8", {}}, {"f3", "h4", {}}, {"b8", "a8", {}}, {"h4", "f3", {}}});
    bool three = false;
    for (const auto& t : trajectories(s)) {
        std::set<uint8_t> d(t.squares.begin(), t.squares.end());
        if (d.size() >= 3) three = true;
    }
    REQUIRE(three);
    CHECK_FALSE(has_pendulum(s));
}

TEST_CASE("an empty solution shows no line theme", "[themes][line]") {
    // Black Kg8 mated by Ra8 along the eighth with white Kg6 covering f7/g7/h7:
    // a position that is already mate, hence a solution with no plies at all.
    auto b = Board::from_fen("R5k1/8/6K1/8/8/8/8/8 b - - 0 1");
    REQUIRE(b);
    Solution s{*b, {}};
    REQUIRE(s.start.state() == PosState::Checkmate);
    REQUIRE_FALSE(has_promotion(s));
    REQUIRE_FALSE(has_underpromotion(s));
    REQUIRE_FALSE(has_excelsior(s));
    REQUIRE_FALSE(has_switchback(s));
    REQUIRE_FALSE(has_closed_walk(s));
    REQUIRE_FALSE(has_self_block(s));
    REQUIRE_FALSE(has_en_passant(s));
    REQUIRE_FALSE(is_single_piece(s));  // no side moved at all
    REQUIRE_FALSE(has_schnoebelen(s));  // no plies at all, so certainly no promotion on one
    REQUIRE_FALSE(has_pendulum(s));     // no plies at all, so certainly no unit trajectory
    REQUIRE_FALSE(is_capture_free(s));  // nothing was played, so nothing is shown
    REQUIRE_FALSE(is_check_free(s));    // same: a vacuous "no check" is not a theme
    REQUIRE_FALSE(has_umnov(s));
    REQUIRE_FALSE(has_umnov_mate(s));
    REQUIRE_FALSE(has_klasinc(s));
    REQUIRE_FALSE(has_indian(s));
    REQUIRE_FALSE(has_maslar(s));
    REQUIRE_FALSE(has_maslar_black_white(s));
    REQUIRE(promotion_multiset(s).empty());
}

// Indian fixture: white Ke5, Ra1, Bf3; black Kb3; White to move. The rook
// crosses d1 (Ra1-h1, the critical move), the bishop interferes on d1, the
// black king walks onto the shut-off first rank, and the bishop leaves d1
// uncovering check from h1.
static const char* kIndianFen = "8/8/8/4K3/8/1k3B2/8/R7 w - - 0 1";

TEST_CASE("indian: critical move, own-colour interference, discovered check along the line",
          "[themes][line]") {
    auto s = play(kIndianFen,
                  {{"a1", "h1", {}}, {"b3", "b2", {}}, {"f3", "d1", {}}, {"b2", "c1", {}}, {"d1", "e2", {}}});
    REQUIRE(s.plies.back().is_check);
    REQUIRE(has_indian(s));
    REQUIRE_FALSE(has_maslar(s));  // nothing is captured
}

TEST_CASE("indian: the interferer leaving without check is not an Indian", "[themes][line]") {
    // The king goes to a2 instead of c1, off the line: Be2 checks nothing.
    auto s = play(kIndianFen,
                  {{"a1", "h1", {}}, {"b3", "b2", {}}, {"f3", "d1", {}}, {"b2", "a2", {}}, {"d1", "e2", {}}});
    REQUIRE_FALSE(s.plies.back().is_check);
    REQUIRE_FALSE(has_indian(s));
}

TEST_CASE("indian: a check the departing unit gives by itself is not a discovered one", "[themes][line]") {
    // Bd1-b3+ checks the king on a2 directly; the rook's line plays no part.
    auto s = play(kIndianFen,
                  {{"a1", "h1", {}}, {"b3", "b2", {}}, {"f3", "d1", {}}, {"b2", "a2", {}}, {"d1", "b3", {}}});
    REQUIRE(s.plies.back().is_check);
    REQUIRE_FALSE(has_indian(s));
}

TEST_CASE("indian: the line piece may not move between the critical move and the discovery",
          "[themes][line]") {
    // Rh1-g1 after the interference: the discovered check comes from g1, and
    // the rook's move to g1 crossed nothing -- no critical move behind it.
    auto s = play(kIndianFen, {{"a1", "h1", {}},
                               {"b3", "b2", {}},
                               {"f3", "d1", {}},
                               {"b2", "c1", {}},
                               {"h1", "g1", {}},
                               {"c1", "b1", {}},
                               {"d1", "e2", {}}});
    REQUIRE(s.plies.back().is_check);
    REQUIRE_FALSE(has_indian(s));
}

// Maslar fixture: white Kg5, Ra1; black Kb3, Ne3; White to move. The rook
// crosses d1, the knight interferes on d1, the black king walks to c1 on the
// line beyond d1, and the rook takes on d1 with check.
static const char* kMaslarFen = "8/8/8/6K1/8/1k2n3/8/R7 w - - 0 1";

TEST_CASE("maslar: critical move, black interference, king arrives on the line, capture with check",
          "[themes][line]") {
    auto s = play(kMaslarFen, {{"a1", "h1", {}},
                               {"e3", "d1", {}},
                               {"g5", "f5", {}},
                               {"b3", "c2", {}},
                               {"f5", "f4", {}},
                               {"c2", "c1", {}},
                               {"h1", "d1", {}}});
    REQUIRE(s.plies.back().captured == PieceType::Knight);
    REQUIRE(s.plies.back().is_check);
    REQUIRE(has_maslar(s));
    REQUIRE_FALSE(has_maslar_black_white(s));
    REQUIRE_FALSE(has_indian(s));  // the interferer is the enemy's, and nothing uncovers a check
}

TEST_CASE("maslar: the capture must give check to a king that arrived on the line", "[themes][line]") {
    // The king goes back to b3 instead of c1: Rxd1 is no check.
    auto s = play(kMaslarFen, {{"a1", "h1", {}},
                               {"e3", "d1", {}},
                               {"g5", "f5", {}},
                               {"b3", "c2", {}},
                               {"f5", "f4", {}},
                               {"c2", "b3", {}},
                               {"h1", "d1", {}}});
    REQUIRE(s.plies.back().captured == PieceType::Knight);
    REQUIRE_FALSE(s.plies.back().is_check);
    REQUIRE_FALSE(has_maslar(s));
}

TEST_CASE("maslar: the line piece may not move between the critical move and the capture", "[themes][line]") {
    // Rh1-g1 instead of a king move: Rg1xd1+ still captures with check, but
    // from g1, which the rook reached without crossing anything.
    auto s = play(kMaslarFen, {{"a1", "h1", {}},
                               {"e3", "d1", {}},
                               {"g5", "f5", {}},
                               {"b3", "c2", {}},
                               {"h1", "g1", {}},
                               {"c2", "c1", {}},
                               {"g1", "d1", {}}});
    REQUIRE(s.plies.back().is_check);
    REQUIRE_FALSE(has_maslar(s));
}

// Black-White Maslar fixture: black Kb6, Ra8; white Kg4, Ne6; Black to move.
static const char* kBlackWhiteMaslarFen = "r7/8/1k2N3/8/6K1/8/8/8 b - - 0 1";

TEST_CASE("maslar:black-white: Black's critical move, White's interference, Black captures",
          "[themes][line]") {
    auto s = play(kBlackWhiteMaslarFen, {{"a8", "h8", {}}, {"e6", "d8", {}}, {"h8", "d8", {}}});
    REQUIRE(s.plies.back().captured == PieceType::Knight);
    REQUIRE(has_maslar_black_white(s));
    REQUIRE_FALSE(has_maslar(s));  // the white-first form needs a white line piece
}

TEST_CASE("maslar:black-white: the capturing rook must be the one that made the critical move from b",
          "[themes][line]") {
    // Rh8-g8+ before the capture: the rook leaves b, and g8 was reached
    // without crossing anything. (The white king steps off the g-file.)
    auto s = play(kBlackWhiteMaslarFen,
                  {{"a8", "h8", {}}, {"e6", "d8", {}}, {"h8", "g8", {}}, {"g4", "f3", {}}, {"g8", "d8", {}}});
    REQUIRE(s.plies.back().captured == PieceType::Knight);
    REQUIRE_FALSE(has_maslar_black_white(s));
}

TEST_CASE("umnov: a unit moves onto the square the opponent just vacated", "[themes][line]") {
    // Black Kh8 steps to g8; the white rook on a7 then lands on h8? No -- the
    // rook lands on the vacated h8 only via the h-file. Use Rh1: 1...Kg8 2.Rh8+.
    auto s = play("7k/8/8/8/8/8/8/K6R b - - 0 1", {{"h8", "g8", {}}, {"h1", "h8", {}}});
    REQUIRE(s.plies[1].to == s.plies[0].from);
    REQUIRE(has_umnov(s));
    REQUIRE(has_umnov_mate(s));  // the last ply did it, so the mate variant fires too
}

TEST_CASE("umnov: arriving on a square vacated two plies earlier is not umnov", "[themes][line]") {
    // 1...Kg8 2.Rh2 Kf8 3.Rh1 Kg8 4.Rh8+: the rook arrives on h8, which Black
    // vacated SIX plies earlier; the immediately preceding ply, Kf8-g8,
    // vacated f8. No ply lands where the previous ply started, so not umnov.
    auto s = play("7k/8/8/8/8/8/8/K6R b - - 0 1", {{"h8", "g8", {}},
                                                   {"h1", "h2", {}},
                                                   {"g8", "f8", {}},
                                                   {"h2", "h1", {}},
                                                   {"f8", "g8", {}},
                                                   {"h1", "h8", {}}});
    REQUIRE_FALSE(has_umnov(s));
    REQUIRE_FALSE(has_umnov_mate(s));
}

TEST_CASE("umnov-mate needs the LAST ply to land on the square Black just left", "[themes][line]") {
    // 1...Kg8 2.Rh8+ Kf7: the umnov arrival is followed by another ply, so the
    // line shows umnov but not umnov-mate.
    auto s = play("7k/8/8/8/8/8/8/K6R b - - 0 1", {{"h8", "g8", {}}, {"h1", "h8", {}}, {"g8", "f7", {}}});
    REQUIRE(has_umnov(s));
    REQUIRE_FALSE(has_umnov_mate(s));
}

TEST_CASE("klasinc: a unit clears a square, a line piece passes over it, the unit returns",
          "[themes][line]") {
    // Black knight d4 leaves d4 (Nd4-b5), white rook d1 passes OVER d4 to d7
    // (Rd1-d7), the knight returns to d4 (Nb5-d4). Kings a8/h1 keep it legal.
    auto s = play("k7/8/8/8/3n4/8/8/3R3K b - - 0 1", {{"d4", "b5", {}}, {"d1", "d7", {}}, {"b5", "d4", {}}});
    REQUIRE(has_klasinc(s));
}

TEST_CASE("klasinc: a line move that ENDS on the vacated square does not pass over it", "[themes][line]") {
    auto s = play("k7/8/8/8/3n4/8/8/3R3K b - - 0 1", {{"d4", "b5", {}}, {"d1", "d4", {}}, {"b5", "a7", {}}});
    REQUIRE_FALSE(has_klasinc(s));
}

TEST_CASE("klasinc: the line piece must pass AFTER the clearance and BEFORE the return", "[themes][line]") {
    // Rook passes over d4? It cannot while the knight stands there. So: knight
    // leaves, knight returns, THEN the rook passes -- too late.
    auto s = play("k7/8/8/8/3n4/8/8/3R3K b - - 0 1", {{"d4", "b5", {}},
                                                      {"h1", "g1", {}},
                                                      {"b5", "d4", {}},
                                                      {"g1", "h1", {}},
                                                      {"d4", "b5", {}},
                                                      {"d1", "d7", {}}});
    // the second clearance opens a new window in which the rook DOES pass, but
    // the knight never returns afterwards
    REQUIRE_FALSE(has_klasinc(s));
    // and a knight's leap over d4 is not a line move
    auto leap =
        play("k7/8/8/8/3n4/8/8/3R2NK b - - 0 1", {{"d4", "b5", {}}, {"g1", "e2", {}}, {"b5", "d4", {}}});
    REQUIRE_FALSE(has_klasinc(leap));
}

TEST_CASE("klasinc: a promoted queen is a line piece", "[themes][line]") {
    // Black rook e5 clears e5 (Re5-a5); white pawn e7 promotes to a queen on
    // e8 with check along the rank (a pawn move, not a line move); Black
    // steps out of it; the queen then runs e8-e1, passing over e5; the rook
    // returns to e5. A promoted unit's later plies carry its promoted type
    // (collect_solutions reads the mover off the board), which is what the
    // detector relies on; asserted here so that assumption cannot rot.
    auto s = play("k7/4P3/8/4r3/8/8/8/7K b - - 0 1", {{"e5", "a5", {}},
                                                      {"e7", "e8", PieceType::Queen},
                                                      {"a8", "b7", {}},
                                                      {"e8", "e1", {}},
                                                      {"a5", "e5", {}}});
    REQUIRE(s.plies[1].piece.type == PieceType::Pawn);   // the promoting ply is a pawn move
    REQUIRE(s.plies[3].piece.type == PieceType::Queen);  // its later move is a queen move
    REQUIRE(has_klasinc(s));
}

TEST_CASE("promotion multiset is order-independent and counts multiplicity", "[themes][line]") {
    auto queen = play("k7/6P1/8/8/8/8/8/K7 w - - 0 1", {{"g7", "g8", PieceType::Queen}});
    REQUIRE(promotion_multiset(queen) == "q");
    auto knight = play("k7/6P1/8/8/8/8/8/K7 w - - 0 1", {{"g7", "g8", PieceType::Knight}});
    REQUIRE(promotion_multiset(knight) == "n");
    REQUIRE(canon_promotions("rq") == "qr");
    REQUIRE(canon_promotions("QRR") == "qrr");
    REQUIRE(canon_promotions("nbrq") == "qrbn");
    REQUIRE_FALSE(canon_promotions("").has_value());
    REQUIRE_FALSE(canon_promotions("qk").has_value());
    REQUIRE_FALSE(canon_promotions("qqqqqqqqq").has_value());    // nine letters
    REQUIRE(canon_promotions("qrr") != canon_promotions("qr"));  // multiplicity counts
}

TEST_CASE("nocapture: a solution in which nothing is taken", "[themes][line]") {
    // The golden KQvk h#1: 1...Kh8 2.Qg7#. Quiet throughout.
    auto s = play("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", {{"h7", "h8", {}}, {"g1", "g7", {}}});
    REQUIRE(s.plies.back().after.state() == PosState::Checkmate);
    REQUIRE(is_capture_free(s));
}

TEST_CASE("nocapture: any capture anywhere in the line breaks it", "[themes][line]") {
    // Rd1xd5 in the middle of the line, then a recapture.
    auto s =
        play("3r3k/8/3p4/8/8/8/8/K2R4 b - - 0 1", {{"d6", "d5", {}}, {"d1", "d5", {}}, {"d8", "d5", {}}});
    REQUIRE(s.plies[1].captured == PieceType::Pawn);
    REQUIRE_FALSE(is_capture_free(s));
    // A capture on the LAST ply counts too: the mating move is not exempt for
    // nocapture, only for nocheck.
    auto last = play("3r3k/8/3p4/8/8/8/8/K2R4 b - - 0 1", {{"d6", "d5", {}}, {"d1", "d5", {}}});
    REQUIRE(last.plies.back().captured == PieceType::Pawn);
    REQUIRE_FALSE(is_capture_free(last));
}

TEST_CASE("nocapture: an en-passant capture is a capture", "[themes][line]") {
    // Same fixture as the en-passant theme: black g7-g5, white f5xg6 ep.
    auto s = play("k7/6p1/8/5P2/8/8/8/K7 b - - 0 1", {{"g7", "g5", {}}, {"f5", "g6", {}}});
    REQUIRE(s.plies.back().is_ep);
    REQUIRE_FALSE(is_capture_free(s));
}

TEST_CASE("nocheck: only the final move may give check", "[themes][line]") {
    // 1...Kh8 2.Qg7#: the mate is a check, and nothing before it is.
    auto s = play("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", {{"h7", "h8", {}}, {"g1", "g7", {}}});
    REQUIRE(s.plies.back().is_check);
    REQUIRE_FALSE(s.plies.front().is_check);
    REQUIRE(is_check_free(s));
}

TEST_CASE("nocheck: a check before the last move breaks it", "[themes][line]") {
    // Black Ka8, white Ke2 + Qh1: 1.Qa1+ is a check on the very first ply.
    auto s = play("k7/8/8/8/8/8/4K3/7Q w - - 0 1", {{"h1", "a1", {}}, {"a8", "b8", {}}, {"a1", "b1", {}}});
    REQUIRE(s.plies[0].is_check);
    REQUIRE_FALSE(is_check_free(s));
    // The same shape with the check moved to the end: a quiet start, then
    // the check as the LAST ply, is allowed. (Qh3, not Qh2: Qh2 would guard
    // b8 and make Kb8 illegal.)
    auto tail = play("k7/8/8/8/8/8/4K3/7Q w - - 0 1", {{"h1", "h3", {}}, {"a8", "b8", {}}, {"h3", "b3", {}}});
    REQUIRE(tail.plies.back().is_check);
    REQUIRE_FALSE(tail.plies[0].is_check);
    REQUIRE_FALSE(tail.plies[1].is_check);
    REQUIRE(is_check_free(tail));
}

TEST_CASE("nocheck: a black check before the mate breaks it too", "[themes][line]") {
    // Black Ra8 + Kh8, white Kb1 + Qg2: 1...Ra1+ is a black check on the
    // first ply, answered by 2.Kxa1.
    auto s = play("r6k/8/8/8/8/8/6Q1/1K6 b - - 0 1", {{"a8", "a1", {}}, {"b1", "a1", {}}});
    REQUIRE(s.plies[0].is_check);
    REQUIRE(s.plies[0].piece.color == Color::Black);
    REQUIRE_FALSE(is_check_free(s));
}

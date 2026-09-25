#include <catch2/catch_test_macros.hpp>
#include <algorithm>
#include "chess/board.h"
using namespace hm;

TEST_CASE("fen round trip, no castling accepted") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    REQUIRE(b); CHECK(b->fen() == "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    CHECK(!Board::from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")); // castling
    CHECK(!Board::from_fen("not a fen"));
}
TEST_CASE("perft CPW position 3 (EP-rich, castling-free)") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    CHECK(b->perft(1) == 14); CHECK(b->perft(2) == 191);
    CHECK(b->perft(3) == 2812); CHECK(b->perft(4) == 43238); CHECK(b->perft(5) == 674624);
}
TEST_CASE("perft promotion-heavy position") {
    auto b = Board::from_fen("n1n5/PPPk4/8/8/8/8/4Kppp/5N1N b - - 0 1");
    CHECK(b->perft(1) == 24); CHECK(b->perft(2) == 496);
    CHECK(b->perft(3) == 9483); CHECK(b->perft(4) == 182838);
}
TEST_CASE("from_pieces / pieces round trip and state") {
    // KQvk mate: k h8, Q g7, K f6 — btm checkmate
    std::vector<PlacedPiece> pp = {
        {{Color::White, PieceType::King}, 45}, {{Color::White, PieceType::Queen}, 54},
        {{Color::Black, PieceType::King}, 63}};
    Board b = Board::from_pieces(pp, Color::Black);
    CHECK(b.state() == PosState::Checkmate);
    CHECK(b.fen() == "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1");
    CHECK(b.pieces().size() == 3);
    Board w = Board::from_pieces(pp, Color::White);
    CHECK(w.opponent_in_check());               // black in check, white to move => illegal
}
TEST_CASE("pieces can fill and reuse caller-owned storage") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    REQUIRE(b);

    std::vector<PlacedPiece> storage;
    storage.reserve(16);
    auto* buffer = storage.data();
    b->pieces(storage);
    CHECK(storage.data() == buffer);
    REQUIRE(storage.size() == 10);

    const std::vector<PlacedPiece> before = {
        {{Color::White, PieceType::Pawn}, 12}, {{Color::White, PieceType::Pawn}, 14},
        {{Color::Black, PieceType::Pawn}, 29}, {{Color::Black, PieceType::King}, 31},
        {{Color::White, PieceType::King}, 32}, {{Color::White, PieceType::Pawn}, 33},
        {{Color::Black, PieceType::Rook}, 39}, {{Color::Black, PieceType::Pawn}, 43},
        {{Color::Black, PieceType::Pawn}, 50}, {{Color::White, PieceType::Rook}, 25}};
    // Board::pieces is square ordered; compare after sorting the independently listed fixture.
    auto by_square = [](const PlacedPiece& a, const PlacedPiece& b) { return a.square < b.square; };
    auto expected = before;
    std::sort(expected.begin(), expected.end(), by_square);
    REQUIRE(storage.size() == expected.size());
    for (size_t i = 0; i < storage.size(); ++i) {
        CHECK(storage[i].square == expected[i].square);
        CHECK(storage[i].piece == expected[i].piece);
    }

    Move capture{};
    for (const Move& m : b->legal_moves()) if (m.uci() == "b4f4") capture = m;
    REQUIRE(capture.uci() == "b4f4");
    b->make(capture);
    b->pieces(storage);
    CHECK(storage.data() == buffer);
    CHECK(storage.size() == 9);
    auto moved_rook = std::find_if(storage.begin(), storage.end(), [](const PlacedPiece& p) {
        return p.square == 29;
    });
    REQUIRE(moved_rook != storage.end());
    CHECK((moved_rook->piece == Piece{Color::White, PieceType::Rook}));
    CHECK(std::none_of(storage.begin(), storage.end(), [](const PlacedPiece& p) { return p.square == 25; }));
}
TEST_CASE("stalemate detection") {
    auto b = Board::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1");  // k h8, K f7?? -> use classic: k a8, Q b6, K c7? btm
    // Classic KQ stalemate: k h8, K g6, Q g7?? is mate; use k a1, K c2, Q b3: black to move, no moves, not in check
    auto s = Board::from_fen("8/8/8/8/8/1Q6/2K5/k7 b - - 0 1");
    REQUIRE(s); CHECK(s->state() == PosState::Stalemate);
}
TEST_CASE("make/unmake restores position") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    std::string before = b->fen();
    auto moves = b->legal_moves();
    REQUIRE(moves.size() == 14);
    for (auto& m : moves) { b->make(m); b->unmake(m); }
    CHECK(b->fen() == before);
}
TEST_CASE("double push sets ep square; ep move flagged") {
    auto b = Board::from_fen("8/8/8/8/1p6/8/P7/K1k5 w - - 0 1");   // a2 pawn, black b4 pawn
    auto moves = b->legal_moves();
    Move dp{};
    for (auto& m : moves) if (m.uci() == "a2a4") dp = m;
    REQUIRE(dp.uci() == "a2a4"); CHECK(dp.is_double_push());
    b->make(dp);
    CHECK(b->ep_square() == 16);                                    // a3
    bool found_ep = false;
    for (auto& m : b->legal_moves()) if (m.uci() == "b4a3" && m.is_ep()) found_ep = true;
    CHECK(found_ep);
}
TEST_CASE("promotion moves carry promotion type") {
    auto b = Board::from_fen("6k1/4P3/6K1/8/8/8/8/8 w - - 0 1");
    int promos = 0;
    for (auto& m : b->legal_moves())
        if (m.promotion()) { promos++; CHECK(m.from == 52); CHECK(m.to == 60); }
    CHECK(promos == 4);                                             // Q R B N
}
TEST_CASE("copy preserves ep square") {
    auto b = Board::from_fen("8/8/8/8/1p6/8/P7/K1k5 w - - 0 1");
    Move dp{};
    for (auto& m : b->legal_moves()) if (m.uci() == "a2a4") dp = m;
    REQUIRE(dp.uci() == "a2a4");
    b->make(dp);
    REQUIRE(b->ep_square() == 16);
    Board copy_ctor(*b);
    CHECK(copy_ctor.ep_square() == b->ep_square());
    CHECK(copy_ctor.fen() == b->fen());
    Board copy_assign;
    copy_assign = *b;
    CHECK(copy_assign.ep_square() == b->ep_square());
    CHECK(copy_assign.fen() == b->fen());
}
TEST_CASE("hash changes after make, restored after unmake") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    uint64_t before = b->hash();
    auto moves = b->legal_moves();
    REQUIRE(!moves.empty());
    Move m = moves.front();
    b->make(m);
    CHECK(b->hash() != before);
    b->unmake(m);
    CHECK(b->hash() == before);
}
TEST_CASE("copy preserves captured-piece history for unmake") {
    auto b = Board::from_fen("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1");
    std::string before = b->fen();
    Move capture{};
    for (auto& m : b->legal_moves()) if (m.uci() == "b4f4") capture = m;
    REQUIRE(capture.uci() == "b4f4"); CHECK(capture.is_capture());
    b->make(capture);

    Board copy_ctor(*b);
    copy_ctor.unmake(capture);
    CHECK(copy_ctor.fen() == before);

    Board copy_assign;
    copy_assign = *b;
    copy_assign.unmake(capture);
    CHECK(copy_assign.fen() == before);
}

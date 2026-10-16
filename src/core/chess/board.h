#pragma once
#include <array>
#include <cstdint>
#include <memory>
#include <vector>

#include "chess/types.h"

namespace hm {

// Fixed storage for one position's legal moves, for callers that list moves
// in a hot loop: unlike a std::vector it is never resized or initialized.
struct MoveBuffer {
    // surge lists at most 218 moves; legal_moves() may expand one into four
    // (see board.cpp), so this bound holds whatever the list contains.
    static constexpr size_t kCapacity = 4 * 218;
    std::array<Move, kCapacity> moves;
    size_t size = 0;
    const Move* begin() const { return moves.data(); }
    const Move* end() const { return moves.data() + size; }
};

class Board {  // pimpl over surge Position; copyable
public:
    Board();
    Board(const Board&);
    Board& operator=(const Board&);
    ~Board();

    static std::optional<Board> from_fen(const std::string&);  // nullopt on parse error or castling rights
    static Board from_pieces(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);
    void reset(const std::vector<PlacedPiece>&, Color stm, int ep_square = -1);  // reuse allocation

    std::string fen() const;
    Color stm() const;
    int ep_square() const;  // -1 if none
    std::vector<PlacedPiece> pieces() const;
    void pieces(std::vector<PlacedPiece>& out) const;  // fills reusable caller-owned storage
    // pieces(out) plus, in the same pass, the number of pieces of each type:
    // counts[color] holds one byte per PieceType (byte t = count of type t),
    // the packed form of Material (see Material::Counts).
    void pieces(std::vector<PlacedPiece>& out, std::array<uint64_t, 2>& counts) const;
    bool in_check() const;             // side to move
    bool opponent_in_check() const;    // true => position illegal
    PosState state() const;            // for side to move
    std::vector<Move> legal_moves() const;
    void legal_moves(std::vector<Move>& out) const;  // fills reusable caller-owned storage
    void legal_moves(MoveBuffer& out) const;
    void make(const Move&);
    void unmake(const Move&);
    uint64_t perft(int depth);
    // Zobrist-style hash of the position, including side to move and en
    // passant square (surge's own incrementally-updated hash covers piece
    // placement only -- see board.cpp for why those two are mixed in here).
    uint64_t hash() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace hm

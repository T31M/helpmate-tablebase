#pragma once
#include <cstdint>
#include <optional>
#include <string>
#include <algorithm>

namespace hm {

enum class Color : uint8_t { White = 0, Black = 1 };
enum class PieceType : uint8_t { King = 0, Queen = 1, Rook = 2, Bishop = 3, Knight = 4, Pawn = 5 };

struct Piece {
    Color color;
    PieceType type;
    bool operator==(const Piece&) const = default;
};

struct PlacedPiece {
    Piece piece;
    uint8_t square;
};

enum class PosState : uint8_t { Open, Check, Checkmate, Stalemate };

struct ValuePair {
    uint8_t dtm;
    uint8_t count;
};

constexpr uint8_t DTM_UNSET = 253, DTM_INVALID = 254, DTM_UNSOLVABLE = 255;
constexpr uint8_t DTM_MAX = 252, COUNT_SAT = 255;

inline uint8_t sat_add(unsigned a, unsigned b) { return (uint8_t)std::min(255u, a + b); }

inline int sq_file(int sq) { return sq & 7; }
inline int sq_rank(int sq) { return sq >> 3; }
std::string sq_name(int sq);  // "e4"

struct Move {  // flags byte uses ChessMG/surge encoding (MoveFlags in libsurge.h)
    uint8_t from, to, flags;
    // Inline: the generator tests these for every move it scans.
    bool is_capture() const { return flags & 0b1000; }
    bool is_double_push() const { return flags == 0b0001; }
    bool is_ep() const { return flags == 0b1010; }  // EN_PASSANT
    std::optional<PieceType> promotion() const {
        if ((flags & 0b0100) == 0) return std::nullopt;  // PR_*/PC_* have bit 2 set
        constexpr PieceType kByLowBits[4] = {PieceType::Knight, PieceType::Bishop, PieceType::Rook,
                                             PieceType::Queen};
        return kByLowBits[flags & 0b0011];
    }
    std::string uci() const;  // "e2e4", "e7e8q"
};

}  // namespace hm

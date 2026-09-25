#include "chess/board.h"
// Vendored ChessMG headers; inclusion contained to this TU. libcmg.h (which
// transitively includes libsurge.h) is required rather than libsurge.h alone:
// it defines the static initializer that populates the magic-bitboard/zobrist
// lookup tables (initialise_all_databases()/zobrist::initialise_zobrist_keys()).
// That initializer has internal linkage, so it must run in a TU that is
// definitely linked in -- board.cpp itself -- rather than relying on the
// linker pulling in libcmg.cpp's object file from the static archive.
#include "libcmg.h"
#include <array>
#include <new>
#include <sstream>
#include <utility>

namespace hm {

// --- free helpers declared in types.h ---
std::string sq_name(int sq) {
    std::string s;
    s += char('a' + sq_file(sq));
    s += char('1' + sq_rank(sq));
    return s;
}

// --- Move flag helpers (surge MoveFlags encoding, verified against libsurge.h) ---
bool Move::is_capture() const { return flags & 0b1000; }
bool Move::is_double_push() const { return flags == 0b0001; }
bool Move::is_ep() const { return flags == 0b1010; }  // EN_PASSANT
std::optional<PieceType> Move::promotion() const {
    if ((flags & 0b0100) == 0) return std::nullopt;  // PR_*/PC_* have bit 2 set
    switch (flags & 0b0011) {
        case 0: return PieceType::Knight;
        case 1: return PieceType::Bishop;
        case 2: return PieceType::Rook;
        default: return PieceType::Queen;
    }
}
std::string Move::uci() const {
    std::string s = sq_name(from) + sq_name(to);
    if (auto pr = promotion()) {
        switch (*pr) {
            case PieceType::Knight: s += 'n'; break;
            case PieceType::Bishop: s += 'b'; break;
            case PieceType::Rook: s += 'r'; break;
            case PieceType::Queen: s += 'q'; break;
            default: break;
        }
    }
    return s;
}

// --- piece mapping: hm::Piece <-> surge Piece (WHITE_PAWN=0..BLACK_KING=13) ---
static int to_surge(Piece p) {
    static const int w[6] = {WHITE_KING, WHITE_QUEEN, WHITE_ROOK, WHITE_BISHOP, WHITE_KNIGHT, WHITE_PAWN};
    static const int b[6] = {BLACK_KING, BLACK_QUEEN, BLACK_ROOK, BLACK_BISHOP, BLACK_KNIGHT, BLACK_PAWN};
    return (p.color == Color::White ? w : b)[(int)p.type];
}
static std::optional<Piece> from_surge(int sp) {
    if (sp == NO_PIECE) return std::nullopt;
    auto surge_piece = static_cast<::Piece>(sp);
    auto surge_type = type_of(surge_piece);    // global ::PieceType (PAWN..KING)
    auto surge_color = color_of(surge_piece);  // global ::Color
    static const PieceType type_map[6] = {PieceType::Pawn,  PieceType::Knight, PieceType::Bishop,
                                           PieceType::Rook,  PieceType::Queen,  PieceType::King};
    Piece out;
    out.type = type_map[static_cast<int>(surge_type)];
    out.color = (surge_color == WHITE) ? Color::White : Color::Black;
    return out;
}

struct Board::Impl {
    Position pos;
};

// Position's (compiler-generated) copy constructor copy-constructs its
// `history[256]` array of UndoInfo elementwise, and UndoInfo has a
// user-provided copy constructor -- `UndoInfo(const UndoInfo& prev) :
// entry(prev.entry), captured(NO_PIECE), epsq(NO_SQUARE) {}` -- written for
// ply-advance (history[ply] = UndoInfo(history[ply-1])), which intentionally
// resets captured/epsq for the *new* ply. That same constructor fires for a
// whole-Position copy too, silently discarding every history entry's
// `captured` and `epsq`. Restore both fields, across the full history array
// (not just the current ply), so unmake() chains still work after a copy.
static void restore_history_fields(Position& dst, const Position& src) {
    for (int i = 0; i < 256; ++i) {
        dst.history[i].captured = src.history[i].captured;
        dst.history[i].epsq = src.history[i].epsq;
    }
}

Board::Board() : impl_(std::make_unique<Impl>()) {}
Board::Board(const Board& other) : impl_(std::make_unique<Impl>(*other.impl_)) {
    restore_history_fields(impl_->pos, other.impl_->pos);
}
Board& Board::operator=(const Board& other) {
    if (this != &other) {
        impl_ = std::make_unique<Impl>(*other.impl_);
        restore_history_fields(impl_->pos, other.impl_->pos);
    }
    return *this;
}
Board::~Board() = default;

std::optional<Board> Board::from_fen(const std::string& fen) {
    // reject castling: field 3 of FEN must be "-"; also reject truncated FENs
    std::istringstream ss(fen);
    std::string board_s, stm_s, cast_s, ep_s;
    if (!(ss >> board_s >> stm_s >> cast_s >> ep_s)) return std::nullopt;
    if (cast_s != "-") return std::nullopt;

    Board b;
    try {
        Position::set(fen, b.impl_->pos);
    } catch (const std::exception&) {
        return std::nullopt;
    }

    auto pieces = b.pieces();
    int white_kings = 0, black_kings = 0;
    for (auto& pp : pieces) {
        if (pp.piece.type == PieceType::King) {
            if (pp.piece.color == Color::White) ++white_kings;
            else ++black_kings;
        }
    }
    if (white_kings != 1 || black_kings != 1) return std::nullopt;

    return b;
}

void Board::reset(const std::vector<PlacedPiece>& pp, Color stm, int ep) {
    // Position::set_position() does not clear prior state, so fully reconstruct
    // in place before placing pieces (this is what lets us reuse the allocation).
    impl_->pos.~Position();
    new (&impl_->pos) Position();

    std::vector<std::pair<::Piece, Square>> pl;
    pl.reserve(pp.size());
    for (auto& p : pp) pl.emplace_back(static_cast<::Piece>(to_surge(p.piece)), static_cast<Square>(p.square));

    Position::set_position(pl, stm == Color::White ? WHITE : BLACK, "",
                            ep < 0 ? NO_SQUARE : static_cast<Square>(ep), impl_->pos);
}

Board Board::from_pieces(const std::vector<PlacedPiece>& pp, Color stm, int ep_square) {
    Board b;
    b.reset(pp, stm, ep_square);
    return b;
}

std::string Board::fen() const { return impl_->pos.fen(); }

Color Board::stm() const { return impl_->pos.turn() == WHITE ? Color::White : Color::Black; }

int Board::ep_square() const {
    auto sq = impl_->pos.history[impl_->pos.ply()].epsq;
    return sq == NO_SQUARE ? -1 : static_cast<int>(sq);
}

std::vector<PlacedPiece> Board::pieces() const {
    std::vector<PlacedPiece> out;
    pieces(out);
    return out;
}

void Board::pieces(std::vector<PlacedPiece>& out) const {
    out.clear();
    const Position& pos = impl_->pos;
    Bitboard occupied = pos.all_pieces<WHITE>() | pos.all_pieces<BLACK>();
    while (occupied) {
        Square sq = bsf(occupied);
        occupied &= occupied - 1;
        auto sp = pos.at(sq);
        if (sp == NO_PIECE) continue;
        if (auto hp = from_surge(static_cast<int>(sp)))
            out.push_back(PlacedPiece{*hp, static_cast<uint8_t>(sq)});
    }
}

bool Board::in_check() const {
    const Position& p = impl_->pos;
    auto occ = p.all_pieces<WHITE>() | p.all_pieces<BLACK>();
    if (p.turn() == WHITE) return p.attackers_from<BLACK>(bsf(p.bitboard_of(WHITE_KING)), occ) != 0;
    return p.attackers_from<WHITE>(bsf(p.bitboard_of(BLACK_KING)), occ) != 0;
}

bool Board::opponent_in_check() const {
    const Position& p = impl_->pos;
    auto occ = p.all_pieces<WHITE>() | p.all_pieces<BLACK>();
    if (p.turn() == WHITE) return p.attackers_from<WHITE>(bsf(p.bitboard_of(BLACK_KING)), occ) != 0;
    return p.attackers_from<BLACK>(bsf(p.bitboard_of(WHITE_KING)), occ) != 0;
}

std::vector<Move> Board::legal_moves() const {
    std::vector<Move> out;
    // unique_ptr::operator->() const still yields a non-const pointee, so no
    // const_cast is needed to get a mutable Position& from a const method.
    Position& p = impl_->pos;
    auto conv = [&](auto& list) {
        for (::Move sm : list) {
            uint8_t from = (uint8_t)sm.from(), to = (uint8_t)sm.to(), flags = (uint8_t)sm.flags();
            // Workaround for a ChessMG/surge defect: when the side to move is in check
            // from a knight (or, via case fallthrough, the pawn that just double-pushed),
            // surge's single-check branch answers with "capture the checker" moves that
            // are unconditionally flagged plain CAPTURE -- even when the capturing piece
            // is a pawn landing on its own promotion rank. That silently drops the
            // promotion, so play() would leave an actual pawn sitting on rank 1/8 (an
            // impossible position). Recover the four promotion-capture variants surge's
            // ordinary (not-in-check) pawn code would have produced for the same capture.
            if (flags == CAPTURE) {
                auto sp = p.at(static_cast<Square>(from));
                if (sp != NO_PIECE && type_of(static_cast<::Piece>(sp)) == PAWN &&
                    (sq_rank(to) == 0 || sq_rank(to) == 7)) {
                    for (MoveFlags pf : {PC_KNIGHT, PC_BISHOP, PC_ROOK, PC_QUEEN})
                        out.push_back(Move{from, to, (uint8_t)pf});
                    continue;
                }
            }
            out.push_back(Move{from, to, flags});
        }
    };
    if (p.turn() == WHITE) {
        MoveList<WHITE> l(p);
        conv(l);
    } else {
        MoveList<BLACK> l(p);
        conv(l);
    }
    return out;
}

void Board::make(const Move& m) {
    ::Move sm(static_cast<Square>(m.from), static_cast<Square>(m.to), static_cast<MoveFlags>(m.flags));
    if (impl_->pos.turn() == WHITE) impl_->pos.play<WHITE>(sm);
    else impl_->pos.play<BLACK>(sm);
}

void Board::unmake(const Move& m) {
    ::Move sm(static_cast<Square>(m.from), static_cast<Square>(m.to), static_cast<MoveFlags>(m.flags));
    // after make(), turn() is the opponent of whoever actually played this move
    auto mover = ~impl_->pos.turn();
    if (mover == WHITE) impl_->pos.undo<WHITE>(sm);
    else impl_->pos.undo<BLACK>(sm);
}

PosState Board::state() const {
    bool any = !legal_moves().empty();
    bool chk = in_check();
    if (any) return chk ? PosState::Check : PosState::Open;
    return chk ? PosState::Checkmate : PosState::Stalemate;
}

namespace {
// splitmix64, used only to derive fixed pseudo-random constants below.
constexpr uint64_t splitmix64(uint64_t& state) {
    uint64_t z = (state += 0x9E3779B97F4A7C15ULL);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}
constexpr uint64_t kSideToMoveKey = [] {
    uint64_t s = 0x853c49e6748fea9bULL;
    return splitmix64(s);
}();
constexpr std::array<uint64_t, 64> kEpKeys = [] {
    std::array<uint64_t, 64> out{};
    uint64_t s = 0x2545F4914F6CDD1DULL;
    for (auto& k : out) k = splitmix64(s);
    return out;
}();
}  // namespace

// Surge's Position::hash is incrementally updated by put_piece/remove_piece
// only (see libsurge.h), so it covers piece placement alone -- side to move
// and the en passant square are NOT folded in. Two positions that differ
// only in whose turn it is, or only in EP availability, would otherwise
// collide under this key. Mix both in here so callers (e.g. the oracle's
// memoization) get a hash that distinguishes them.
uint64_t Board::hash() const {
    uint64_t h = impl_->pos.get_hash();
    if (impl_->pos.turn() == BLACK) h ^= kSideToMoveKey;
    int ep = ep_square();
    if (ep >= 0) h ^= kEpKeys[ep];
    return h;
}

uint64_t Board::perft(int depth) {
    if (depth == 0) return 1;
    uint64_t nodes = 0;
    for (auto& m : legal_moves()) {
        make(m);
        nodes += perft(depth - 1);
        unmake(m);
    }
    return nodes;
}

}  // namespace hm

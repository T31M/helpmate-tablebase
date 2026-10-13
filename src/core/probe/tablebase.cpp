#include "probe/tablebase.h"

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <exception>
#include <set>
#include <thread>
#include <utility>

#include "chess/san.h"
#include "generator/eval.h"
#include "themes/registry.h"

namespace hm {

namespace {
// Color flip is exact here because castling rights don't exist in this game:
// mirror ranks (sq ^ 56), swap every piece's color, flip the side to move, and
// mirror any en passant square the same way.
Board flip_colors(const Board& b) {
    std::vector<PlacedPiece> pp;
    for (auto& p : b.pieces())
        pp.push_back({{p.piece.color == Color::White ? Color::Black : Color::White, p.piece.type},
                       (uint8_t)(p.square ^ 56)});
    Color stm = b.stm() == Color::White ? Color::Black : Color::White;
    int ep = b.ep_square();
    return Board::from_pieces(pp, stm, ep >= 0 ? (ep ^ 56) : -1);
}
}  // namespace

Tablebase::Tablebase(std::string dir) : dir_(std::move(dir)) {}

const Tablebase::Slice* Tablebase::load(const Material& m) const {
    std::lock_guard lk(mu_);
    auto it = cache_.find(m.name());
    if (it != cache_.end()) return it->second.get();
    std::string path = dir_ + "/" + m.name() + ".hm";
    TableReader::OpenError oerr = TableReader::OpenError::None;
    auto r = TableReader::open(path, &oerr);
    if (!r && oerr == TableReader::OpenError::UnsupportedVersion)
        throw UnsupportedTableVersionError("table " + path + " was written by a newer helpmate"
                                           " (unsupported table format version); upgrade this build");
    if (r) {
        // Identity check (before caching anything): the file must actually be the table
        // its name promises, or every later lookup would silently index the wrong planes.
        SliceIndex si(m);
        if (r->material_name() != m.name())
            throw std::runtime_error("table " + path + " is for material '" +
                                     r->material_name() + "', expected '" + m.name() + "'");
        if (r->plane_size() != si.size())
            throw std::runtime_error("table " + path + " has plane size " +
                                     std::to_string(r->plane_size()) + ", expected " +
                                     std::to_string(si.size()) + " for " + m.name());
        auto& slot = cache_[m.name()];
        slot = std::make_unique<Slice>(Slice{std::move(*r), std::move(si)});
        return slot.get();
    }
    return cache_[m.name()].get();  // caches the miss
}

ValuePair Tablebase::value_of(Board& b) const {
    auto lookup = [this](Board& x) -> ValuePair {
        Material m = Material::of(x.pieces());
        const Slice* s = load(m);
        if (!s) throw MissingTableError("no table for " + m.name());
        auto cell = s->index.encode(x.pieces());
        if (!cell) throw MissingTableError("position not encodable in table for " + m.name());
        return s->reader.get(x.stm(), *cell);
    };
    return eval_board(b, lookup);
}

uint8_t Tablebase::dtm_of(Board& b) const {
    // eval_board takes the minimum over DTMs only, so a lookup with count 0
    // gives the same DTM as value_of; the count it returns is meaningless.
    auto lookup = [this](Board& x) -> ValuePair {
        Material m = Material::of(x.pieces());
        const Slice* s = load(m);
        if (!s) throw MissingTableError("no table for " + m.name());
        auto cell = s->index.encode(x.pieces());
        if (!cell) throw MissingTableError("position not encodable in table for " + m.name());
        return {s->reader.get_dtm(x.stm(), *cell), 0};
    };
    return eval_board(b, lookup).dtm;
}

std::optional<Tablebase::Probe> Tablebase::probe(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Material m = Material::of(b->pieces());
    bool flipped = false;
    Board target = *b;
    const Slice* s = nullptr;
    // A future-format primary table must not preempt the color-flip fallback: remember
    // the diagnostic and keep going. Only the primary attempt is wrapped -- if the flip
    // attempt itself throws (its own table is unreadable/future-format), that propagates
    // unmodified, and if it merely comes up empty, the remembered primary error (if any)
    // is more informative than a generic "no table" message.
    std::optional<UnsupportedTableVersionError> primary_err;
    try {
        s = load(m);
    } catch (const UnsupportedTableVersionError& e) {
        primary_err = e;
    }
    if (!s) {
        target = flip_colors(*b);
        flipped = true;
        if (!load(Material::of(target.pieces()))) {
            if (primary_err) throw *primary_err;
            throw MissingTableError("no table for " + m.name() + " nor its color flip");
        }
    }
    ValuePair v = value_of(target);
    if (v.dtm > DTM_MAX) return std::nullopt;  // UNSOLVABLE (INVALID can't reach here: FEN was legal)
    return Probe{(int)v.dtm, (int)v.count, flipped};
}

void Tablebase::collect_lines(Board& b, std::vector<std::string>& path,
                               std::vector<std::vector<std::string>>& out, int max) const {
    if ((int)out.size() >= max) return;
    uint8_t dtm = dtm_of(b);
    if (dtm == 0) {
        out.push_back(path);
        return;
    }
    for (const Move& m : b.legal_moves()) {
        if ((int)out.size() >= max) return;
        b.make(m);
        uint8_t ndtm = dtm_of(b);
        bool on_optimal = ndtm <= DTM_MAX && (int)ndtm == (int)dtm - 1;
        b.unmake(m);
        if (!on_optimal) continue;
        path.push_back(san(b, m));  // b is still pre-move here; san() restores it too
        b.make(m);
        collect_lines(b, path, out, max);
        b.unmake(m);
        path.pop_back();
    }
}

std::vector<std::vector<std::string>> Tablebase::lines(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<std::vector<std::string>> out;
    std::vector<std::string> path;
    collect_lines(*b, path, out, max);
    return out;
}

void Tablebase::collect_solutions(Board& b, std::vector<Ply>& path, std::vector<Solution>& out,
                                  const Board& start, int max) const {
    if ((int)out.size() >= max) return;
    uint8_t dtm = dtm_of(b);
    if (dtm == 0) {
        out.push_back(Solution{start, path});
        return;
    }
    for (const Move& m : b.legal_moves()) {
        if ((int)out.size() >= max) return;
        b.make(m);
        uint8_t ndtm = dtm_of(b);
        bool on_optimal = ndtm <= DTM_MAX && (int)ndtm == (int)dtm - 1;
        b.unmake(m);
        if (!on_optimal) continue;

        Ply p;
        p.from = m.from;
        p.to = m.to;
        p.promotion = m.promotion();
        p.is_ep = m.is_ep();
        for (const auto& pp : b.pieces()) {  // b is still PRE-move here
            if (pp.square == m.from) p.piece = pp.piece;
            else if (pp.square == m.to) p.captured = pp.piece.type;
        }
        // An en-passant capture takes a pawn that is NOT on m.to, so the scan
        // above cannot see it.
        if (p.is_ep) p.captured = PieceType::Pawn;

        b.make(m);
        p.is_check = b.in_check();
        p.after = b;
        path.push_back(std::move(p));
        collect_solutions(b, path, out, start, max);
        path.pop_back();
        b.unmake(m);
    }
}

std::vector<Solution> Tablebase::solutions(const std::string& fen, int max) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    Board start = *b;
    std::vector<Solution> out;
    std::vector<Ply> path;
    collect_solutions(*b, path, out, start, max);
    return out;
}

std::vector<std::string> Tablebase::line(const std::string& fen) const {
    auto ls = lines(fen, 1);
    return ls.empty() ? std::vector<std::string>{} : ls[0];
}

std::vector<MoveInfo> Tablebase::moves(const std::string& fen) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN: " + fen);
    int parent_dtm = -1;
    if (auto p = probe(fen)) parent_dtm = p->dtm;

    std::vector<MoveInfo> out;
    for (const Move& m : b->legal_moves()) {
        MoveInfo mi;
        mi.uci = m.uci();
        mi.san = san(*b, m);          // SAN must be computed BEFORE the move is made
        b->make(m);
        mi.fen = b->fen();
        b->unmake(m);
        try {
            if (auto c = probe(mi.fen)) {
                mi.dtm = c->dtm;
                mi.count = c->count;
                mi.solvable = true;
                // parent_dtm > 0: a dtm-0 position is mate and has no legal moves, so the
                // loop body never runs for it (this guard just avoids an accidental match
                // against the sentinel -1 when the parent itself was unsolvable).
                mi.optimal = parent_dtm > 0 && c->dtm == parent_dtm - 1;
            }
        } catch (const MissingTableError&) {
            // no table for the resulting material: leave solvable=false
        } catch (const std::invalid_argument&) {
            // The move leads somewhere the tablebase cannot describe at all --
            // in practice a king capture, which is only reachable when the
            // query position is itself illegal (the side not to move is
            // already in check). The position editor produces such positions
            // on the way to real ones, so the move list must stay complete and
            // report the move as having no value, exactly like a missing
            // table. Throwing here would answer a whole legal-move request
            // with an invalid_fen error naming a FEN the caller never sent.
        }
        out.push_back(std::move(mi));
    }
    return out;
}

SolutionShape shape_of(int count, const std::vector<std::vector<std::string>>& lines) {
    if (count >= (int)COUNT_SAT) return {0, 0, false};  // cannot enumerate exhaustively
    std::set<std::string> firsts, lasts;
    for (const auto& l : lines) {
        if (l.empty()) continue;                       // dtm 0: already mate, no moves
        firsts.insert(l.front());
        lasts.insert(l.back());
    }
    return {(int)firsts.size(), (int)lasts.size(), true};
}

SolutionShape Tablebase::solution_shape(const std::string& fen) const {
    auto p = probe(fen);
    if (!p) return {0, 0, true};                       // unsolvable: no solutions at all
    if (p->count >= (int)COUNT_SAT) return shape_of(p->count, {});  // never enumerate a saturated position
    return shape_of(p->count, lines(fen, p->count));
}

struct Tablebase::MineScan {
    Material m;
    Color stm;
    Color other_stm;
    MineFilter f;
    std::vector<themes::ResolvedTheme> dets;
    themes::Needs need;
    bool want_shape;
    bool want_solutions;
    bool want_plane;
};

void Tablebase::mine(const Material& m, const MineFilter& f,
                     const std::function<bool(const std::string&)>& cb, uint64_t* skipped_saturated,
                     int threads) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    Color stm = (f.dtm % 2) ? Color::White : Color::Black;  // parity invariant: wtm dtm odd, btm dtm even

    // Resolve theme names ONCE, before the scan: a typo must be an error that
    // names the valid options, not millions of positions filtered by nothing.
    std::vector<themes::ResolvedTheme> dets;
    themes::Needs need = themes::Needs::Position;
    for (const auto& n : f.themes) {
        std::string err;
        auto r = themes::resolve_theme(n, &err);
        if (!r) throw std::invalid_argument(err);
        need = std::max(need, r->def->needs);
        dets.push_back(std::move(*r));
    }

    const bool want_shape = f.starts >= 0 || f.ends >= 0;
    // Enumerate only when something actually needs the solutions. A query whose
    // themes read only the diagram skips enumeration and answers on saturated
    // positions too, at the cost of one decode plus one Board construction per
    // candidate -- measured at 26s over a 31.5M-candidate query.
    const bool want_solutions = want_shape || (!dets.empty() && need == themes::Needs::Solutions);
    const bool want_plane = !dets.empty() && need >= themes::Needs::Plane;
    const MineScan q{m,
                     stm,
                     stm == Color::White ? Color::Black : Color::White,
                     f,
                     std::move(dets),
                     need,
                     want_shape,
                     want_solutions,
                     want_plane};

    const uint64_t plane_cells = s->index.size();
    // About 16 segments per worker, so a slow segment (one dense in
    // candidates) does not leave the other workers idle at the end, within
    // [4096, 2^20] cells: large enough that claiming one is cheap, small
    // enough that a --max stop does not wait long for workers to finish.
    const uint64_t kSegment = std::clamp<uint64_t>(plane_cells / (16 * (uint64_t)std::max(threads, 1)),
                                                   uint64_t{1} << 12, uint64_t{1} << 20);
    const uint64_t segments = (plane_cells + kSegment - 1) / kSegment;
    if (threads <= 1 || segments <= 1) {
        mine_range(q, 0, plane_cells, cb, skipped_saturated);
        return;
    }

    // Workers claim segments in order and park each result in a ring slot;
    // this thread hands the results to `cb` in segment order, so the caller
    // sees the single-threaded sequence. A worker never claims more than
    // `window` segments past the last one handed out, which bounds the
    // buffered FENs no matter how slow `cb` is.
    struct Segment {
        bool done = false;
        // Each hit with the saturated skips before it in its segment, so a
        // stop at that hit leaves the same tally one thread would.
        std::vector<std::pair<std::string, uint64_t>> hits;
        uint64_t skipped = 0;
        std::exception_ptr error;
    };
    const uint64_t workers = std::min<uint64_t>((uint64_t)threads, segments);
    const uint64_t window = 4 * workers;
    std::vector<Segment> ring(window);
    std::mutex mu;
    std::condition_variable cv;
    uint64_t next = 0;     // first unclaimed segment
    uint64_t emitted = 0;  // segments handed to cb so far
    std::atomic<bool> stop{false};

    auto work = [&] {
        // Its own Tablebase: own readers, own block caches, no shared lock.
        Tablebase own(dir_);
        for (;;) {
            uint64_t k;
            {
                std::unique_lock lk(mu);
                cv.wait(lk, [&] { return stop.load() || next >= segments || next < emitted + window; });
                if (stop.load() || next >= segments) return;
                k = next++;
            }
            Segment seg;
            try {
                const uint64_t begin = k * kSegment;
                own.mine_range(
                    q, begin, std::min(plane_cells, begin + kSegment),
                    [&](const std::string& fen) {
                        seg.hits.emplace_back(fen, seg.skipped);
                        return !stop.load();
                    },
                    &seg.skipped);
            } catch (...) { seg.error = std::current_exception(); }
            seg.done = true;
            {
                std::lock_guard lk(mu);
                ring[k % window] = std::move(seg);
            }
            cv.notify_all();
        }
    };
    std::vector<std::thread> pool;
    auto finish = [&] {
        {
            std::lock_guard lk(mu);
            stop = true;
        }
        cv.notify_all();
        for (auto& th : pool) th.join();
    };
    const uint64_t tally0 = skipped_saturated ? *skipped_saturated : 0;
    uint64_t tally = 0;  // saturated skips in the segments handed out so far
    try {
        for (uint64_t i = 0; i < workers; ++i) pool.emplace_back(work);
        for (uint64_t k = 0; k < segments; ++k) {
            Segment seg;
            {
                std::unique_lock lk(mu);
                cv.wait(lk, [&] { return ring[k % window].done; });
                seg = std::move(ring[k % window]);
                ring[k % window] = Segment{};
                ++emitted;
            }
            cv.notify_all();
            for (const auto& [fen, before] : seg.hits) {
                if (skipped_saturated) *skipped_saturated = tally0 + tally + before;
                if (!cb(fen)) {
                    finish();
                    return;
                }
            }
            tally += seg.skipped;
            if (skipped_saturated) *skipped_saturated = tally0 + tally;
            // A worker's error surfaces where one thread would have hit it:
            // after every FEN before the failing cell.
            if (seg.error) std::rethrow_exception(seg.error);
        }
    } catch (...) {
        finish();
        throw;
    }
    finish();
}

bool Tablebase::mine_range(const MineScan& q, uint64_t begin, uint64_t end,
                           const std::function<bool(const std::string&)>& cb,
                           uint64_t* skipped_saturated) const {
    const Slice* s = load(q.m);
    if (!s) throw MissingTableError("no table for " + q.m.name());
    const MineFilter& f = q.f;
    const Color stm = q.stm, other_stm = q.other_stm;
    const auto& dets = q.dets;
    const themes::Needs need = q.need;
    const bool want_shape = q.want_shape, want_solutions = q.want_solutions, want_plane = q.want_plane;
    std::vector<PlacedPiece> pp;
    // Read the two planes in block-sized chunks instead of one cell at a time.
    // get() on a compressed table takes the block cache's mutex and memcpys a
    // single byte per call; over a whole plane that -- not the decompression --
    // was the cost, measured at 14x raw on KRvkbn before this loop was chunked.
    // read_values() pays one lock and one memcpy per block touched.
    constexpr size_t kScanChunk = 1 << 16;
    std::vector<uint8_t> dtm_buf(kScanChunk), cnt_buf(kScanChunk);
    // Third buffer for the sibling side-to-move plane, filled only when some
    // requested theme needs it (Needs::Plane). A cell index is independent of
    // side to move -- side to move selects the plane, not the index -- so the
    // sibling value for candidate cell c is the same cell c read from the
    // other plane, one extra read_values() call over the same chunk.
    std::vector<uint8_t> other_buf(want_plane ? kScanChunk : 0);
    uint64_t chunk_base = begin;
    size_t chunk_n = 0;
    for (uint64_t c = begin; c < end; ++c) {
        if (c - chunk_base >= chunk_n) {
            chunk_base = c;
            chunk_n = (size_t)std::min<uint64_t>(kScanChunk, end - c);
            s->reader.read_values(stm, chunk_base, chunk_n, dtm_buf.data(), cnt_buf.data());
            if (want_plane) s->reader.read_values(other_stm, chunk_base, chunk_n, other_buf.data(), nullptr);
        }
        ValuePair v{dtm_buf[c - chunk_base], cnt_buf[c - chunk_base]};
        if (v.dtm != (uint8_t)f.dtm) continue;
        if (f.count >= 0 && v.count != (uint8_t)f.count) continue;
        if (!s->index.decode(c, pp)) continue;
        Board b = Board::from_pieces(pp, stm);
        // fen is built lazily -- only where it is actually consumed
        // (lines()/solutions() below, or cb() on an actual match). A
        // Needs::Position theme (the diagram alone, no table access) never
        // touches it, and b.fen() is not free: skipping it is most of the
        // point of this function honouring `needs` at all, since evaluating
        // a Needs::Position detector never requires it.
        std::string fen;
        // v.count is this cell's own stored count -- the same number a
        // probe() of `fen` would return. Using it directly saves a
        // redundant table lookup per candidate; two things make that
        // safe, not "probe() cannot color-flip" (it can, in general):
        // Board::from_pieces(pp, stm) above defaults ep_square to -1, so
        // eval_board's EP branch -- the only place probe()'s answer can
        // differ from this cell's raw value -- is inert for every FEN
        // built here; and load(m) already succeeded (this loop is
        // iterating `s`, a slice it returned), so probe()'s color-flip
        // fallback, which only triggers when the PRIMARY load fails,
        // never runs for `fen`. Mining pawn material with reconstructed
        // en-passant positions is a plausible next rung -- if that ever
        // makes fen carry a real ep_square, the first load-bearer above
        // stops holding and this shortcut needs revisiting.
        //
        // Only applies when solutions are actually wanted: a Position-only
        // theme query answers on saturated positions too, since it never
        // asks a saturated cell for the very thing it cannot give.
        if (want_solutions && v.count >= COUNT_SAT) {  // unknowable, never guessed at
            if (skipped_saturated) ++*skipped_saturated;
            continue;
        }
        if (want_shape) {
            // --starts/--ends are a released v0.6.2 feature (see CHANGELOG.md)
            // keyed on SAN, not on (from, to, promotion): SAN disambiguates a
            // capture from a quiet move sharing the same (from, to) (Qxa4# vs
            // Qa4#: v0.6.2 counts 2 distinct mating moves), and distinguishes
            // two moves that happen to share a destination square but render
            // identically otherwise (Qb4-b1# vs Qe4-b1#, both SAN "Qb1#": v0.6.2
            // counts 1). A (from, to, promotion) key gets both cases backwards.
            // Changing --ends's meaning as a side effect of adding themes is not
            // acceptable, so this goes through lines()/shape_of exactly like
            // v0.6.2 did, not through solutions().
            fen = b.fen();
            SolutionShape sh = shape_of((int)v.count, lines(fen, (int)v.count));
            if (f.starts >= 0 && sh.starts != f.starts) continue;
            if (f.ends >= 0 && sh.ends != f.ends) continue;
        }
        if (!dets.empty()) {
            std::vector<Solution> sols;
            if (need == themes::Needs::Solutions) {
                if (fen.empty()) fen = b.fen();
                sols = solutions(fen, (int)v.count);
            }
            std::optional<ValuePair> other;
            if (want_plane) other = ValuePair{other_buf[c - chunk_base], 0};
            themes::ThemeInput in{b, v, other, sols};
            bool all_present = true;
            for (const auto& d : dets) {  // AND across themes; `any` (or `every`, for
                if (!d.eval(in)) {        // nocapture/nocheck) within one is inside d
                                          // itself: any_of<> / all_of<>
                    all_present = false;
                    break;
                }
            }
            if (!all_present) continue;
        }
        if (fen.empty()) fen = b.fen();  // only reached by an actual match
        if (!cb(fen)) return false;
    }
    return true;
}

void Tablebase::with_theme_input(const std::string& fen, int max,
                                 const std::function<void(const themes::ThemeInput&)>& use) const {
    auto b = Board::from_fen(fen);
    if (!b) throw std::invalid_argument("bad FEN (or castling rights): " + fen);
    std::vector<Solution> sols = solutions(fen, max);
    ValuePair value{DTM_UNSOLVABLE, 0};
    try {
        value = value_of(*b);
    } catch (const MissingTableError&) {
        // no table for this position's own plane: leave the DTM_UNSOLVABLE
        // sentinel rather than inventing a value -- has_set_play answers "no".
    }
    std::optional<ValuePair> other;
    Board flipped = *b;
    flipped.reset(b->pieces(), b->stm() == Color::White ? Color::Black : Color::White);
    try {
        other = value_of(flipped);
    } catch (const MissingTableError&) {
        other = std::nullopt;  // no table for the sibling plane: answer "no"
    }
    themes::ThemeInput in{*b, value, other, sols};
    use(in);
}

std::vector<std::string> Tablebase::themes_of(const std::string& fen, int max) const {
    std::vector<std::string> out;
    with_theme_input(fen, max, [&](const themes::ThemeInput& in) { out = themes::detect(in); });
    return out;
}

bool Tablebase::shows_theme(const std::string& fen, const themes::ResolvedTheme& t, int max) const {
    bool r = false;
    with_theme_input(fen, max, [&](const themes::ThemeInput& in) { r = t.eval(in); });
    return r;
}

std::string Tablebase::stats_json(const Material& m) const {
    const Slice* s = load(m);
    if (!s) throw MissingTableError("no table for " + m.name());
    return s->reader.meta_json();
}

std::string Tablebase::h_notation(int dtm, Color) {
    int moves = dtm / 2;
    return "h#" + std::to_string(moves) + (dtm % 2 ? ".5" : "");
}

}  // namespace hm

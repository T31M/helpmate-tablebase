#include "generator/generator.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>

#include "chess/board.h"
#include "generator/eval.h"
#include "generator/parallel.h"
#include "version.h"

namespace hm {

std::string describe_position(const std::vector<PlacedPiece>& pp, Color stm) {
    try {
        return Board::from_pieces(pp, stm).fen();
    } catch (...) { return "<unavailable>"; }
}

namespace {
// Names the cell a failed lookup came from. Built only on the throwing path.
std::string cell_context(const Material& mat, uint64_t cell, int stm, int depth) {
    return "slice " + mat.name() + ", cell " + std::to_string(cell) + ", stm " + (stm ? "black" : "white") +
           ", scan depth " + std::to_string(depth);
}

std::string gib(uint64_t bytes) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.2f", (double)bytes / (1024.0 * 1024.0 * 1024.0));
    return buf;
}

// Seconds since t0, formatted "%.1f". Progress/verbose reporting only.
std::string secs_since(std::chrono::steady_clock::time_point t0) {
    double s = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
    char buf[32];
    std::snprintf(buf, sizeof buf, "%.1f", s);
    return buf;
}
}  // namespace

std::optional<uint64_t> mem_available_bytes() {
    std::ifstream f("/proc/meminfo");
    if (!f) return std::nullopt;
    std::string line;
    while (std::getline(f, line)) {
        constexpr const char* kKey = "MemAvailable:";
        if (line.rfind(kKey, 0) != 0) continue;
        char* end = nullptr;
        unsigned long long kb = std::strtoull(line.c_str() + std::strlen(kKey), &end, 10);
        if (end == line.c_str() + std::strlen(kKey)) return std::nullopt;  // no number followed
        return (uint64_t)kb * 1024;
    }
    return std::nullopt;
}

std::optional<std::string> ram_guard_error(const std::string& slice, uint64_t required_bytes,
                                           uint64_t available_bytes) {
    if (required_bytes <= available_bytes) return std::nullopt;
    return "not enough memory to generate slice " + slice + ": its four value planes need ~" +
           gib(required_bytes) + " GiB but only " + gib(available_bytes) +
           " GiB is available (MemAvailable, /proc/meminfo); re-run with --force-ram to override";
}

bool slice_has_any_mate(const Material& m) {
    SliceIndex idx(m);
    std::vector<PlacedPiece> pp;
    Board b;
    uint64_t n = idx.size();
    for (uint64_t c = 0; c < n; ++c) {
        if (!idx.decode(c, pp)) continue;
        auto e = idx.encode_for_material(pp, m);
        if (!e || *e != c) continue;          // non-canonical duplicate
        b.reset(pp, Color::Black);            // mates are black-to-move
        if (b.opponent_in_check()) continue;  // illegal for this stm
        if (b.state() == PosState::Checkmate) return true;
    }
    return false;
}

SliceGen::SliceGen(const Material& m, const GenOptions& opt) : mat_(m), opt_(opt), idx_(m), ps_(idx_.size()) {
    for (int s = 0; s < 2; ++s) {
        dtm_[s].assign(ps_, DTM_UNSET);
        cnt_[s].assign(ps_, 0);
    }
}

void SliceGen::init_pass() {
    auto t0 = std::chrono::steady_clock::now();
    // Each cell c is examined and written independently of every other cell
    // (opponent_in_check()/state() depend only on pp/s decoded from c itself),
    // so a disjoint [begin,end) range per worker is race-free; each worker
    // gets its own Board/pp (Board is stateful, not shareable across threads).
    parallel_for(ps_, opt_.threads, [this](uint64_t begin, uint64_t end) {
        std::vector<PlacedPiece> pp;
        Board b;
        for (uint64_t c = begin; c < end; ++c) {
            if (!idx_.decode(c, pp)) {
                dtm_[0][c] = dtm_[1][c] = DTM_INVALID;
                continue;
            }
            auto e = idx_.encode_for_material(pp, mat_);
            if (!e || *e != c) {
                dtm_[0][c] = dtm_[1][c] = DTM_INVALID;
                continue;
            }  // non-canonical duplicate
            for (int s = 0; s < 2; ++s) {
                b.reset(pp, (Color)s);
                if (b.opponent_in_check()) {
                    dtm_[s][c] = DTM_INVALID;
                    continue;
                }
                if (s == 1 && b.state() == PosState::Checkmate) dtm_[1][c] = 0;
            }
        }
    });
    if (opt_.progress) std::cerr << "  " << mat_.name() << ": init pass done (" << secs_since(t0) << " s)\n";
}

void SliceGen::count_sweep() {
    // Pass d reads only counts of cells with dtm d-1, which the previous
    // iteration finalized; sub-slice tables were fully counted before this
    // slice (topological build order); eval_board merges EP branches with
    // the same min/sum rule. Within one d, cell c only ever writes cnt_[s][c]
    // and reads already-finalized lower-depth cells/sub-tables, so cells are
    // independent of each other and safe to split across worker threads;
    // the d loop itself stays sequential since depth d depends on depth d-1.
    parallel_for(ps_, opt_.threads, [this](uint64_t begin, uint64_t end) {
        for (uint64_t c = begin; c < end; ++c)
            if (dtm_[1][c] == 0) cnt_[1][c] = 1;
    });
    for (int d = 1; d <= max_dtm_; ++d) {
        auto t0 = std::chrono::steady_clock::now();
        int s = (d % 2) ? 0 : 1;
        parallel_for(ps_, opt_.threads, [this, s, d](uint64_t begin, uint64_t end) {
            std::vector<PlacedPiece> pp;
            Board b;
            for (uint64_t c = begin; c < end; ++c) {
                if (dtm_[s][c] != d) continue;
                if (!idx_.decode(c, pp))
                    throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": solved cell does not decode");
                b.reset(pp, (Color)s);
                unsigned total = 0;
                try {
                    for (const Move& m : b.legal_moves()) {
                        b.make(m);
                        ValuePair v = eval_board(b, [this, &pp](Board& x) { return lookup_epless(x, pp); });
                        b.unmake(m);
                        if (v.dtm == d - 1) total = std::min(255u, total + (unsigned)v.count);
                    }
                } catch (const GeneratorLookupError& e) {
                    throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
                } catch (const std::out_of_range& e) {  // TableReader::get bounds guard
                    throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
                }
                cnt_[s][c] = (uint8_t)total;  // >= 1 by construction of dtm
            }
        });
        // Reported from the coordinating thread at a pass boundary only --
        // the worker loop above is untouched by any progress bookkeeping.
        if (opt_.progress)
            std::cerr << "  " << mat_.name() << ": count sweep d=" << d << "/" << max_dtm_ << " done ("
                      << secs_since(t0) << " s)\n";
    }
}

const std::vector<uint8_t>& SliceGen::dtm(Color stm) const { return dtm_[(int)stm]; }
const std::vector<uint8_t>& SliceGen::cnt(Color stm) const { return cnt_[(int)stm]; }
const SliceIndex& SliceGen::index() const { return idx_; }
int SliceGen::max_dtm() const { return max_dtm_; }

ValuePair SliceGen::lookup_epless(Board& b, std::vector<PlacedPiece>& piece_scratch) {
    b.pieces(piece_scratch);
    const auto& pp = piece_scratch;
    Material m = Material::of(pp);
    if (m == mat_) {
        auto e = idx_.encode_for_material(pp, m);
        int s = (int)b.stm();
        // encode() is disengaged for positions this slice cannot hold (kings adjacent/equal).
        // Dereferencing it unchecked read uninitialised stack, and since vec[i] is
        // *(data() + i) with wrapping arithmetic, a garbage index lands anywhere in the
        // address space -- a silently wrong value at best, a wild access at worst.
        if (!e)
            throw GeneratorLookupError("position not encodable in own slice " + m.name() +
                                       "; position after move " + describe_position(pp, b.stm()));
        if (*e >= ps_)
            throw GeneratorLookupError("cell " + std::to_string(*e) + " out of range for slice " + m.name() +
                                       " (plane size " + std::to_string(ps_) + "); position after move " +
                                       describe_position(pp, b.stm()));
        return {dtm_[s][*e], cnt_[s][*e]};
    }
    return subs_.lookup_for_material(m, pp, b.stm());
}

bool SliceGen::scan_pass(int d) {
    // Safety argument for running this pass's cell loop across worker threads:
    // pass d writes only the value d, and only into currently-UNSET cells of
    // ONE plane (dtm_[s], s = mover's side); it reads (a) the opposite-parity
    // plane, which this pass never writes -- a cell's successors after one
    // ply always have the other side to move -- (b) finished sub-tables
    // (read-only after load_for(), before any pass runs), and (c) same-plane
    // values only to check DTM_UNSET (never written by another cell). So two
    // workers touching different cells c1 != c2 never read-during-write or
    // write-during-write each other's data. Each worker owns a disjoint cell
    // range (and its own Board/pp, since Board is stateful); the only shared
    // mutable state is `resolved`, a counter each worker adds its private
    // per-chunk tally to exactly once, after its cell loop -- so the hot loop
    // itself carries no locks, IO, or shared atomic traffic.
    auto t0 = std::chrono::steady_clock::now();
    Color mover = (d % 2) ? Color::White : Color::Black;
    int s = (int)mover;
    std::atomic<uint64_t> resolved{0};
    parallel_for(ps_, opt_.threads, [this, s, mover, d, &resolved](uint64_t begin, uint64_t end) {
        std::vector<PlacedPiece> pp;
        Board b;
        uint64_t local = 0;
        for (uint64_t c = begin; c < end; ++c) {
            if (dtm_[s][c] != DTM_UNSET) continue;
            if (!idx_.decode(c, pp))  // UNSET cells always decode
                throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": UNSET cell does not decode");
            b.reset(pp, mover);
            // Catch here rather than tracking the current cell in a variable: zero-cost EH puts
            // nothing on the happy path. (The unchanged-instruction-sequence argument applies to
            // this scan_pass loop only; count_sweep's identical wrapper makes no such claim.)
            try {
                for (const Move& m : b.legal_moves()) {
                    b.make(m);
                    ValuePair v = eval_board(b, [this, &pp](Board& x) { return lookup_epless(x, pp); });
                    b.unmake(m);
                    if (v.dtm == d - 1) {
                        dtm_[s][c] = (uint8_t)d;
                        ++local;
                        break;
                    }
                }
            } catch (const GeneratorLookupError& e) {
                throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
            } catch (const std::out_of_range& e) {  // TableReader::get bounds guard
                throw GeneratorLookupError(cell_context(mat_, c, s, d) + ": " + e.what());
            }
        }
        if (local) resolved.fetch_add(local, std::memory_order_relaxed);
    });
    uint64_t n = resolved.load();
    // Reported from the coordinating thread at the pass boundary only.
    if (opt_.progress)
        std::cerr << "  " << mat_.name() << ": pass d=" << d << " resolved " << n << " cells ("
                  << secs_since(t0) << " s)\n";
    return n > 0;
}

void SliceGen::run_all_passes() {
    subs_.load_for(mat_, opt_.tables_dir);
    init_pass();
    max_dtm_ = -1;
    {
        bool any0 = false;
        for (uint64_t c = 0; c < ps_; ++c)
            if (dtm_[1][c] == 0) {
                any0 = true;
                break;
            }
        if (any0) max_dtm_ = 0;
    }
    int misses = 0;
    for (int d = 1; d <= DTM_MAX && misses < 2; ++d) {
        if (scan_pass(d)) {
            max_dtm_ = d;
            misses = 0;
        } else misses++;
    }
}

nlohmann::json SliceGen::stats_json() const {
    using nlohmann::json;
    static const char* kStm[2] = {"wtm", "btm"};

    json cells_invalid, cells_unsolvable, histogram, uniqueness;
    for (int s = 0; s < 2; ++s) {
        uint64_t invalid = 0, unsolvable = 0;
        std::map<int, uint64_t> hist;
        std::map<int, std::map<int, uint64_t>> uniq;
        for (uint64_t c = 0; c < ps_; ++c) {
            uint8_t d = dtm_[s][c];
            if (d == DTM_INVALID) {
                ++invalid;
                continue;
            }
            if (d == DTM_UNSOLVABLE) {
                ++unsolvable;
                continue;
            }
            ++hist[d];
            ++uniq[d][cnt_[s][c]];
        }
        cells_invalid[kStm[s]] = invalid;
        cells_unsolvable[kStm[s]] = unsolvable;

        json hj = json::object();
        for (auto& [depth, count] : hist) hj[std::to_string(depth)] = count;
        histogram[kStm[s]] = hj;

        json uj = json::object();
        for (auto& [depth, counts] : uniq) {
            json cj = json::object();
            for (auto& [cnt, n] : counts) cj[std::to_string(cnt)] = n;
            uj[std::to_string(depth)] = cj;
        }
        uniqueness[kStm[s]] = uj;
    }

    json deepest = json::array(), deepest_unique = json::array();
    if (max_dtm_ >= 0) {
        std::vector<PlacedPiece> pp;
        int s = (max_dtm_ % 2) ? 0 : 1;  // parity: odd depths are wtm, even are btm
        for (uint64_t c = 0; c < ps_ && deepest.size() < 5; ++c) {
            if (dtm_[s][c] != (uint8_t)max_dtm_) continue;
            if (!idx_.decode(c, pp)) continue;
            deepest.push_back(Board::from_pieces(pp, (Color)s).fen());
        }
        for (int d = max_dtm_; d >= 0 && deepest_unique.empty(); --d) {
            int ss = (d % 2) ? 0 : 1;
            for (uint64_t c = 0; c < ps_ && deepest_unique.size() < 5; ++c) {
                if (dtm_[ss][c] != (uint8_t)d || cnt_[ss][c] != 1) continue;
                if (!idx_.decode(c, pp)) continue;
                deepest_unique.push_back(Board::from_pieces(pp, (Color)ss).fen());
            }
        }
    }

    json j;
    j["material"] = mat_.name();
    j["plane_size"] = ps_;
    j["max_dtm"] = max_dtm_ < 0 ? (int)DTM_UNSOLVABLE : max_dtm_;
    j["cells"] = {{"invalid", cells_invalid}, {"unsolvable", cells_unsolvable}};
    j["dtm_histogram"] = histogram;
    j["uniqueness"] = uniqueness;
    j["deepest"] = deepest;
    j["deepest_unique"] = deepest_unique;
    j["generator_version"] = HELPMATE_VERSION;
    return j;
}

void SliceGen::finalize_and_write() {
    for (int s = 0; s < 2; ++s)
        for (uint64_t c = 0; c < ps_; ++c)
            if (dtm_[s][c] == DTM_UNSET) dtm_[s][c] = DTM_UNSOLVABLE;
    nlohmann::json j = stats_json();
    std::string meta = j.dump(2);
    std::filesystem::create_directories(opt_.tables_dir);
    std::string base = opt_.tables_dir + "/" + mat_.name();
    uint8_t max_dtm_byte = max_dtm_ < 0 ? DTM_UNSOLVABLE : (uint8_t)max_dtm_;
    if (opt_.compress) {
        TableWriter::write_compressed(base + ".hm", mat_, ps_, max_dtm_byte, meta, dtm_[0].data(),
                                      dtm_[1].data(), cnt_[0].data(), cnt_[1].data(), opt_.block_size);
    } else {
        TableWriter::write(base + ".hm", mat_, ps_, max_dtm_byte, meta, dtm_[0].data(), dtm_[1].data(),
                           cnt_[0].data(), cnt_[1].data());
    }
    std::ofstream out(base + ".stats.json", std::ios::trunc);
    out << meta;
}

std::vector<std::string> generate(const Material& root, const GenOptions& opt_in) {
    GenOptions opt = opt_in;
    if (opt.verbose) opt.progress = true;  // --verbose implies --progress

    auto closure = Material::closure_topo(root);

    // Pre-flight: index sizes are pure mixed-radix math, so the whole closure
    // can be costed before a single byte is allocated. An impossible run
    // (typically the root slice of a 7-8 piece material) must fail *now*, not
    // after days of sub-slice generation.
    struct Todo {
        const Material* m;
        uint64_t cells;
    };
    std::vector<Todo> missing;
    for (auto& m : closure)
        if (!std::filesystem::exists(opt.tables_dir + "/" + m.name() + ".hm"))
            missing.push_back({&m, SliceIndex(m).size()});
    if (opt.verbose) {
        std::cerr << "gen " << root.name() << ": closure has " << closure.size() << " slice(s):";
        for (auto& m : closure) std::cerr << " " << m.name();
        std::cerr << "\n";
    }
    auto avail = mem_available_bytes();
    if (!missing.empty()) {
        auto largest = std::max_element(missing.begin(), missing.end(),
                                        [](const Todo& a, const Todo& b) { return a.cells < b.cells; });
        if (opt.verbose) {
            std::cerr << "gen " << root.name() << ": " << missing.size() << " slice(s) to build; largest "
                      << largest->m->name() << " (" << largest->cells << " cells, ~"
                      << gib(plane_ram_bytes(largest->cells)) << " GiB RAM";
            if (avail) std::cerr << "; " << gib(*avail) << " GiB available";
            std::cerr << ")\n";
        }
        if (!opt.force_ram && avail)
            if (auto err = ram_guard_error(largest->m->name(), plane_ram_bytes(largest->cells), *avail))
                throw std::runtime_error(*err);
    }

    std::vector<std::string> written;
    for (auto& m : closure) {
        std::string path = opt.tables_dir + "/" + m.name() + ".hm";
        if (std::filesystem::exists(path)) {
            if (opt.verbose) std::cerr << "cached " << m.name() << " (already on disk)\n";
            continue;
        }
        if (opt.prune) {
            // A slice has no solvable position iff it contains no mate and every
            // successor is itself entirely unsolvable (every solution ends in a
            // mate, in this slice or in one reachable by a capture/promotion).
            bool successors_dead = true;
            for (auto& s : m.successors()) {
                std::string spath = opt.tables_dir + "/" + s.name() + ".hm";
                TableReader::OpenError oerr = TableReader::OpenError::None;
                auto r = TableReader::open(spath, &oerr);
                if (!r && oerr == TableReader::OpenError::UnsupportedVersion)
                    throw std::runtime_error("table " + spath +
                                             " was written by a newer helpmate"
                                             " (unsupported table format version); upgrade this build");
                if (!r) {
                    successors_dead = false;
                    break;
                }
                // Identity check: the file must actually be the table its name promises,
                // or a misnamed/misplaced/stale table would silently feed a wrong prune
                // verdict -- the one correctness-critical decision in the whole prune path.
                SliceIndex si(s);
                if (r->material_name() != s.name())
                    throw std::runtime_error("sub-table " + spath + " is for material '" +
                                             r->material_name() + "', expected '" + s.name() + "'");
                if (r->plane_size() != si.size())
                    throw std::runtime_error("sub-table " + spath + " has plane size " +
                                             std::to_string(r->plane_size()) + ", expected " +
                                             std::to_string(si.size()) + " for " + s.name());
                if (!r->all_unsolvable()) {
                    successors_dead = false;
                    break;
                }
            }
            bool unsolvable = m.mating_side_is_bare_king() || (successors_dead && !slice_has_any_mate(m));
            if (unsolvable) {
                uint64_t ps = SliceIndex(m).size();
                // Same shape as SliceGen::stats_json(): a marker table's reader
                // returns DTM_UNSOLVABLE for every cell (invalid cells included),
                // so reporting all cells as unsolvable and none as invalid is
                // exactly what a consumer reading this table observes.
                nlohmann::json j;
                j["material"] = m.name();
                j["plane_size"] = ps;
                j["max_dtm"] = (int)DTM_UNSOLVABLE;
                j["cells"] = {{"invalid", {{"wtm", 0}, {"btm", 0}}},
                              {"unsolvable", {{"wtm", ps}, {"btm", ps}}}};
                j["dtm_histogram"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
                j["uniqueness"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
                j["deepest"] = nlohmann::json::array();
                j["deepest_unique"] = nlohmann::json::array();
                j["generator_version"] = HELPMATE_VERSION;
                j["all_unsolvable"] = true;
                std::string meta = j.dump(2);
                std::filesystem::create_directories(opt.tables_dir);
                TableWriter::write_unsolvable(path, m, ps, meta);
                std::ofstream(opt.tables_dir + "/" + m.name() + ".stats.json", std::ios::trunc) << meta;
                if (opt.verbose)
                    std::cerr << "pruned " << m.name() << " (provably no helpmate; marker table written)\n";
                written.push_back(path);
                continue;
            }
        }
        uint64_t cells = SliceIndex(m).size();
        // Re-check right before this slice's planes are allocated: available
        // memory shrinks as other processes (or the page cache holding the
        // tables just written) consume it, and the pre-flight only costed the
        // largest slice.
        if (!opt.force_ram)
            if (auto now_avail = mem_available_bytes())
                if (auto err = ram_guard_error(m.name(), plane_ram_bytes(cells), *now_avail))
                    throw std::runtime_error(*err);
        if (opt.verbose) std::cerr << "generating " << m.name() << " (" << cells << " cells)...\n";
        auto t0 = std::chrono::steady_clock::now();
        SliceGen g(m, opt);
        g.run_all_passes();
        g.count_sweep();
        g.finalize_and_write();
        if (opt.verbose) {
            int md = g.max_dtm() < 0 ? (int)DTM_UNSOLVABLE : g.max_dtm();
            std::cerr << "done " << m.name() << " (max_dtm=" << md << ", " << secs_since(t0) << " seconds)\n";
        }
        written.push_back(path);
    }
    return written;
}

}  // namespace hm

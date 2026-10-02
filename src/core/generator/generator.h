#pragma once
#include <cstdint>
#include <map>
#include <nlohmann/json.hpp>
#include <optional>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "chess/board.h"
#include "chess/types.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"

namespace hm {

// A generator lookup hit a position its tables cannot answer. Every throw site attaches the
// material, the FEN of the offending position and (once it has unwound to the cell loop) the
// slice/cell/depth it came from. Before this existed the same conditions surfaced either as a
// bare std::out_of_range("map::at") with no context, or -- worse -- as `*e` on a disengaged
// optional, i.e. UB: a garbage index into a 121 MB plane, which only shows up much later as a
// SIGSEGV somewhere unrelated (typically inside malloc).
struct GeneratorLookupError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// FEN of a decoded piece list, for error messages ("<unavailable>" if it cannot be rendered).
std::string describe_position(const std::vector<PlacedPiece>& pp, Color stm);

struct GenOptions {
    std::string tables_dir = "tables";
    int threads = 1;
    bool verbose = false;    // per-slice lifecycle lines on stderr (implies progress)
    bool progress = false;   // per-pass progress lines on stderr
    bool force_ram = false;  // skip the pre-allocation RAM guard
    bool prune = true;       // skip slices that provably contain no helpmate
    bool compress = false;   // write block-compressed tables (v0.7.5+ readers only)
    uint32_t block_size = kDefaultBlockSize;  // only used when compress is set
};

// ---- RAM guard --------------------------------------------------------------
// generate() refuses to start a slice whose four value planes (dtm/count x
// wtm/btm, one byte per cell each) would not fit in currently-available RAM,
// *before* allocating anything. The decision is a pure function so it is unit-
// testable without a 30 GB box.

// Bytes SliceGen allocates for a slice: 4 planes x plane_size (dtm_[2] + cnt_[2]).
constexpr uint64_t plane_ram_bytes(uint64_t plane_size) { return 4 * plane_size; }

// MemAvailable from /proc/meminfo, in bytes; nullopt if unreadable (then the
// guard is skipped -- better to try than to refuse on an unknown platform).
std::optional<uint64_t> mem_available_bytes();

// Engaged (with a complete, actionable message) iff required > available.
std::optional<std::string> ram_guard_error(const std::string& slice, uint64_t required_bytes,
                                           uint64_t available_bytes);

// Builds the whole closure (missing slices only), root last. Returns paths of written files.
std::vector<std::string> generate(const Material& root, const GenOptions& = {});

// True iff any position in this slice is checkmate (black to move, mated).
// Allocates no value planes: it is the cheap half of init_pass, used to decide
// whether a slice can be pruned before committing to its RAM.
bool slice_has_any_mate(const Material& m);

// Finished successor-slice tables, loaded on demand for cross-slice lookups
// (after a capture / promotion changes the material of a position).
struct SubTables {
    std::map<std::string, std::pair<TableReader, SliceIndex>> t_;
    void load_for(const Material& m, const std::string& dir) {
        for (auto& s : m.successors()) {
            if (t_.count(s.name())) continue;
            std::string path = dir + "/" + s.name() + ".hm";
            TableReader::OpenError oerr = TableReader::OpenError::None;
            auto r = TableReader::open(path, &oerr);
            if (!r && oerr == TableReader::OpenError::UnsupportedVersion)
                throw std::runtime_error("sub-table " + path +
                                         " was written by a newer helpmate"
                                         " (unsupported table format version); upgrade this build");
            if (!r) throw std::runtime_error("missing sub-table " + s.name());
            // Identity check: the file must actually be the table its name promises,
            // or every later lookup would silently index the wrong planes.
            SliceIndex si(s);
            if (r->material_name() != s.name())
                throw std::runtime_error("sub-table " + path + " is for material '" + r->material_name() +
                                         "', expected '" + s.name() + "'");
            if (r->plane_size() != si.size())
                throw std::runtime_error("sub-table " + path + " has plane size " +
                                         std::to_string(r->plane_size()) + ", expected " +
                                         std::to_string(si.size()) + " for " + s.name());
            t_.emplace(s.name(), std::pair(std::move(*r), std::move(si)));
        }
        // Map nodes never move, so these pointers stay valid across later loads.
        by_material_.clear();
        for (auto& [name, table] : t_) {
            Material mat = *Material::parse(name);
            by_material_.push_back({mat.counts(), mat, &table});
        }
    }
    // Each step is checked rather than assumed: only direct successors of the slice being
    // generated are loaded, and encode() is disengaged for positions no slice can hold (e.g.
    // adjacent kings), so an unexpected post-move position must fail loudly and locally.
    ValuePair lookup(const Material& m, const std::vector<PlacedPiece>& pp, Color stm) const {
        return lookup_impl(m, pp, stm, false);
    }

private:
    friend class SliceGen;

    struct Loaded {
        Material::Counts counts;
        Material mat;
        const std::pair<TableReader, SliceIndex>* table;
    };
    // A handful of direct successors: a linear scan beats building m.name()
    // and searching the string-keyed map on every lookup.
    std::vector<Loaded> by_material_;

    // Generator hot path: material arrives packed from Board::pieces(out, counts).
    ValuePair lookup_for_counts(const Material::Counts& c, const std::vector<PlacedPiece>& pp, Color stm) const {
        for (auto& l : by_material_)
            if (l.counts == c) return lookup_in(l, l.mat, pp, stm, true);
        throw_not_loaded(Material::from_counts(c), pp, stm);
    }

    ValuePair lookup_impl(const Material& m, const std::vector<PlacedPiece>& pp, Color stm,
                          bool material_is_known) const {
        for (auto& l : by_material_)
            if (l.mat == m) return lookup_in(l, m, pp, stm, material_is_known);
        throw_not_loaded(m, pp, stm);
    }

    [[noreturn]] static void throw_not_loaded(const Material& m, const std::vector<PlacedPiece>& pp, Color stm) {
        throw GeneratorLookupError("no sub-table loaded for material " + m.name() +
                                   " (only direct successors are loaded); position after move " +
                                   describe_position(pp, stm));
    }

    ValuePair lookup_in(const Loaded& l, const Material& m, const std::vector<PlacedPiece>& pp, Color stm,
                        bool material_is_known) const {
        auto& [rd, si] = *l.table;
        auto e = material_is_known ? si.encode_for_material(pp, m) : si.encode(pp);
        if (!e)
            throw GeneratorLookupError("position not encodable in sub-table " + m.name() +
                                       "; position after move " + describe_position(pp, stm));
        if (*e >= rd.plane_size())
            throw GeneratorLookupError("cell " + std::to_string(*e) + " out of range for sub-table " +
                                       m.name() + " (plane size " + std::to_string(rd.plane_size()) +
                                       "); position after move " + describe_position(pp, stm));
        return rd.get(stm, *e);
    }
};

class SliceGen {  // exposed for tests
public:
    SliceGen(const Material&, const GenOptions&);
    void init_pass();
    bool scan_pass(int d);              // Task 10
    void run_all_passes();              // Task 10: scan until fixed point; sets max_dtm_
    void finalize_and_write();          // Task 10 (stats extended in Task 13)
    nlohmann::json stats_json() const;  // Task 13
    // test accessors:
    const std::vector<uint8_t>& dtm(Color stm) const;
    const std::vector<uint8_t>& cnt(Color stm) const;
    const SliceIndex& index() const;
    int max_dtm() const;

private:
    ValuePair lookup_epless(Board& b, std::vector<PlacedPiece>& piece_scratch);

    Material mat_;
    Material::Counts mat_counts_;
    GenOptions opt_;
    SliceIndex idx_;
    uint64_t ps_;
    std::vector<uint8_t> dtm_[2];
    std::vector<uint8_t> cnt_[2];
    int max_dtm_ = 0;
    SubTables subs_;
};

}  // namespace hm

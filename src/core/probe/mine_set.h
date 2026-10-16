#pragma once
#include <cstdint>
#include <functional>
#include <memory>
#include <nlohmann/json.hpp>
#include <optional>
#include <ostream>
#include <string>
#include <utility>
#include <vector>

#include "indexing/material.h"
#include "probe/tablebase.h"

namespace hm {

// One mined position. dtm/count come from a single probe at load; the
// optionals are filled on demand and cached. `unavailable` non-empty means
// enrichment threw MissingTableError (its text) -- the hit stays in the set,
// never matches a theme or shape narrowing, and says so in every output.
struct Hit {
    std::string fen;
    int dtm = -1, count = -1;
    std::optional<SolutionShape> shape;
    std::optional<std::vector<std::string>> themes;                  // non-parametric names only
    std::optional<std::vector<std::vector<std::string>>> solutions;  // SAN, one vector per solution
    std::string unavailable;
};

// Keeps the entries of a themes_of() result whose registry entry is not
// parametric. Judged by the registry (`param == nullptr`), never by the
// presence of a colon: single-piece:white is a full non-parametric name.
std::vector<std::string> non_parametric(const std::vector<std::string>& names);

// A mine result held in memory: the hits of one scan plus everything that
// can be computed from them without rescanning. Narrowing returns a new set
// so the shell can keep the old one for `back`. A MineSet holds a
// NON-OWNING pointer to the Tablebase it was built from (enrichment probes
// it on demand), which must therefore outlive the set and every set derived
// from it by narrowing.
class MineSet {
public:
    struct Facets {
        bool themes = false;
        bool solutions = false;
    };
    using Progress = std::function<void(size_t done, size_t total)>;

    MineSet(const Tablebase& tb, Material m, MineFilter f, int max);

    void add(const std::string& fen);  // one probe: dtm, count
    void add(Hit h);
    // The probe `add(fen)` does, without storing the hit: the streaming
    // path's building block (`--jsonl` writes a hit as the scan finds it and
    // never holds the set). `enrich` fills what `f` asks for, via the
    // ensure_* below, so a streamed record carries the same fields as a held
    // one.
    Hit make_hit(const std::string& fen) const;
    void enrich(Hit& h, Facets f) const;
    // The same against another Tablebase on the same tables -- a scan
    // worker's, so a streamed hit is probed and enriched where it was found.
    // Safe to call concurrently: they touch only `h` and the given Tablebase.
    Hit make_hit(const Tablebase& tb, const std::string& fen) const;
    void enrich(const Tablebase& tb, Hit& h, Facets f) const;
    const std::vector<Hit>& hits() const { return hits_; }
    // Mutable access to one hit, so a caller can enrich it IN the set (the
    // cache) instead of enriching a copy. Throws std::out_of_range.
    Hit& hit(size_t i);
    size_t size() const { return hits_.size(); }
    const Material& material() const { return m_; }
    const MineFilter& filter() const { return f_; }
    int max() const { return max_; }  // INT_MAX = infinity
    uint64_t skipped_saturated() const { return skipped_; }
    void set_skipped_saturated(uint64_t n) { skipped_ = n; }
    // Enrich on `threads` workers (default 1: on the calling thread, as
    // before). Each worker opens its own Tablebase on the same directory,
    // with an equal share of the set's Tablebase's cache budget, so no lock
    // is shared; the workers are created on first use and kept, by this set
    // and every set derived from it, so their caches stay warm across
    // narrowings. Results do not depend on the thread count.
    void set_threads(int threads);

    // Enrichment: idempotent, cached in the hit. A MissingTableError marks
    // the hit unavailable (its text) instead of propagating; a hit already
    // marked is skipped. Progress, when given, is called with (done, total)
    // over the whole set while hits that need work are processed -- after
    // every one on one thread, periodically on several -- ending with
    // (total, total), and never when there was nothing to do. It always runs
    // on the calling thread.
    void ensure_shape(Hit& h) const;
    void ensure_themes(Hit& h) const;
    void ensure_solutions(Hit& h) const;
    void ensure_themes_all(const Progress& progress = nullptr);
    void ensure_solutions_all(const Progress& progress = nullptr);
    bool all_have_themes() const;
    size_t unavailable_count() const;

    // Narrowing. Each returns a NEW set (same tb/material/filter/max/skipped)
    // holding the hits that match; `this` keeps its hits, now enriched, so
    // the shell's `back` costs nothing. A hit marked unavailable never
    // matches, with or without `negate`. Unknown theme: std::invalid_argument
    // carrying resolve_theme's message.
    MineSet with_theme(const std::string& name, bool negate, const Progress& progress = nullptr);
    MineSet with_count(int n);
    MineSet with_starts(int n);
    MineSet with_ends(int n);

    // (name, hits showing it) for every non-parametric registry theme, in
    // registry order, zeros included. Forces ensure_themes_all.
    std::vector<std::pair<std::string, size_t>> theme_histogram(const Progress& progress = nullptr);

    // Output. Both force whatever enrichment the facets need, hence non-const.
    std::string to_json(Facets f, const Progress& progress = nullptr);
    void to_text(std::ostream& os, Facets f, const Progress& progress = nullptr);
    // JSON Lines: the --json document as one line per object, so a file can
    // be streamed, split, grepped and read back a line at a time. Line 1 is
    // the header (material, filter, max -- the top-level keys minus the
    // array), then one record per hit exactly as --json's positions[] element
    // (a reader tells them apart by the `fen` key), then the footer with the
    // counts ({"positions": N, "skipped_saturated": M}), which a streaming
    // writer only knows at the end -- and whose absence marks a truncated
    // file. to_jsonl writes all three for the held set (forcing enrichment);
    // the three builders let the CLI stream the same bytes without a set.
    std::string jsonl_header() const;
    std::string jsonl_record(const Hit& h, Facets f) const;  // writes what h holds; never enriches
    std::string jsonl_footer(size_t positions) const;
    void to_jsonl(std::ostream& os, Facets f, const Progress& progress = nullptr);
    // One hit's text block exactly as to_text renders it, minus the trailing
    // blank line: FEN, then `  unavailable:` or the requested facets. Writes
    // only what `h` already holds -- it never enriches, so the caller decides
    // (and pays for) that. THE one place the per-hit layout is defined.
    void write_hit(std::ostream& os, const Hit& h, Facets f) const;

private:
    int enum_cap(const Hit& h) const;  // COUNT_SAT -> 100, else the hit's own count
    template <class F>
    void guarded(Hit& h, F&& f) const;  // runs f, marks unavailable on MissingTableError
    // The ensure_* above, against a given Tablebase (a worker's or tb_).
    void shape_on(const Tablebase& tb, Hit& h) const;
    void themes_on(const Tablebase& tb, Hit& h) const;
    void solutions_on(const Tablebase& tb, Hit& h) const;
    // Runs work(tb, index) for every hit index where need(hit) holds, on
    // threads_ workers or inline, with the progress contract described at
    // ensure_themes_all. Each call writes only its own hit (or slot).
    template <class Need, class Work>
    void for_each_needing(Need&& need, Work&& work, const Progress& progress);
    struct Workers;                     // the worker Tablebases; shared by derived sets
    MineSet empty_like() const;         // same tb/material/filter/max/skipped, no hits
    template <class Pred>
    MineSet filtered(Pred&& keep) const;
    void enrich_for(Facets f, const Progress& progress);
    nlohmann::ordered_json header_json() const;                          // material, filter, max
    nlohmann::ordered_json position_json(const Hit& h, Facets f) const;  // THE one --json/--jsonl record

    const Tablebase* tb_;
    Material m_;
    MineFilter f_;
    int max_;
    uint64_t skipped_ = 0;
    std::vector<Hit> hits_;
    int threads_ = 1;
    std::shared_ptr<Workers> workers_;
};

}  // namespace hm

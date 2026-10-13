#pragma once
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <vector>

#include "chess/board.h"
#include "chess/types.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "indexing/slice_index.h"
#include "probe/solution.h"

namespace hm::themes {
struct ResolvedTheme;
struct ThemeInput;
}  // namespace hm::themes

namespace hm {

struct MissingTableError : std::runtime_error { using std::runtime_error::runtime_error; };

// A table file exists but was written by a newer helpmate than this build
// understands (TableReader::OpenError::UnsupportedVersion). Kept distinct from
// MissingTableError so Tablebase::probe can tell "absent, try the color flip"
// apart from "present but unreadable" -- the latter still permits a flip retry,
// but if the flip doesn't pan out either, this is the more informative error
// to surface than a generic "no table" message.
struct UnsupportedTableVersionError : std::runtime_error {
    using std::runtime_error::runtime_error;
};

// Selection criteria for Tablebase::mine. -1 means "don't filter on this".
// Grouped in a struct so later filters (the web dashboard will want more) can
// be added without changing every call site again.
struct MineFilter {
    int dtm    = -1;   // required, exact
    int count  = -1;   // optional, exact
    int starts = -1;   // optional, exact: distinct first moves across optimal lines
    int ends   = -1;   // optional, exact: distinct final (mating) moves
    // Theme names, validated against themes::theme_registry(). A position
    // matches when EVERY listed theme is shown by AT LEAST ONE of its optimal
    // solutions -- `any` within a theme, AND across themes. The two set-wide
    // themes (nocapture, nocheck) are the exception: each holds only when
    // EVERY solution qualifies, which the registry expresses through
    // all_of<> rather than any_of<>, so this loop need not know. An unregistered
    // name throws std::invalid_argument rather than being silently dropped.
    std::vector<std::string> themes;
};

// Shape of a position's optimal-solution set: how many distinct moves the
// solutions start with, and how many distinct moves they mate with.
// `exhaustive` is false when the stored optimal-line count is saturated
// (COUNT_SAT), in which case the solutions cannot be enumerated in full and
// starts/ends carry no meaning.
struct SolutionShape { int starts = 0; int ends = 0; bool exhaustive = true; };

// One legal move from a queried position, with the value of the position it
// leads to. `dtm == -1 && !solvable` covers both "unsolvable" and "no table
// for the resulting material" -- the list is always the complete legal-move
// list, so a caller can render every option.
struct MoveInfo {
    std::string uci;
    std::string san;
    std::string fen;
    int  dtm      = -1;
    int  count    = 0;
    bool solvable = false;
    bool optimal  = false;
};

// Shape of an already-enumerated optimal-line set. `count` is the position's
// stored optimal-line count; when it is saturated (COUNT_SAT) the set cannot be
// complete, so the numbers are meaningless and `exhaustive` is false. Empty
// lines (a position that is already mate) contribute nothing.
// Free function so both branches are unit-testable without a table that
// saturates -- no such position exists in any material generated so far.
SolutionShape shape_of(int count, const std::vector<std::vector<std::string>>& lines);

// Read side of the tablebase: loads generated .hm files on demand (lazily, cached)
// and answers position queries. All public methods are logically const (internal
// cache access is mutex-guarded), so a single Tablebase can be shared/queried
// concurrently from multiple threads.
class Tablebase {
public:
    explicit Tablebase(std::string dir);

    struct Probe { int dtm; int count; bool flipped; };  // flipped: colors were swapped to match a slice

    // nullopt = position is valid but unsolvable. Throws MissingTableError (with the
    // slice names tried) or std::invalid_argument (bad FEN / castling rights).
    std::optional<Probe> probe(const std::string& fen) const;
    // one optimal line, SAN, from `fen` to mate.
    std::vector<std::string> line(const std::string& fen) const;
    // all optimal lines, SAN, capped at `max`.
    std::vector<std::vector<std::string>> lines(const std::string& fen, int max = 100) const;
    // All optimal solutions in structured form, capped at `max`. Same walk and
    // same cap as lines(), but keeping the mover, from/to, captures,
    // promotions and the board after each ply -- everything SAN throws away.
    std::vector<Solution> solutions(const std::string& fen, int max = 100) const;
    // Distinct first/last moves across all optimal lines from `fen`.
    SolutionShape solution_shape(const std::string& fen) const;
    // Every legal move from `fen`, each with the value of the resulting position.
    std::vector<MoveInfo> moves(const std::string& fen) const;
    // stream FENs of canonical cells of material `m` matching `f`; stop as soon as
    // `cb` returns false. When ANY filter that needs the solution set is used --
    // a shape filter (starts/ends) OR a theme filter -- candidates whose solution
    // count is saturated (unenumerable) are skipped and tallied into
    // `skipped_saturated` if non-null; existing callers that omit it are
    // unaffected. Pass it for theme-only queries too, or those positions are
    // dropped with no tally.
    //
    // `threads` > 1 scans the plane in segments on that many workers, each with
    // its own Tablebase (own readers and block caches, so no lock is shared).
    // `cb` still runs only on the calling thread, in cell order, and sees exactly
    // the FENs -- and `skipped_saturated` exactly the tally -- that one thread
    // would give it.
    void mine(const Material& m, const MineFilter& f, const std::function<bool(const std::string&)>& cb,
              uint64_t* skipped_saturated = nullptr, int threads = 1) const;
    // Theme names this position shows. CLI, bindings and API all route here,
    // so they cannot drift apart; the ThemeInput itself is built in exactly
    // one place, with_theme_input (private, below), shared with shows_theme.
    // `max` caps enumeration; -1 means "this position's own solution count".
    std::vector<std::string> themes_of(const std::string& fen, int max) const;
    // Does `fen` show the (possibly parametric) theme `t`? Same ThemeInput
    // as themes_of, so a parametric value such as promotions:qrr is judged by
    // the registry's own eval, never by string-matching themes_of's output.
    bool shows_theme(const std::string& fen, const themes::ResolvedTheme& t, int max) const;
    // sidecar stats content for material `m`; throws MissingTableError if absent.
    std::string stats_json(const Material& m) const;
    // "h#2", "h#1.5", "h#0" style helpmate notation for a dtm/side-to-move pair.
    static std::string h_notation(int dtm, Color stm);

private:
    struct Slice { TableReader reader; SliceIndex index; };
    // The resolved, read-only part of one mine() query, shared by its workers.
    struct MineScan;
    // mine() over cells [begin, end) of the query's slice; false when `cb` stopped it.
    bool mine_range(const MineScan& q, uint64_t begin, uint64_t end,
                    const std::function<bool(const std::string&)>& cb, uint64_t* skipped_saturated) const;
    const Slice* load(const Material& m) const;
    ValuePair value_of(Board& b) const;
    // The slices one search has already looked up, by material. A search
    // visits a handful of materials, so a linear scan without a lock beats
    // load()'s mutex and name-keyed map on every position. The pointers stay
    // valid: cache_ never drops an entry while this Tablebase lives.
    struct SliceMemo {
        std::vector<std::pair<Material, const Slice*>> slices;
    };
    // value_of(b).dtm without reading any count byte; the line searches use
    // only the DTM.
    uint8_t dtm_of(Board& b, SliceMemo& memo) const;
    void collect_lines(Board& b, std::vector<std::string>& path, std::vector<std::vector<std::string>>& out,
                       int max, SliceMemo& memo) const;
    void collect_solutions(Board& b, std::vector<Ply>& path, std::vector<Solution>& out, const Board& start,
                           int max, SliceMemo& memo) const;
    std::vector<std::vector<std::string>> lines(const std::string& fen, int max, SliceMemo& memo) const;
    std::vector<Solution> solutions(const std::string& fen, int max, SliceMemo& memo) const;
    // THE one place a ThemeInput is built (themes_of and shows_theme both
    // route here). `use` runs while the input's referents are alive.
    void with_theme_input(const std::string& fen, int max,
                          const std::function<void(const themes::ThemeInput&)>& use) const;

    std::string dir_;
    mutable std::mutex mu_;
    mutable std::map<std::string, std::unique_ptr<Slice>> cache_;
};

}  // namespace hm

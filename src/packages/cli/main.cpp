#include <algorithm>
#include <chrono>
#include <climits>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <nlohmann/json.hpp>
#include <set>
#include <string>
#include <vector>
#ifdef __GLIBC__     // defined by any libc header above
#include <malloc.h>  // mallopt(M_TOP_PAD) in cmd_mine
#endif

#include "format/table_file.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "probe/mine_set.h"
#include "probe/mine_shell.h"
#include "probe/tablebase.h"
#include "themes/registry.h"
#include "version.h"

using namespace hm;

namespace {

void usage() {
    std::cerr << "helpmate - build and query helpmate chess tablebases\n"
                 "\n"
                 "Usage:\n"
                 "  helpmate gen <MATERIAL> [--tables DIR] [--threads N] [--verbose]\n"
                 "               [--progress] [--force-ram] [--compress] [--block-size N]\n"
                 "  helpmate probe <FEN> [--tables DIR]\n"
                 "  helpmate line <FEN> [--tables DIR] [--all] [--max N]\n"
                 "  helpmate stats [MATERIAL] [--tables DIR]\n"
                 "  helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N]\n"
                 "                           [--theme NAME]... [--themes] [--solutions] [--json|--jsonl]\n"
                 "                           [--interactive] [--max N|infinity] [--tables DIR]\n"
                 "                           [--threads N] [--cache-mb N]\n"
                 "  helpmate themes\n"
                 "  helpmate compact <DIR> [--dry-run] [--compress] [--block-size N]\n"
                 "  helpmate --version\n"
                 "\n"
                 "MATERIAL is a canonical piece string, e.g. \"KQvk\" (White king+queen vs\n"
                 "black king) or \"KBNvkq\". FEN is standard 6-field notation; castling\n"
                 "rights must be \"-\" (this engine has no castling).\n"
                 "\n"
                 "Commands:\n"
                 "  gen    Generate every table needed to answer queries about MATERIAL\n"
                 "         (including sub-slices reached by captures/promotions), writing\n"
                 "         one <name>.hm file plus a <name>.stats.json sidecar per slice\n"
                 "         into --tables DIR. Existing files are left alone (re-run is\n"
                 "         cheap after adding a new root material).\n"
                 "  probe  Look up one position: distance-to-mate (dtm), helpmate notation\n"
                 "         (h#N / h#N.5), and how many optimal replies tie for best.\n"
                 "  line   Print one optimal mating line from FEN as SAN moves. With\n"
                 "         --all, print every optimal line (one per output line), capped\n"
                 "         at --max.\n"
                 "  stats  With MATERIAL, print its generation-time statistics JSON (cell\n"
                 "         counts, dtm histogram, deepest positions, ...). With no\n"
                 "         MATERIAL, print a summary of every table in --tables DIR:\n"
                 "         formats and sizes, cell breakdown, deepest mate, largest\n"
                 "         tables.\n"
                 "  mine   Print positions in MATERIAL matching --dtm exactly (and, if given,\n"
                 "         --count/--starts/--ends/--theme), up to --max, one FEN per line.\n"
                 "         --themes adds every theme each position shows, --solutions every\n"
                 "         optimal solution, --json (--jsonl) emits JSON (JSON Lines) instead of text,\n"
                 "         --interactive opens a shell over the result (see docs/USAGE.md).\n"
                 "  themes List every theme detector this build knows, each with the\n"
                 "         definition it uses. These names are what --theme accepts.\n"
                 "  compact Rewrite every .hm table in DIR whose cells are all\n"
                 "         unsolvable (or invalid) as a tiny marker file, reclaiming\n"
                 "         disk space. Tables with any solvable cell are left\n"
                 "         untouched. --dry-run reports what would be rewritten\n"
                 "         without writing anything. --compress instead rewrites\n"
                 "         raw tables as block-compressed (see --compress below).\n"
                 "\n"
                 "Options:\n"
                 "  --tables DIR   table directory (default: \"tables\")\n"
                 "  --threads N    worker threads for gen and mine (default: 1); mine's\n"
                 "                 output is identical for every N\n"
                 "  --cache-mb N   mine: total memory for decompressed table blocks, shared\n"
                 "                 by all tables and threads (default: up to 64 MiB per\n"
                 "                 table and thread)\n"
                 "  --verbose      gen: per-slice lifecycle lines on stderr (closure\n"
                 "                 summary, generating/cached/done per slice); implies\n"
                 "                 --progress. stdout stays scriptable.\n"
                 "  --progress     gen: per-pass progress lines on stderr while a slice\n"
                 "                 is being generated (init pass, each scan pass with\n"
                 "                 cells resolved, each count-sweep depth, with timings)\n"
                 "  --force-ram    gen: skip the RAM guard (which refuses to start a\n"
                 "                 slice whose planes exceed available memory)\n"
                 "  --compress     gen: write block-compressed tables (v0.7.5+ readers only)\n"
                 "                 compact: rewrite existing tables as block-compressed\n"
                 "  --block-size N gen/compact --compress: block size in KiB (default 64,\n"
                 "                 i.e. 64 KiB; see docs/USAGE.md for the measured\n"
                 "                 ratio/speed trade-off at other sizes).\n"
                 "                 Must be >= 4 (4 KiB) and <= 16384 (16 MiB). compact\n"
                 "                 --compress can re-block an already-compressed table to a\n"
                 "                 new size in place, without regenerating it.\n"
                 "  --all          line: print every optimal line, not just one\n"
                 "  --max N        cap on lines/FENs printed (default: 10); \"infinity\" or\n"
                 "                 \"inf\" for no cap\n"
                 "  --dtm D        mine: required, exact distance-to-mate to match\n"
                 "  --count C      mine: optional, exact optimal-reply count to match\n"
                 "  --starts N     mine: optional, exact number of distinct first moves across\n"
                 "                 the optimal solutions (must be >= 1, and <= --count if given)\n"
                 "  --ends N       mine: optional, exact number of distinct mating moves\n"
                 "  --theme NAME   mine: only positions where at least one optimal solution\n"
                 "                 shows theme NAME (nocapture and nocheck: where EVERY\n"
                 "                 optimal solution does). Repeatable; every named theme must\n"
                 "                 be present, though not necessarily in the same solution.\n"
                 "                 A parametric theme takes a value: --theme promotions:qrr\n"
                 "                 `helpmate themes` lists the names and their definitions.\n"
                 "  --themes       probe: also print the themes the position's solutions show\n"
                 "                 mine: annotate every hit with all (non-parametric) themes\n"
                 "  --solutions    mine: print every optimal solution of each hit (SAN)\n"
                 "  --json         mine: one JSON document (material, filter, positions[])\n"
                 "  --jsonl        mine: JSON Lines -- a header line, one object per position\n"
                 "                 streamed as found, a footer line with the counts\n"
                 "  --interactive  mine: after the scan, a shell to narrow/inspect/save the\n"
                 "                 result without rescanning (--tui is an alias)\n"
                 "  --dry-run      compact: report what would be rewritten, write nothing\n"
                 "  --version      print version (\"helpmate "
              << HELPMATE_VERSION
              << "\") and exit\n"
                 "\n"
                 "Examples:\n"
                 "  helpmate gen KQvk --tables tt\n"
                 "  helpmate probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt\n"
                 "  helpmate line  \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --tables tt --all\n"
                 "  helpmate stats KQvk --tables tt\n"
                 "  helpmate stats --tables tt\n"
                 "  helpmate mine KQvk --dtm 2 --count 1 --max 5 --tables tt\n"
                 "  helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --tables tt\n"
                 "  helpmate mine KQvk --dtm 2 --theme mirror --max 5 --tables tt\n"
                 "  helpmate probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --themes --tables tt\n"
                 "  helpmate mine KQvk --dtm 2 --max infinity --json --themes --tables tt\n"
                 "  helpmate mine KQvk --dtm 4 --max 5000 --interactive --tables tt\n"
                 "\n"
                 "Exit codes: 0 success (an \"unsolvable\" answer is still success), 2 a\n"
                 "table needed to answer the query is missing (message says which one and\n"
                 "how to build it), 3 bad usage or unparseable input.\n";
}

// Side to move, read straight from the FEN's 2nd field ("w"/"b"); only called
// after the FEN has already been accepted by the API, so it is well-formed.
Color stm_of(const std::string& fen) {
    auto sp1 = fen.find(' ');
    if (sp1 == std::string::npos) return Color::White;
    return fen[sp1 + 1] == 'b' ? Color::Black : Color::White;
}

void print_line(const std::vector<std::string>& moves) {
    for (size_t i = 0; i < moves.size(); ++i) std::cout << (i ? " " : "") << moves[i];
    std::cout << "\n";
}

// Parses `value` as an integer; never throws -- malformed input ("abc") and
// out-of-range input (overflowing int) both just return false, so the caller
// can print one clear, actionable message instead of an uncaught
// std::invalid_argument/std::out_of_range crashing the process.
bool parse_int(const std::string& value, int& out) {
    try {
        size_t used = 0;
        long v = std::stol(value, &used);
        if (used != value.size() || v < INT_MIN || v > INT_MAX) return false;
        out = (int)v;
        return true;
    } catch (const std::exception&) { return false; }
}

int cmd_gen(const std::vector<std::string>& pos, const std::string& tables, int threads, bool verbose,
            bool progress, bool force_ram, bool compress, uint32_t block_size) {
    if (pos.empty()) {
        std::cerr << "error: gen needs a MATERIAL argument (e.g. KQvk)\n\n";
        usage();
        return 3;
    }
    auto m = Material::parse(pos[0]);
    if (!m) {
        std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n";
        return 3;
    }
    GenOptions opt;
    opt.tables_dir = tables;
    opt.threads = threads;
    opt.verbose = verbose;
    opt.progress = progress;
    opt.force_ram = force_ram;
    opt.compress = compress;
    opt.block_size = block_size;
    auto written = generate(*m, opt);
    if (written.empty())
        std::cout << "nothing to do: all tables for " << m->name() << " already exist in " << tables << "\n";
    for (auto& path : written) {
        std::cout << path;
        if (auto r = TableReader::open(path)) std::cout << " max_dtm=" << (int)r->max_dtm();
        std::cout << "\n";
    }
    return 0;
}

int cmd_probe(const std::vector<std::string>& pos, const std::string& tables, bool show_themes) {
    if (pos.empty()) {
        std::cerr << "error: probe needs a FEN argument\n\n";
        usage();
        return 3;
    }
    Tablebase tb(tables);
    auto p = tb.probe(pos[0]);
    if (!p) {
        std::cout << "unsolvable\n";
        return 0;
    }
    std::cout << "dtm=" << p->dtm << " (" << Tablebase::h_notation(p->dtm, stm_of(pos[0]))
              << (p->flipped ? ", colors flipped" : "") << ") count=" << p->count << "\n";
    if (show_themes) {
        if (p->flipped) {
            // tb.solutions(pos[0], ...) walks the position AS QUERIED. When probe
            // only found an answer by color-flipping to the OTHER material, that
            // material's table cannot answer a solutions() walk of the original
            // (unflipped) FEN -- it throws MissingTableError, turning a working
            // probe into a half-printed answer plus exit 2. Flipping the position
            // ourselves and detecting on THAT is not a fix either: the mate
            // detectors are hard-coded to the black king, so pure/model/ideal/
            // mirror would survive the flip unchanged but the colour-labelled
            // ones (single-piece:white/:black, excelsior:white/:black) would
            // come out swapped -- a wrong answer dressed as a right one.
            //
            // The stdout line matters as much as the note: without it,
            // `probe FEN --themes 2>/dev/null | grep '^themes:'` yields nothing
            // at exit 0, which a script cannot tell apart from a position that
            // genuinely has no themes (that case prints "themes: (none)").
            std::cout << "themes: (unavailable: colors were flipped to find a table)\n";
            std::cerr << "note: themes are unavailable for a color-flipped probe. The mate "
                         "detectors are hard-coded to the black king, so the colour-labelled "
                         "themes would come out swapped. Re-run with the colours of the "
                         "position exchanged to get a correct answer.\n";
        } else {
            // Detection forces solution enumeration, so it stays opt-in: a plain
            // probe must not start paying for a field most callers never read.
            try {
                auto names = tb.themes_of(pos[0], p->count >= (int)COUNT_SAT ? 100 : p->count);
                std::cout << "themes:";
                if (names.empty()) std::cout << " (none)";
                for (const auto& n : names) std::cout << " " << n;
                std::cout << "\n";
                if (p->count >= (int)COUNT_SAT)
                    std::cerr << "note: this position's solution count is saturated (255+); themes were "
                                 "detected from the first 100 solutions only\n";
            } catch (const MissingTableError& e) {
                // solutions() walks every legal child move, including captures
                // and promotions into material this --tables directory
                // doesn't have -- routine with a partial (e.g. on-demand HF)
                // table set. dtm=.../count=... is already on stdout above:
                // letting this propagate past main()'s MissingTableError
                // handler would be the exact "half-printed answer plus exit
                // 2" the flip branch's comment above exists to prevent, just
                // reached from a different cause. Same fix: stay exit 0,
                // finish the answer with a clear note instead of throwing.
                std::cout << "themes: (unavailable: " << e.what() << ")\n";
                std::cerr << "note: themes could not be detected: " << e.what()
                          << "\nrun: helpmate gen "
                             "<MATERIAL> --tables "
                          << tables << "\n";
            }
        }
    }
    return 0;
}

int cmd_line(const std::vector<std::string>& pos, const std::string& tables, bool all, int maxn) {
    if (pos.empty()) {
        std::cerr << "error: line needs a FEN argument\n\n";
        usage();
        return 3;
    }
    Tablebase tb(tables);
    if (all) {
        auto ls = tb.lines(pos[0], maxn);
        // ls == {} means unsolvable; ls == {{}} (one *empty* line) means the
        // position is already checkmate (dtm==0) -- both print nothing
        // useful move-wise, so give the same message the non---all branch
        // gives instead of silently printing a blank line.
        if (ls.empty() || ls[0].empty()) {
            std::cout << "unsolvable (or already mate: no line to print)\n";
            return 0;
        }
        for (auto& l : ls) print_line(l);
    } else {
        auto l = tb.line(pos[0]);
        if (l.empty()) {
            std::cout << "unsolvable (or already mate: no line to print)\n";
            return 0;
        }
        print_line(l);
    }
    return 0;
}

// One row of the corpus summary. Header fields come from the .hm itself; the
// cell breakdown comes from the <Material>.stats.json sidecar, which is
// generation-time truth and cheap to read. A table with no sidecar still
// contributes its size and format -- it just cannot contribute cell counts,
// and the summary says how many such tables it found rather than quietly
// reporting a smaller corpus.
static std::string human_bytes(uint64_t n);  // defined with the compact commands below

// Cell counts here run to eleven digits; unseparated they are unreadable.
static std::string group(uint64_t n) {
    std::string s = std::to_string(n), out;
    int c = 0;
    for (int i = (int)s.size() - 1; i >= 0; --i) {
        out.push_back(s[(size_t)i]);
        if (++c % 3 == 0 && i) out.push_back(',');
    }
    std::reverse(out.begin(), out.end());
    return out;
}

static std::string pct_of(uint64_t part, uint64_t whole) {
    char b[32];
    std::snprintf(b, sizeof b, "%.1f%%", whole ? 100.0 * double(part) / double(whole) : 0.0);
    return b;
}

static std::string ratio_x(uint64_t from, uint64_t to) {
    char b[32];
    std::snprintf(b, sizeof b, "%.2fx", to ? double(from) / double(to) : 0.0);
    return b;
}

struct CorpusEntry {
    std::string stem;
    int pieces = 0;
    bool marker = false;
    bool compressed = false;
    uint32_t block_size = 0;
    uint64_t plane_size = 0;
    int max_dtm = -1;  // -1 when nothing is solvable
    uint64_t file_bytes = 0;
    bool has_sidecar = false;
    uint64_t invalid = 0, unsolvable = 0, solvable = 0, unique = 0;
    std::string generator_version;
};

static int piece_count(const std::string& material) {
    int n = 0;
    for (char c : material)
        if (c != 'v') ++n;
    return n;
}

static int cmd_stats_corpus(const std::string& tables) {
    namespace fs = std::filesystem;
    if (!fs::is_directory(tables)) {
        std::cerr << "error: not a directory: " << tables << "\n";
        return 3;
    }
    std::vector<CorpusEntry> es;
    int unreadable = 0, future = 0;
    for (auto& e : fs::directory_iterator(tables)) {
        if (e.path().extension() != ".hm") continue;
        TableReader::OpenError oe = TableReader::OpenError::None;
        auto r = TableReader::open(e.path().string(), &oe);
        if (!r) {
            if (oe == TableReader::OpenError::UnsupportedVersion) ++future;
            else ++unreadable;
            continue;
        }
        CorpusEntry c;
        c.stem = e.path().stem().string();
        c.pieces = piece_count(r->material_name());
        c.marker = r->all_unsolvable();
        c.compressed = r->is_compressed();
        c.block_size = r->block_size();
        c.plane_size = r->plane_size();
        c.max_dtm = r->max_dtm() > DTM_MAX ? -1 : (int)r->max_dtm();
        c.file_bytes = fs::file_size(e.path());

        std::ifstream sc(tables + "/" + c.stem + ".stats.json");
        if (sc) {
            try {
                nlohmann::json j;
                sc >> j;
                c.has_sidecar = true;
                c.generator_version = j.value("generator_version", "");
                for (const char* side : {"wtm", "btm"}) {
                    c.invalid += j["cells"]["invalid"].value(side, 0ull);
                    c.unsolvable += j["cells"]["unsolvable"].value(side, 0ull);
                    for (auto& [dtm, hist] : j["uniqueness"][side].items()) c.unique += hist.value("1", 0ull);
                }
                c.solvable = 2 * c.plane_size - c.invalid - c.unsolvable;
            } catch (const std::exception&) {
                c.has_sidecar = false;  // a malformed sidecar is a missing one
            }
        }
        es.push_back(std::move(c));
    }
    if (es.empty()) {
        std::cerr << "error: no readable .hm tables in " << tables << "\n";
        return 3;
    }
    std::sort(es.begin(), es.end(),
              [](const CorpusEntry& a, const CorpusEntry& b) { return a.file_bytes > b.file_bytes; });

    int tables_n = 0, markers_n = 0, comp_n = 0, raw_n = 0, no_sidecar = 0;
    uint64_t bytes = 0, logical = 0, comp_bytes = 0, comp_logical = 0;
    uint64_t cells = 0, invalid = 0, unsolvable = 0, solvable = 0, unique = 0;
    std::map<int, int> by_pieces;
    std::map<uint32_t, int> by_block;
    std::set<std::string> gens;
    int deepest = -1;
    std::string deepest_material;
    for (const auto& c : es) {
        bytes += c.file_bytes;
        by_pieces[c.pieces]++;
        if (c.marker) {
            ++markers_n;
        } else {
            ++tables_n;
            logical += 4 * c.plane_size;
            if (c.compressed) {
                ++comp_n;
                by_block[c.block_size]++;
                comp_bytes += c.file_bytes;
                comp_logical += 4 * c.plane_size;
            } else {
                ++raw_n;
            }
        }
        if (c.has_sidecar) {
            cells += 2 * c.plane_size;
            invalid += c.invalid;
            unsolvable += c.unsolvable;
            solvable += c.solvable;
            unique += c.unique;
            if (!c.generator_version.empty()) gens.insert(c.generator_version);
        } else if (!c.marker) {
            ++no_sidecar;
        }
        if (c.max_dtm > deepest) {
            deepest = c.max_dtm;
            deepest_material = c.stem;
        }
    }

    std::cout << tables << "\n\n";
    std::cout << "Files\n";
    std::cout << "  " << es.size() << " readable .hm: " << tables_n << " table(s), " << markers_n
              << " all-unsolvable marker(s)\n";
    std::cout << "  format: " << comp_n << " block-compressed (v3)";
    for (auto& [bs, n] : by_block) std::cout << " [" << n << " at " << bs / 1024 << " KiB]";
    std::cout << ", " << raw_n << " raw (v1)\n";
    std::cout << "  on disk: " << human_bytes(bytes) << "\n";
    if (comp_logical) {
        std::cout << "  compressed tables: " << human_bytes(comp_bytes) << " on disk from "
                  << human_bytes(comp_logical) << " of planes (" << ratio_x(comp_logical, comp_bytes)
                  << ")\n";
    }
    if (raw_n) {
        std::cout << "  " << raw_n << " raw table(s) could be compressed"
                  << " -- see tools/compress-corpus.sh\n";
    }
    std::cout << "  by piece count:";
    for (auto& [p, n] : by_pieces) std::cout << "  " << p << ":" << n;
    std::cout << "\n";
    if (future) std::cout << "  " << future << " written by a newer helpmate (upgrade this build)\n";
    if (unreadable) std::cout << "  " << unreadable << " unreadable\n";

    std::cout << "\nPositions (from " << (es.size() - no_sidecar - unreadable - future) << " sidecar(s)";
    if (no_sidecar) std::cout << "; " << no_sidecar << " table(s) have none, excluded";
    std::cout << ")\n";
    auto row = [](const char* label, uint64_t n, const std::string& of) {
        char buf[128];
        std::snprintf(buf, sizeof buf, "  %-22s %18s  %7s\n", label, group(n).c_str(), of.c_str());
        std::cout << buf;
    };
    row("plane cells", cells, "");
    row("invalid", invalid, pct_of(invalid, cells));
    row("unsolvable", unsolvable, pct_of(unsolvable, cells));
    row("solvable", solvable, pct_of(solvable, cells));
    row("unique (count==1)", unique, pct_of(unique, solvable));
    std::cout << "  (percentages are of plane cells, except unique, which is of solvable)\n";

    std::cout << "\nMate length\n";
    if (deepest >= 0) {
        std::cout << "  deepest: dtm " << deepest << " ("
                  << Tablebase::h_notation((uint8_t)deepest, deepest % 2 ? Color::White : Color::Black)
                  << ") in " << deepest_material << "\n";
    } else {
        std::cout << "  no solvable position in any table\n";
    }

    std::cout << "\nLargest tables\n";
    for (size_t i = 0; i < es.size() && i < 5; ++i) {
        std::cout << "  " << es[i].stem << "  " << human_bytes(es[i].file_bytes);
        if (es[i].compressed) std::cout << "  (compressed, " << es[i].block_size / 1024 << " KiB blocks)";
        else if (es[i].marker) std::cout << "  (marker)";
        else std::cout << "  (raw)";
        std::cout << "\n";
    }
    if (!gens.empty()) {
        std::cout << "\nGenerated by:";
        for (const auto& g : gens) std::cout << " " << g;
        std::cout << "\n";
    }
    return 0;
}

int cmd_stats(const std::vector<std::string>& pos, const std::string& tables) {
    if (pos.empty()) return cmd_stats_corpus(tables);
    auto m = Material::parse(pos[0]);
    if (!m) {
        std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n";
        return 3;
    }
    Tablebase tb(tables);
    std::cout << tb.stats_json(*m) << "\n";
    return 0;
}

// What `mine` should print, beyond the bare FEN list: mutually-compatible
// output-mode flags parsed by main() and passed straight through.
struct MineOutput {
    bool json = false, jsonl = false, themes = false, solutions = false, interactive = false;
    bool wants_set() const { return json || jsonl || themes || solutions || interactive; }
};

void note_skipped(uint64_t skipped) {
    std::cerr << "note: skipped " << skipped
              << " position(s) whose solution count is saturated (255+): their"
                 " solutions cannot be enumerated exhaustively\n";
}

int cmd_mine(const std::vector<std::string>& pos, const std::string& tables, int dtm, int count, int maxn,
             int starts, int ends, bool starts_given, bool ends_given,
             const std::vector<std::string>& theme_names, const MineOutput& out, int threads, int cache_mb) {
    if (pos.empty()) {
        std::cerr << "error: mine needs a MATERIAL argument (e.g. KQvk)\n\n";
        usage();
        return 3;
    }
    if (pos.size() > 1) {
        // A stray extra positional used to be silently ignored (mine only ever
        // read pos[0]) -- the same class of bug as a discarded --theme/--themes
        // typo above: something the user typed changes nothing about what gets
        // printed, with no indication anything was dropped.
        std::cerr << "error: mine takes exactly one MATERIAL argument; unexpected extra argument(s):";
        for (size_t i = 1; i < pos.size(); ++i) std::cerr << " \"" << pos[i] << "\"";
        std::cerr << "\n\n";
        usage();
        return 3;
    }
    if (dtm < 0) {
        std::cerr << "error: mine requires --dtm D\n\n";
        usage();
        return 3;
    }
    for (auto [flag, val, given, noun] : {std::tuple{"--starts", starts, starts_given, "first moves"},
                                          std::tuple{"--ends", ends, ends_given, "mating moves"}}) {
        if (!given)
            continue;  // not given; -1 is a value the
                       // user CAN type, not the sentinel
        if (val < 1) {
            std::cerr << "error: " << flag << " must be at least 1\n";
            return 3;
        }
        if (count >= 0 && val > count) {
            std::cerr << "error: " << flag << " " << val << " cannot exceed --count " << count
                      << " (a position with " << count << " solution(s) has at most " << count << " distinct "
                      << noun << ")\n";
            return 3;
        }
    }
    for (const auto& n : theme_names) {
        std::string err;
        if (themes::resolve_theme(n, &err)) continue;
        std::cerr << "error: " << err << "\nvalid themes:";
        for (const auto& t : themes::theme_registry()) std::cerr << " " << themes::display_name(t);
        std::cerr << "\nrun: helpmate themes    (for what each one means)\n";
        return 3;
    }
    auto m = Material::parse(pos[0]);
    if (!m) {
        std::cerr << "error: not a valid material string: \"" << pos[0] << "\"\n";
        return 3;
    }
    // A mine scan's workers allocate their decompressed blocks (up to the
    // whole --cache-mb budget) while they run. glibc grows each thread's heap
    // a page range at a time with mprotect(), which serializes against the
    // other threads' page faults: at 16 threads and --cache-mb 8192 that was
    // 1.2 million voluntary context switches and 45 s instead of 23 s. Growing
    // by a whole 64 MiB thread heap at once removes it; the reserve is only
    // address space until a block is written into it.
#ifdef __GLIBC__
    mallopt(M_TOP_PAD, 64 << 20);
#endif
    // --cache-mb: one block-cache budget for the whole scan, split among
    // the workers; without it each table keeps its own cache per worker.
    Tablebase tb(tables, cache_mb > 0 ? static_cast<size_t>(cache_mb) << 20 : 0);
    MineFilter filter{.dtm = dtm, .count = count, .starts = starts, .ends = ends, .themes = theme_names};
    uint64_t skipped = 0;
    if (!out.wants_set()) {
        // Streaming path, byte-identical to every release before 0.18.0.
        int printed = 0;
        tb.mine(
            *m, filter,
            [&](const std::string& fen) {
                if (printed >= maxn) return false;  // handles --max 0
                std::cout << fen << "\n";
                ++printed;
                return printed < maxn;
            },
            &skipped, threads);
        if (skipped) note_skipped(skipped);
        return 0;
    }
    MineSet set(tb, *m, filter, maxn);
    MineSet::Facets facets{out.themes, out.solutions};
    if (out.jsonl && !out.interactive) {
        // JSON Lines streams: header, then each hit the moment the scan finds
        // it (probed and enriched, never stored), then the footer with the
        // counts only the end of the scan knows. Memory stays O(1) in hits,
        // which is the whole point of the format on a --max infinity scan.
        std::cout << set.jsonl_header();
        size_t n = 0, unavailable = 0;
        if (maxn > 0)
            tb.mine(
                *m, filter,
                [&](const std::string& fen) {
                    Hit h = set.make_hit(fen);
                    set.enrich(h, facets);
                    if (!h.unavailable.empty()) ++unavailable;
                    std::cout << set.jsonl_record(h, facets);
                    ++n;
                    return (int)n < maxn;
                },
                &skipped, threads);
        set.set_skipped_saturated(skipped);
        std::cout << set.jsonl_footer(n);
        if (skipped) note_skipped(skipped);
        if (unavailable)
            std::cerr << "note: " << unavailable
                      << " position(s) could not be annotated: a table their solutions reach is missing from "
                      << tables << " (each says which); run: helpmate gen " << pos[0] << " --tables "
                      << tables << "\n";
        return 0;
    }
    if (maxn > 0)
        tb.mine(
            *m, filter,
            [&](const std::string& fen) {
                set.add(fen);
                return (int)set.size() < maxn;
            },
            &skipped, threads);
    set.set_skipped_saturated(skipped);
    if (skipped) note_skipped(skipped);
    // Every 100 hits OR every second, per the spec, and worded exactly as the
    // shell words it: 100 alone goes quiet for minutes on slow enrichment.
    auto last_tick = std::chrono::steady_clock::now();
    auto progress = [&last_tick](size_t done, size_t total) {
        auto now = std::chrono::steady_clock::now();
        if (done % 100 != 0 && now - last_tick < std::chrono::seconds(1)) return;
        last_tick = now;
        std::cerr << "evaluating: " << done << "/" << total << "\n";
    };
    if (out.interactive) {
        std::cerr << "loaded " << set.size() << " positions (" << m->name() << " dtm=" << dtm << ")\n";
        return run_mine_shell(std::move(set), std::cin, std::cout, std::cerr, facets, tables);
    }
    if (out.json) std::cout << set.to_json(facets, progress);
    else if (out.jsonl) set.to_jsonl(std::cout, facets, progress);  // unreachable: streamed above
    else set.to_text(std::cout, facets, progress);
    if (set.unavailable_count())
        std::cerr << "note: " << set.unavailable_count()
                  << " position(s) could not be annotated: a table their solutions reach is missing from "
                  << tables << " (each says which); run: helpmate gen " << pos[0] << " --tables " << tables
                  << "\n";
    return 0;
}

// Integer MiB truncates a 146 KB -> 71 KB conversion to "0 MiB -> 0 MiB",
// which reads as "nothing happened" for work that did happen. Pick a unit
// that keeps one significant figure for the value at hand.
static std::string human_bytes(uint64_t n) {
    char buf[32];
    if (n >= 1024ull * 1024 * 1024)
        std::snprintf(buf, sizeof buf, "%.2f GiB", double(n) / (1024.0 * 1024 * 1024));
    else if (n >= 1024ull * 1024) std::snprintf(buf, sizeof buf, "%.1f MiB", double(n) / (1024.0 * 1024));
    else if (n >= 1024ull) std::snprintf(buf, sizeof buf, "%.1f KiB", double(n) / 1024.0);
    else std::snprintf(buf, sizeof buf, "%llu B", (unsigned long long)n);
    return buf;
}

// helpmate compact <DIR> --compress [--dry-run] [--block-size N]
// Rewrites every RAW .hm in DIR as block-compressed, streaming off the
// source table's mapping at constant memory (TableWriter::compress_existing)
// rather than buffering the four planes -- see compress_existing's doc
// comment in table_file.h for why that distinction matters (31 GB for a
// six-piece table if it were buffered). Also re-blocks an already-compressed
// table found at a different block size than requested (TableWriter::
// compress_existing now supports that via TableReader::read_range, which
// works for compressed sources too -- see its doc comment in table_file.h),
// so a tunable block size never becomes a "regenerate from scratch" trap.
int cmd_compact_compress(const std::string& dir, bool dry, uint32_t block_size) {
    int compressed_new = 0, would_compress_new = 0;
    int reblocked = 0, would_reblock = 0;
    int already = 0, markers = 0, skipped_recent = 0;
    uint64_t bytes_before = 0, bytes_after = 0;
    for (auto& e : std::filesystem::directory_iterator(dir)) {
        if (e.path().extension() != ".hm") continue;

        // Skip anything written in the last hour: a long generation run may be
        // active in this directory, and rewriting a table mid-write would
        // corrupt it. This check comes before the file is even opened.
        auto age = std::filesystem::file_time_type::clock::now() - std::filesystem::last_write_time(e.path());
        if (age < std::chrono::hours(1)) {
            ++skipped_recent;
            continue;
        }

        TableReader::OpenError oe = TableReader::OpenError::None;
        auto r = TableReader::open(e.path().string(), &oe);
        if (!r && oe == TableReader::OpenError::UnsupportedVersion) {
            std::cerr << "error: table " << e.path()
                      << " was written by a newer helpmate"
                         " (unsupported table format version); upgrade this build\n";
            return 3;
        }
        if (!r) {
            std::cerr << "error: unreadable table " << e.path() << "\n";
            return 3;
        }
        if (r->all_unsolvable()) {
            ++markers;
            continue;
        }  // nothing to compress

        // A compressed table already at the requested block size is a true
        // no-op -- re-writing it would burn a full decompress+recompress
        // pass to produce byte-for-byte the same blocks. Only a DIFFERENT
        // block size is worth touching.
        bool reblock = false;
        if (r->is_compressed()) {
            if (r->block_size() == block_size) {
                ++already;
                continue;
            }
            reblock = true;
        }

        std::string name = r->material_name();
        std::string stem = e.path().stem().string();
        // Same identity check as the marker-compaction path below: keyed off
        // the file's own name, not the header's self-reported material.
        if (name != stem) {
            std::cerr << "error: table " << e.path() << " is for material '" << name << "', expected '"
                      << stem << "' from filename; refusing to touch it\n";
            return 3;
        }

        uint64_t size_before = std::filesystem::file_size(e.path());
        if (dry) {
            if (reblock) {
                std::cout << "would re-block " << name << " (" << human_bytes(size_before) << ", "
                          << (r->block_size() / 1024) << " KiB -> " << (block_size / 1024) << " KiB)\n";
                ++would_reblock;
            } else {
                std::cout << "would compress " << name << " (" << human_bytes(size_before) << ")\n";
                ++would_compress_new;
            }
            bytes_before += size_before;
            continue;
        }

        TableWriter::compress_existing(e.path().string(), *r, block_size);
        r.reset();  // unmap the source mapping only after the rename completes
        uint64_t size_after = std::filesystem::file_size(e.path());
        std::cout << (reblock ? "re-blocked " : "compressed ") << name << " (" << human_bytes(size_before)
                  << " -> " << human_bytes(size_after) << ")\n";
        bytes_before += size_before;
        bytes_after += size_after;
        if (reblock) ++reblocked;
        else ++compressed_new;
    }
    int rewritten = compressed_new + reblocked;
    int would_rewrite = would_compress_new + would_reblock;
    std::cout << rewritten << " rewritten (" << compressed_new << " compressed, " << reblocked
              << " re-blocked), ";
    if (dry)
        std::cout << would_rewrite << " would-rewrite (dry-run) (" << would_compress_new << " compress, "
                  << would_reblock << " re-block), ";
    std::cout << already << " already compressed at this block size, " << markers << " marker(s) skipped, "
              << skipped_recent << " skipped (recently written)\n";
    // A bare "N skipped (recently written)" reads as a malfunction to anyone
    // who just created the files they are trying to convert -- which is what
    // happens the first time someone tries this on a test directory. State the
    // reason and the way forward, not just the count.
    if (skipped_recent > 0 && rewritten == 0 && would_rewrite == 0) {
        std::cout << "\nNothing was converted: every table here was written in the last hour.\n"
                  << "That guard exists because a multi-day generation run writes into the\n"
                  << "directory it also reads sub-slices from, and rewriting a table mid-write\n"
                  << "would corrupt it.\n"
                  << "If nothing is generating into " << dir << ", age the files and re-run:\n"
                  << "  touch -d '2 hours ago' " << dir << "/*.hm\n";
    }
    // bytes_after is only ever accumulated on an actual rewrite -- under
    // --dry-run nothing is compressed, so it stays 0 regardless of how much
    // would be reclaimed, and printing it as "0 MiB after" on a real corpus
    // reads as "everything vanishes" rather than "not measured". Report only
    // the "before" total in dry-run; the real "before -> after" line appears
    // once files are actually rewritten.
    if (bytes_before) {
        if (dry) {
            std::cout << human_bytes(bytes_before) << " before (after size unknown until rewritten)\n";
        } else {
            std::cout << human_bytes(bytes_before) << " before -> " << human_bytes(bytes_after) << " after\n";
        }
    }
    return 0;
}

// helpmate compact <DIR> [--dry-run] [--compress] [--block-size N]
// Rewrites every .hm in DIR whose cells are all unsolvable as a marker table.
// With --compress, rewrites raw tables as block-compressed instead (see
// cmd_compact_compress above); the two modes are mutually exclusive.
int cmd_compact(const std::vector<std::string>& args, bool compress, bool dry, uint32_t block_size) {
    if (args.empty()) {
        std::cerr << "error: compact needs a tables directory\n";
        return 3;
    }
    std::string dir = args[0];
    if (!std::filesystem::is_directory(dir)) {
        std::cerr << "error: not a directory: " << dir << "\n";
        return 3;
    }
    if (compress) return cmd_compact_compress(dir, dry, block_size);
    uint64_t reclaimed = 0;
    int rewritten = 0, skipped = 0;
    for (auto& e : std::filesystem::directory_iterator(dir)) {
        if (e.path().extension() != ".hm") continue;
        TableReader::OpenError oerr = TableReader::OpenError::None;
        auto r = TableReader::open(e.path().string(), &oerr);
        if (!r && oerr == TableReader::OpenError::UnsupportedVersion) {
            std::cerr << "error: table " << e.path()
                      << " was written by a newer helpmate"
                         " (unsupported table format version); upgrade this build\n";
            return 3;
        }
        if (!r) {
            std::cerr << "error: unreadable table " << e.path() << "\n";
            return 3;
        }
        if (r->all_unsolvable()) {
            ++skipped;
            continue;
        }  // already compact
        // Chunked, and with a null count buffer: this scan only ever looks at
        // DTM, and on a compressed table asking for counts too would decompress
        // a second set of blocks for nothing. Cell-at-a-time get() here would
        // take the block cache's mutex once per byte over the whole plane.
        bool any_solvable = false;
        {
            constexpr size_t kScanChunk = 1 << 16;
            const uint64_t plane_cells = r->plane_size();
            std::vector<uint8_t> dtm(kScanChunk);
            for (uint64_t base = 0; base < plane_cells && !any_solvable; base += kScanChunk) {
                const size_t n = (size_t)std::min<uint64_t>(kScanChunk, plane_cells - base);
                for (Color stm : {Color::White, Color::Black}) {
                    r->read_values(stm, base, n, dtm.data(), nullptr);
                    for (size_t i = 0; i < n; ++i)
                        if (dtm[i] != DTM_UNSOLVABLE && dtm[i] != DTM_INVALID) {
                            any_solvable = true;
                            break;
                        }
                    if (any_solvable) break;
                }
            }
        }
        if (any_solvable) {
            ++skipped;
            continue;
        }
        uint64_t size = std::filesystem::file_size(e.path());
        std::string name = r->material_name();
        std::string stem = e.path().stem().string();
        uint64_t ps = r->plane_size();
        // Identity check: the sidecar and the rewrite must be keyed off the file's own
        // name, not the header's self-reported material -- otherwise a name/header
        // mismatch would rewrite the right .hm but clobber a DIFFERENT material's
        // .stats.json (or write a marker table under the wrong identity).
        if (name != stem) {
            std::cerr << "error: table " << e.path() << " is for material '" << name << "', expected '"
                      << stem << "' from filename; refusing to touch it\n";
            return 3;
        }
        std::cout << (dry ? "would rewrite " : "rewrote ") << name << " (" << size / (1024 * 1024)
                  << " MiB)\n";
        reclaimed += size;
        if (!dry) {
            auto mat = Material::parse(name);
            if (!mat) {
                std::cerr << "error: bad material in header: " << name << "\n";
                return 3;
            }
            // Synthesize fresh marker metadata -- same shape as the generator's
            // opt.prune path (generator.cpp), not the original table's stale
            // meta_json -- so tooling that inspects metadata recognises a
            // compact-produced marker the same way it recognises a
            // generator-produced one.
            nlohmann::json j;
            j["material"] = name;
            j["plane_size"] = ps;
            j["max_dtm"] = (int)DTM_UNSOLVABLE;
            j["cells"] = {{"invalid", {{"wtm", 0}, {"btm", 0}}}, {"unsolvable", {{"wtm", ps}, {"btm", ps}}}};
            j["dtm_histogram"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
            j["uniqueness"] = {{"wtm", nlohmann::json::object()}, {"btm", nlohmann::json::object()}};
            j["deepest"] = nlohmann::json::array();
            j["deepest_unique"] = nlohmann::json::array();
            j["generator_version"] = HELPMATE_VERSION;
            j["all_unsolvable"] = true;
            std::string meta = j.dump(2);
            r.reset();  // unmap before replacing
            TableWriter::write_unsolvable(e.path().string(), *mat, ps, meta);
            std::ofstream(dir + "/" + stem + ".stats.json", std::ios::trunc) << meta;
        }
        ++rewritten;
    }
    std::cout << (dry ? "would reclaim " : "reclaimed ") << reclaimed / (1024 * 1024) << " MiB from "
              << rewritten << " table(s); " << skipped << " left unchanged (solvable or already compact)\n";
    if (rewritten == 0) std::cout << "already compact\n";
    return 0;
}

// helpmate themes -- print the detector registry. The vocabulary has to be
// discoverable without the docs, and each entry carries its own definition so
// a disagreement about what a theme means is visible right here.
// Wrap `text` at ~72 columns under a 4-space indent.
void print_wrapped(const std::string& text) {
    size_t pos = 0;
    while (pos < text.size()) {
        size_t take = std::min<size_t>(72, text.size() - pos);
        if (pos + take < text.size()) {
            size_t sp = text.rfind(' ', pos + take);
            if (sp != std::string::npos && sp > pos) take = sp - pos;
        }
        std::cout << "    " << text.substr(pos, take) << "\n";
        pos += take;
        while (pos < text.size() && text[pos] == ' ') ++pos;
    }
}

int cmd_themes() {
    for (const auto& t : themes::theme_registry()) {
        std::cout << themes::display_name(t) << "\n";
        std::cout << "    needs: " << themes::needs_name(t.needs) << "\n";
        print_wrapped(std::string(t.doc));
        // A parametric theme says what goes after the colon, right here, so
        // `--theme promotions:qrr` is discoverable without the docs.
        if (t.param)
            print_wrapped("parameter " + std::string(t.param->name) + " (e.g. " + std::string(t.name) + ":" +
                          std::string(t.param->example) + "): " + std::string(t.param->doc));
    }
    return 0;
}

}  // namespace

int main(int argc, char** argv) {
    std::vector<std::string> args(argv + 1, argv + argc);
    if (args.empty()) {
        usage();
        return 3;
    }
    std::string cmd = args[0];
    if (cmd == "--help" || cmd == "-h" || cmd == "help") {
        usage();
        return 0;
    }
    if (cmd == "--version" || cmd == "-V" || cmd == "version") {
        std::cout << "helpmate " << HELPMATE_VERSION << "\n";
        return 0;
    }

    std::string tables = "tables";
    int threads = 1, dtm = -1, count = -1, maxn = 10, starts = -1, ends = -1;
    int block_size_kib = -1;  // -1 = not given: use kDefaultBlockSize
    int cache_mb = -1;        // -1 = not given: per-table block caches
    bool all = false, verbose = false, progress = false, force_ram = false, compress = false;
    bool dry_run = false;
    bool starts_given = false, ends_given = false;
    std::vector<std::string> pos;  // positional args
    std::vector<std::string> theme_names;  // --theme, repeatable
    bool show_themes = false;              // probe --themes
    MineOutput mine_out;                   // mine --json/--themes/--solutions/--interactive
    // Flags below all take a value; if one appears with nothing after it,
    // that's a usage error, not a stray positional argument (e.g. `probe FEN
    // --tables` with no directory should not silently treat "--tables" as
    // the FEN's replacement).
    auto needs_value = [](const std::string& a) {
        return a == "--tables" || a == "--threads" || a == "--dtm" || a == "--count" || a == "--max" ||
               a == "--starts" || a == "--ends" || a == "--block-size" || a == "--theme" || a == "--cache-mb";
    };
    // Consumes the value following flag `a` (already known to exist) into
    // `target`; on malformed/out-of-range input prints one clear message +
    // usage and signals the caller to exit 3, instead of ever calling
    // std::stoi directly where an exception would escape uncaught.
    bool bad_int = false;
    auto set_int = [&](const std::string& a, size_t& i, int& target) {
        if (!parse_int(args[++i], target)) {
            std::cerr << "error: " << a << " expects an integer, got \"" << args[i] << "\"\n\n";
            usage();
            bad_int = true;
        }
    };
    for (size_t i = 1; i < args.size() && !bad_int; ++i) {
        const std::string& a = args[i];
        if (needs_value(a) && i + 1 >= args.size()) {
            std::cerr << "error: " << a << " requires a value\n\n";
            usage();
            return 3;
        }
        if (a == "--tables") tables = args[++i];
        else if (a == "--threads") set_int(a, i, threads);
        else if (a == "--dtm") set_int(a, i, dtm);
        else if (a == "--count") set_int(a, i, count);
        else if (a == "--max") {
            const std::string& v = args[++i];
            if (v == "infinity" || v == "inf") maxn = INT_MAX;
            else if (!parse_int(v, maxn)) {
                std::cerr << "error: --max expects an integer, \"infinity\" or \"inf\", got \"" << v
                          << "\"\n\n";
                usage();
                return 3;
            } else if (maxn < 0) {
                // A negative cap parses fine and then silently behaves as
                // --max 0 (nothing printed), which reads as "no matches".
                std::cerr << "error: --max must be 0 or more, \"infinity\" or \"inf\", got \"" << v
                          << "\"\n\n";
                usage();
                return 3;
            }
        } else if (a == "--starts") {
            set_int(a, i, starts);
            starts_given = true;
        } else if (a == "--ends") {
            set_int(a, i, ends);
            ends_given = true;
        } else if (a == "--all") all = true;
        else if (a == "--verbose") verbose = true;
        else if (a == "--progress") progress = true;
        else if (a == "--force-ram") force_ram = true;
        else if (a == "--compress") compress = true;
        else if (a == "--dry-run") dry_run = true;
        else if (a == "--block-size") set_int(a, i, block_size_kib);
        else if (a == "--cache-mb") set_int(a, i, cache_mb);
        else if (a == "--theme") {
            // --theme (repeatable, value) is mine's per-theme filter; --themes
            // (boolean) is probe's "also print the themes shown". They read as
            // a singular/plural typo of each other -- exactly the --end/--ends
            // incident the comment below exists to prevent -- so on any OTHER
            // command this must be a loud error naming the command that
            // actually honours it, not a filter that silently falls through
            // to positionals and gets ignored (verbatim: `mine --themes
            // mirror` used to run to completion with "mirror" discarded as a
            // stray positional; `stats KQvk --theme model` and `line FEN
            // --themes` are the same defect on commands that never even
            // looked at either flag).
            if (cmd == "probe") {
                std::cerr << "error: probe has no \"--theme\" flag; did you mean \"--themes\" "
                             "(no value, prints the themes shown)?\n\n";
                usage();
                return 3;
            }
            if (cmd != "mine") {
                std::cerr << "error: " << cmd
                          << " has no \"--theme\" flag; only \"mine\" filters by theme "
                             "(\"--theme NAME\", repeatable)\n\n";
                usage();
                return 3;
            }
            theme_names.push_back(args[++i]);
        } else if (a == "--themes") {
            if (cmd == "mine") {
                mine_out.themes = true;
                continue;
            }
            if (cmd != "probe") {
                std::cerr << "error: " << cmd
                          << " has no \"--themes\" flag; only \"probe\" prints the themes shown "
                             "(\"--themes\", no value)\n\n";
                usage();
                return 3;
            }
            show_themes = true;
        } else if (a == "--json" || a == "--jsonl" || a == "--solutions" || a == "--interactive" ||
                   a == "--tui") {
            if (cmd != "mine") {
                std::cerr << "error: " << cmd << " has no \"" << a << "\" flag; only \"mine\" has it\n\n";
                usage();
                return 3;
            }
            if (a == "--json") mine_out.json = true;
            else if (a == "--jsonl") mine_out.jsonl = true;
            else if (a == "--solutions") mine_out.solutions = true;
            else mine_out.interactive = true;
        }
        // An unrecognised --flag is a usage error, never a positional argument.
        // Silently ignoring it is worse than useless here: `mine --end 2` (the
        // real flag is --ends) used to run to completion with the filter simply
        // discarded, returning positions that do not match what was asked for,
        // with nothing to indicate it.
        else if (a.rfind("--", 0) == 0) {
            std::cerr << "error: unknown option \"" << a << "\"\n\n";
            usage();
            return 3;
        } else pos.push_back(a);
    }
    if (bad_int) return 3;
    if (mine_out.json && mine_out.jsonl) {
        std::cerr
            << "error: --json and --jsonl are mutually exclusive (one document, or one object per line)\n\n";
        usage();
        return 3;
    }

    if (cache_mb == 0 || cache_mb < -1) {
        std::cerr << "error: --cache-mb must be a positive number of MiB, got " << cache_mb << "\n";
        return 3;
    }

    // --block-size is given in KiB (documented in --help): "64" means 64
    // KiB == 65536 bytes, matching how the size/miss-cost trade-off is
    // discussed everywhere else (docs/USAGE.md, kDefaultBlockSize's
    // comment). Bounds mirror what TableReader::open() enforces at the
    // upper end (kMaxBlockSize, 16 MiB) plus a 4 KiB floor below which a
    // block's fixed zstd frame overhead dominates the payload.
    uint32_t block_size = kDefaultBlockSize;
    if (block_size_kib != -1) {
        if (block_size_kib <= 0) {
            std::cerr << "error: --block-size must be a positive number of KiB, got " << block_size_kib
                      << "\n";
            return 3;
        }
        uint64_t bytes = static_cast<uint64_t>(block_size_kib) * 1024ull;
        constexpr uint64_t kMinBlockSizeBytes = 4096;  // 4 KiB
        if (bytes < kMinBlockSizeBytes || bytes > kMaxBlockSize) {
            std::cerr << "error: --block-size " << block_size_kib << " (" << bytes
                      << " bytes) is out of range: must be between " << (kMinBlockSizeBytes / 1024)
                      << " KiB and " << (kMaxBlockSize / 1024) << " KiB\n";
            return 3;
        }
        block_size = static_cast<uint32_t>(bytes);
    }

    try {
        if (cmd == "gen")
            return cmd_gen(pos, tables, threads, verbose, progress, force_ram, compress, block_size);
        if (cmd == "probe") return cmd_probe(pos, tables, show_themes);
        if (cmd == "line") return cmd_line(pos, tables, all, maxn);
        if (cmd == "stats") return cmd_stats(pos, tables);
        if (cmd == "mine")
            return cmd_mine(pos, tables, dtm, count, maxn, starts, ends, starts_given, ends_given,
                            theme_names, mine_out, threads, cache_mb);
        if (cmd == "themes") return cmd_themes();
        if (cmd == "compact") return cmd_compact(pos, compress, dry_run, block_size);
        std::cerr << "error: unknown command \"" << cmd << "\"\n\n";
        usage();
        return 3;
    } catch (const MissingTableError& e) {
        std::cerr << "error: " << e.what() << "\nrun: helpmate gen <MATERIAL> --tables " << tables << "\n";
        return 2;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 3;
    }
}

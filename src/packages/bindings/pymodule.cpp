#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "chess/board.h"
#include "generator/generator.h"
#include "indexing/material.h"
#include "probe/tablebase.h"
#include "themes/registry.h"
#include "version.h"
namespace py = pybind11;
using namespace hm;
static Material mat_or_throw(const std::string& s) {
    auto m = Material::parse(s);
    if (!m) throw std::invalid_argument("bad material string: " + s);
    return *m;
}
// Mirrors the validation in src/packages/cli/main.cpp's cmd_mine. Unlike the CLI, this
// binding has no "was the flag given" distinction: -1 is the documented wire
// value for "unset" (the HTTP API converts None -> -1 before calling), so -1
// must always be accepted here, even though the CLI treats a user-typed -1
// as an error. Do not "fix" that into matching the CLI.
static void validate_mine_shape(int count, int starts, int ends) {
    if (starts != -1 && starts < 1)
        throw std::invalid_argument("starts must be at least 1");
    if (ends != -1 && ends < 1)
        throw std::invalid_argument("ends must be at least 1");
    if (count >= 0 && starts > count)
        throw std::invalid_argument(
            "starts=" + std::to_string(starts) + " cannot exceed count=" + std::to_string(count));
    if (count >= 0 && ends > count)
        throw std::invalid_argument(
            "ends=" + std::to_string(ends) + " cannot exceed count=" + std::to_string(count));
}
PYBIND11_MODULE(_helpmate, mod) {
    mod.attr("__version__") = hm::HELPMATE_VERSION;
    py::register_exception<MissingTableError>(mod, "MissingTableError", PyExc_RuntimeError);
    mod.def(
        "generate",
        [](const std::string& mat, const std::string& tables, int threads, bool verbose, bool progress,
           bool force_ram, bool compress, unsigned int block_size) {
            GenOptions o;
            o.tables_dir = tables;
            o.threads = threads;
            o.verbose = verbose;
            o.progress = progress;
            o.force_ram = force_ram;
            o.compress = compress;
            // KiB, matching the CLI's --block-size. Keeping the two in the
            // same unit matters more than matching GenOptions' internal bytes:
            // a user reading `--block-size 64` and writing block_size=64 must
            // get the same table, not a 64-byte-block one.
            o.block_size = block_size * 1024;
            return generate(mat_or_throw(mat), o);
        },
        py::arg("material"), py::arg("tables") = "tables", py::arg("threads") = 1, py::arg("verbose") = false,
        py::arg("progress") = false, py::arg("force_ram") = false,
        // compress/block_size mirror the CLI's `gen --compress`/`--block-size`
        // (see docs/USAGE.md's Table format section), in the SAME unit: KiB.
        py::arg("compress") = false, py::arg("block_size") = kDefaultBlockSize / 1024);
    py::class_<Tablebase>(mod, "Tablebase")
        .def(py::init<std::string>())
        .def("probe",
             [](const Tablebase& t, const std::string& fen) -> py::object {
                 auto p = t.probe(fen);
                 if (!p) return py::none();
                 return py::make_tuple(p->dtm, p->count, p->flipped);
             })
        .def("line", &Tablebase::line)
        .def("lines", &Tablebase::lines, py::arg("fen"), py::arg("max") = 100)
        .def(
            "themes",
            [](const Tablebase& t, const std::string& fen, int max) {
                if (max < 0) {
                    // Sentinel: use the position's own solution count, the
                    // same cap `helpmate probe --themes` uses (saturated
                    // positions fall back to 100, same as the CLI). A fixed
                    // default here (the old default was 100) disagreed with
                    // the CLI for any 100 < count < 255: the same position
                    // would enumerate a different number of solutions on
                    // each surface and so could report different themes
                    // (e.g. `closed-walk` present on one, absent on the
                    // other). Every caller of this binding -- including
                    // app.py's /v1/probe?themes=true -- inherits the fix by
                    // simply not overriding `max`.
                    auto p = t.probe(fen);
                    bool saturated = p && p->count >= (int)COUNT_SAT;
                    max = (!p) ? 100 : (saturated ? 100 : p->count);
                    if (saturated) {
                        // Same disclosure as app.py's themes_note and the
                        // CLI's stderr note: on a saturated position (stored
                        // count == 255) this list is not merely incomplete,
                        // it is representative-dependent -- two mirror-image
                        // FENs of the same position class can enumerate a
                        // different first 100 solutions and so report
                        // different themes. A Python return value has no
                        // sibling-field slot the way a dict/JSON response
                        // does, so the idiomatic disclosure here is a
                        // Python warning (PyErr_WarnEx, catchable with
                        // pytest.warns/warnings.catch_warnings), not a
                        // silently different return shape.
                        PyErr_WarnEx(PyExc_RuntimeWarning,
                                     "themes(): this position's solution count is saturated "
                                     "(255+); themes were detected from the first 100 "
                                     "solutions only, and the list may differ between "
                                     "mirror-image representatives of the same position.",
                                     1);
                    }
                }
                return t.themes_of(fen, max);
            },
            py::arg("fen"), py::arg("max") = -1)
        .def(
            "moves",
            [](const Tablebase& t, const std::string& fen) {
                py::list out;
                for (const auto& m : t.moves(fen)) {
                    py::dict d;
                    d["uci"] = m.uci;
                    d["san"] = m.san;
                    d["fen"] = m.fen;
                    d["dtm"] = m.solvable ? py::cast(m.dtm) : py::none();
                    d["count"] = m.count;
                    d["solvable"] = m.solvable;
                    d["optimal"] = m.optimal;
                    out.append(std::move(d));
                }
                return out;
            },
            py::arg("fen"))
        .def(
            "mine",
            [](const Tablebase& t, const std::string& mat, int dtm, int count, int max, int starts, int ends,
               std::vector<std::string> themes) {
                validate_mine_shape(count, starts, ends);
                std::vector<std::string> out;
                t.mine(mat_or_throw(mat),
                       MineFilter{.dtm = dtm,
                                  .count = count,
                                  .starts = starts,
                                  .ends = ends,
                                  .themes = std::move(themes)},
                       [&](const std::string& f) {
                           out.push_back(f);
                           return (int)out.size() < max;
                       });
                return out;
            },
            py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
            py::arg("starts") = -1, py::arg("ends") = -1, py::arg("themes") = std::vector<std::string>{})
        .def(
            "_mine_with_stats",
            [](const Tablebase& t, const std::string& mat, int dtm, int count, int max, int starts, int ends,
               std::vector<std::string> themes) {
                validate_mine_shape(count, starts, ends);
                std::vector<std::string> out;
                uint64_t skipped = 0;
                t.mine(
                    mat_or_throw(mat),
                    MineFilter{.dtm = dtm,
                               .count = count,
                               .starts = starts,
                               .ends = ends,
                               .themes = std::move(themes)},
                    [&](const std::string& f) {
                        out.push_back(f);
                        return (int)out.size() < max;
                    },
                    &skipped);
                return std::make_pair(out, skipped);  // -> (list[str], int) in Python
            },
            py::arg("material"), py::arg("dtm"), py::arg("count") = -1, py::arg("max") = 100,
            py::arg("starts") = -1, py::arg("ends") = -1, py::arg("themes") = std::vector<std::string>{})
        .def("_stats_json",
             [](const Tablebase& t, const std::string& mat) { return t.stats_json(mat_or_throw(mat)); });
    mod.def(
        "themes",
        []() {
            py::list out;
            for (const auto& t : themes::theme_registry()) {
                py::dict d;
                // The DISPLAY name: "promotions:<types>" for a parametric
                // theme, so every listing surface shows that a value goes
                // after the colon. `parameter` says what the value is.
                d["name"] = themes::display_name(t);
                d["doc"] = std::string(t.doc);
                d["needs"] = std::string(themes::needs_name(t.needs));
                if (t.param) {
                    py::dict prm;
                    prm["name"] = std::string(t.param->name);
                    prm["doc"] = std::string(t.param->doc);
                    prm["example"] = std::string(t.param->example);
                    d["parameter"] = std::move(prm);
                } else {
                    d["parameter"] = py::none();
                }
                out.append(std::move(d));
            }
            return out;
        },
        "Every theme detector this build knows: [{name, doc, needs, parameter}, ...], in display "
        "order. `parameter` is None for a boolean theme, or {name, doc, example} for a parametric "
        "one whose query form is name:value (promotions:qrr).");
    mod.def(
        "check_theme",
        [](const std::string& name) -> py::object {
            std::string err;
            if (themes::resolve_theme(name, &err)) return py::none();
            return py::str(err);
        },
        py::arg("name"),
        "None when `name` is a theme mine() accepts (a registry name, or name:value for a "
        "parametric theme), else the error message naming what is wrong.");
    mod.def("_perft", [](const std::string& fen, int depth) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        return b->perft(depth);
    });
    mod.def("_legal_moves", [](const std::string& fen) {
        auto b = Board::from_fen(fen);
        if (!b) throw std::invalid_argument("bad fen");
        std::vector<std::string> out;
        for (auto& m : b->legal_moves()) out.push_back(m.uci());
        return out;
    });
}

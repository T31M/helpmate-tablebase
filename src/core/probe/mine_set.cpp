#include "probe/mine_set.h"

#include <algorithm>
#include <atomic>
#include <chrono>
#include <climits>
#include <condition_variable>
#include <exception>
#include <mutex>
#include <nlohmann/json.hpp>
#include <stdexcept>
#include <thread>

#include "chess/types.h"
#include "themes/registry.h"

namespace hm {

std::vector<std::string> non_parametric(const std::vector<std::string>& names) {
    std::vector<std::string> out;
    for (const auto& n : names) {
        auto r = themes::resolve_theme(n);
        if (r && r->def->param == nullptr) out.push_back(n);
    }
    return out;
}

MineSet::MineSet(const Tablebase& tb, Material m, MineFilter f, int max)
    : tb_(&tb), m_(std::move(m)), f_(std::move(f)), max_(max) {}

struct MineSet::Workers {
    std::vector<std::unique_ptr<Tablebase>> tbs;
};

void MineSet::set_threads(int threads) {
    threads_ = std::max(threads, 1);
    workers_.reset();  // rebuilt for the new count on first use
}

Hit MineSet::make_hit(const std::string& fen) const { return make_hit(*tb_, fen); }

Hit MineSet::make_hit(const Tablebase& tb, const std::string& fen) const {
    Hit h;
    h.fen = fen;
    if (auto p = tb.probe(fen)) {
        h.dtm = p->dtm;
        h.count = p->count;
    }
    return h;
}

void MineSet::add(const std::string& fen) { hits_.push_back(make_hit(fen)); }

void MineSet::enrich(Hit& h, Facets f) const { enrich(*tb_, h, f); }

void MineSet::enrich(const Tablebase& tb, Hit& h, Facets f) const {
    if (f.themes) themes_on(tb, h);
    if (f.solutions) {
        solutions_on(tb, h);
        shape_on(tb, h);
    }
}

void MineSet::add(Hit h) { hits_.push_back(std::move(h)); }

Hit& MineSet::hit(size_t i) {
    if (i >= hits_.size())
        throw std::out_of_range("MineSet::hit: no hit " + std::to_string(i) + " (set has " +
                                std::to_string(hits_.size()) + ")");
    return hits_[i];
}

int MineSet::enum_cap(const Hit& h) const { return h.count >= (int)COUNT_SAT ? 100 : h.count; }

template <class F>
void MineSet::guarded(Hit& h, F&& f) const {
    if (!h.unavailable.empty()) return;
    try {
        f();
    } catch (const MissingTableError& e) {
        h.unavailable = e.what();
    } catch (const UnsupportedTableVersionError& e) {
        // Same contract as a missing table from the caller's point of view:
        // this hit cannot be annotated, but it is still a hit. Letting this
        // one escape would kill the shell mid-narrowing.
        h.unavailable = e.what();
    }
}

void MineSet::shape_on(const Tablebase& tb, Hit& h) const {
    if (h.shape) return;
    guarded(h, [&] { h.shape = tb.solution_shape(h.fen); });
}

void MineSet::themes_on(const Tablebase& tb, Hit& h) const {
    if (h.themes) return;
    guarded(h, [&] { h.themes = non_parametric(tb.themes_of(h.fen, enum_cap(h))); });
}

void MineSet::solutions_on(const Tablebase& tb, Hit& h) const {
    if (h.solutions) return;
    guarded(h, [&] { h.solutions = tb.lines(h.fen, enum_cap(h)); });
}

void MineSet::ensure_shape(Hit& h) const { shape_on(*tb_, h); }
void MineSet::ensure_themes(Hit& h) const { themes_on(*tb_, h); }
void MineSet::ensure_solutions(Hit& h) const { solutions_on(*tb_, h); }

template <class Need, class Work>
void MineSet::for_each_needing(Need&& need, Work&& work, const Progress& progress) {
    std::vector<size_t> todo;
    for (size_t i = 0; i < hits_.size(); ++i)
        if (need(hits_[i])) todo.push_back(i);
    if (todo.empty()) return;
    const size_t total = hits_.size();
    if (threads_ <= 1 || todo.size() == 1) {
        for (size_t i : todo) {
            work(*tb_, i);
            if (progress) progress(i + 1, total);
        }
        return;
    }

    // One Tablebase per worker (own readers and block caches, no shared
    // lock), as in Tablebase::mine; kept across calls so caches stay warm.
    if (!workers_) {
        workers_ = std::make_shared<Workers>();
        const size_t share =
            tb_->cache_bytes() ? std::max<size_t>(tb_->cache_bytes() / threads_, 1 << 16) : 0;
        for (int w = 0; w < threads_; ++w)
            workers_->tbs.push_back(std::make_unique<Tablebase>(tb_->dir(), share));
    }
    const size_t n = std::min<size_t>(workers_->tbs.size(), todo.size());
    // Workers claim contiguous chunks, not single hits: a set is in table
    // order, so neighbouring hits share table blocks, and one worker reading
    // a run of them finds those blocks in its own cache. Handing neighbours
    // to different workers made each decompress the same blocks again (5.5x
    // the CPU of one thread on 20,000 KBvkqrn hits). Four chunks per worker
    // still balance an uneven tail; 16 were as fast with 15% more CPU.
    const size_t chunk = std::max<size_t>(1, todo.size() / (4 * n));
    std::atomic<size_t> next{0}, finished{0};
    std::atomic<bool> failed{false};
    std::exception_ptr error;
    std::mutex mu;
    std::condition_variable cv;
    std::vector<std::thread> pool;
    for (size_t w = 0; w < n; ++w)
        pool.emplace_back([&, w] {
            const Tablebase& tb = *workers_->tbs[w];
            for (size_t first; !failed.load() && (first = next.fetch_add(chunk)) < todo.size();) {
                const size_t last = std::min(first + chunk, todo.size());
                for (size_t k = first; k < last && !failed.load(); ++k) {
                    try {
                        work(tb, todo[k]);
                    } catch (...) {
                        std::lock_guard lk(mu);
                        if (!error) error = std::current_exception();
                        failed = true;
                    }
                    if (finished.fetch_add(1) + 1 == todo.size()) {
                        std::lock_guard lk(mu);
                        cv.notify_all();
                    }
                }
            }
        });
    // Progress from this thread only: the callback may write to a stream.
    // `done` counts the hits that needed no work as already done.
    const size_t skipped = total - todo.size();
    size_t reported = 0;
    {
        std::unique_lock lk(mu);
        while (!failed.load() && finished.load() < todo.size()) {
            cv.wait_for(lk, std::chrono::milliseconds(100));
            const size_t now = finished.load();
            if (progress && now > reported && now < todo.size()) {
                reported = now;
                lk.unlock();
                progress(skipped + now, total);
                lk.lock();
            }
        }
    }
    for (auto& t : pool) t.join();
    if (error) std::rethrow_exception(error);
    if (progress) progress(total, total);
}

void MineSet::ensure_themes_all(const Progress& progress) {
    for_each_needing([](const Hit& h) { return !h.themes && h.unavailable.empty(); },
                     [&](const Tablebase& tb, size_t i) { themes_on(tb, hits_[i]); }, progress);
}

void MineSet::ensure_solutions_all(const Progress& progress) {
    for_each_needing([](const Hit& h) { return !(h.solutions && h.shape) && h.unavailable.empty(); },
                     [&](const Tablebase& tb, size_t i) {
                         solutions_on(tb, hits_[i]);
                         shape_on(tb, hits_[i]);
                     },
                     progress);
}

bool MineSet::all_have_themes() const {
    for (const auto& h : hits_)
        if (!h.themes && h.unavailable.empty()) return false;
    return true;
}

size_t MineSet::unavailable_count() const {
    size_t n = 0;
    for (const auto& h : hits_) n += !h.unavailable.empty();
    return n;
}

MineSet MineSet::empty_like() const {
    MineSet s(*tb_, m_, f_, max_);
    s.skipped_ = skipped_;
    s.threads_ = threads_;
    s.workers_ = workers_;
    return s;
}

template <class Pred>
MineSet MineSet::filtered(Pred&& keep) const {
    MineSet out = empty_like();
    for (const auto& h : hits_)
        if (h.unavailable.empty() && keep(h)) out.hits_.push_back(h);
    return out;
}

MineSet MineSet::with_theme(const std::string& name, bool negate, const Progress& progress) {
    std::string err;
    auto r = themes::resolve_theme(name, &err);
    if (!r) throw std::invalid_argument(err);
    if (r->def->param == nullptr) {
        ensure_themes_all(progress);
        const std::string canon = r->name();
        return filtered([&](const Hit& h) {
            bool shows = std::find(h.themes->begin(), h.themes->end(), canon) != h.themes->end();
            return shows != negate;
        });
    }
    // Parametric: the registry's own eval per hit; no cache, the value differs per query.
    std::vector<char> shows(hits_.size(), 0);
    for_each_needing([](const Hit& h) { return h.unavailable.empty(); },
                     [&](const Tablebase& tb, size_t i) {
                         guarded(hits_[i],
                                 [&] { shows[i] = tb.shows_theme(hits_[i].fen, *r, enum_cap(hits_[i])); });
                     },
                     progress);
    MineSet out = empty_like();
    for (size_t i = 0; i < hits_.size(); ++i)
        if (hits_[i].unavailable.empty() && (shows[i] != 0) != negate) out.hits_.push_back(hits_[i]);
    return out;
}

MineSet MineSet::with_count(int n) {
    return filtered([&](const Hit& h) { return h.count == n; });
}

MineSet MineSet::with_starts(int n) {
    for_each_needing([](const Hit& h) { return !h.shape && h.unavailable.empty(); },
                     [&](const Tablebase& tb, size_t i) { shape_on(tb, hits_[i]); }, nullptr);
    return filtered([&](const Hit& h) { return h.shape->exhaustive && h.shape->starts == n; });
}

MineSet MineSet::with_ends(int n) {
    for_each_needing([](const Hit& h) { return !h.shape && h.unavailable.empty(); },
                     [&](const Tablebase& tb, size_t i) { shape_on(tb, hits_[i]); }, nullptr);
    return filtered([&](const Hit& h) { return h.shape->exhaustive && h.shape->ends == n; });
}

std::vector<std::pair<std::string, size_t>> MineSet::theme_histogram(const Progress& progress) {
    ensure_themes_all(progress);
    std::vector<std::pair<std::string, size_t>> out;
    for (const auto& t : themes::theme_registry()) {
        if (t.param) continue;
        std::string name(t.name);
        size_t n = 0;
        for (const auto& h : hits_)
            if (h.themes && std::find(h.themes->begin(), h.themes->end(), name) != h.themes->end()) ++n;
        out.emplace_back(std::move(name), n);
    }
    return out;
}

void MineSet::enrich_for(Facets f, const Progress& progress) {
    if (f.themes) ensure_themes_all(progress);
    if (f.solutions) ensure_solutions_all(progress);
}

nlohmann::ordered_json MineSet::header_json() const {
    nlohmann::ordered_json j;
    j["material"] = m_.name();
    j["filter"] = {{"dtm", f_.dtm},
                   {"count", f_.count},
                   {"starts", f_.starts},
                   {"ends", f_.ends},
                   {"themes", f_.themes}};
    if (max_ == INT_MAX) j["max"] = "infinity";
    else j["max"] = max_;
    return j;
}

nlohmann::ordered_json MineSet::position_json(const Hit& h, Facets f) const {
    nlohmann::ordered_json p;
    p["fen"] = h.fen;
    p["dtm"] = h.dtm;
    p["count"] = h.count;
    if (!h.unavailable.empty()) {
        p["unavailable"] = h.unavailable;
    } else {
        if (f.themes && h.themes) p["themes"] = *h.themes;
        if (f.solutions && h.shape && h.solutions) {
            // A saturated position has no countable solution set, so
            // `starts`/`ends` would be a guess presented as a fact: say
            // so with one explicit key instead, and keep `solutions`,
            // which is honestly the first 100 (enum_cap).
            if (h.shape->exhaustive) {
                p["starts"] = h.shape->starts;
                p["ends"] = h.shape->ends;
            } else {
                p["exhaustive"] = false;
            }
            p["solutions"] = *h.solutions;
        }
    }
    return p;
}

std::string MineSet::to_json(Facets f, const Progress& progress) {
    enrich_for(f, progress);
    nlohmann::ordered_json j = header_json();
    j["skipped_saturated"] = skipped_;
    auto positions = nlohmann::ordered_json::array();
    for (const auto& h : hits_) positions.push_back(position_json(h, f));
    j["positions"] = std::move(positions);
    return j.dump(2) + "\n";
}

std::string MineSet::jsonl_header() const { return header_json().dump() + "\n"; }

std::string MineSet::jsonl_record(const Hit& h, Facets f) const { return position_json(h, f).dump() + "\n"; }

std::string MineSet::jsonl_footer(size_t positions) const {
    nlohmann::ordered_json j;
    j["positions"] = positions;
    j["skipped_saturated"] = skipped_;
    return j.dump() + "\n";
}

void MineSet::to_jsonl(std::ostream& os, Facets f, const Progress& progress) {
    enrich_for(f, progress);
    os << jsonl_header();
    for (const auto& h : hits_) os << jsonl_record(h, f);
    os << jsonl_footer(hits_.size());
}

void MineSet::write_hit(std::ostream& os, const Hit& h, Facets f) const {
    os << h.fen << "\n";
    if (!f.themes && !f.solutions) return;
    if (!h.unavailable.empty()) {
        os << "  unavailable: " << h.unavailable << "\n";
        return;
    }
    if (f.themes && h.themes) {
        os << "  themes:";
        if (h.themes->empty()) os << " (none)";
        for (const auto& n : *h.themes) os << " " << n;
        os << "\n";
    }
    if (f.solutions && h.solutions) {
        for (const auto& line : *h.solutions) {
            if (line.empty()) continue;  // dtm 0: already mate, nothing to print
            os << " ";
            for (const auto& mv : line) os << " " << mv;
            os << "\n";
        }
        // Same honesty as to_json's `exhaustive`: these are the first 100 of
        // an uncountable set, not the whole set.
        if (h.shape && !h.shape->exhaustive) os << "  (solution count saturated: first 100 solutions only)\n";
    }
}

void MineSet::to_text(std::ostream& os, Facets f, const Progress& progress) {
    enrich_for(f, progress);
    const bool facets = f.themes || f.solutions;
    for (const auto& h : hits_) {
        write_hit(os, h, f);
        if (facets) os << "\n";  // one blank line between annotated hits
    }
}

}  // namespace hm

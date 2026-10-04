# Roadmap

Origin: the raw capability notes in `specs/specround_2026_07_29.md`, decomposed
and ordered in the brainstorming session of 2026-07-30. Each rung gets its own
design spec (`docs/superpowers/specs/`) and implementation plan when its turn
comes; this file records the agreed order, goals, dependencies, and open
questions. v0.5.0 (released 2026-07-30) is the baseline: generator to 6
pieces, probe library, CLI, Python bindings, CI, docs.

## v0.18.0 — `mine` result sets: JSON, solutions, `--max infinity`, interactive shell

- **Shipped.** Design: `docs/superpowers/specs/2026-09-10-mine-interactive-design.md`.
- Follow-up: expose `MineSet` through the Python bindings and `/v1/mine`.

## v0.6 — Storage + read-only API

**Goal:** tablebase files stored not only locally (Hugging Face dataset +
manifest, sync via CLI tooling), and a read-only FastAPI service exposing
probe / lines / mining / stats / catalog to remote CLI clients and the future
dashboard.

- Design: **approved** — `docs/superpowers/specs/2026-07-30-storage-read-api-design.md`
- Depends on: nothing (baseline v0.5.0)
- Out of scope: pattern/theme search, auth, 7-piece serving
- Open questions: none blocking; S3-compatible backend (B2/R2) optional later

## v0.6.1 — Unsolvable-material prune

**Goal:** never generate or store a material that provably cannot contain a
helpmate, and reclaim the tables already spent on such material.

- Design: **approved** — `docs/superpowers/specs/2026-07-30-unsolvable-material-prune-design.md`
- Plan: `docs/superpowers/plans/2026-07-30-unsolvable-material-prune.md`
- Depends on: v0.6 (marker tables travel through the storage/sync layer)

## v0.6.2 — `mine` starts/ends filters

**Goal:** let `mine` (CLI, HTTP API and Python) select positions by the shape of
their solution set — how many distinct moves the optimal solutions begin with
(`--starts`) and how many distinct moves they mate with (`--ends`). Composition
search leans on exactly this: "four solutions that all start with the same
move", "two solutions converging on one mate".

- Design: **approved** — `docs/superpowers/specs/2026-07-31-mine-starts-ends-filters-design.md`
- Depends on: nothing beyond v0.6
- The last release before the web dashboard.

## v0.7 — Web dashboard

**Goal:** the visible layer — a browser client of the v0.6 read-only API:
position explorer with an interactive board and per-move evaluations, material
browser with stats, mining/composition search with the v0.6.2 shape filters,
and client-side export (FEN/PGN/CSV). Static files served by the existing
FastAPI process; no build step; cm-chessboard vendored. One API addition:
`GET /v1/moves`, which returns every legal move with the value it leads to.

- Design: **approved** — `docs/superpowers/specs/2026-07-31-web-dashboard-design.md`
- Depends on: v0.6 API, v0.6.2 filters
- Delivered beyond the MVP line: the piece palette / free position editing,
  and the mate-length and solution-count histograms in the material browser.
- Verified end-to-end: Playwright + headless Chromium drives a real server in
  CI (`ui` job), alongside `node --test` for the pure helpers. The earlier
  note that Playwright was unusable on the development box was wrong — only
  the driver package was missing.

## v0.7.1 — Package split

**Goal:** reorganise the repo into three independently installable
distributions — `helpmate` (root `pyproject.toml`: C++ core, CLI binary,
Python bindings), `helpmate-api` (`src/packages/api/`), `helpmate-web`
(`src/packages/web/`) — each verifiable on its own, with a single `VERSION`
file every declared version is checked against.

- Design: **approved** — `docs/superpowers/specs/2026-08-01-package-split-design.md`
- Depends on: v0.7 (splits the dashboard and API that already existed)
- No release: a repo-layout rung, not a user-facing one.

## v0.7.2 — PR gate

**Goal:** every pull request gated by linting, type checking, C++ formatting
on changed lines, and the full test suite, with `main` branch-protected so a
red check disables the merge button.

- Plan: `docs/superpowers/plans/2026-08-01-pr-gate.md`
- Depends on: v0.7.1 (the per-package layout the jobs run against)
- No release: a process rung.

## v0.7.5 — Block-compressed tables

**Goal:** cut the on-disk size of the table corpus, which is the binding
constraint on publishing 6-piece sets, without giving up the random access
probing depends on. Fixed-size blocks compressed independently with zstd,
plus a block-offset index and a small decompressed-block cache.

Promoted here from the Backlog once measured: **14.5×** on a real 6-piece
plane at 64 KB / level 3, against the Backlog's ≥5× ship condition. The same
measurement pass demoted combinatorial indexing, which returns only 3.5% on
this corpus — helpmate materials are mostly one-of-each, unlike the Syzygy
case that motivates it.

- Design: **approved** — `docs/superpowers/specs/2026-08-02-block-compression-design.md`
- Depends on: v0.6.1 (whole-slice elimination first — strictly cheaper than
  compressing a file that need not exist)
- Ships only if the Backlog's performance conditions hold; see the spec.
- No release.

## v0.8 — Pattern / theme search

**Goal:** search by theme and pattern, the capability the original notes asked
for. Split out of v0.7 because it needs its own foundations: a definition of
what a "theme" is, a precomputed index per material, generation tooling, and
new query endpoints. Starts with its own brainstorming session.

- **Shipped in v0.8.0.** Twelve themes across CLI (`mine --theme`,
  `probe --themes`, `helpmate themes`), API (`/v1/themes`, `theme=` on
  `/v1/mine`, `themes=true` on `/v1/probe`) and the dashboard.
- Design: **approved** — `docs/superpowers/specs/2026-08-03-theme-detection-design.md`
- Depends on: v0.7 (the UI that will present it), v0.6 storage
- Scoped to twelve cheap, precisely-defined themes computed on the fly during
  a `mine` scan — no precomputed index, no new file format, since definitions
  will change as they are argued with. Naming follows the Helpmate Analyzer
  glossary so results are comparable with established practice.
- Deferred to a later rung: cross-solution themes (echo, Zilahi, AUW), the
  geometric patterns, twins and set play. Permanently impossible: anything
  requiring castling, which the table format never supports.

## Dropped — cross-platform support

**Decided 2026-08-08: Linux only. No Windows, no macOS.** This entry
previously called for native Windows / macOS / WSL builds and a CI release
matrix. It is recorded as dropped rather than deleted so the survey behind it
is not repeated.

This matches reality rather than changing it: CI is `ubuntu-24.04` on every
job in both workflows, and no other platform has ever been tested.

What a Windows port would have cost, measured rather than estimated:

- **All POSIX usage sits in one file**, `src/core/format/table_file.cpp`
  (`mmap`, `munmap`, `madvise`, `sysconf`, `open`/`fstat`/`close`). Nothing
  else in the tree needs porting.
- **The vendored move generator is portable** — ChessMG has zero
  `__builtin_*` and zero POSIX includes, and neither does our own code. That
  was the expected blocker and it is not one.
- **Only the mapping itself is correctness-critical.** `madvise` appears
  solely in `SequentialPageReleaser`, which bounds RSS during conversion; a
  port could no-op it and stay correct at the cost of memory. The real work
  is `CreateFileMapping`/`MapViewOfFile` behind an interface.
- Windows' case-insensitive filesystem **cannot** collide two materials:
  case encodes colour, but `v` is the separator and is not a piece letter, so
  a case-folded name still splits unambiguously.

So the code was never the hard part. The cost was the tail: a second
toolchain to keep green, libzstd with no system package, MSVC 2022 for the
C++20 Python extension, and `taskset`/`touch -d`/bash across the Makefile,
the ctest cases and `tools/`.

### Why the decision is load-bearing, not just paperwork

`mem_available_bytes()` (`generator.cpp`) reads `/proc/meminfo` and returns
`nullopt` when it cannot. The RAM guard that refuses to start a slice whose
planes exceed memory therefore **disappears silently on any non-Linux
platform** — exactly where it matters most, since a 6-piece slice is 14-28 GB
of resident planes. Deciding "Linux only" keeps that guard a guarantee
instead of a coincidence. Any future port must restore it, not inherit the
`nullopt`.

## v0.9 — Seven pieces ("humongous tablebases", part 1)

**Goal:** the project's namesake research goal. 7-piece slices exceed RAM
(~1.8 TB naive planes — the v0.5.0 RAM guard already computes this), so the
generator needs an out-of-core redesign: disk-backed planes with streaming
passes, partial generation (single sub-slices on demand), checkpoint/resume,
and the deferred perf items (dynamic chunking, thread pool, encode()
allocation elimination). Distributed generation (several machines splitting
a closure) is designed here, delivered incrementally.

- Depends on: nothing functionally; benefits from v0.6 storage for
  distributing finished slices
- Open questions: on-disk pass layout (sequential sweep vs bucketed);
  compression of resident planes; whether distributed-first or
  single-machine-out-of-core-first (recommendation: out-of-core first);
  verification strategy at a scale where exhaustive cross-checks are
  impossible.

## v1.0 — Eight pieces ("humongous tablebases", part 2)

**Goal:** 8-piece generation and serving on distributed infrastructure;
partial/on-demand generation as the primary mode (full 8-piece closures are
compute-years — the value is generating *chosen* slices reproducibly).

- Depends on: v0.9's out-of-core + distributed foundation
- Open questions: hardware budget; which 8-piece materials matter to the
  composition community; public serving economics.

## Exploratory track (parallel, unversioned) — Fairy chess

**Goal:** other stipulations (h=, hs#, ser-h#, …), fairy conditions (Circe,
Madrasi, …), fairy pieces. This changes the move-generation foundation, so it
must not block the main ladder. First step is a feasibility spike: evaluate
Popeye as move generator (its licence, embeddability, speed for tablebase
workloads) vs extending ChessMG — outcome decides everything downstream.

- Depends on: nothing (separate branch of work)
- Open questions: everything — starts with its own brainstorming session.

## Backlog (unscheduled)

### Release automation — release-please, no `develop` branch

**Goal:** with outside contributors arriving, versioning and the CHANGELOG
stop being hand work, while the maintainer still decides when to release.

- Decided against a `develop` branch: `main` is already protected (six
  required checks, up to date, no force-push), and a second long-lived branch
  adds syncing and delays Pages, which deploys from `main`.
- **release-please** keeps one open release PR collecting everything merged
  since the last tag, derives the next version from commit types, and updates
  the CHANGELOG and version files; merging it tags `v*`, which the existing
  release workflow already handles. On 0.x, breaking changes bump the minor.
- Prerequisites: conventional PR titles (`feat:` / `fix:` / `docs:`) enforced
  by a PR-title check, squash-only merges, and release-please configured to
  bump every file `tests/repo/test_version_consistency.py` checks (`VERSION`,
  the three `pyproject.toml`, the two package `__version__`s, the API's
  `helpmate` pin).
- Option: deploy Pages on a release tag so the live site means "released".

### Query acceleration — indexing so `mine` stops scanning

**Goal:** selective mining queries stop reading a whole plane. 97.1% of the
corpus's 180,864 `(dtm, count)` buckets match under 0.1% of a plane; we read
100% of it to find them.

- Design: **not scheduled** —
  `docs/superpowers/specs/2026-08-08-query-acceleration-design.md`
- Settled by that design, and worth not re-litigating: **no database holds a
  cell.** SQLite, DuckDB, Parquet, RocksDB, LMDB, ClickHouse were all
  researched and measured out — the key is already the array offset, so there
  is nothing to look up, and each charges 16-19 bytes of per-row structure for
  a 4-byte row. Zone maps and skip indexes are dead here too: matching cells
  do not cluster (measured). Syzygy, Nalimov, Gaviota and Lomonosov ship point
  probers with no query layer at all, so there is no prior art to copy.
- Three layers, in order: (0) defer the count plane in `mine`'s scan and
  vectorise the predicate loop — no index, no new artifacts, and it speeds up
  the queries no index could help; (1) SQLite catalogue and planner built from
  the `uniqueness` histograms the generator already writes and nothing reads;
  (2) a tiered index whose granularity follows selectivity.
- Layers 1 and 2 are deliberately gated on Layer 0's measurements, so their
  thresholds get set against an optimised scan rather than today's.
- Subsumes the `helpmate list <dir>` item below (Layer 1's catalogue) and the
  live-result-count problem the query-surface concept could not solve.

### `helpmate list <dir>` — what is actually on disk

**Goal:** the local equivalent of the API's `/v1/materials`: material, table
version, encoding, block size, `max_dtm`, and size on disk, one line per file.

Raised 2026-08-02 while considering whether compressed tables should use a
distinct `.hmc` extension. They should not — the header already carries
`version` and `encoding`, and a filename that can disagree with its own
contents is a bug waiting to happen (`compact` already has to refuse tables
whose filename disagrees with their header material). But the impulse behind
the question was real: after converting a corpus there is no way to see at a
glance which files are compressed, short of inferring it from size. This is a
tooling gap, not a naming one.

- Depends on: nothing
- Small. Consider folding the same information into `stats` output.


### Major question 1 — smaller tables and leaner generation

Our tables are still too large: 4 bytes per cell (dtm and solution count for both
sides to move), a pawnless six-piece table is 28.9 GiB raw / ~1–3 GiB compressed,
a one-pawn one up to ~85 GiB raw / ~12.6 GiB compressed, about half of all cells
are illegal positions the dense index reserves. Open question: how far can storage
and generation be condensed? To be answered by a deep analysis that reads the
other tablebase projects' algorithms carefully (Syzygy WDL/DTZ with one side to
move, don't-care filling and per-table index ordering; Nalimov; Gaviota;
Lomonosov; bitbases; checkers databases; Bourzutschky/Konoval) and measures what
transfers to cooperative DTM plus solution counts: one stored side to move plus a
one-ply search, reduced or on-demand counts, don't-care filling of illegal cells,
better index, entropy coding, memory-lean / out-of-core generation.

Status: **analysed 2026-10-03** — `docs/research/2026-10-condensed-tables.md`. Findings:
the count planes are 66–80 % of every compressed file; counts as a 2-bit class
{0, 1, 2, 3+} (exact under the generator's rule), don't-care filling of illegal
cells and zstd 19 with larger blocks together make tables **4.8–11.6× smaller**
(corpus ≈ 341 → 45–70 GiB) by conversion, no regeneration; storing only Black to
move reaches ~16× at the cost of slower wtm probes and odd-DTM mining. A better
index helps generation RAM, not disk. Generator: 2-bit counts in RAM (−37 %), then
a bitmap frontier (~1 B/cell, every six-piece class within 32 GiB).
Proposed order: zstd-19 re-blocking (no format change) → format v4 with converter
→ optional two download tiers → generator RAM. Open decisions: keep wtm (h#n.5,
set play) in the default download? exact counts beyond "3+" needed, or on demand?
Measure one-pawn six-piece tables before committing to v4.

### Major question 2 — other stipulations

How to extend the tablebase mechanism beyond helpmates: (a) selfmate s#n,
(b) series helpmate ser-h#n, (c) direct mate #n, and further genres (reflexmate,
helpselfmate, series selfmate / series direct mate, stalemate stipulations h= s= =,
…). Needs per genre: the rules and edge cases (checks in series movers, stalemate),
the value (cooperative min/min vs adversarial min/max), the retrograde recurrence
in our generator, what "number of solutions" and soundness mean, cost; and a
common "genre" abstraction, file-format and dataset layout, verify checks, and an
order of genres by value × effort.

Status: **analysed 2026-10-03** — `docs/research/2026-10-other-stipulations.md`. Findings:
the forward-scan generator generalises with four parameters (goal, MIN/MAX per side,
alternating or series schedule, reflex/no-check obligations); adversarial genres need
no unmove generator to be correct. Soundness differs: help and series genres keep
"one solution", direct play needs a unique key (store the number of optimal moves per
node). Proposed order: genre layer (helpmate byte-identical) → h= and hs# → **ser-h#**
(half the memory, terminal = existing helpmate tables; best value for effort) → # as
validation vehicle (exhaustive Gaviota check, depth cap needed: deepest 6-man mate is
#262) → s# (no public selfmate tablebase found), r#, =, s=. Non-helpmate files as
format v4 in per-genre folders. Proof games and fairy conditions out of scope.
Open decisions: merge final promotion duals (Q/R, Q/B) in counts? depth cap for # and
s#? one Hugging Face repo or one per genre?

### Ideas from the 2026-10-03 brainstorm

Unprioritised unless noted. Agreed next small PRs are marked **next**.

**Contributors — more tables, faster**
- **next** — *Delta verify*: `verify --pr N` re-checks only tables that failed or are
  missing in the existing report and reuses the passed ones when the PR head, the file
  and the tool version are unchanged (PR #18 had to be re-verified fully, ~3 h, for one
  table). `accept` keeps trusting only a complete, consistent report.
- **next** — *Per-table progress lines in `verify`*: long PRs looked stuck.
- **next** — *Sub-table block cache fix* (analysed 2026-10-03): round the cache capacity
  up, dtm-only probes in the scan passes, thread-local zstd context (6× on KQvkr), then
  `gen --subtable-cache auto|0|N` resident sub-tables inside a RAM-guard-counted budget
  (est. 2–3× for six-piece tables on 64/96 GiB machines). After T31M's performance fork
  is merged (his PR).
- `helpmate-tables contribute KBvk???`: one command from claim to dataset PR (fetch only
  the needed sub-tables, generate, verify, push with `--claim`).
- Pull only a material's sub-table closure instead of the whole corpus.
- PyPI wheels and a Docker image for contributors (`docker run … contribute X`).
- Merge T31M's performance fork (1.5–4×; T31M opens the PR).
- Out-of-core generator for seven pieces (see v0.9).

**Trust and provenance**
- Generator commit hash / build id in every sidecar: a version string alone cannot show
  which build wrote a table.
- Second-builder confirmation: a second contributor regenerates a table; a matching
  sha256 marks it "independently confirmed".
- C++ `helpmate verify` with the internal oracle on large samples.

**Chess problems**
- Soundness check of the published-problems database (23,807 problems): verdict sound /
  cooked / longer than stated per problem in covered materials, as a site page.
- Records page: longest mate per material class, most unique positions, "the only
  position at depth N".
- Theme search across the corpus on the site.
- Problem of the day on the site, with an RSS feed.
- Exports: Popeye input, PGN/EPD per material, a LaTeX booklet per material.

**Access and reach**
- Probe in the browser: WASM reader plus HTTP range requests on Hugging Face (only the
  needed blocks), no server.
- Statistics as Parquet on Hugging Face (all sidecars in one table).
- Statistics page with charts (DTM distribution, unique share per material).
- A small public API ("is this a helpmate, how deep?") for Lichess and other tools.

**Community**
- Contributor statistics on the site (tables, CPU hours).
- Claim expiry with reminder and release (the bot only labels stale claims today).
- Write-up of the first community-computed six-piece tables and the h#17 records.

### Compression — promoted to v0.7.5

Moved out of the Backlog on 2026-08-02 after the decision spike this entry
demanded was run: block-independent zstd measured **11.4x-17.9x** on a real
6-piece plane, against the >=5x ship condition recorded here. See the v0.7.5
rung above and
`docs/superpowers/specs/2026-08-02-block-compression-design.md`, which carries
the full measurement table, the parameter choice and the performance gate
this entry defined.

The fallback this entry named -- compress for transport in
`helpmate-tables push/pull` only, at zero runtime cost -- remains the
documented outcome if the warm-probe or generation-slowdown conditions fail
in implementation.

## Standing constraints (apply to every rung)

- Correctness first: every new capability ships with the same verification
  rigor as v0.5.0 (independent cross-checks, golden tests, review gates).
- The published table format carries generator_version; format changes bump
  it and stay loadable-or-rejected via the load-time identity checks.
- Max 4 cores for local testing on the development box; heavy generation runs
  are the user's call.

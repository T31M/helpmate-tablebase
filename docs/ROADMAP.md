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

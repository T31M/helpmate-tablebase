# Internals

How the tablebase is built, stored, and checked. None of this is needed to
*use* the project — start at [USAGE.md](USAGE.md) for that. This page exists
because a tablebase is only worth as much as your reason to trust it, and
that reasoning should be public.

## Table format

Each material class is one file, `tables/<SLICE>.hm` (e.g. `tables/KQvk.hm`): a 64-byte
fixed header (magic, version, canonical material name, symmetry kind, index plane
size, max dtm) followed by a length-prefixed JSON metadata blob, followed by four
memory-mappable byte planes — DTM-white-to-move, DTM-black-to-move,
count-white-to-move, count-black-to-move — one byte per index cell, sentinel `255` for
unsolvable/invalid cells. `TableReader`/`TableWriter` (mmap-backed, atomic
write-then-rename) are the whole implementation; see
[`src/core/format/table_file.h`](../src/core/format/table_file.h) for the exact layout.

Since v0.7.5 there's a third table shape alongside the raw layout above and
the all-unsolvable marker: a **block-compressed** table (`version = 3`,
`encoding = 2`) that cuts the four planes into fixed-size blocks (64 KiB by
default, tunable per run with `--block-size`) compressed independently with
zstd, keeping random-access probing cheap while shrinking real multi-piece
tables by 9-14x on disk. Mining a compressed table costs 1.14x raw on
solution enumeration and 2.3x on a full plane scan as of v0.8.1 — the much
larger penalty documented through v0.8.0 was two fixable bugs, not a
property of compression; see [USAGE.md's Table format
section](USAGE.md#table-format) for the measured trade-off. It's opt-in
(`gen --compress`, `compact --compress`), requires a v0.7.5+ reader, and an
already-compressed table can be re-blocked to a new `--block-size` in place
without regenerating it — see USAGE.md for the full format, the measured
numbers, and the `compact --compress` conversion mechanics.

## Architecture

- **Indexing** (`src/core/indexing/`): each position maps to a dense integer index within
  its material's plane via a symmetry-reduced mixed-radix scheme. Both kings are
  indexed jointly through a precomputed non-adjacent-kings table — 1806 states for
  slices with pawns (left-right mirror symmetry only, since pawns break diagonal
  symmetry), 462 for pawnless slices (full 8-fold board symmetry, White king
  restricted to the a1-d1-d4 triangle). Every other piece indexes ×64 (×48 for a pawn,
  ranks 2-7 only — pawns never index rank 1/8). En passant is *not* indexed: whenever
  a double pawn push next to an enemy pawn is reachable, its value is folded in as
  `min(table value, 1 + value of the EP-capture successor)`, looked up in whatever
  (necessarily different-material) sub-slice table the EP capture lands in. Castling
  is out of scope entirely — no castling rights ever appear in any FEN this project
  reads or writes.
- **Generation** (`src/core/generator/`): for material `M`, first compute the closure of
  every sub-slice reachable via a capture or promotion (topologically sorted, built
  before `M` itself, since `M`'s forward-scan needs their tables to look up capture/
  promotion successors), then run an init pass (mark invalid cells; mark dtm=0 for
  every Black-to-move checkmate) followed by forward-scan fixed-point passes: pass
  `d` scans still-unresolved cells, generates their legal moves, and assigns `dtm=d`
  to any cell with a successor at `dtm=d-1`, together with its optimal-line count
  (`count(p) = Σ count(s)` over exactly those successors, saturating at 255);
  passes stop when one assigns nothing. Each pass runs on worker threads that take
  coarse tiles of the index range from a shared cursor: pass `d` only ever writes
  into cells that are still unresolved and only ever reads values below `d`, so
  there is no read/write race between threads working on different tiles of the
  same pass, and multithreaded output is required to be byte-identical to
  single-threaded output (enforced by tests). A quiet move by a lone piece or a
  king usually changes one digit of the index, so its successor's index is
  computed from the parent's instead of re-encoding the position.
- **Storage/probing** (`src/core/format/`, `src/core/probe/`): tables are written atomically
  (temp file + rename) and read back via mmap, so probing a huge table costs a page
  fault, not a full load. A compressed table is read through an LRU cache of
  decompressed blocks (up to 64 MiB per table, split into independently locked
  shards; `mine --cache-mb` sets one budget for all tables instead), with a few
  blocks per thread kept in front of it so that repeat probes take no lock.
  `Tablebase` lazily loads and caches whatever slices a query
  touches, reconstructs optimal lines by greedy descent through the dtm planes (with
  the same EP adjustment applied during descent), and falls back to a color-flip of
  the position when only the flipped slice was generated (e.g. probing `KvkQ` when
  only `KQvk` was built) — reflecting the reduced index's built-in "White always
  delivers mate" canonicalization.

## Verification story

Because the entire point of a tablebase is that its answers are trustworthy, this
project leans hard on independent cross-checks rather than trusting the generator to
grade its own homework:

- **An independent oracle.** `src/core/generator/oracle.cpp` is a from-scratch cooperative
  iterative-deepening DFS solver that shares only the move generator with the
  fixed-point generator — no shared indexing, no shared search structure. It re-solves
  sampled positions from every generated slice, checking both dtm *and* the number of
  optimal lines (which it enumerates itself, capped at 255), and any mismatch fails
  the build.
- **Exhaustive python-chess cross-validation — a third, wholly independent
  implementation.** `src/packages/bindings/tests/test_crosscheck.py::test_exhaustive_kqvk` (marked
  `slow`, run with `--run-slow`) enumerates *every one* of the 368,452 legal `KQvk`
  positions, runs a plain forward-scan BFS written directly against
  [python-chess](https://python-chess.readthedocs.io/) (no helpmate code involved in
  computing the reference values), and asserts agreement with `tb.probe()` on both
  dtm and optimal-line count for every single position, in both directions (no
  reference-solvable position reported unsolvable by the tablebase, and vice versa).
  The default (non-`slow`) suite still exercises the same movegen/perft
  cross-validation on 200 random positions and 25 random perft(3) roots every run.
- **Byte-identical multithreaded determinism.** Generation is required to produce
  identical output files whether run with 1 thread or N; this is asserted directly
  (including on `KPvkp`, a material class where en passant successors are actually
  reachable, so the multithreading story is exercised on the one code path — the EP
  two-ply lookup — whose safety depends on values already written by another slice/
  thread).
- **Golden compositions.** Known-answer positions (including the `KQvk` example
  above) are checked exactly, including their full set of optimal lines, not just
  their dtm.

## Coverage

Measured with `make coverage` (gcovr, GCC `--coverage` instrumentation, fast suite
only, on `helpmate_core`'s sources under `src/`), as CI's informational coverage job
runs it on every PR. For 0.21.0: **92.2% line coverage** (3172/3440 lines), 98.2%
function coverage, 59.6% branch coverage, 379 tests. The full per-file HTML report
is at `build-cov/coverage/index.html` after running `make coverage`.

The per-file analysis below is from the first measurement, in the 0.5.x era (91.6%
of 809 lines, 97.2% of functions, 61.8% of branches). Its biggest gaps:
`src/core/format/table_file.cpp` (85%) and `src/core/chess/board.cpp`
(90%) — mostly defensive error paths for malformed/truncated table files and rare
hash/copy edge cases; `src/core/generator/parallel.h` (68%) — the per-worker
exception-propagation path, which by design only runs when a worker thread throws,
not exercised by the happy-path tests; `src/core/generator/eval.h` (50% by gcov's line
count, but see caveat below).

Caveat worth stating plainly rather than hiding: `eval.h`'s en-passant branch and
`parallel.h`'s hot loops are both exercised by dedicated tests with exact value
assertions (`test_generator_pawns.cpp`'s "eval_board combines EP branch with table
value" calls `eval_board` directly and checks its returned dtm/count for both a
clear-winner and a tied-count case) and by real KPvk/KPvkp generation runs under
multiple threads — but GCC's `--coverage` counters are not thread-safe (a known
upstream limitation, gcc.gnu.org/bugzilla/show_bug.cgi?id=68080: concurrent
non-atomic increments to the same line counter from multiple threads can corrupt or
lose hits). This run's raw gcov output contained "suspicious hit"/negative-hit
warnings on exactly the hot, multithreaded-generator-loop lines in `board.cpp`
(silenced with `--gcov-ignore-parse-errors=all` to let gcovr complete), which is
consistent with some genuinely-executed lines in the template-heavy, multithreaded
`eval.h`/`parallel.h` code losing their counters to the same tool limitation rather
than never having run. Net effect: the reported numbers are honest
and unmodified gcovr output, comfortably above the 80% line-coverage bar either way,
but the two lowest-scoring files specifically should be read with that caveat rather
than as "half the logic is untested."

Earlier coverage runs also hit a known, separately-tracked issue: a pre-existing
heap corruption bug in the root-slice generation scan (manifesting as a SIGSEGV in
one run and a `map::at` exception in another, on different `test_probe.cpp` cases
each time — same signature independently diagnosed for a user-reported 5-piece
`KNvkqr` crash, also mentioned under [Limits](#limits) below). It is intermittent:
across four full `make coverage` attempts, two hit this bug (on a different
`test_probe.cpp` test each time) and two completed with all 64 fast-suite tests
passing cleanly end to end — including the run that produced the 91.6%/97.2%/61.8%
numbers of that first measurement (one unbroken `cmake` configure → build → `ctest` → `gcovr`
log, no separate/unlogged steps). The affected tests pass reliably and repeatedly in
the normal (`-O2`) build; the fix is tracked as a separate follow-up task and
intentionally not addressed here.

## Limits

- **Materials**: any combination of the six piece types on both sides, two to
  eight pieces including both kings. Castling is never supported (no FEN
  carrying castling rights is accepted); the 50-move rule is ignored, which is
  irrelevant to a cooperative shortest-path value; en passant is exact.

- **Scaling, measured.** Cost is set by the index plane size,
  `KK x prod(48 if pawn else 64)`, where `KK` is 462 pawnless or 1806 with
  pawns. Generation holds four bytes per cell resident, so **peak RAM equals
  the raw file size**:

  | pieces | raw table | peak RAM | wall time |
  | --- | --- | --- | --- |
  | 3-4 | KB to MB | trivial | seconds (~0.6 s for `KQvk`) |
  | 5 | 0.5-1.4 GiB | same | seconds to minutes (`KBBvkq`: 3 min on one thread, 23 s on 14) |
  | 6, pawnless | 28.9 GiB | 28.9 GiB | ~40 min on 16 threads (`KBvkqrb`; 13.5 min on 32) |
  | 6, with pawns | 35.7-84.7 GiB | same | longer, up to 3x the cells; not timed since 0.21 |

  Compression applies to storage only, never to generation: a table is built
  raw in RAM and compressed on the way out. A 96 GiB machine covers every
  6-piece material; 32 GiB covers all 286 pawnless ones.

- **Seven pieces and beyond are not reachable today.** A 7-piece class needs
  roughly 2 TB resident, far past any single machine, and would need an
  out-of-core generator that does not exist yet. The versioned encoding field
  and the slice-DAG generation order are deliberately designed so such a
  format can be added without invalidating existing tables.

- **Slow tests**: the full-closure and multithreaded-determinism tests tagged
  `[slow]` (tens of minutes each) are excluded from `make test` and from `pip
  install`'s default test run. Run them explicitly
  (`./build/helpmate_tests "[slow]"`, `pytest src/packages/bindings/tests
  --run-slow`) when you want that assurance for a new material class or after
  touching the generator.

- **One unresolved bug, stated plainly.** Coverage runs in the 0.5.x era hit
  intermittent heap corruption in the root-slice generation scan (a SIGSEGV in
  one run, a `map::at` throw in another, on different `test_probe.cpp` cases
  each time), matching a user-reported 5-piece `KNvkqr` crash. It has not been
  observed since, and none has been reported for any of the 592 tables published
  today, most of the six-piece ones computed on contributors' machines. That is strong evidence but not a
  fix: no commit claims to have closed it, and an intermittent fault that
  stops reproducing has not been proven absent. Treat a generation crash as a
  bug worth reporting, not as expected behaviour.

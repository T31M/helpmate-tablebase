# Using helpmate

The `helpmate` CLI and Python API in detail: generating tables, probing
positions, listing optimal lines, reading statistics, mining for composition
candidates — plus the exact DTM semantics, the `stats.json` field reference,
and resource guidance per piece count.

All CLI examples below are real outputs, reproduced from this repository's
test suite and README (the `8/7k/5K2/8/8/8/8/6Q1 b - - 0 1` position is the
project's golden test case).

## Concepts

### DTM semantics (plies, h#n notation)

- **dtm** is the distance to mate in **half-moves (plies)**, assuming both
  sides cooperate optimally. In a helpmate, Black moves first and helps White
  deliver mate.
- A Black-to-move position always has **even** dtm; a White-to-move position
  always has **odd** dtm (mate is a Black-to-move position with dtm 0).
- Composer notation is derived directly from dtm: a Black-to-move position
  with `dtm = 2n` is **h#n** (n Black moves + n White moves); a White-to-move
  position with `dtm = 2n+1` is **h#n.5** (White needs one extra half-move to
  deliver the actual mate). So `h#n` corresponds to `2n` plies.
- **count** is the number of *distinct* optimal lines that reach mate in the
  minimal number of plies, saturating at 255 (a stored 255 means "255 or
  more"). `count = 1` means a unique solution — what composers need for a
  sound problem; 2+ means duals.
- The byte value **255** in the tables is a sentinel for
  unsolvable/invalid cells; a slice whose *every* position is unsolvable
  (e.g. `Kvk`) reports `max_dtm=255`.

### Material names

A material string lists White's pieces in uppercase, then `v`, then Black's in
lowercase, using the letters `K Q R B N P` — e.g. `KQvk` (White king + queen
vs black king), `KBNvkq`, `KNvkqr`. Rules:

- exactly one `K` and one `k` are required;
- canonical order within each side is K, Q, R, B, N, P (the parser accepts any
  order and canonicalizes; generated files always use the canonical name);
- any combination of the six piece types, 2-8 pieces total, is accepted by the
  format (see [Resource guidance](#resource-guidance) for what is *practical*).

### Scope and rules

- **Castling is never supported**: any FEN must have `-` in the castling
  field; no FEN with castling rights is read or written.
- **En passant is exact** but not indexed: EP-dependent values are folded in
  as `min(table value, 1 + value of the EP-capture successor)` at generation
  and probe time.
- **Underpromotions are fully supported** (promotions to Q, R, B, N are all
  searched).
- The 50-move rule is ignored (irrelevant to a cooperative shortest path).

### Symmetry reduction

Positions are indexed in a symmetry-reduced dense plane. Both kings index
jointly through a precomputed non-adjacent-kings table: **462** king-pair
classes for pawnless material (full 8-fold board symmetry; White king confined
to the a1-d1-d4 triangle) and **1806** for material with pawns (left-right
mirror symmetry only, since pawns break diagonal symmetry). Every further
piece multiplies the plane by 64 (48 for a pawn — ranks 2-7 only). One
consequence: the index bakes in "White delivers mate", so probing a position
where *Black* is the mating side (e.g. `KvkQ` when only `KQvk` was generated)
is answered through an automatic **color flip** (see `probe` below).

### Table format

Every `.hm` file opens with the same 64-byte header (magic, `version`,
`encoding`, canonical material name, symmetry kind, plane size, max dtm) plus
a length-prefixed JSON metadata blob; what follows the header depends on
`version`:

- **version 1** — an ordinary table: four contiguous byte planes (DTM-white,
  DTM-black, count-white, count-black), one byte per index cell, `encoding =
  1` (raw).
- **version 2** — a **marker** table: header + JSON only, no payload at all.
  Every cell reads as unsolvable/invalid. Written when a slice's closure
  computation finds no solvable cell at all (e.g. `Kvk`); see
  [Pruning and marker tables](#pruning-and-marker-tables) below.
- **version 3** — a **block-compressed** table (since v0.7.5), `encoding =
  2`. The four planes are treated as one logical byte range, cut into
  fixed-size blocks (**64 KiB by default**, tunable via `--block-size`; see
  below), each compressed independently with zstd (level 3 by default), plus
  a `uint64` offset index and a bounded LRU cache of decompressed blocks in
  the reader (a byte budget rather than a block count, so it is independent
  of the `block_size` chosen: **64 MB per table since v0.8.1**, capped at the
  table's own logical size, and only ever filled with blocks actually
  touched). Random access is preserved — a probe decompresses at most one
  block, not the whole table.

  **Mining a compressed table used to be much slower than mining the raw
  equivalent. As of the fix described below, it is not.** Measured on a real
  462 MiB `KRvkbn` table (compressed 70.8 MiB), `taskset -c 0-3`, warm:

  | workload | before | after |
  |---|---|---|
  | full plane scan (`mine --dtm 14 --count 1`, no early exit) | **14.2x** raw | **2.3x** raw |
  | solution enumeration (`mine --dtm 8 --theme model --max 200`) | **11.8x** raw | **1.14x** raw |
  | single warm `probe` | 1.09x raw | unchanged |

  There were two independent causes, and neither was block size:

  - **A plane-wide scan read one byte per cache call.** `mine` walked the
    DTM and count planes cell by cell through `TableReader::get()`, and on a
    compressed table each such call takes the block cache's mutex and copies
    a single byte. Over a whole plane that, not the decompression, was the
    cost — decompressing both planes accounts for only ~0.2s of the 9.06s
    the scan took. Scans now go through `TableReader::read_values()`, which
    pays one lock and one memcpy per block touched.
  - **The enumeration path's working set did not fit the block cache.**
    `--theme`/`--starts`/`--ends` evaluate every legal move from a position
    to count optimal replies, and most quiet moves stay within the *same*
    material's table at cell indices with no relationship to move adjacency
    — so the access pattern is effectively random across the whole table.
    With a 4 MB cache nearly every probe missed and paid a full block
    decompression to read one byte. Raising the budget to 64 MB (see
    `kBlockCacheBytes` in `src/core/format/table_file.cpp`) took the theme
    workload from 10.74s against 0.91s raw, to 0.67s against 0.59s raw. 16
    MB already reached parity; 64 MB leaves headroom for larger materials.
    The budget is a ceiling, not a reservation: the LRU only allocates
    blocks actually touched, and that run peaked at 62 MB RSS in total. It
    is also capped per table at that table's own logical size, so a closure
    of small sub-slice tables cannot each claim the full 64 MB.

  Note that the benchmark this section used to quote — `mine KRvkbn --dtm 8
  --count 1 --max 20000` — **exits as soon as it has 20000 hits and never
  scans the plane**, so it understated the scan cost by 3x. Use a filter with
  few or no matches (`--dtm 14`) if you want to time a full scan.

  Compression ratio depends heavily on table size and block size: a real
  6-piece plane measured 14.5x at 64 KiB/level 3, and a real 5-piece table
  (`KBvkbn`) went from 462 MiB to 50 MiB end to end (9.22x) at 64 KiB. Small
  materials compress far less well — `KQvk` at 146 KB measures only 2.0x at
  64 KiB — because the fixed per-file overhead (header, JSON, a block index
  covering just 2-3 blocks) dominates a file too small to give zstd much to
  work with. This is expected, not a defect: don't read "only 2x" on a toy
  table as evidence something is broken.

  **Why the default is 64 KiB, not something smaller — a hypothesis that
  was tried and rejected, and was rejected for the right reason.** Smaller
  blocks are cheaper to decompress per cache miss, so a 16 KiB default was
  tried on the theory that it would cut the mining regression above. In
  isolation the per-block-miss numbers looked promising: 16 KiB/level 3
  gives an 11.4x ratio at ~11 us per block miss; 64 KiB/level 3 gives 14.5x
  at ~38 us — smaller blocks trade ratio for per-miss cost, so 16 KiB became
  the default for one version.

  **Measured end to end against a real table, the theory did not pan out,
  and 16 KiB was reverted before release rather than kept on the strength of
  the isolated numbers.** Reproducing the `mine --count` regression on a
  real `KRvkbn` table (462 MiB raw; closure `KRvkbn` + `KRvkb` + `KRvkn` +
  `KRvk` + `Kvk`; `helpmate mine KRvkbn --dtm 8 --count 1 --max 20000`,
  `/usr/bin/time`, two runs each):

  | table            | size (bytes)  | size    | ratio | elapsed (2 runs) | vs raw |
  |------------------|---------------|---------|-------|-------------------|--------|
  | raw               | 484,493,974  | 462.0 MiB | 1x   | 0.05s, 0.05s     | 1x     |
  | compressed, 64 KiB | 74,243,651  | 70.8 MiB  | 6.53x | 0.32s, 0.33s     | ~6.5x  |
  | compressed, 16 KiB | 81,545,441  | 77.8 MiB  | 5.94x | 0.32s, 0.33s     | ~6.5x  |

  The 16 KiB run was produced by *re-blocking* the 64 KiB table in place
  (`compact --compress --block-size 16`, see below) rather than regenerating
  it, and its bytes were confirmed identical to compressing the same raw
  table directly at 16 KiB (`md5sum` match, all four non-marker files in the
  closure). **16 KiB brought no measurable speed improvement over 64 KiB in
  this reproduction** — both ran the mining workload in ~0.32-0.33s, roughly
  6.5x the raw baseline, not the ~1.5-2x the isolated per-block-miss numbers
  predicted — **while compressing 8% worse** (77.8 MiB vs. 70.8 MiB, 5.94x
  vs. 6.53x). That is a pure loss: less compression and no measured speed
  benefit. (The original real-world report that motivated trying a smaller
  block measured 5x at 64 KiB on a slightly different 477 MB table; 6.5x
  here is the same class of regression, on different hardware/table.)

  So the default was moved back to 64 KiB — and that measurement has since
  been explained rather than merely recorded. Block size was never the
  variable: the regression was per-byte cache access on the scan and a cache
  too small for the enumeration's working set, both described above and both
  now fixed. 64 KiB remains the right default because it wins on ratio and
  the thing it was suspected of costing turned out not to be its fault.
  Re-run `tools/bench_compression.py` against your own tables if this matters
  for your workload.

**Older binaries and compressed tables.** A version-3 table is readable only
by v0.7.5+. A pre-0.7.5 binary that encounters one does not report a generic
"unreadable table" error — the version field is checked before the payload
is touched, so it reports *"table ... was written by a newer helpmate
(unsupported table format version); upgrade this build"*, same message a
future version-4+ format would produce. `gen` and `probe` both surface this
distinction (`OpenError::UnsupportedVersion` vs. `Unreadable`).

**Opting in.** `helpmate gen --compress` writes new tables directly as
version 3 instead of version 1; raw stays the default (`gen` without the
flag behaves exactly as before) — the default flips to compressed in a
later version, once the performance gate above has been re-run at larger
scale than a handful of measured materials. `helpmate compact --compress`
instead rewrites *existing* raw tables on disk to block-compressed, one file
at a time via a temp file and atomic rename, streaming off the source
table's mmap at constant memory rather than buffering all four planes (a
6-piece table's four planes are ~31 GB; the converter's own peak RSS is
12-14 MiB regardless of table size). It leaves markers and tables that are
already compressed alone, and — like plain `compact` — skips any `.hm` file
whose material doesn't match its filename. It also skips any file **written
in the last hour**, checked before the file is even opened: a multi-hour/
multi-day generation run may still be writing into the same directory, and
rewriting a table mid-write would corrupt it, so `compact --compress` simply
leaves recent files for a later run rather than risking that.

See `tools/bench_compression.py` (documented in [BUILD.md](BUILD.md)) to
re-measure any of the numbers above against your own hardware or a larger
table.

### Converting a raw corpus into a compressed one

`compact --compress` rewrites tables **in place**. To compress a directory of
raw tables into a *different* directory, leaving the originals untouched, use
`tools/compress-corpus.sh`:

```bash
tools/compress-corpus.sh -n ~/tb/raw ~/tb    # dry run: what would be done
tools/compress-corpus.sh    ~/tb/raw ~/tb    # do it
```

It stages one table at a time into a scratch directory on the destination's
filesystem, compresses it there, and moves the result across — so peak extra
disk is one table plus its output, not the size of the corpus. Tables already
present in the destination are left alone, markers are copied as-is (they have
no payload to compress), and sidecars travel with their tables.

Two safety properties worth knowing, because they are why it is shaped this
way. The source is only ever read and nothing is deleted. And the script
applies the same **one-hour rule** `compact --compress` uses — it will not
even read a table written in the last hour, because a generation run may still
be writing it. `cp -p` preserves mtimes precisely so that guard keeps working
on the staged copy; a plain `cp` would stamp everything with the current time
and the guard would then skip every file.

**Already-compressed tables need no attention.** `compact --compress` treats a
table already compressed at the requested block size as a true no-op,
deliberately, so that it never burns a decompress-and-recompress pass to
produce byte-for-byte the same blocks. Re-running the conversion over a
directory that is already done costs a header read per file and nothing else.

**Running it by accident is safe.** All four ways of misfiring it were tested:

| what you run | what happens |
|---|---|
| the same directory for `SRC` and `DST` | refuses, exit 3 |
| a `SRC` that is already compressed | copies it — `compact --compress` no-ops, so the result is byte-identical |
| the two directories reversed | every file already exists in `DST`, so all are skipped and nothing is touched |
| `-b` differing from the source's block size | re-blocks; correct, but can come out **larger**, since smaller blocks compress worse |

The property that makes those safe is that **a file already present in `DST`
is never overwritten** — it is skipped. The per-table line says which of
`compressing` / `copying` / `re-blocking` actually happened, so a run that
merely copied does not read as one that compressed.

## Getting the binary

Build per [BUILD.md](BUILD.md); the CLI lands at `./build/helpmate`. Running
`helpmate --help` prints the full usage text, every flag, and the exit codes;
`helpmate --version` prints the version (e.g. `helpmate 0.5.0`).

Common options (all subcommands): `--tables DIR` — the table directory
(default `tables`).

## `gen` — generate tables

```
helpmate gen <MATERIAL> [--tables DIR] [--threads N] [--verbose] [--progress] [--force-ram] [--compress] [--block-size N]
```

- `--threads N`: worker threads for generation (default 1). Multithreaded
  output is byte-identical to single-threaded output (enforced by tests).
- `--verbose`: per-slice lifecycle reporting on **stderr** (stdout stays
  scriptable): the closure summary (which slices, how many are missing, the
  largest missing slice with its cell count and estimated RAM vs. what is
  available), then per slice either `cached <name> (already on disk)` or
  `generating <name> (N cells)...` / `done <name> (max_dtm=D, T seconds)`.
  Implies `--progress`.
- `--progress`: per-pass progress lines on stderr while a slice is being
  generated: the init pass, every scan pass (`pass d=K resolved M cells
  (S s)`), and every count-sweep depth, each with its wall time. Reported only
  at pass boundaries from the coordinating thread, so it adds no per-cell
  overhead; useful on its own when `--verbose`'s lifecycle lines are too chatty
  for a script but you still want a heartbeat during multi-hour 5-6 piece
  passes.
- `--force-ram`: override the RAM guard. By default `gen` estimates, before
  allocating anything, the memory each missing slice needs (4 one-byte planes
  x plane size) and compares it against `MemAvailable` from `/proc/meminfo`
  (the whole closure is costed upfront, so a hopeless 7-8 piece run fails
  immediately, not after days of sub-slice generation). If a slice does not
  fit, `gen` aborts with the slice name and both sizes in GiB; `--force-ram`
  proceeds anyway (e.g. when you trust swap to absorb it). On systems without
  a readable `/proc/meminfo` the guard is skipped.
- `--compress`: write every table in this run as block-compressed (version
  3) instead of raw (version 1). Raw remains the default when the flag is
  omitted. Mining a compressed table is now close to raw speed (1.14x on
  solution enumeration, 2.3x on a full plane scan — see [Table
  format](#table-format) above for the measured numbers); the large penalty
  documented here before v0.8.1 has been fixed.
- `--block-size N`: only meaningful with `--compress`. Block size **in
  KiB** — `--block-size 64` means 64 KiB (65536 bytes), matching how the
  size/miss-cost trade-off is discussed in [Table format](#table-format)
  above. Default 64 (64 KiB, `kDefaultBlockSize`). Must be at least 4 (4
  KiB — below that a block's fixed zstd frame overhead swamps the payload)
  and at most 16384 (16 MiB, `kMaxBlockSize` — the ceiling `TableReader`
  itself enforces at `open()`, since the reader sizes its decompressed-block
  cache off this value). Out-of-range or non-positive values are rejected
  before anything is written.

Example (real output; all reporting lines on stderr, the two `.hm` result
lines on stdout as before):

```
$ helpmate gen KRvk --tables tt --threads 2 --verbose
gen KRvk: closure has 2 slice(s): Kvk KRvk
gen KRvk: 2 slice(s) to build; largest KRvk (29568 cells, ~0.00 GiB RAM; 54.16 GiB available)
generating Kvk (462 cells)...
  Kvk: init pass done (0.0 s)
  Kvk: pass d=1 resolved 0 cells (0.0 s)
  Kvk: pass d=2 resolved 0 cells (0.0 s)
done Kvk (max_dtm=255, 0.0 seconds)
generating KRvk (29568 cells)...
  KRvk: init pass done (0.0 s)
  KRvk: pass d=1 resolved 189 cells (0.1 s)
  ...
  KRvk: count sweep d=14/14 done (0.0 s)
done KRvk (max_dtm=14, 0.4 seconds)
tt/Kvk.hm max_dtm=255
tt/KRvk.hm max_dtm=14
```

And the guard refusing a slice that cannot fit (here a 7-piece root on a
64 GB machine; exit code 3, nothing was allocated or generated):

```
$ helpmate gen KQRRvkqr --tables tt
error: not enough memory to generate slice KQRRvkqr: its four value planes
need ~1848.00 GiB but only 54.17 GiB is available (MemAvailable,
/proc/meminfo); re-run with --force-ram to override
```

`gen` builds **every** table needed to answer queries about MATERIAL — the
whole closure of sub-slices reachable via captures and promotions, in
topological order, before the root slice itself (the root's scan needs the
sub-slice tables to evaluate capture/promotion successors). Each slice writes
one `<name>.hm` table plus a `<name>.stats.json` sidecar into the tables
directory. **Existing files are left alone**, so re-running after adding a new
root material is cheap, and closures shared between materials are reused
automatically.

```
$ helpmate gen KQvk --tables tt
tt/Kvk.hm max_dtm=255
tt/KQvk.hm max_dtm=14
```

`Kvk` (king vs king — unconditionally unsolvable, hence `max_dtm=255`) is
built first because a Black king capturing the queen lands there; `KQvk`
itself tops out at `max_dtm=14`, i.e. the longest optimal helpmate in this
material is `h#7`. A re-run prints
`nothing to do: all tables for KQvk already exist in tt`.

## `probe` — look up one position

```
helpmate probe <FEN> [--tables DIR] [--themes]
```

```
$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
dtm=2 (h#1) count=4
```

Output is `dtm=<plies> (<h#-notation>) count=<optimal lines>`. For a legal
but unsolvable position it prints `unsolvable` (still exit 0). If the
position's own slice is missing but the color-flipped slice exists, the probe
transparently flips colors and annotates the output
(`dtm=2 (h#1, colors flipped) count=4`).

- `--themes`: also print which named themes (see [Themes](#themes) below) the
  position's optimal solutions show. Opt-in — detection forces solution
  enumeration, work a plain probe does not otherwise pay for:

```
$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt --themes
dtm=2 (h#1) count=4
themes: set-play pure model ideal mirror single-piece single-piece:white single-piece:black nocapture nocheck
```

  A position with no themes prints `themes: (none)`. A color-flipped probe
  (see above) cannot show themes at all — the detectors are hard-coded to the
  black king, so a flipped position's colour-labelled themes would come out
  swapped — and prints `themes: (unavailable: colors were flipped to find a
  table)` instead, still at exit 0.

## `line` — print optimal lines

```
helpmate line <FEN> [--tables DIR] [--all] [--max N]
```

- `--all`: print *every* optimal line, one per output line;
- `--max N`: cap on lines printed with `--all` (default 10); `--max infinity`
  (or `inf`) lifts it here too, since the flag is shared with `mine`.

```
$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt
Kh6 Qh2#

$ helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables tt --all
Kh6 Qh2#
Kh6 Qh1#
Kh6 Qg6#
Kh8 Qg7#
```

Moves are SAN. Lines are reconstructed by greedy descent through the dtm
planes (with the same en-passant adjustment applied during descent), so the
count of `--all` lines matches `probe`'s `count` (up to the `--max` cap). For
an unsolvable position — or one that is *already* checkmate, where there are
no moves to print — it prints
`unsolvable (or already mate: no line to print)` (exit 0). Note: unlike
`probe`, `line` has **no color-flip fallback** — it needs the position's own
slice generated, and exits 2 with the exact `helpmate gen` command otherwise.

## `stats` — generation statistics

```
helpmate stats [MATERIAL] [--tables DIR]
```

**With no MATERIAL**, prints a summary of every table in `--tables DIR` —
what is on disk, in what format, and what is in it. Header fields come from
each `.hm`; cell counts come from the `<Material>.stats.json` sidecars, which
are generation-time truth and cheap to read.

```
$ helpmate stats --tables ~/tb
/home/os/tb

Files
  98 readable .hm: 61 table(s), 37 all-unsolvable marker(s)
  format: 61 block-compressed (v3) [61 at 64 KiB], 0 raw (v1)
  on disk: 9.81 GiB
  compressed tables: 9.81 GiB on disk from 83.49 GiB of planes (8.51x)
  by piece count:  2:1  3:10  4:40  5:43  6:4

Positions (from 98 sidecar(s))
  plane cells                78,578,630,172
  invalid                    19,984,889,649    25.4%
  unsolvable                 38,062,458,684    48.4%
  solvable                   20,531,281,839    26.1%
  unique (count==1)             216,123,629     1.1%
  (percentages are of plane cells, except unique, which is of solvable)

Mate length
  deepest: dtm 34 (h#17) in KBvkqp

Largest tables
  KBvkqrn  3.32 GiB  (compressed, 64 KiB blocks)
  ...

Generated by: 0.1.0 0.5.0 0.6.1 0.6.2
```

The compression line is the honest whole-corpus ratio: bytes on disk against
`4 × plane_size` of logical planes, so it is directly comparable with the
per-table figures in [Table format](#table-format) above. Notes worth reading
off it: markers are counted separately because they have no payload to
measure; a table whose sidecar is missing still contributes its size and
format but is excluded from the cell breakdown, and the header says how many
such tables there were, so the summary never quietly reports a smaller
corpus than exists.

An empty or nonexistent directory is an error (exit 3), not a report of a
zero-table corpus — the likeliest cause is a mistyped `--tables`.

**With a MATERIAL**, prints the complete generation-time statistics JSON for
that material class (the same content as the `<name>.stats.json` sidecar
written by `gen`):

```
$ helpmate stats KQvk --tables tt
{
  "material": "KQvk",
  "plane_size": 29568,
  "max_dtm": 14,
  "cells": { "invalid": {...}, "unsolvable": {...} },
  "dtm_histogram": { "wtm": {...}, "btm": {...} },
  "uniqueness": { "wtm": {...}, "btm": {...} },
  "deepest": [ "8/6k1/5Q2/8/8/8/8/K7 b - - 0 1", ... ],
  "deepest_unique": [ "8/8/7k/6Q1/8/8/8/K7 b - - 0 1", ... ],
  "generator_version": "0.5.0"
}
```

### `stats.json` field reference

Throughout, `wtm`/`btm` = White/Black to move; per-plane cell values are keyed
by side to move.

| Field | Meaning |
|---|---|
| `material` | canonical material name of the slice. |
| `plane_size` | number of index cells per plane (the symmetry-reduced position count per side to move; e.g. 29568 = 462 king-pair classes × 64 queen squares for `KQvk`). |
| `max_dtm` | deepest dtm in the slice, in plies; `255` if nothing in the slice is solvable (sentinel). |
| `cells.invalid.{wtm,btm}` | cells whose index decodes to no legal position for that side to move (e.g. side not to move in check, coincident squares). |
| `cells.unsolvable.{wtm,btm}` | legal positions from which no cooperative mate exists. |
| `dtm_histogram.{wtm,btm}` | object mapping dtm (as a string key) → number of positions with exactly that dtm. Depths with zero positions are omitted. |
| `uniqueness.{wtm,btm}` | object mapping dtm → (optimal-line count → number of positions): how many positions at each depth have exactly 1, 2, 3, … optimal solutions. Counts saturate at 255 ("255" = 255 or more). The `"1"` entries are the sound-composition candidates. |
| `deepest` | **a sample, capped at 5 FENs**, of positions at `max_dtm` (side to move follows dtm parity: odd = White to move, even = Black to move). |
| `deepest_unique` | **a sample, capped at 5 FENs**, of positions with a *unique* solution (`count = 1`) at the greatest depth where any such position exists (searching downward from `max_dtm`). |
| `generator_version` | version string of the generator that wrote the slice. |

**Important**: `deepest` and `deepest_unique` are illustrative *samples* (at
most 5 FENs each, taken in index order) — they are not exhaustive lists. The
complete, exact data lives in `dtm_histogram` and `uniqueness`; use `mine` to
enumerate the actual positions at any (dtm, count).

## `mine` — scan for composition candidates

```
helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N] [--theme NAME]... [--max N|infinity] [--themes] [--solutions] [--json|--jsonl] [--interactive] [--tables DIR]
```

- `--dtm D` (**required**): exact distance-to-mate, in plies, to match;
- `--count C` (optional): additionally require exactly C optimal solutions;
- `--starts N` (optional): additionally require exactly N *distinct first
  moves* across the optimal solutions — i.e. how many different ways White
  can begin the mate, ignoring how each one finishes;
- `--ends N` (optional): additionally require exactly N *distinct mating
  moves* across the optimal solutions — i.e. how many different final moves
  deliver mate, ignoring how each one got there;
- `--theme NAME` (optional, repeatable): additionally require that at least
  one optimal solution shows theme NAME; every named theme must be shown
  (by some solution, not necessarily the same one). The two set-wide themes,
  `nocapture` and `nocheck`, are the exception: they hold only when **every**
  optimal solution qualifies; `zilahi` and `allumwandlung` compare solutions
  with each other. A parametric theme takes its value after a colon:
  `--theme promotions:qrr`. See [Themes](#themes)
  below for the full semantics, the theme list, and the performance caveat —
  theme filters force solution enumeration and cost noticeably more than a
  plain `--dtm`/`--count`/`--starts`/`--ends` scan;
- `--max N`: cap on positions (default 10); `--max infinity` (or `inf`) lifts
  the cap;
- `--themes`: annotate every hit with all the themes it shows (every
  non-parametric theme; `promotions:<types>` is asked for with `--theme`);
- `--solutions`: print every optimal solution of each hit as SAN;
- `--json`: emit one JSON document instead of text (below);
- `--jsonl`: emit JSON Lines instead: a header line, one object per position
  streamed as the scan finds it, a footer line with the counts (below);
- `--interactive` (alias `--tui`): after the scan, open a shell over the
  result (below).

`--starts`/`--ends` are exact-match filters, evaluated (cheaply) only for
positions that already matched `--dtm`/`--count` — a position that matches
`--dtm 2 --count 4` but has 3 distinct first moves is excluded by `--starts
2` just as surely as one with the wrong `--dtm`. Both must be `>= 1`, and if
`--count` is also given, each must be `<= --count` (a position with C
solutions cannot have more than C distinct starts or ends); violating either
rule is a usage error (exit 3), not a silently empty result — including a
literal `-1`, which is otherwise a value `--starts`/`--ends` could take.

Prints matching FENs one per line, scanning the slice's index planes (an O(1)
table read per cell — no search):

```
$ helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables tt
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
8/8/8/8/8/2Q5/8/k1K5 b - - 0 1
8/8/8/8/4Q3/8/8/k1K5 b - - 0 1
```

(three `h#1` positions with a *unique* solution — raw material for a sound
one-line composition; `--dtm 2 --count 2` would list positions with exactly
one dual, etc.)

`--starts`/`--ends` narrow this further to a specific *shape* of dual: take
`8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` (`dtm=2, count=4`), whose four optimal
lines are `Ka1 Qb2#`, `Kc1 Qg1#`, `Kc1 Qh1#`, `Kc1 Qc2#`. Only two distinct
first moves appear (`Ka1`, `Kc1` — one of them, `Kc1`, has three tries), but
all four mating moves are distinct, so this position has `starts=2, ends=4`:

```
$ helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 3 --tables tt
8/8/8/8/8/2K5/4Q3/1k6 b - - 0 1
8/8/8/8/8/2K5/7Q/1k6 b - - 0 1
```

(the second FEN printed is the position above, in its canonical — i.e.
symmetry-reduced — form; `mine` always prints canonical FENs, which need not
match the FEN a query used to reach the same position.)

If any matched position's solution count is *saturated* (stored as 255+,
meaning the true count is unenumerable — see [DTM
semantics](#dtm-semantics-plies-hn-notation)), it can't be checked against
`--starts`/`--ends`/`--theme` and is skipped rather than guessed at (a
`--theme`-only query, with neither `--starts` nor `--ends` given, skips and
tallies these exactly the same way); `mine` tallies these and, if any were
skipped, prints a note to stderr when it exits:

```
note: skipped N position(s) whose solution count is saturated (255+): their
solutions cannot be enumerated exhaustively
```

(`KQvk` has no saturated-count positions, so this note never fires for the
examples above; it applies to richer material classes where hundreds of
optimal replies can tie.)

### Annotated text output

With `--themes` and/or `--solutions` each hit becomes a block: the FEN, an
indented `themes:` line, one indented line per solution, then a blank line.
The bare FEN list is `grep -v '^ ' | grep .` away.

```
$ helpmate mine KQvk --dtm 2 --max 2 --themes --solutions --tables tt
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
  themes: set-play pure model ideal mirror single-piece single-piece:white single-piece:black nocapture nocheck
  Ka2 Qa4#

8/8/8/8/8/2Q5/8/k1K5 b - - 0 1
  themes: single-piece single-piece:white single-piece:black nocapture nocheck
  Ka2 Qb2#

```

A hit whose solutions reach a material this `--tables` directory lacks
prints `  unavailable: <reason>` instead, and `mine` prints one note with the
`gen` command that fixes it.

### JSON output

`--json` prints one object. `fen`, `dtm`, `count` are always present per
position; `themes` needs `--themes`; `starts`, `ends`, `solutions` need
`--solutions`. `max` is the integer given or `"infinity"`. The filter block
repeats what was asked, `-1` meaning "not filtered". A position whose
solution count is saturated carries `"exhaustive": false` and no
`starts`/`ends` (they are not countable) — its `solutions` are the first 100.

```
$ helpmate mine KQvk --dtm 2 --max 1 --json --themes --solutions --tables tt
{
  "material": "KQvk",
  "filter": {"dtm": 2, "count": -1, "starts": -1, "ends": -1, "themes": []},
  "max": 1,
  "skipped_saturated": 0,
  "positions": [
    {
      "fen": "8/8/8/8/8/8/8/k1KQ4 b - - 0 1",
      "dtm": 2,
      "count": 1,
      "themes": ["set-play", "pure", "model", "ideal", "mirror", "single-piece", "single-piece:white", "single-piece:black", "nocapture", "nocheck"],
      "starts": 1,
      "ends": 1,
      "solutions": [["Ka2", "Qa4#"]]
    }
  ]
}
```

### JSON Lines output

`--jsonl` is the same data as `--json`, one object per line, for results too
large to parse as a single document. Line 1 is the header: the top-level keys
of `--json` minus the array (`material`, `filter`, `max`). Then one line per
position, byte-for-byte the record `--json` puts in `positions[]`, with the
same optional fields under the same flags. The last line is the footer,
`{"positions": N, "skipped_saturated": M}`. A reader tells the three apart by
their keys: a position has `fen`, the header has `material`, the footer has
`positions`. `jq -c 'select(.fen)'` yields the positions alone.

```
$ helpmate mine KQvk --dtm 2 --max 1 --jsonl --themes --solutions --tables tt
{"material":"KQvk","filter":{"dtm":2,"count":-1,"starts":-1,"ends":-1,"themes":[]},"max":1}
{"fen":"8/8/8/8/8/8/8/k1KQ4 b - - 0 1","dtm":2,"count":1,"themes":["set-play","pure","model","ideal","mirror","single-piece","single-piece:white","single-piece:black","nocapture","nocheck"],"starts":1,"ends":1,"solutions":[["Ka2","Qa4#"]]}
{"positions":1,"skipped_saturated":0}
```

Unlike `--json`, `--jsonl` streams: each position is probed, annotated and
written the moment the scan finds it, and nothing is held in memory, so a
`--max infinity` scan of a large class costs a constant amount of RAM
however many hits it has. That is also why the counts are in the footer
rather than the header: a writer only knows them at the end. A file without
a footer was cut short. `--json` and `--jsonl` are mutually exclusive.

### Interactive mining

`--interactive` runs the scan once, keeps the hits in memory, and opens a
prompt. Nothing rescans the table: narrowing, tallies and `show` work on the
held set, computing each position's themes and solutions the first time they
are needed and caching them. The prompt (on stderr) shows the current size.

| Command | Effect |
|---|---|
| `theme NAME` | keep positions showing NAME (`promotions:qrr` works too) |
| `not theme NAME` | drop positions showing NAME |
| `count N`, `starts N`, `ends N` | keep positions with exactly that value |
| `back` | undo the last narrowing; `reset` returns to the loaded set |
| `list [FROM [N]]` | print FENs FROM..FROM+N-1 with their index (default 1, 20) |
| `show I` | FEN, themes and every solution of hit I |
| `themes` | how many positions in the current set show each theme |
| `save FILE` | `.json`: the JSON document above; `.jsonl`: the JSON Lines form (header, records, footer); both with themes if known for the whole set or `--themes` given, solutions if `--solutions` given; anything else: bare FENs |
| `help`, `quit`, `exit` | (EOF quits too) |

Only a lowercase `.json` suffix selects JSON output for `save`; `FILE.JSON`
or `FILE.json.gz` writes bare FENs. The rest of the line after `save` is the
path, spaces and all, so `save my hits.json` writes `my hits.json`.

```
$ helpmate mine KQvk --dtm 2 --max infinity --interactive --tables tt
loaded 580 positions (KQvk dtm=2)
[580] mine> theme mirror
477 positions
[477] mine> count 1
257 positions
[257] mine> show 1
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
  themes: set-play pure model ideal mirror single-piece single-piece:white single-piece:black nocapture nocheck
  Ka2 Qa4#
[257] mine> save mirror-unique.json
saved 257 positions to mirror-unique.json (json, themes)
[257] mine> quit
```

Stdout carries only results, so `helpmate mine ... --interactive < script > out`
gives a clean file. There is no line editing; use `rlwrap helpmate ...` for
history. `back` keeps whole copies of each previous set, which for a
100k-position root and a deep stack is tens of MB.

## Themes

Since v0.8.0, `mine`, `probe` and the HTTP API can search and annotate by
**theme** — a named, precisely defined property of a mate (`pure`, `model`,
…) or of a solution's moves (`promotion`, `switchback`, …). Naming follows
the [Helpmate Analyzer glossary](https://helpman.komtera.lt/themes.html)
(Viktoras Paliulionis) wherever a name already exists there, so results are
comparable with established practice. `helpmate themes` always prints the
authoritative, in-build list below — read that if this table and the binary
you're running ever disagree.

Thirty-three registry entries cover twenty-eight themes. Five themes exist in
more than one form (`excelsior`/`excelsior:white`/`excelsior:black`,
`single-piece`/`single-piece:white`/`single-piece:black`, and
`maslar`/`maslar:black-white`, whose second form swaps the colours' roles)
because a detector only ever answers yes/no — it cannot itself report *which*
side showed the theme, so each form is a separate registry entry rather than
an extra output field. Castling themes are absent for a structural reason:
no table holds a castling move (see [Scope and rules](#scope-and-rules)). Four entries describe the whole
solution set rather than one line in it: `nocapture` and `nocheck` match
only when every optimal solution qualifies, `zilahi` and `allumwandlung`
compare solutions with each other — see
[Match semantics](#match-semantics-any-within-a-theme-and-across-themes)
below. One entry, `promotions:<types>`, is **parametric**: it is asked with a
value, `--theme promotions:qrr`, and `probe` prints the position's combined
promotion multiset as one `promotions:<value>` — see
[Parametric themes](#parametric-themes-a-name-with-a-value) below.

Real output, `./build/helpmate themes` on this checkout:

```
$ helpmate themes
set-play
    needs: plane
    Set play: the same position with the other side to move is solvable one
    move sooner (sibling dtm == this position's dtm - 1) -- the mate is
    already available and the side to move merely delays it. A sibling one
    move LONGER is the opposite of set play, not set play.
pure
    needs: solutions
    Pure mate: every square of the black king's field is unavailable for
    exactly one reason, and the king's square is attacked exactly once (so
    double check is impure).
model
    needs: solutions
    Model mate: pure, and every white unit except the king and pawns
    participates -- attacks the king's square or a field square, or stands
    on one.
ideal
    needs: solutions
    Ideal mate: model with no exemptions -- the white king and white pawns
    must participate too, and every black unit other than the king must
    stand on a field square.
mirror
    needs: solutions
    Mirror mate: every square adjacent to the black king is empty, of either
    colour.
promotion
    needs: solutions
    A pawn promotes during the solution.
underpromotion
    needs: solutions
    A pawn promotes to rook, bishop or knight.
excelsior
    needs: solutions
    A pawn standing on its own second rank at the start of the solution
    promotes during it (either colour).
excelsior:white
    needs: solutions
    Excelsior by a white pawn.
excelsior:black
    needs: solutions
    Excelsior by a black pawn.
switchback
    needs: solutions
    A unit leaves a square and returns to it, having visited exactly one
    intermediate square.
closed-walk
    needs: solutions
    Rundlauf: a unit returns to its departure square having visited two or
    more distinct intermediate squares, so it traverses a circuit rather
    than retracing its path.
self-block
    needs: solutions
    A black unit other than the king moves onto a square of its own king's
    field and stands there unattacked in the mating position, blocking a
    flight square.
single-piece
    needs: solutions
    Every move by one side is made by the same unit (either side).
single-piece:white
    needs: solutions
    Every white move is made by the same unit.
single-piece:black
    needs: solutions
    Every black move is made by the same unit; with the king, this is the
    Analyzer's 'BK moves only'.
en-passant
    needs: solutions
    A ply is an en-passant capture.
kniest
    needs: solutions
    Kniest: a unit is captured on the square where the black king is later
    mated.
zajic
    needs: solutions
    Zajic: a unit is captured on the square where the black king is mated,
    and the king recaptures there.
phoenix
    needs: solutions
    Phoenix: a unit is captured and a pawn of the same colour later promotes
    to that same type.
schnoebelen
    needs: solutions
    Schnoebelen: a promoted unit is captured on its promotion square without
    ever having moved.
pendulum
    needs: solutions
    Pendulum: a unit oscillates between exactly two squares, returning at
    least twice.
nocapture
    needs: solutions
    No capture: no unit is captured in any optimal solution (en passant
    included). Holds only when EVERY solution is capture-free, unlike the
    themes above, which match when any one solution shows them.
nocheck
    needs: solutions
    No check: no move gives check in any optimal solution except the last
    move of each solution, the mate itself. Holds only when EVERY solution
    is check-free before its final move, unlike the themes above, which
    match when any one solution shows them.
umnov
    needs: solutions
    Umnov: a unit moves onto the square the opponent's immediately preceding
    move vacated.
umnov-mate
    needs: solutions
    Umnov mate: the mating move lands on the square Black's last move
    vacated.
klasinc
    needs: solutions
    Klasinc: a unit leaves square a, a line piece (queen, rook or bishop,
    either colour) later moves along a line that passes over a, and after
    that the first unit returns to a.
zilahi
    needs: solutions
    Zilahi: two solutions and two white units X and Y such that X gives mate
    in one solution and is captured in the other, while Y gives mate in the
    second and is captured in the first. Units are identified by their
    diagram square; a promoted pawn keeps its identity; in a battery mate
    the unit that moved is the mating unit. On a saturated position only the
    first 100 solutions are compared.
allumwandlung
    needs: solutions
    Allumwandlung (AUW): across the position's optimal solutions, pawns
    promote to all four types -- queen, rook, bishop and knight -- either
    colour, in any number of solutions. The same question as
    promotions:qrbn.
promotions:<types>
    needs: solutions
    Promotions: taking the promotions of all optimal solutions together, at
    least these types occur, with multiplicity, either colour --
    promotions:qrr needs one queen and two rooks among them (q and r in one
    solution and r in another, or all three in one), and further promotions
    may occur. Letters q r b n in any order; a multiset, not a sequence.
    probe prints the position's full combined multiset as one
    promotions:<types> entry. On a saturated position only the first 100
    solutions are counted.
    parameter types (e.g. promotions:qrr): one letter per promotion
    required, q r b n in any order and case, up to eight; a multiset, so qrr
    asks for one queen and two rooks among the promotions of all solutions
    together and rq is the same as qr; further promotions may occur
indian
    needs: solutions
    Indian: a line piece crosses a critical square, a unit of its own colour
    then interferes on that square, and later that unit moves away giving
    discovered check from the line piece along the line through the square.
    Either colour.
maslar
    needs: solutions
    Maslar: a white line piece plays a critical move along the thematic
    line, a black unit interferes on the crossed square, the black king then
    arrives on the line beyond it, and the white piece captures the
    interfering unit giving check (or mate).
maslar:black-white
    needs: solutions
    Black-White Maslar: Black makes the critical move with a line piece,
    White interferes on the crossed square, and the black line piece finally
    captures the interfering white unit.
```

### `needs`: what a theme actually reads

Every theme declares a `needs` field, one of three values, in increasing
order of what a query has to do to answer it:

| `needs` | What the detector reads | Consequence for `mine` |
|---|---|---|
| `position` | The diagram alone (the starting position, before any move). | No solution enumeration at all — the position is decoded and the detector runs directly on it. Answers even when the position's solution count is saturated (255+), which every `solutions`-needing theme below must skip. |
| `plane` | One extra byte already read during the scan: the sibling side-to-move plane's value at the same cell index. | Same as `position` — no enumeration, saturation is not a problem. |
| `solutions` | The full set of optimal solutions, which must be enumerated. | This is the pre-v0.9 behaviour: enumeration is forced, and a saturated position can never be answered because its exact solution set is unknowable. |

Currently `set-play` is the only `plane` theme; every other theme needs
`solutions` — including `nocapture` and `nocheck`, which must see the whole
solution set to say that *every* line qualifies. No theme in the registry currently needs only `position`: the
one candidate, `homebase`, was added and then removed during this same
release, because it is not invariant under the tablebase index's symmetry
group (see the CHANGELOG's "Fixed (branch review)" entry for the full
mechanism). That failure establishes a real constraint on any future
`Needs::Position` theme: it must be invariant under the index's symmetry
group, or `mine` cannot answer it correctly. When **every** theme named in a
query needs only `position` and/or `plane`, `mine` skips solution
enumeration entirely for that query — this is a capability change, not a
speed optimisation: it makes `mine --theme set-play` answer on positions
that `mine --theme pure` (or any other solutions-needing theme) silently
skips via the saturation cap, described further under [Two things to know
before you trust a result](#two-things-to-know-before-you-trust-a-result)
below. It does **not** mean these queries run at "scan speed" — evaluating
a plane theme still requires materialising the position (decode +
`Board::from_pieces`), so the floor is decode speed. Measured on
`KRvkbn --dtm 8` (31.5M candidates, zero matches): 26 seconds, down from an
initial 51 seconds once `fen` construction was made lazy for the
non-matching path. The number that matters is the comparison against
actually enumerating those same 31.5M candidates' solutions, which was
measured at over 100 hours — `set-play` turns a query that was previously
unanswerable at any speed into one that finishes in well under a minute,
which is the headline, not the seconds-level speed figure itself. That
mechanism is real and verified for `set-play` — see the worked examples
below.

### v0.9.1: `set-play`'s definition changed — a behaviour change to a released theme

`set-play` shipped in v0.9.0 meaning "the same position with the other side to
move is solvable, at any distance." That reading is nearly vacuous — on
`KQvk --dtm 2` it matched **423 of 580** positions (72.9%) — and it conflated
two opposite things. With the position's own distance called D, and its
sibling's distance called D′ (D′ is always D − 1 or D + 1, never D — parity
forbids a tie):

- **D′ = D − 1** — the mate is already available one move sooner; the side to
  move merely delays it. This **is** set play.
- **D′ = D + 1** — flipping the side to move makes the mate *longer*. This is
  the **opposite** of set play, and v0.9.0 reported it anyway.

As of v0.9.1, `set-play` means **the sibling plane is solvable at exactly
D − 1**. On the same query this drops the match count from 423 to **183**
(31.6% of the 580, not 72.9%): 183 true D − 1 hits, and the 240 D + 1 hits
that were previously reported incorrectly are now excluded (423 − 183 = 240).
The "any shorter distance" reading some compositional literature also calls
set play — a sibling solvable well before D − 1 — is a separate notion (the
glossary's *Short set play*) and is not implemented by any theme here.

Both directions, worked:

```
$ helpmate probe "8/8/8/8/8/8/8/k1KQ4 b - - 0 1" --themes --tables ~/tb
dtm=2 (h#1) count=1
themes: set-play pure model ideal mirror single-piece single-piece:white single-piece:black nocapture nocheck
$ helpmate probe "8/8/8/8/8/8/8/k1KQ4 w - - 0 1" --tables ~/tb
dtm=1 (h#0.5) count=1
```

D = 2 (`Ka2 Qa4#`), sibling D − 1 = 1 (`Qa4#` immediately) — `set-play` fires.

```
$ helpmate probe "8/8/8/8/8/8/k7/2K1Q3 b - - 0 1" --themes --tables ~/tb
dtm=2 (h#1) count=1
themes: pure model ideal mirror single-piece single-piece:white single-piece:black
$ helpmate probe "8/8/8/8/8/8/k7/2K1Q3 w - - 0 1" --tables ~/tb
dtm=3 (h#1.5) count=28
```

D = 2 (`Ka1 Qa5#`), sibling D + 1 = 3 (`Kc2 Ka3 Qa5#`, 28 solutions) —
`set-play` does **not** fire; under v0.9.0 it incorrectly did.

### The six v0.9 themes: real examples, honestly reported

Real, verified output for three of the six — real, hand-derived FENs
against `~/tb`, cross-checked with `probe --themes` the same way the
pre-v0.9 table above was built:

```
$ helpmate mine KQvk --dtm 2 --theme set-play --max 3 --tables ~/tb
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
8/8/8/8/1Q6/8/8/k1K5 b - - 0 1
8/8/8/8/4Q3/8/8/k1K5 b - - 0 1

$ helpmate mine KQvk --dtm 8 --theme pendulum --max 3 --tables ~/tb
8/8/8/8/8/8/8/KQk5 b - - 0 1
8/8/8/8/8/8/1Q6/K1k5 b - - 0 1
8/8/8/8/8/1Q6/8/K1k5 b - - 0 1
note: skipped 4 position(s) whose solution count is saturated (255+): their solutions cannot be enumerated exhaustively

$ helpmate probe "k7/7n/1K6/8/8/8/1p6/7R w - - 0 1" --themes --tables ~/tb
dtm=3 (h#1.5) count=27
themes: set-play pure model mirror promotion underpromotion single-piece single-piece:white single-piece:black phoenix
```

(That KRvknp output was captured before `nocapture` and `nocheck` existed
and has not been re-run — the table was not to hand. `nocapture` cannot
appear on it, because `phoenix` requires a capture; whether `nocheck` does
is not known.)

```
$ helpmate probe "4k3/8/8/8/8/8/8/3QK3 b - - 0 1" --themes --tables ~/tb
dtm=8 (h#4) count=78
themes: pure model ideal mirror single-piece single-piece:black nocapture
```

(This last position is itself a small illustration of the v0.9.1 fix above:
its sibling is at dtm=9 — D + 1, not D − 1 — so as of v0.9.1 `set-play` no
longer appears in its theme list, where it incorrectly did under v0.9.0's
"solvable, full stop" definition.)

### `nocapture` and `nocheck`: real examples

Both are `every`-solution themes (see [Match
semantics](#match-semantics-any-within-a-theme-and-across-themes) below), and
that shows in the numbers. Measured against freshly generated `KQvk` and
`KQvkr` tables:

| Query | Matches | of which enumerable | `nocapture` | `nocheck` | both |
|---|---|---|---|---|---|
| `KQvk --dtm 8` | 9197 | 3924 (5273 saturated, skipped) | 3924 | 819 | 819 |
| `KQvkr --dtm 4` | 357,472 | 346,094 (11,378 saturated, skipped) | 267,132 | 178,467 | — |

In `KQvk` every enumerable position is `nocapture`, and necessarily so: Black
has nothing but a king, and a king that takes the queen has ended the mate,
so no optimal line can capture. That makes `KQvk` useless as a test of the
theme and `KQvkr` the honest one — a black rook is exactly the unit an
optimal line may sacrifice. `nocheck` is the rarer property in both classes:
at `KQvk --dtm 8` fewer than a quarter of the enumerable positions get to the
mate without an intermediate check.

Three `KQvkr` h#2 positions, one per case:

```
$ helpmate probe "8/8/8/8/8/8/8/K1kr1Q2 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=9
themes: set-play switchback self-block single-piece single-piece:white single-piece:black nocapture nocheck
$ helpmate line "8/8/8/8/8/8/8/K1kr1Q2 b - - 0 1" --tables ~/tb
Re1 Qe2 Rd1 Qb2#
...

$ helpmate probe "8/8/8/8/8/8/2r5/KQk5 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=1
themes: switchback single-piece single-piece:white single-piece:black nocapture
$ helpmate line "8/8/8/8/8/8/2r5/KQk5 b - - 0 1" --tables ~/tb
Kd2 Qb4+ Kc1 Qe1#

$ helpmate probe "8/8/8/8/8/k3Q3/3r4/1K6 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=1
themes: single-piece single-piece:black nocheck
$ helpmate line "8/8/8/8/8/k3Q3/3r4/1K6 b - - 0 1" --tables ~/tb
Rd3 Kc2 Rb3 Qxb3#
```

The first shows both: all nine solutions are quiet until the mate. The
second is `nocapture` but not `nocheck` — its one solution passes through
`Qb4+`. The third is `nocheck` but not `nocapture` — the rook is sacrificed
and the mate is the capture `Qxb3#`. For the first position, nine solutions
all had to be capture-free and check-free; for a set-wide theme one
exception anywhere in the set would have removed the name.

### `umnov`, `klasinc`, `promotions:<types>`: real examples

Against the same freshly generated `KQvkr` table, plus a `KPvk` one for the
promotion family:

```
$ helpmate probe "8/8/8/8/8/8/4r3/K1k2Q2 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=9
themes: self-block single-piece single-piece:white single-piece:black nocapture nocheck umnov
$ helpmate line "8/8/8/8/8/8/4r3/K1k2Q2 b - - 0 1" --tables ~/tb
Re1 Qe2 Rd1 Qb2#
```

`umnov`: the black rook leaves e2 and the white queen lands on it at once.
Not `umnov-mate` — the mate lands on b2, which nobody has just left. At
`KQvkr --dtm 4` no enumerable position shows `umnov-mate` at all; at h#2
Black's last move is a king move next to the mating square, not onto it.

```
$ helpmate probe "8/8/8/8/8/8/Q2r4/1K1k4 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=67
themes: set-play switchback self-block single-piece single-piece:white single-piece:black nocapture klasinc
```

`klasinc`, from one of the 67 solutions (`helpmate.Tablebase.lines`):
`Rd3 Qf2 Rd2 Qf1#` — the rook clears d2, the queen runs a2–f2 *over* d2,
the rook returns to d2 (a switchback, hence that theme too), and the queen
mates. The printed `line` picks another solution, `Ke1 Qc4 Kd1 Qf1#`, which
is why `any` semantics matter here.

```
$ helpmate probe "8/P7/8/8/8/1k6/8/1K6 b - - 0 1" --themes --tables ~/tb
dtm=4 (h#2) count=2
themes: pure model ideal mirror promotion underpromotion single-piece single-piece:black nocapture nocheck promotions:qr
$ helpmate line "8/P7/8/8/8/1k6/8/1K6 b - - 0 1" --tables ~/tb
Ka3 Kc2 Ka2 a8=R#

$ helpmate mine KPvk --dtm 4 --theme promotions:qr --max 3 --tables ~/tb
8/P7/8/8/8/1k6/8/1K6 b - - 0 1
8/P7/8/8/k7/8/8/1K6 b - - 0 1
8/P7/8/8/1k6/8/8/1K6 b - - 0 1
```

Two solutions, one promoting to a rook and one to a queen, so the
position's combined multiset is `qr`, which `probe` prints once; `--theme
promotions:q`, `promotions:r` and `promotions:qr` all accept it, `promotions:qq`
does not. Measured at `KPvk --dtm 4`: 1194 positions, of which 1176 show at
least one queen promotion, 867 at least one rook promotion, 849 both, 540
two queen promotions across their solutions and 261 two rook promotions;
none shows `promotions:n` or `promotions:b`, and `allumwandlung` cannot
occur in `KPvk` at all — a lone knight or bishop never mates a bare king,
so no optimal line ever underpromotes to either.

**`zilahi` has no real example in this pass.** It needs two white units
that can each mate and each be captured, which is a five-piece class
(`KRBvkn` or similar); no such table was to hand. The detector is verified
on hand-played fixtures only (two lines from one diagram in which a rook
and a bishop swap the mating and the captured role), and the first table
that offers a genuine pair should be run before the theme is trusted.

### `indian` and `maslar`: real examples

Against a freshly generated `KRBvk` table, the textbook Indian:

```
$ helpmate probe "8/8/8/8/2k5/8/2K5/R5B1 w - - 0 1" --themes --tables ~/tb
dtm=5 (h#2.5) count=1
themes: mirror single-piece single-piece:black nocapture nocheck indian
$ helpmate line "8/8/8/8/2k5/8/2K5/R5B1 w - - 0 1" --tables ~/tb
Ra8 Kb4 Ba7 Ka3 Bc5#
```

1.Ra8 crosses a7 (the critical move), 2.Ba7 interferes on it, the black
king walks onto the shut-off a-file, and 3.Bc5# mates by discovery from
a8. `mine KRBvk --dtm 5 --theme indian` finds 1201 positions (3324
saturated positions skipped), `--dtm 6` finds 2235; none exists at `--dtm 4`,
since an Indian needs three moves by one side.

A Maslar with a unique solution, from a freshly generated `KRvkb` table:

```
$ helpmate probe "8/8/8/8/8/8/2k4b/KR6 w - - 0 1" --themes --tables ~/tb
dtm=7 (h#3.5) count=1
themes: pure model ideal mirror nocheck maslar
$ helpmate line "8/8/8/8/8/8/2k4b/KR6 w - - 0 1" --tables ~/tb
Rh1 Bg1 Ka2 Kc1 Kb3 Kb1 Rxg1#
```

1.Rh1 crosses g1 (the critical move), 1...Bg1 interferes on it, the black
king walks c1-b1 onto the first rank beyond g1, and 4.Rxg1# captures the
interfering bishop with mate. `KRvkn` shows the same picture with a knight
(`8/8/8/8/8/8/2k1n3/KR6 w - - 0 1`: `Rh1 Ng1 Ka2 Kc1 Kb3 Kb1 Rxg1#`). In
those two classes `mine --theme maslar` first finds positions at `--dtm 7`;
the `--dtm 5` and `--dtm 6` scans were stopped at a five-minute cap without
a match, so shallower Maslars there are not ruled out, only not found.

With a queen and a black rook it comes a move sooner. `KQvkr` has Maslars
at `--dtm 5`:

```
$ helpmate probe "8/8/8/8/1r6/1k6/8/QK6 w - - 0 1" --themes --tables ~/tb
dtm=5 (h#2.5) count=211
themes: set-play pure model ideal mirror switchback self-block single-piece single-piece:white single-piece:black umnov maslar
```

One of its 211 solutions is `Qa8 Ra4 Kc1 Ka2 Qxa4#`: the queen crosses a4,
the rook interferes there, the king steps onto the a-file beyond it, and
the queen captures with mate. Not every solution shows the theme (`any`
semantics), and no unique-solution `KQvkr` Maslar at `--dtm 5` turned up
within the cap.

**`maslar:black-white` has no real example in this pass.** After Black
captures the interfering white unit, White must still be able to mate, so
the theme needs at least five units: a black line piece, a white
interferer, and white mating material besides. `KNvkr` (the four-unit
candidate) duly shows none at `--dtm 4` or `--dtm 5`, and no five-unit
table was to hand. The detector is verified on hand-played fixtures only.

**`kniest`, `zajic` and `schnoebelen` have no verified real example in this
pass.** All three need `solutions`, which forces full enumeration; several
materials likely to contain them were tried (`KRvkq`, `KRvkr`, `KRvkb`,
`KRvkn`, `KQvkr`, `KQvkn`, `KQvkb` at `--dtm 4`, `--tables ~/tb`) and each
timed out well past a minute before completing the scan — `KRvkbn`-scale
material at shallow depth is exactly the ~30-second-plus territory the
Performance section above documents, and these did not finish faster.
Smaller minor-piece materials that *did* complete quickly (`KBvkr`, `KBvkn`,
`KNvkr`, `KNvkb` at `--dtm 2` and `--dtm 4`) found no matches. Rather than
fabricate a FEN, this is disclosed plainly: their definitions above are
exactly what `helpmate themes` prints, and their unit tests
(`src/core/tests/test_line_themes.cpp`) are hand-built `Solution` fixtures,
not tablebase-verified positions — a genuine tablebase example for these
three is unresolved as of this writing.

### Match semantics: `any` within a theme, `AND` across themes

A position matches `--theme X` when **at least one** of its optimal solutions
shows theme `X` — not every solution. Naming several themes (`--theme model
--theme self-block`, or `theme=model&theme=self-block` on the API) requires
**all** of them to be shown, but not necessarily by the same solution: a
position with two solutions, one a model mate and the other showing
self-block, matches `--theme model --theme self-block` even though no single
solution shows both. A same-solution ("this one line shows both") variant is
not offered in v0.8.

**Two themes are `every`, not `any`: `nocapture` and `nocheck`.** They are
properties of the whole solution set — "no unit is captured in any solution",
"no move gives check in any solution except the mating move" — so a position
matches only when **every** optimal solution qualifies, and one capturing (or
checking) line is enough to break it. `any` would make a negative theme
nearly meaningless: a position with ten solutions, nine of them capturing,
would count as capture-free because the tenth happened to be quiet. An empty
solution set shows neither (nothing is vacuously capture-free), and a
position that is already mate (dtm 0, no moves at all) shows neither either,
in line with every other line theme. The `AND`-across-themes rule is
unchanged: `--theme nocapture --theme model` needs every solution to be
capture-free *and* at least one to end in a model mate. On a saturated
position (255+ solutions) `probe --themes` and `/v1/probe?themes=true`
detect from the first 100 solutions only, and the usual truncation note
applies — for these two themes it means "every one of the 100 examined",
not "every solution".

**Two themes compare solutions with each other: `zilahi` and
`allumwandlung`.** Neither is a property of one line. `zilahi` needs two
solutions in which the two white units swap roles (the one that mates here
is captured there, and vice versa); `allumwandlung` needs the four promotion
types to occur somewhere across the set, in any number of solutions and of
either colour. A position with a single solution can be neither. Both are
this project's reason for having exhaustive solution data: a single-problem
analyser has to find every solution before it can ask either question. The
same first-100 truncation applies on saturated positions, and `zilahi`'s
definition says so.

### Parametric themes: a name with a value

`promotions:<types>` is the first theme that is a *family* of questions
rather than one. It reads the promotions of **all** optimal solutions taken
together, with multiplicity, and asks whether **at least** the given ones
occur: `--theme promotions:qrr` needs one queen and two rooks among them —
q and r in one solution and r in another, or all three in one line — and a
position whose solutions also promote to a knight still matches. `--theme
promotions:n` asks for a knight underpromotion anywhere in the set. The
value is a multiset — `rq` and `qr` are the same question, `qrr` asks for
more than `qr` — and the server canonicalises it (lower-case, sorted
q r b n), which is also how `probe` prints the position's own combined
multiset. The rules that make this safe, on every surface:

- The bare name is an error that shows the form: `theme "promotions" needs a
  value, e.g. promotions:qrr`.
- A value the theme does not accept is an error naming the letters allowed.
- The singular typo `promotion:qrr` is an error suggesting `promotions:qrr`,
  never a silent match on the boolean `promotion` with the value discarded —
  the `--end`/`--ends` lesson applied before it could recur.
- Colour variants are unaffected: `excelsior:white` is still one full name.

`probe --themes` reports the family as one value, the combined multiset of
every solution (`promotions:qr` on a position whose two solutions promote
to a rook and to a queen), and nothing when nothing promotes; every
sub-multiset of that value is a `--theme` that accepts the position.
`GET /v1/themes` marks the entry with a `parameter` object
(`{"name": "types", "doc": ..., "example": "qrr"}`; `null` on every boolean
theme), which is how the dashboard knows to draw a text box rather than a
checkbox for it. `allumwandlung` stays as a named boolean for the classic
task; it is the same question as `promotions:qrbn`.

### The three CLI surfaces

```
helpmate mine <MATERIAL> --dtm N [--theme NAME]...   # repeatable, ANDed
helpmate probe <FEN> --themes                         # annotate one position
helpmate themes                                       # list detectors + their definitions
```

`helpmate themes` prints exactly the output shown above, generated from the
in-build registry — the vocabulary `--theme` and `--themes` accept is always
discoverable without the docs, and never drifts from the binary.

### The three API surfaces

- `GET /v1/themes` — the registry as JSON, so the dashboard (or any client)
  can build its own theme picker without a hard-coded list:

  ```
  $ curl -s http://127.0.0.1:8642/v1/themes
  {"themes":[{"name":"set-play","doc":"Set play: the same position with the other side to move is solvable one move sooner (sibling dtm == this position's dtm - 1) -- the mate is already available and the side to move merely delays it. A sibling one move LONGER is the opposite of set play, not set play.","needs":"plane"},{"name":"pure","doc":"Pure mate: ...","needs":"solutions"}, ...]}
  ```

  Each entry now carries a `needs` field (`"position"`, `"plane"` or
  `"solutions"`) — see [`needs`: what a theme actually reads](#needs-what-a-theme-actually-reads)
  above. `/v1/themes` itself needed no source change to gain this: it already
  serves the registry verbatim, so the field appeared automatically once the
  registry started carrying it.

- `GET /v1/mine` gains a repeatable `theme=` query parameter (same `any`
  within a theme, `AND` across themes semantics as the CLI; a parametric
  theme is passed as `theme=promotions:qrr`). An unknown name, a bare
  parametric name or a rejected value is a `400 invalid_theme` whose message
  names the problem and whose hint lists every valid name, never silently
  ignored:

  ```
  $ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" \
      --data-urlencode "dtm=2" --data-urlencode "theme=mirror" --data-urlencode "max=5"
  {"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1", ...],"truncated":true,"skipped_saturated":0}

  $ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" \
      --data-urlencode "dtm=2" --data-urlencode "theme=bogus"
  {"error":{"code":"invalid_theme","message":"unknown theme: bogus","hint":"valid themes: pure, model, ..."}}
  ```

- `GET /v1/probe?fen=…&themes=true` — opt-in (default `false`): detection
  forces solution enumeration, and `probe` is on the dashboard's hot path, so
  a plain probe must not pay for a field most callers never read. On a match,
  the response gains a `themes` array:

  ```
  $ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" \
      --data-urlencode "themes=true"
  {"dtm":2,"count":4,"flipped":false,"notation":"h#1",
   "themes":["set-play","pure","model","ideal","mirror","single-piece","single-piece:white","single-piece:black","nocapture","nocheck"]}
  ```

  For a color-flipped probe, `themes` is `null` (not an empty array — that
  would mean "no themes found") with a sibling `themes_note` explaining why;
  see [Two honest limitations](#two-honest-limitations) below.

  For a **saturated** position (stored `count` == 255, the cap), `themes` is
  still a real list — detection falls back to the first 100 of the
  (unknowably larger) true solution set — but the list is
  representative-dependent, not merely incomplete: two mirror-image FENs of
  the same position class can enumerate a different first 100 and so report
  different themes, while full enumeration would report the same theme for
  both. `themes_note` says so, alongside the (non-null) list:

  ```
  $ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/8/8/8/8/8/8/K1k2Q2 b - - 0 1" \
      --data-urlencode "themes=true"
  {"dtm":8,"count":255,"flipped":false,"notation":"h#4","themes":["pure","model","ideal","mirror","switchback","closed-walk","single-piece","single-piece:black","nocapture"],"themes_note":"this position's solution count is saturated (255+); themes were detected from the first 100 solutions only, and the list may differ between mirror-image representatives of the same position."}
  ```

  The Python binding makes the same disclosure with a `RuntimeWarning`
  instead of a sibling field, since `helpmate.Tablebase.themes()` returns a
  plain list with no room for one: `tb.themes(fen)` on a saturated position
  (with the auto-cap, i.e. no explicit `max=`) issues a `RuntimeWarning`
  before returning, catchable with `pytest.warns`/`warnings.catch_warnings`.

### Two things to know before you trust a result

**The solution cap is a false-negative source.** Themes are detected across
a position's optimal solutions, capped at the position's own solution count.
A position whose count is saturated (255+) is never enumerated and never
matches a theme filter; `mine` reports these in its skipped tally rather than
dropping them silently.

**Theme filters used to be slow on compressed tables.** Detection forces
solution enumeration, which is a random-access pattern — and with the 4 MB
block cache shipped through v0.8.0 that defeated the cache entirely,
costing 11.8x over raw. Raising the cache budget fixed it: the same query
now measures 1.14x raw. The old advice to mine against raw tables for large
theme searches no longer applies.

### Performance

Measured on `KQvk` at `--dtm 2` (a shallow query: matched positions have at
most a handful of optimal solutions each), milliseconds per query (`--tables`
on local disk, raw format):

| Query | ms/query |
|---|---|
| process floor (empty invocation) | 3.12 |
| plain `--dtm` | 4.06 |
| `--starts 1` (enumerates solutions, zero detectors) | 13.12 |
| `--theme mirror` (one detector) | 13.20 |
| four `--theme` flags | 14.46 |

**The detectors cost under 1% of the added work at this depth** — but that
number is scoped to this shallow `dtm=2` query, not a general figure. The
cost is solution enumeration itself — exactly the work the existing
`--starts`/`--ends` filters already pay, not something the theme feature
introduces — and enumeration cost scales with how many solutions a matched
position actually has. Measured on deeper positions of the same `KQvk` table,
where `detect()` has more solutions to run its detectors over: `solutions()`
5.59 ms vs. `detect()` 0.34 ms at count 160 (detectors are 5.8% of the added
work), and 7.42 ms vs. 0.42 ms at count 218 (5.4%). The qualitative claim
still holds at every depth measured — the cost is enumeration, not the
detectors — but "under 1%" is specific to the shallow case; expect low
single digits generally. On scan work alone (subtracting the process floor
from each `dtm=2` number above) a theme query runs at roughly **10.7x** a
plain `--dtm` scan. That is the cost of enumeration itself and applies to
raw and compressed tables alike; the separate block-compression penalty
these numbers used to compound with was fixed in v0.8.1 (see [Table
format](#table-format) above).

### Two honest limitations

**Colour-flipped positions cannot be annotated — even though most themes
would survive the flip unharmed.** When `probe` resolves a position by
flipping colours to find a table (see [Symmetry reduction](#symmetry-reduction)
above), `solutions()`/`detect()` cannot simply run on the flipped board
either: `solutions()` walks the position AS QUERIED, and the flip-found
table cannot answer a walk of the *original* (unflipped) FEN. Flipping the
position ourselves and detecting on *that* is not a fix: every detector is
hard-coded to the black king, so the four colour-labelled themes
(`single-piece:white`/`:black`, `excelsior:white`/`:black`) would come out
swapped — a wrong answer dressed as a right one. The other twenty-nine registry
entries, including `pure`/`model`/`ideal`/`mirror` and the two v0.9 line
themes that reference the mated king (`kniest`, `zajic`), are in fact
flip-invariant (they read from the black king's field the same way
regardless of which side of the board it's on) and could, in principle,
still be answered on a flipped board — that selective re-detection is a
known follow-up, not something v0.9.0 ships; today the whole `themes` field
is withheld rather than risk the four that aren't. `set-play` never
references a specific colour at all — it reads the plane generically by
each unit's own colour — so it carries no asymmetry to begin with;
`phoenix`, `schnoebelen` and `pendulum` are likewise colour-generic in
their source, as are `nocapture` and `nocheck`, which read only the
`captured` and `is_check` flags of each ply, and `umnov`, `umnov-mate`,
`klasinc`, `allumwandlung` and `promotions:<types>`, which read squares,
types and promotion flags only; `indian` is tested for both colours.
`zilahi`, `maslar` and `maslar:black-white` name the side that plays each
role, which is the definition's own convention and colour-specific. The CLI prints a note and exits 0; the API returns `"themes":
null` with a `themes_note` field explaining why, distinct from `[]` (no
themes found).

**Verification against published problems was deferred by explicit
decision.** The definitions above are this project's own — stated precisely
enough to be argued with, not certified against the Helpmate Analyzer or any
other authority. A detector subtly at odds with composition convention will
return a confident, wrong result, and nothing in this project's test suite
will catch that; only comparison against known compositions would. That
comparison has not been done. Treat every theme match as this codebase's
opinion, not an authoritative ruling.

## `compact` — reclaim disk space in already-unsolvable tables

```
helpmate compact <DIR> [--dry-run] [--compress] [--block-size N]
```

Rewrites every `.hm` table in `DIR` whose cells are **all** unsolvable (or
invalid) into a tiny marker file, reclaiming disk space without changing what
any query can answer. Tables with at least one solvable cell are left
completely untouched, and a table that is already a marker is skipped (not
rewritten again). When a run rewrites nothing at all — every table was either
solvable or already a marker — it prints `already compact`. `--dry-run`
reports what *would* be rewritten and reclaims nothing — it never opens a
file for writing.

With `--compress` (since v0.7.5), `compact` switches to a different mode
entirely: instead of hunting for all-unsolvable tables, it rewrites every
*raw* table in `DIR` as block-compressed at `--block-size` (default 64 KiB;
see [Table format](#table-format) and [`gen`](#gen--generate-tables) above),
skipping markers and —
always, not just under `--dry-run` — anything written in the last hour, so a
generation run still writing into the same directory is never disturbed.
`--compress` and the marker-compaction mode above are mutually exclusive.

A table that is **already compressed** is handled by comparing its stored
block size against `--block-size`:

- same block size: a true no-op, reported as "already compressed at this
  block size" — nothing is read or rewritten.
- different block size: **re-blocked** in place — decompressed and
  recompressed at the new block size, streaming through a bounded
  decompressed-block cache rather than buffering the whole table (same
  constant-memory approach as a first compression), reported as `re-blocked
  NAME (before -> after)` and counted separately from a first compression in
  the summary line (`N rewritten (X compressed, Y re-blocked)`).

This means **a block size chosen at generation time is not permanent**: a
table compressed at 16 KiB can be moved to 64 KiB (or vice versa) with
`compact --compress --block-size 64` without regenerating it from scratch —
hours for a 5-piece table, over a day for a 6-piece. Re-blocking only ever
changes how a table is *stored*; the decompressed content at every cell is
unchanged (verified: re-blocking a real 462 MiB `KRvkbn` table's 64 KiB
compressed form down to 16 KiB produced a file `md5sum`-identical to
compressing the same raw table directly at 16 KiB).

Do not run `compact --compress` (a first compression or a re-block) inside a
Hugging Face dataset cache directory: rewriting a table's bytes in place
changes its size and sha256 without updating the local `manifest.json`, so
every entry it touches goes stale and the next `pull` silently re-downloads
those files instead of recognizing them as already present.

This exists for tables generated **before v0.6.1**, when `gen` had no pruning
and wrote a full-size table even for slices like `Kvk` where every cell is
unsolvable. Since v0.6.1, `gen` already prunes such slices to markers at
generation time (see [Pruning and marker tables](#pruning-and-marker-tables)
below) — so `compact` typically has nothing to do on tables generated after
the upgrade; run it once against older tables to shrink them in place.

Real captured output below. `demo/` holds a real, freshly generated `KQvk`
closure (`KQvk.hm` — solvable, left alone) next to a fabricated stand-in for
a pre-v0.6.1 `Kvk.hm`: a full-size, ordinary (version 1) table whose every
cell is unsolvable, the shape `compact` exists to shrink.

```
$ ls -l demo/
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users   4087 Kvk.hm

$ helpmate compact demo --dry-run
would rewrite Kvk (0 MiB)
would reclaim 0 MiB from 1 table(s); 1 left unchanged (solvable or already compact)

$ ls -l demo/          # --dry-run wrote nothing; every size unchanged
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users   4087 Kvk.hm

$ helpmate compact demo
rewrote Kvk (0 MiB)
reclaimed 0 MiB from 1 table(s); 1 left unchanged (solvable or already compact)

$ ls -l demo/          # Kvk.hm shrank; KQvk.hm/.stats.json byte-identical
-rw-r--r-- 1 os users 146117 KQvk.hm
-rw-r--r-- 1 os users  27781 KQvk.stats.json
-rw-r--r-- 1 os users    469 Kvk.hm
-rw-r--r-- 1 os users    405 Kvk.stats.json

$ helpmate compact demo    # re-run: nothing left to do
reclaimed 0 MiB from 0 table(s); 2 left unchanged (solvable or already compact)
already compact

$ helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables demo
dtm=2 (h#1) count=4
```

(`Kvk`'s 4087→469 bytes is a rounding-to-0-MiB demo at 2-piece scale; the same
mechanism reclaims gigabytes on a real 5-6 piece run where a dead slice would
otherwise have been a multi-GB full table.) The rewritten `.stats.json`
sidecar is regenerated fresh, not copied from the original — it carries
`"all_unsolvable": true` and the compacting binary's own
`generator_version`, exactly like a marker `gen` produces directly.

### Pruning and marker tables

Since v0.6.1, `gen` skips writing a full table for any slice it can *prove*
contains no helpmate at all, writing a **marker table** instead. A slice is
pruned when either:

- **the mating side is a bare king** — White (the side the index always
  treats as delivering mate; see [Symmetry reduction](#symmetry-reduction))
  has no piece besides its king. A lone king can never deliver check, so the
  slice is unsolvable regardless of what Black holds (e.g. `Kvk`, `Kvkq`,
  `Kvkr` are all pruned this way, unconditionally); or
- **every successor's table reports all of its cells unsolvable, and the
  slice has no checkmate position of its own** — every solution ends in a mate
  either in this slice or in one reached by a capture/promotion, so if every
  reachable successor slice is proven dead *and* scanning this slice directly
  finds no checkmate, the slice is dead too.

A **marker table** is a table file with no payload at all: just the 64-byte
header (format `version = 2`, versus `1` for an ordinary table) plus the
metadata JSON — the four value planes (dtm/count × White-to-move/Black-to-move)
that make up the bulk of an ordinary table's bytes are simply not written.
Every cell reads back as `DTM_UNSOLVABLE` when probed, exactly as it would if
the slice had been generated in full and turned out to be entirely
unsolvable. `TableReader` accepts both versions transparently — probing,
`stats`, `mine`, and `compact` all work unchanged whether a table on disk is
an ordinary version-1 table or a version-2 marker; nothing reading tables
needs to change for this feature.

Since v0.6.2, a table file whose format `version` is newer than this build
understands is diagnosed as such — `error: table ... was written by a newer
helpmate (unsupported table format version); upgrade this build` (exit code
`3`) — rather than being reported as a missing table (exit code `2`); the
message is what tells "you need to build it" apart from "you need a newer
helpmate". Every command that opens a table reports it this way: the query
commands (`probe`, `line`, `mine`, `stats`), `compact`, and both table reads
in `gen` — the `--prune` successor check, which treats it as an error rather
than silently assuming the successor isn't proven dead, and the sub-table load
that cross-material lookups depend on during generation. `probe` is the
one place it isn't necessarily fatal: a future-format table only stops the
query if it *also* defeats the color-flip fallback above — if the position's
own slice is the one that's unreadable but the color-flipped slice is a
usable, understood table, `probe` answers from the flip exactly as it would
for a missing (not just future-format) primary slice, and the version
mismatch is never reported at all.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | success — including a reported `unsolvable` answer. |
| `2` | a table needed to answer the query is missing; the message names it and the exact `helpmate gen` command that builds it. |
| `3` | bad usage or unparseable input (unknown command, malformed FEN or material string, malformed/out-of-range numeric flag, flag missing its value; includes `compact` given no directory, or a path that is not a directory) — also a table written by a newer helpmate (unsupported table format version), which is a runtime error rather than bad usage but shares this exit code. |

## Resource guidance

Per-slice plane sizes follow directly from the indexing scheme (four 1-byte
planes per slice: dtm and count for each side to move; a small header + JSON
metadata on top). `gen` always builds the whole capture/promotion closure, so
total time/space is the sum over all slices in the closure.

| Pieces | Typical generation time | Typical table size | Notes |
|---|---|---|---|
| 3 | well under a second (~0.6 s measured for the whole `KQvk` closure) | ~120 KB per pawnless slice (29,568 cells × 4 planes) | instant to experiment with |
| 4 | seconds | ~7.6 MB per pawnless slice (462 × 64² cells × 4 planes) | still interactive |
| 5 | minutes to a couple of hours, material-dependent | ~0.5 GB per pawnless slice (462 × 64³ ≈ 121 M cells × 4 planes) | see the known-bug note below |
| 6 | multi-day runs | roughly **14-28 GB** of table storage/RAM for a class at the current 1-byte/cell, uncompressed encoding | feasible but heavy; use `--threads` |
| 7-8 | out of scope for this version | — | the versioned format is designed so a future compressed/out-of-core encoding can be added without invalidating existing tables |

Pawnful slices index 1806 king-pair classes (×48 per pawn instead of ×64), so
they are larger per remaining piece than the pawnless numbers above. Tables
are mmap-backed: probing costs a page fault, not a full load, so querying huge
tables is cheap even when generation was not.

**Known issue**: 5-piece generation has had a known, intermittent crash bug
(heap corruption in the root-slice generation scan — bug #21); see the
Limits and Coverage sections of the [README](../README.md) for its current
status. Re-running `gen` is safe: completed slices are never rewritten, so a
crashed run resumes where it left off.

## Python API

Install per [BUILD.md](BUILD.md) (`pip install .`), then:

```python
import helpmate

# build (or reuse, if already built) every table this material class needs;
# returns the list of table files actually written
helpmate.generate("KQvk", tables="tables/", threads=4)

tb = helpmate.Tablebase("tables/")

dtm, count, flipped = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# dtm=2, count=4, flipped=False

tb.line("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1")
# ['Kh6', 'Qh2#']

tb.lines("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1", max=10)
# [['Kh6', 'Qh2#'], ['Kh6', 'Qh1#'], ['Kh6', 'Qg6#'], ['Kh8', 'Qg7#']]

tb.mine("KQvk", dtm=2, count=1, max=3)
# ['8/8/8/8/8/8/8/k1KQ4 b - - 0 1', '8/8/8/8/8/2Q5/8/k1K5 b - - 0 1', ...]

tb.stats("KQvk")["max_dtm"]
# 14
```

Reference:

- `helpmate.generate(material, tables="tables", threads=1, verbose=False,
  progress=False, force_ram=False, compress=False, block_size=64)` —
  generates the closure exactly like the CLI's `gen` (`verbose`/`progress`/
  `force_ram` match `--verbose`/`--progress`/`--force-ram`; reporting goes to
  the process's stderr); returns the list of `.hm` paths written (empty if
  everything already existed). `compress`/`block_size` mirror `gen
  --compress`/`--block-size` (see [Table format](#table-format) above) — same
  unit, too: `block_size` here is **KiB**, exactly like the CLI's
  `--block-size` (`block_size=64` means 64 KiB), even though it is converted
  to raw bytes internally before reaching `GenOptions::block_size`. Earlier
  versions of this binding took raw bytes here while the CLI took KiB; that
  mismatch was a trap (`--block-size 64` on the CLI and `block_size=64` here
  used to produce different tables) and has been fixed by converting in the
  binding, not by documenting around it.
- `Tablebase(tables_dir)` — lazily mmap-loads and caches whatever slices
  queries touch.
- `tb.probe(fen)` — returns a `(dtm, count, flipped)` tuple, or **`None`** for
  a legal but unsolvable position. `flipped=True` means the answer came from
  the color-flipped slice.
- `tb.line(fen)` — one optimal line as a list of SAN strings (empty list if
  unsolvable or already mate).
- `tb.lines(fen, max=100)` — every optimal line, capped at `max`.
- `tb.mine(material, dtm, count=-1, max=100, starts=-1, ends=-1, themes=[])`
  — list of FENs matching `dtm` exactly and, for each of `count`/`starts`/
  `ends` that is `>= 0`/`>= 1`, that criterion exactly too (`starts`/`ends`:
  distinct first moves / distinct mating moves among the optimal solutions —
  see the CLI [`mine`](#mine--scan-for-composition-candidates) section for
  what these mean). `themes`: a list of theme names, every one of which must
  be shown by at least one optimal solution (not necessarily the same one —
  see "Match semantics" under [Themes](#themes) above; `nocapture` and
  `nocheck` instead require every optimal solution to qualify; a parametric
  theme is written `"promotions:qrr"`); an unknown name, a bare parametric
  name or a rejected value raises `ValueError` with the same message
  `helpmate.check_theme(name)` returns (`None` when the name is acceptable).
- `tb.mine_with_stats(material, dtm, count=-1, max=100, starts=-1, ends=-1,
  themes=[])` — like `tb.mine`, but returns `(fens, skipped_saturated)`: the
  FEN list plus how many matched-so-far positions were skipped because their
  stored solution count is saturated (255+) and so couldn't be checked
  against `starts`/`ends`/`themes`.
- `tb.themes(fen, max=-1)` — the theme names the position's optimal solutions
  show, as a list (same detectors and `any`-within-a-theme semantics as
  `probe --themes`/`GET /v1/probe?themes=true`). `max=-1` (the default) is a
  sentinel meaning "the position's own solution count" — capped at 100 if
  that count is saturated (255+) — exactly the cap the CLI uses; passing an
  explicit non-negative `max` enumerates at most that many solutions instead,
  which can under-count themes relative to the CLI/API defaults for a
  position with more solutions than the `max` given. Raises
  `helpmate.MissingTableError` if a solution walk needs a table this
  `Tablebase` doesn't have (e.g. a capture into missing sub-material). When
  the auto-cap engages on a saturated position (stored count == 255), the
  returned list is representative-dependent, not merely incomplete (two
  mirror-image FENs of the same position class can enumerate a different
  first 100 solutions and report different themes) — `tb.themes()` issues a
  `RuntimeWarning` saying so before returning, the same disclosure
  `GET /v1/probe?themes=true`'s `themes_note` and `probe --themes`'s stderr
  note make on their own surfaces. Passing an explicit `max` is treated as
  an intentional override and does not warn.
- `helpmate.themes()` — the theme registry as a list of `{"name": ...,
  "doc": ...}` dicts, in display order; the same data `helpmate themes` and
  `GET /v1/themes` print, generated from the in-build registry so it never
  drifts from the binary.
- `tb.stats(material)` — the stats JSON as a Python dict (fields as in the
  [reference](#statsjson-field-reference) above).

Errors: a missing table with no usable color-flip fallback raises
`helpmate.MissingTableError` (a `RuntimeError` subclass) whose message names
the exact `helpmate gen` invocation that would build it; malformed FENs or
material strings raise `ValueError`.

Python tests live in `src/packages/bindings/tests/` (`pytest
src/packages/bindings/tests`; add `--run-slow` for the exhaustive
python-chess cross-validation of the full KQvk closure).

## Web dashboard

The browser front end for everything above. It is served by the same process
as the API — there is no second port, no build step, no npm, and nothing is
fetched from a CDN at runtime. Install all three distributions, in
dependency order (`helpmate-api` requires `helpmate`; `helpmate-web` is what
gives the API a dashboard to serve):

```bash
make install
# or: pip install . ./src/packages/api ./src/packages/web
helpmate-server --tables ~/tb --port 8642
# then open http://127.0.0.1:8642/
```

If `helpmate-web` isn't installed (just `helpmate` + `helpmate-api`), the
server still runs but `/` 404s — pass `--web-root DIR` to serve a dashboard
checkout from an arbitrary directory instead, or `--no-web` to say
explicitly that you want the API alone.

Since v0.11.0, every screen is a grey **rail** — the board, the palette, the
material list, the search form: what you manipulate — beside a white
**readout** — the move list, the table stats, the results: what the tables
say. Both surfaces are aliases over the existing palette; no new colours were
introduced to build the split. Since v0.13.0 that is **one palette, full
stop** — there is no colour-theme control on this page any more; see
[Palette](#palette) below.

Five screens on the nav by default; a sixth, Search, only when the server was
started with `--enable-mine` (see [`--enable-mine`](#api-server) below). Two
more — Technique and Privacy — exist without a nav button and are reached from
About and from the footer.

Since v0.15.0 the **header is sticky** and every pinned column (the board, the
material list, the search form) comes to rest below it rather than at the top
of the viewport. The board already stuck; what scrolled away was the nav, the
title and the server chip, which left the board jammed against the window edge
with its piece tray clipped. The offset is `--pin-top`, derived from
`--header-h`, which `js/chrome.js` publishes from a `ResizeObserver` on the
header — the header wraps to two lines between roughly 860px and 1100px, so a
hard-coded offset is wrong at one width or the other.

- **Explorer** — an interactive board. Drag a piece to play its move, or click
  one from the complete legal-move list, which is grouped into **Optimal**
  (keeps the shortest mate), **Slower** and **No mate**, with the optimal
  moves ordered by how forcing they are — the child position's optimal-line
  count, ascending, since mate length is constant across that group by
  construction. A saturated count renders as `255+`, never `255`. Slower and
  No-mate moves render as chips under a shared distance label instead of a
  full row each — within one distance every full row would have read the
  same, so the distance is stated once and the moves that share it follow as
  chips. Below the list, the optimal lines in SAN, exportable as PGN, and
  (since v0.8.0) the current position's themes — fetched via `probe --themes`
  (opt-in on the client too), showing `themes_note` in place of the list for
  a color-flipped position rather than a blank field. The position is
  encoded in the URL (`/#fen=<urlencoded>`), so every position is a
  shareable link and the browser's back button walks the history. Since
  v0.11.0, a band below the board and the move list names the table that
  answered the current position (the `material` the API reports — see
  [`GET /v1/probe`](#get-v1probe) below — which is the mirrored table
  whenever colours were flipped to find an answer); since v0.12.0 that band
  is one line — the material, its deepest mate and how much of it is
  solvable — with a link straight into Materials for that entry's full
  histograms, rather than repeating them under every position.
- **Materials** — every table the server can reach, with piece count, size and
  location (`local` / `cached` / `remote`). Since v0.11.0 the list opens on a
  pinned **All tables** entry showing the corpus aggregate from
  [`GET /v1/stats`](#get-v1stats) — including the materials with no helpmate
  at all and the spread of generator versions that built the corpus — and the
  rest of the list scrolls inside its rail, filters on a substring of the
  material name, and is grouped by piece count. Selecting a single material
  shows where its cells went (solvable / no mate / illegal), a histogram of
  mate lengths split by side to move, a histogram of how many optimal
  solutions positions have, and the deepest sample positions — each clickable
  into the explorer.
- **Search** (only present when the server was started with `--enable-mine`;
  otherwise the screen and its nav button are absent from the document
  entirely, not merely hidden) — a form over [`/v1/mine`](#get-v1mine),
  including the `starts` / `ends` shape filters and (since v0.8.0) a theme
  multi-select populated from
  [`/v1/themes`](#get-v1themes), so the picker's vocabulary always matches the
  server's own build rather than a hard-coded list. Results are clickable
  FENs, exportable as a FEN list or CSV. Results are numbered so a row is
  nameable. Impossible filter combinations (`starts` greater than `count`)
  are rejected before the request; the server stays the authority for the
  rest. Since v0.11.0 the form is itself a rail, with a **Stop** button next
  to Search and a live elapsed-time counter shown against the server's own
  `--mine-timeout` budget (read from [`GET /v1/health`](#get-v1health)'s
  `mine_timeout`, so the countdown is never a number hard-coded on the
  client). A search that runs out the clock is reported honestly as a
  timeout, not as "0 position(s)". **Stop only abandons the browser's
  request** — the scan itself runs in the server's thread pool, and dropping
  the client side of an HTTP response does not cancel the work already
  queued there; the server still finishes or drops the scan on its own
  `--mine-timeout` clock. Pressing Stop says this in the status line rather
  than implying the server stopped too.
- **Puzzles** (since v0.13.0) — a session of ten one-solution positions
  drawn from a committed EPD file, one per difficulty rung (mate length
  first, piece count second, ascending), easiest first. It reuses the
  explorer's own board construction, not a second editor: the same
  borderless square style, the same rail/readout layout — but no palette, no
  relocation, no FEN box, and only the one move expected at the current ply
  is ever graded. Solving means playing the *whole* line, both colours: a
  helpmate is cooperative, so proving the solution means supplying Black's
  moves too, not just answering "what does White play". Each ply the player
  supplies gets a check or a cross; a wrong move reveals the correct SAN for
  that ply without ending the puzzle, and once the running error count
  passes the puzzle's error budget the rest of the line is revealed
  automatically. The session is filtered, before it is drawn, to materials
  this installation's [`GET /v1/materials`](#get-v1materials) actually lists
  — a puzzle whose material nobody has generated is not a harder puzzle, it
  is a 404 — and when none of the shipped set's materials match, the screen
  says so by name and prints the `helpmate gen` command that would fix it,
  rather than presenting an empty or broken session. See [Puzzle set
  (EPD)](#puzzle-set-epd) below for the file format and how to regenerate
  it.
- **Themes** (since v0.13.0) — every motif this build's tablebase detects,
  in five groups (the mate picture, how a unit travels, pawns and promotion,
  where the mate happens, the structure of the solution) plus a trailing
  "other" group for anything the registry adds later, each group introduced
  by a sentence before its members. Rendered straight from
  [`GET /v1/themes`](#get-v1themes) — never a hard-coded list — so this
  screen cannot drift from the binary it is talking to: a new motif shows up
  here with no edit to the dashboard. Every entry shows the motif's name,
  its definition (the API's own `doc` string), and a one-line explanation of
  what its `needs` value means for a position whose stored solution count
  has saturated at 255 (see [`needs`: what a theme actually
  reads](#needs-what-a-theme-actually-reads) above) — `solutions` detectors
  are silently skipped on such a position, `plane`/`position` ones still
  answer.
- **About** (since v0.15.0) — what a helpmate is, what `dtm`, `count` and
  themes actually mean, what each screen is for, the scope limits (no
  castling, no 50-move rule, exact-but-unindexed en passant, saturation at
  255), and the project's own links. It is the only screen of the three prose
  screens with a nav button; it links onward to the other two. A short form of
  it also sits on the explorer, under the primer, so the landing screen says
  what the site is without a click.
- **Technique** (since v0.15.0, no nav button) — how the tables are computed:
  the symmetry-reduced joint king index (462 pawnless / 1806 with pawns), the
  closure-then-fixed-point generation and the counting sweep, the four byte
  planes and the three file versions, what answering a query costs, and the
  verification story (the independent oracle, the exhaustive python-chess
  cross-check, byte-identical multithreaded output, golden compositions).
- **Privacy** (since v0.15.0, no nav button) — the dashboard sets no cookies
  and uses neither local nor session storage; the position lives in the URL.
  The page names Cloudflare's strictly-necessary cookies for a deployment
  behind it, says what the access log contains, and states the legal basis.
  The no-storage claim is asserted against a real page load in the UI suite,
  not merely written down here.

**Palette.** One palette, full stop. There is no colour-theme control on
this page, and nothing to keep in sync with the OS's own
`prefers-color-scheme` — earlier releases carried a three-state
system/light/dark toggle, remembered per browser and applied before first
paint via a pre-paint script in `<head>`; v0.13.0 removed the toggle, the
stored preference, that script, its drift test, and both dark token blocks
in `app.css` (a net −200 lines). The bare `:root` in `app.css` is the whole
system now.

**Elevation.** Since v0.15.0 both boards sit *on* the rail rather than being
painted into it: a hairline edge, a tight contact shadow and a wide cast, all
three the same achromatic ink the palette already uses, at three opacities —
no new colour and no second hue. The edge is an outset ring rather than an
`inset` shadow, because cm-chessboard fills the element with an opaque `<svg>`
and an inset shadow paints behind its own content. The trays stay flat on
purpose: they are a palette you pick from, not a surface play happens on.

**Footer.** Every screen shares one footer: a live line naming the corpus the
server is reading from left, and on the right a row of about-this-site links.
Through v0.14.0 those were three href-less placeholders (`Source`, `Dataset`,
`Licence`, marked `data-placeholder`); since v0.15.0 they are real —
`Source` and `Licence` to the repository, plus `About` and `Privacy`.
`Dataset` was dropped rather than left dead: the tables are not published yet,
and About says so in a sentence, which is better than a link that 404s.

The two internal ones carry a real `#panel=x` href, never `href="#"`. That is
not pedantry: `href="#"` *clears* `location.hash`, which fires `hashchange`,
and `panels.js` reads an empty hash as the explorer — so clicking one
mid-puzzle used to throw the position away and bounce the user to a screen
they were not on. A delegated `a[data-panel]` handler in `panels.js` then
re-encodes the current `fen` alongside the new panel, so following a footer
link and coming back lands on the position you left.

**Editing a position.** Since v0.12.0 the board has **no editing modes** —
no armed piece, no `Erase`, no `Arrange`, no `Done — evaluate` button to
commit a half-built position. One rule covers every drag:

- A drag whose start and end square match a legal move **plays that move**.
- Any other drag **relocates** the piece to wherever it was dropped —
  including a square already occupied, which is simply overwritten.
- A drag released off the board **deletes** the piece.
- A drag started on either **tray** — black's above the board, white's
  below, each on the side of the board its colour occupies, swapping
  position with `Flip` — **places** that piece on the square it lands on.

`Back` undoes all four the same way: one entry in the same history stack the
move list uses. The one deliberate risk this design accepts: relocating a
piece onto a square that happens to be a legal destination for it **will
play that move** rather than merely place it there — the board cannot tell
"I am rearranging" from "I am moving" except by asking, and asking on every
drop was the armed-mode overhead this removed. If that happens, `Back`
undoes it exactly as it would undo an intended move.

There is also a non-drag path: **two plain clicks on a piece relocate it**,
a side effect of the board's own move-input handling treating a
click-then-click the same as a drag that starts and ends on different
squares. With click-to-place gone, this and dragging from a tray are the
only ways to place or move a piece by hand — there is **no keyboard path**
to placing a tray piece; the **FEN** field (which applies on Enter, no
separate `Set` button) is the keyboard route to an arbitrary position.
`Clear board` still empties every square in one action, and the `To move`
selector still sets the side. Since v0.12.0 the board **is probed on every
drop** — the consequence is that building a position piece by piece can raise
the error banner on an intermediate step, because an intermediate material
may have no table. The one case that still skips the round trip is a
position with no king, or two of one colour: that says so directly instead
of spending a request to be told `invalid_fen`.

**What it needs from the server.** Only the read-only `/v1` routes. Every
contract the API defines is surfaced rather than hidden: `202 fetching` shows
a download-in-progress state and polls, `404` shows the returned `helpmate
gen …` hint, `400` is displayed next to the offending field, and an
unreachable server is reported in the header chip.

Third-party code is vendored, not fetched: **cm-chessboard** 8.7.5 (MIT) lives
under `src/packages/web/helpmate_web/static/vendor/cm-chessboard/` with its
LICENSE and upstream version recorded in
`src/packages/web/helpmate_web/static/vendor/README.md`.

### Puzzle set (EPD)

The Puzzles screen is served against a plain static file,
`src/packages/web/helpmate_web/static/puzzles.epd` (fetched by the client as
`/puzzles.epd` — no dedicated API endpoint), in
[EPD](https://www.chessprogramming.org/Extended_Position_Description),
chess's standard container for a collection of positions. It is committed to
the repo and meant to be **hand-editable**: a custom problem can be added by
typing one line.

```
8/7k/5K2/8/8/8/8/6Q1 b - - ; hm 4 ; id "KQvk.0001"
```

Each line is the four FEN fields — placement, side to move, castling
rights, en passant target; EPD has no halfmove/fullmove clocks, so the
client's own parser appends `0 1` to turn a line back into a FEN the rest of
the dashboard understands — followed by `;`-separated opcodes. Exactly two
are read:

- **`hm`** — the helpmate distance **in plies**, the same unit `dtm` uses
  everywhere else in this project (so `hm 4` is h#2). Stored rather than
  probed, so ordering the whole set by difficulty costs nothing at load
  time.
- **`id`** — a free-form label, not currently shown on screen but kept for
  provenance and hand-editing.

Any other opcode is parsed and ignored (so a future field costs nothing to
add), and a line starting with `#` is a comment. A line with no positive
`hm` is skipped. Piece count is *not* stored — it's derived from the FEN
each time, since it's cheap and storing it would risk drifting from the FEN
it describes.

The committed 1071-position file was mined from a real corpus with
[`tools/mine_puzzles.py`](../tools/mine_puzzles.py): a ladder of ten
`(piece count, mate length)` rungs, each queried against helpmate's mining
API for positions with a unique solution (`count=1`), ranked by how many
such positions each candidate material actually holds (read straight from
that material's `stats.json` uniqueness histogram, no probing needed).
Read-only against `--tables` and deterministic given `--seed`, so
regenerating the file produces a reviewable diff rather than a reshuffle:

```bash
taskset -c 0-3 python3 tools/mine_puzzles.py --tables ~/tb \
    --out src/packages/web/helpmate_web/static/puzzles.epd --seed 1
```

It refuses to write `--out` anywhere under `~/tb` — the same live-corpus
guard `tools/bench_compression.py` applies to `--tables`, here applied to
the write target instead.

## API server

A small read-only HTTP API (FastAPI + uvicorn) for serving generated tables:
health/catalog/stats, `probe`/`line`/`mine` as JSON, and transparent
on-demand fetching of tables that only live in a remote Hugging Face
dataset. Plus a companion CLI, `helpmate-tables`, for pushing tables to and
pulling them from that dataset.

### Install

```bash
pip install . ./src/packages/api
# or, to also get the dashboard: make install
```

`helpmate-api` requires `helpmate` (the core + CLI + bindings), so it must
install second; nothing is published to PyPI yet, so installing out of
order sends pip looking for the name upstream. This installs `fastapi`,
`uvicorn`, and `huggingface_hub` on top of the base package, and registers
two console scripts: `helpmate-server` and `helpmate-tables`.

### Start the server

```bash
helpmate-server --tables ~/myhelpmate/tables --hf-repo USER/DS \
  --cache ~/.cache/helpmate-tables --port 8642
```

- `--tables DIR` (repeatable): one or more local directories searched, in
  order, for `.hm`/`.stats.json` files. Omit entirely to serve only from the
  remote.
- `--web-root DIR`: serve the dashboard from `DIR` instead of the installed
  `helpmate-web` package (useful for a source checkout of the dashboard
  without installing it).
- `--no-web`: serve the API only — `/` 404s instead of the dashboard. Useful
  when `helpmate-web` isn't installed and you want that to be a deliberate
  choice rather than an unexplained 404.
- `--hf-repo USER/DATASET` + `--cache DIR`: an optional Hugging Face dataset
  repo consulted when a material isn't found in any `--tables` dir; downloads
  land in `--cache` (`--hf-repo` requires `--cache`, and vice versa isn't
  enforced but is pointless).
- `--host` / `--port`: default `127.0.0.1:8642`.
- `--mine-cap` (default `1000`) / `--mine-timeout` (default `30.0` seconds):
  see [`/v1/mine`](#get-v1mine) below.
- `--enable-mine`: turn on `/v1/mine` (position search). **Off by default** —
  a disabled server answers `503 mining_disabled` (see
  [`/v1/mine`](#get-v1mine) below for why: a scan cannot be interrupted by
  `SIGTERM`, its timeout is not deterministic under concurrent load, and
  nothing bounds how many run at once). The CLI `helpmate mine` command is
  unaffected — this flag only gates the HTTP endpoint.
- `--cors-origin ORIGIN` (repeatable): allow cross-origin GETs from `ORIGIN`.
  Omitting it entirely installs **no CORS middleware at all** — not an empty
  allow-list — so same-origin use, including the dashboard served by this
  same process, is unaffected either way.
- `--limit-concurrency N`: forwarded straight to uvicorn's own
  `limit_concurrency`. Beyond `N` connections in flight, uvicorn does not
  refuse the connection — it answers `503` and closes it; that bare
  Starlette response carries no error envelope, and now shares its status
  code with `mining_disabled`. Default `None` — uvicorn's own unbounded
  default — so a local run is never silently capped.

All examples below were captured from a real, locally running server
(`helpmate-server --tables <scratch>` with `<scratch>` generated via
`helpmate.generate("KQvk", tables="<scratch>", threads=2)`, i.e. the `KQvk`
closure: `KQvk` + `Kvk`), on `127.0.0.1:8642`.

### Error envelope

Every non-2xx, non-202 response (including framework-generated 404/405s and
uncaught exceptions) has the same shape:

```json
{"error": {"code": "unknown_material", "message": "...", "hint": "..."}}
```

`hint` is `null` when there is nothing actionable to add.

### `GET /v1/health`

```
$ curl -s http://127.0.0.1:8642/v1/health
{"status":"ok","version":"0.14.0","mine_timeout":30.0,"mining_enabled":false,"tables_local":2,"tables_remote":0}
```

`mine_timeout` (since v0.11.0) echoes the server's `--mine-timeout` setting
in seconds, so a client — the dashboard's search screen, in particular — can
show a countdown against the real budget instead of a guessed one.

`mining_enabled` (since v0.14.0) echoes whether `--enable-mine` was passed.
The dashboard reads it once at boot and, when it is not `true` — including
when the server can't be reached at all — removes the Search screen and its
nav button from the document entirely rather than merely hiding them.

### `GET /v1/materials`

Lists every material the chain of local dirs + remote manifest knows about
(one entry per resolved `.hm`/catalog file; `location` is `local`, `cached`,
or `remote`).

```
$ curl -s http://127.0.0.1:8642/v1/materials
{"materials":[{"material":"KQvk","pieces":3,"size_bytes":146117,"max_dtm":14,"cells":29568,"location":"local"},{"material":"Kvk","pieces":2,"size_bytes":2288,"max_dtm":255,"cells":462,"location":"local"}]}
```

`max_dtm`/`cells` are `null` for a `remote` entry (not yet downloaded, so the
stats sidecar hasn't been read), and for a local table whose sidecar is
missing or unreadable — a run interrupted mid-write leaves a truncated
`.stats.json`, and that costs the one table its two fields rather than
failing the listing (or `/v1/stats`, which walks the same catalog).

### `GET /v1/themes`

The theme registry — name, definition, `needs` and `parameter` (`null`, or
`{name, doc, example}` for `promotions:<types>`) for every one of the thirty-three
entries in [Themes](#themes) above — served straight from the
C++ build so the dashboard's theme picker never hard-codes a list that can
drift from the binary it's talking to:

```
$ curl -s http://127.0.0.1:8642/v1/themes
{"themes":[{"name":"set-play","doc":"Set play: the same position with the other side to move is solvable one move sooner (sibling dtm == this position's dtm - 1) -- the mate is already available and the side to move merely delays it. A sibling one move LONGER is the opposite of set play, not set play.","needs":"plane"},{"name":"pure","doc":"Pure mate: every square of the black king's field is unavailable for exactly one reason, and the king's square is attacked exactly once (so double check is impure).","needs":"solutions"}, ...]}
```

### `GET /v1/materials/{name}/stats`

The full `stats.json` for one material class (same content as `helpmate
stats`; see the [field reference](#statsjson-field-reference) above).

```
$ curl -s http://127.0.0.1:8642/v1/materials/KQvk/stats
{"material":"KQvk","plane_size":29568,"max_dtm":14,"cells":{"invalid":{"wtm":11487,"btm":1512},"unsolvable":{"wtm":0,"btm":414}},"dtm_histogram":{...},"uniqueness":{...},"deepest":[...],"generator_version":"0.5.0"}
```

Unknown material → 404 with the standard envelope:

```
$ curl -s http://127.0.0.1:8642/v1/materials/KNvkqr/stats
{"error":{"code":"unknown_material","message":"no table for material 'KNvkqr'","hint":"generate it with: helpmate gen KNvkqr --tables <dir>"}}
```

### `GET /v1/stats`

Since v0.11.0. The corpus-wide aggregate over every sidecar the chain of
local dirs + remote manifest can see — what the dashboard's Materials screen
shows for its pinned **All tables** entry. Unlike
`/v1/materials/{name}/stats`, this never 404s: an empty tables dir answers
with zeroed counters, not an error.

```
$ curl -s http://127.0.0.1:8642/v1/stats
{"tables":2,"tables_by_pieces":{"2":1,"3":1},"tables_without_stats":0,
 "size_bytes":146585,
 "cells":{"solvable":45723,"unsolvable":1338,"invalid":12999,"total":60060},
 "dtm_histogram":{"btm":{...},"wtm":{...}},
 "uniqueness":{"btm":{"all":{...}},"wtm":{"all":{...}}},
 "max_dtm":14,
 "deepest":[{"material":"KQvk","max_dtm":14}],
 "no_helpmate":["Kvk"],
 "generators":{"0.10.0":2}}
```

- `tables` / `tables_by_pieces` / `size_bytes` come from the catalog alone, so
  they count every table the server can reach, including one whose sidecar
  is missing or unreadable (`tables_without_stats` counts those; a truncated
  sidecar from an interrupted generation run is treated the same way, not as
  a hard failure of the whole endpoint).
- `cells`, `dtm_histogram`, `uniqueness`, `max_dtm` and `deepest` are summed
  only over materials that actually **have** a helpmate — a table storing the
  `DTM_UNSOLVABLE` sentinel everywhere (nothing solvable in that material)
  would otherwise corrupt `max_dtm` and the mate-length histograms. `deepest`
  is the ten materials with the longest mate, ties broken by name.
- `no_helpmate` lists every material that has no helpmate at all — sorted by
  name, not counted into any of the histograms above. On the reference
  corpus this is 67 of 300 tables.
- `generators` tallies each sidecar's `generator_version`, so the spread of
  builds that produced the corpus is visible at a glance.

The response is cached on the identity of every sidecar involved (existence,
mtime, size) — recomputing means re-reading every `.stats.json` in the
corpus, which is not free — so the cache invalidates whenever a table is
newly generated or downloaded, or an existing sidecar is rewritten in place
(a corrected regeneration) even with its `.hm` untouched. Every field of that
key comes from `stat()` alone, so the cache is consulted before any sidecar
is read: measured over the 295-table reference corpus (13 MB of sidecars),
0.41s cold and 0.124s warm per call. Most of what remains on the warm path is
the catalog walk itself, which parses every sidecar to report each table's
`max_dtm`/`cells` on `/v1/materials`.

### `GET /v1/probe`

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"dtm":2,"count":4,"flipped":false,"material":"KQvk","notation":"h#1"}
```

A legal but unsolvable position reports `{"solvable": false, "material": ...}`
(no `dtm` field):

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/8/8/8/8/4k3/8/4K3 w - - 0 1"
{"solvable":false,"material":"Kvk"}
```

`material` names the table that answered here too. There is no `flipped` flag
to read on an unsolvable position — the probe returns no result at all — so
it reports whichever direction resolved: the FEN's own material when that
table exists, and the mirrored one when only the mirror does. Naming the
FEN's material unconditionally advertised a table that cannot exist (had it
existed, no flip would have happened), and every such name 404s on
`/v1/materials/{name}/stats`:

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=8/8/Kq6/8/8/5k2/8/8 w - - 0 1"
{"solvable":false,"material":"KQvk"}
```

A malformed FEN is a 400, not a 404:

```
$ curl -sG http://127.0.0.1:8642/v1/probe --data-urlencode "fen=garbage"
{"error":{"code":"invalid_fen","message":"substring not found","hint":null}}
```

A position that is illegal in a way the table's index cannot address — the
two kings adjacent, or the side not to move left in check — is a different
400: `unprobeable_position`, not `unknown_material`. The table named in the
error *is* present; the position just isn't one it stores. This is distinct
from `404 unknown_material`, which means there is no table at all for that
material — `unprobeable_position` fires even when the Materials screen lists
the table as local, so it must never suggest generating it:

```
$ curl -sG http://127.0.0.1:8699/v1/probe --data-urlencode "fen=8/8/8/8/8/8/1k6/K1Q5 b - - 0 1"
{"error":{"code":"unprobeable_position","message":"this position cannot be looked up in the 'KQvk' table","hint":"the table is present -- the position is not one it stores. An illegal position is the usual cause: check that the two kings are not adjacent and that the side NOT to move is not left in check."}}
```

Like the CLI, `probe` transparently falls back to the color-flipped material
when only that slice is generated, and reports it via `"flipped": true`.
`material` (since v0.11.0) names the table that actually answered — the
mirrored material whenever `flipped` is true, not the one derived from the
FEN as queried. It is what the dashboard's explorer uses to fetch the
per-table statistics band and to link into Materials, and it is deliberately
not something a client should derive itself from the FEN: that would be
wrong in exactly the case that matters.

`?themes=true` (opt-in) adds a `themes` array; see [Themes](#themes) above
for the full semantics, the flip-fallback limitation (`themes: null` +
`themes_note`), and a real captured example.

### `GET /v1/line`

`?all=true` returns every optimal line instead of just the first.

```
$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"lines":[["Kh6","Qh2#"]]}

$ curl -sG http://127.0.0.1:8642/v1/line --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --data-urlencode "all=true"
{"lines":[["Kh6","Qh2#"],["Kh6","Qh1#"],["Kh6","Qg6#"],["Kh8","Qg7#"]]}
```

### `GET /v1/moves`

The position's own value plus **every legal move** with the value it leads
to, in one call. This is what the dashboard's move list is built from: a
browser would otherwise need its own move generator and one `probe` per move.

```
$ curl -sG http://127.0.0.1:8642/v1/moves --data-urlencode "fen=8/7k/5K2/8/8/8/8/6Q1 b - - 0 1"
{"fen":"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1","dtm":2,"count":4,"notation":"h#1","flipped":false,
 "material":"KQvk",
 "moves":[
  {"uci":"h7h6","san":"Kh6","fen":"8/8/5K1k/8/8/8/8/6Q1 w - - 0 1","dtm":1,"count":3,
   "solvable":true,"optimal":true,"notation":"h#0.5"},
  {"uci":"h7h8","san":"Kh8","fen":"7k/8/5K2/8/8/8/8/6Q1 w - - 0 1","dtm":1,"count":1,
   "solvable":true,"optimal":true,"notation":"h#0.5"}]}
```

(line-wrapped here; the server sends one line.)

- `optimal` is `true` exactly when the move reaches `dtm - 1`, i.e. it keeps
  the shortest mate.
- The list is always the **complete** legal-move list. A move leading to an
  unsolvable position, to a material with no table, or to something no
  tablebase can describe (capturing a king, reachable only from an already
  illegal position) carries `"dtm": null, "solvable": false, "optimal": false`
  rather than being omitted.
- An unsolvable query position reports `"solvable": false` at the top level
  and still enumerates its moves — a composer may want to walk into a
  solvable branch. `material` is the table that answered there too (the
  mirrored one when only the mirror resolved), exactly as on `/v1/probe`.
- `material` (since v0.11.0) names the table that answered the *query*
  position, same meaning as on [`/v1/probe`](#get-v1probe) — the mirrored
  material whenever `flipped` is true. It is not per-move: each move's own
  `fen` may belong to a different material again (a capture or promotion), so
  the dashboard calls `/v1/moves` fresh for the position it lands on after
  following a move, and re-reads `material` from that response, rather than
  reusing the value from the position it moved away from.
- Errors follow `probe`: 400 `invalid_fen`, 400 `unprobeable_position` for a
  position the table's index can't address (kings adjacent, etc. — see
  [`/v1/probe`](#get-v1probe) above), 404 `unknown_material` with the
  `helpmate gen …` hint, and the 202-fetching contract for remote-only
  material. The color-flip fallback applies too, reported as `"flipped": true`.

### `GET /v1/mine`

**Off by default.** A scan cannot be interrupted by `SIGTERM`, its timeout is
not deterministic under concurrent load, and nothing bounds how many run at
once — so it is not safe to expose until that work is done. Start the server
with `--enable-mine` to turn it on; without it, every request — regardless of
its query parameters — answers `503 mining_disabled`:

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2"
{"error":{"code":"mining_disabled","message":"position search is disabled on this server","hint":"start helpmate-server with --enable-mine to turn it on"}}
```

This gates only the HTTP endpoint; the CLI `helpmate mine` command is
unaffected. The dashboard reads `mining_enabled` from
[`/v1/health`](#get-v1health) once at boot and omits the Search screen
entirely — not merely hides it — when it is not `true`.

Parameters: `material`, `dtm` (required), `count` (optional, exact match),
`starts` / `ends` (optional, exact match on the number of distinct first
moves / distinct mating moves among the optimal solutions — see the CLI
[`mine`](#mine--scan-for-composition-candidates) section for what these mean
and why the golden `8/8/8/8/8/2K5/7Q/1k6 b - - 0 1` position has `starts=2,
ends=4`), repeatable `theme` (optional — see [Themes](#themes) above for the
match semantics, an unknown-name example, and the performance caveat), and
`max`.

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=1" --data-urlencode "max=3"
{"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1","8/8/8/8/8/2Q5/8/k1K5 b - - 0 1","8/8/8/8/4Q3/8/8/k1K5 b - - 0 1"],"truncated":true,"skipped_saturated":0}
```

Every response carries `skipped_saturated`: the number of matched-so-far
positions whose stored solution count was saturated (255+, unenumerable) and
so had to be skipped rather than checked against `starts`/`ends`/`theme` — 0
when none of `starts`, `ends` or `theme` is given (nothing forces solution
enumeration, so nothing is ever skipped on this account), or when nothing
saturated was encountered (as above; `KQvk` has no saturated-count
positions). A theme-only query (`starts`/`ends` both omitted) skips and
tallies saturated positions exactly the same way `starts`/`ends` do — a
saturated position's solutions can't be enumerated, so it can't be checked
against a theme filter either. `starts`/`ends` narrow the match to a
specific dual shape:

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=4" --data-urlencode "starts=2" --data-urlencode "ends=4" --data-urlencode "max=3"
{"fens":["8/8/8/8/8/2K5/4Q3/1k6 b - - 0 1","8/8/8/8/8/2K5/7Q/1k6 b - - 0 1"],"truncated":false,"skipped_saturated":0}
```

`starts`/`ends` must each be `>= 1`, and `<= count` if `count` is also given
(a position with `count` solutions can't have more distinct starts or ends
than that); violating either is a `400 invalid_filter`, e.g. asking for more
starts than the position could possibly have:

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "count=4" --data-urlencode "starts=5"
{"error":{"code":"invalid_filter","message":"starts=5 cannot exceed count=4","hint":"a position with N solutions has at most N distinct starting or mating moves"}}
```

`truncated` is `true` whenever more matches exist than were returned (as
here: `KQvk` has more than 3 positions at `dtm=2, count=1`, so `max=3` cuts
it off) — either because the caller's own `?max=` was reached, or because
the server-side `--mine-cap` was reached first (whichever is smaller wins;
the request's `max` is clamped to `min(max, mine-cap)`). Example with a
server started as `helpmate-server --tables <scratch> --mine-cap 3` and the
client asking for
`max=50` (more than 3 matches exist at this dtm, so the 3-row server cap
bites, not the client's 50):

```
$ curl -sG http://127.0.0.1:8644/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2" --data-urlencode "max=50"
{"fens":["8/8/8/8/8/8/8/k1KQ4 b - - 0 1","8/8/8/8/8/2Q5/8/k1K5 b - - 0 1","8/8/8/8/1Q6/8/8/k1K5 b - - 0 1"],"truncated":true,"skipped_saturated":0}
```

If the scan doesn't finish within `--mine-timeout` seconds (default 30; a
server-only setting, not a query parameter), the endpoint returns an empty,
truncated result rather than blocking indefinitely, with a `note` field
explaining why (server started as `helpmate-server --tables <scratch>
--mine-timeout 0`, forcing an immediate timeout):

```
$ curl -sG http://127.0.0.1:8645/v1/mine --data-urlencode "material=KQvk" --data-urlencode "dtm=2"
{"fens":[],"truncated":true,"note":"timeout","skipped_saturated":0}
```

When a scan genuinely exhausts the whole material with fewer matches than
`max`/`mine-cap`, `truncated` is `false` (e.g. `Kvk` is unsolvable
everywhere, so `dtm=2` matches nothing):

```
$ curl -sG http://127.0.0.1:8642/v1/mine --data-urlencode "material=Kvk" --data-urlencode "dtm=2"
{"fens":[],"truncated":false,"skipped_saturated":0}
```

### The 202-fetching contract

Any endpoint that needs a material (`stats`, `probe`, `line`, `mine`) checks
the local `--tables` dirs first, then the `--hf-repo` remote if configured.
If the material is only in the remote manifest and not yet cached locally,
the **first** request that touches it kicks off a background download and
immediately returns `202 Accepted`. (The examples below use port 8643 — a
second real server, started with `KQvk` only in a fake remote-hub manifest
and no local `--tables` copy, to exercise this path; `--hf-repo` in practice
points at a real Hugging Face dataset instead of a fake hub.)

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 202 Accepted
content-type: application/json

{"status":"fetching","material":"KQvk","size_bytes":146117}
```

Any request that arrives **while** the download is still in flight (whether
it's the same client polling or a different one) also gets `202`, this time
without `size_bytes` (already known to be fetching, no need to look it up
again):

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 202 Accepted
content-type: application/json

{"status":"fetching","material":"KQvk"}
```

Once the download finishes (verified against the manifest's sha256; see
below), subsequent requests resolve normally with `200`:

```
$ curl -si http://127.0.0.1:8643/v1/materials/KQvk/stats
HTTP/1.1 200 OK
content-type: application/json

{"material":"KQvk","plane_size":29568,...}
```

If the download fails (network error, sha256 mismatch), the state becomes
`failed` and requests get a `502` with `fetch_failed`:

```json
{"error": {"code": "fetch_failed", "message": "download of 'KQvk' failed",
           "hint": "check server logs; retry triggers a new download"}}
```

The `hint` is truthful: the very request that *observes* the `failed` state
(the one returning this `502`) re-triggers `start_fetch` before responding,
so by the time the client retries, the download is already under way again.
Concretely: request N discovers the failure and answers `502`; request N+1
already sees `fetching` and answers `202`; once the retried download
finishes, subsequent requests resolve `200` as normal. No server restart
is needed to recover from a bad download.

A material present in neither local dirs nor the remote manifest is a plain
`404 unknown_material`, same as the fully-offline case.

### `helpmate-tables` — push/pull to a Hugging Face dataset

```bash
pip install . ./src/packages/api   # same install as the API server
```

```
helpmate-tables push --tables DIR --repo USER/DATASET [--material NAME ...]
helpmate-tables pull --tables DIR --repo USER/DATASET [--material NAME ...]
```

- `--tables DIR`: local directory to push from / pull into.
- `--repo USER/DATASET`: a Hugging Face **dataset** repo id.
- `--material NAME` (repeatable): restrict the operation to specific
  materials (matches both the `.hm` and `.stats.json` files for that name).
  **Omit it to operate on every material** — `push` with no `--material`
  uploads every `.hm`/`.stats.json` pair found under `--tables`; `pull` with
  no `--material` downloads every material listed in the remote manifest.

**`push`** first (re)writes a local `manifest.json` in `--tables` covering
*every* file currently in that directory (not just the ones being pushed),
then fetches the *existing remote* manifest (if any) and **merges**: files
for the pushed materials are added/updated with their fresh sha256/size,
while every other entry already on the remote manifest is carried forward
unchanged. This means a scoped `push --material X` never forgets materials
a previous, different push already uploaded — the remote manifest only ever
grows or updates, never shrinks, from a scoped push. If the remote has no
manifest yet (first push to a fresh dataset repo), the merge starts from an
empty file set.

**`pull`** fetches the remote manifest, downloads the requested (or, by
default, *all*) `.hm`/`.stats.json` files into `--tables`, and verifies each
downloaded file's sha256 against the manifest entry before accepting it;
a mismatch deletes the partial file and fails the whole pull.

### Manifest format (`manifest.json`)

```json
{
  "schema": 1,
  "generator_version": "0.5.0",
  "files": {
    "KQvk.hm": {"sha256": "<hex>", "size": 146117},
    "KQvk.stats.json": {"sha256": "<hex>", "size": 27781}
  }
}
```

`generator_version` is read from the first `*.stats.json` found in
`--tables` (`"unknown"` if none exist yet). `files` maps every `.hm`/
`.stats.json` filename present under `--tables` at push time to its sha256
and byte size — these are the only two file patterns the manifest ever
records. When `pull` has no `--material`, it derives "all materials" from
every `.hm` entry in `files` (its `.stats.json` sibling is pulled too, if
present).

### Exit codes (`helpmate-tables`)

| Code | Meaning |
|---|---|
| `0` | success. |
| `1` | operation failed after starting (network error, remote has no manifest on `pull`, sha256 mismatch, upload error) — message on stderr, no traceback. |
| `2` | bad usage (`--tables` not a directory, no subcommand given). |

### Smoke-testing a running server

`tools/api_smoke.py` exercises every `/v1` route against a live server and
checks response shapes, the error envelope, and — when a `KQvk` table is
served — the golden values pinned by the C++/Python/CLI test suites. It uses
only the Python standard library, so it runs anywhere the server does,
including against a remote deployment.

```console
$ helpmate-server --tables ~/tb --port 8642 &
$ python3 tools/api_smoke.py --url http://127.0.0.1:8642
helpmate API smoke test against http://127.0.0.1:8642

[health]
  ok   GET /v1/health -> 200
  ok   health reports status/version
       version 0.6.0, 2 local / 0 remote table(s)

[catalog]
  ok   GET /v1/materials -> 200
  ok   catalog is non-empty
  ok   catalog entries carry pieces/size/location
       KQvk, Kvk
       exercising material: KQvk
...
[errors]
  ok   invalid FEN -> 400 envelope
  ok   missing parameter -> 400 envelope
  ok   path traversal in material -> 400 envelope
  ok   unknown material -> 404 envelope with a gen hint
  ok   unknown route -> 404 envelope

20 passed, 0 failed
```

Options:

| Flag | Meaning |
|---|---|
| `--url URL` | base URL of the running server (default `http://127.0.0.1:8642`). |
| `--material NAME` | material to exercise `probe`/`line`/`mine` against. Defaults to `KQvk` when it is served (enabling the golden-value checks), otherwise the first catalogued material — for which the script mines a position and verifies that `probe` and `line` agree with it. |
| `--fetch-timeout N` | when a route answers `202 fetching` (the material lives only on the remote), keep polling for up to `N` seconds instead of skipping the check. Downloads can be large; `0` (the default) does not wait. |

Exit status: `0` all checks passed, `1` at least one failed (each is listed
again at the end), `2` the server was unreachable.

# Condensing the helpmate tablebases: storage and computation

Research report, 2026-10-03. Analysis only, nothing was implemented. Backlog entry:
`docs/ROADMAP.md`, "Major question 1". The measurements were done on copies of real tables
(scratch scripts not kept in the repo).

## Executive summary

1. **Most bytes are solution counts, not DTM.** The two count planes are 66–80 % of every
   compressed table measured; DTM is 20–34 %. 30–84 % of solvable cells hold the saturated
   count 255. Every consumer that matters needs only "unique / dual / many" (`count==1`, the
   enumeration cap, `--count 1`).
2. **Biggest win, low risk: counts as a 2-bit class {0, 1, 2, 3+}.** With don't-care filling of
   illegal cells the count planes shrink from 66–80 % of the file to 3–6 %. The class is closed
   under the generator's rule, `min(Σc,3) = min(Σmin(c,3),3)`, so it can be computed and looked
   up in sub-tables exactly.
3. **Don't-care filling of illegal cells** (Syzygy, Chinook, Lomonosov) cuts the DTM planes by
   20–50 % at the same zstd setting; **zstd level 19** with 256 KiB–1 MiB blocks halves them
   again.
4. **All three, both sides to move kept: 4.8–11.6× smaller** (5 five-piece tables, 1 six-piece
   table). Corpus roughly 341 → 45–70 GiB. Needs a format version bump; existing tables convert
   by streaming, no regeneration.
5. **Storing only Black to move** (Syzygy's one-side trick) gives 15.8× on the six-piece table,
   corpus est. 20–30 GiB. Cost: every wtm probe becomes a 1-ply search (20–40 child probes),
   line enumeration steps 2 plies, and mining odd DTM (h#n.5) becomes impractical unless the wtm
   planes ship as an optional extra file.
6. **A better index (Nalimov/Syzygy style) barely changes the compressed size** (legal cells
   only vs. filled: within ±10 %). It is a RAM lever for generation: 1.25–2.5× fewer cells.
7. **Generation:** 2-bit counts in RAM take 4 → 2.5 B/cell; a bitmap-frontier generator
   (Thompson/Syzygy style) needs about 1 B/cell, so a pawnless six-piece class would need about
   7 GiB instead of 28.9 GiB. Merging the count sweep into the scan passes saves one full
   move-generation pass. A retrograde (unmove) generator is the larger, speculative speed win.

## How others do it

- **Syzygy (R. de Man).** WDL stores both sides; DTZ stores **one side only** (the generator
  estimates both and keeps the smaller). Illegal, broken and capture-resolved positions are
  don't-cares, WDL also has partial don't-cares. DTZ values remapped by frequency. Re-Pair-style
  pair substitution plus canonical Huffman, tiny blocks (64 B WDL, 1 KiB DTZ), piece order in
  the index searched per table. Generation 2 B/cell. 6-man 68 GB WDL + 82 GB DTZ.
- **Nalimov.** DTM in 1 byte, two-sided files; 462 / 3612 king pairs, like pieces as
  N(N−1)/2; datacomp (LZ + Huffman), 8 KiB blocks. 5-man 7.1 GiB, 6-man 1.2 TiB.
- **Gaviota.** DTM 1 B/position, selectable codecs (LZMA default); 5-man 6.5 GiB with LZMA.
- **Lomonosov 7-man.** DTM, about 140 TB; data reordering, Re-Pair, "underdetermined values"
  (don't-cares).
- **Thompson 1986/1996.** Generation on bitmaps (1 bit per position per set), DTM only as
  output; distributed Huffman-coded.
- **Bourzutschky/Konoval, Lichess op1 (8-man partial).** One file per king configuration,
  block index plus zstd blocks.
- **Shredderbases, Scorpio:** WDL bitbases, one side. **Chinook checkers:** 2 bits/position,
  capture positions get the dominant value, run-length coding.
- **Helpmate / problem databases:** none found apart from this project.

## What transfers to helpmates

| Idea | Transfers? | Notes |
|---|---|---|
| Don't-care for illegal cells | yes | the reader can always compute legality; add a "side not to move in check" test; `mine` re-checks candidates; stats come from the generator |
| Store one side to move | partly | `dtm_wtm(p) = 1 + min over White moves of dtm_btm(child)`; wtm probe ≈ 20–40 child probes; `lines` steps 2 plies; `set-play` needs a 1-ply probe; odd-DTM mining needs a whole plane derivation. Keep btm (h#n starts with Black) |
| Partial don't-care for capture-optimal cells | speculative | conflicts with counts; not measured |
| Value remap / moves instead of plies | no gain | DTM parity is fixed already |
| Smarter index (C(n,k), skip occupied squares) | RAM yes, disk barely | like pieces are not combined today (`slice_index.cpp`); KBBvkn is 58.6 % invalid |
| Per-table piece order | small | current order is near best on KRvkrb |
| Re-Pair + Huffman, tiny blocks | possible | maybe 10–30 % over zstd 19, high effort |
| 2-bit / "has mate" bitbases | as count class | the 2-bit class already encodes "solvable / unique" |
| Bitmap generation, out-of-core slices | yes | see options |

What consumers need from counts: uniqueness (`count==1`) for booklets, site and `mine --count 1`;
the count as enumeration cap (255 already means "use 100"); `shape_of` refuses saturated cells;
exact `--count n` for n ≥ 3 can be answered on demand by a memoised count over the optimal-move
DAG capped at n+1; per-DTM count histograms in `stats.json` are produced at generation time.
Dropping the count plane entirely is too slow for `mine --count 1` over 10⁷–10⁸ candidates.

## Measurements

"Fill" = naive forward fill of each `DTM_INVALID` cell (and its count) with the previous legal
value; "c2" = `min(count, 3)` on solvable cells. Ratios are of today's file size. KBvkqqn was
sampled (6.9 % of cells; extrapolated baseline matches the file).

| table | dtm / cnt share today | fill dtm z3 64K | fill dtm z19 1M | c2 fill z19 1M | **A** = both sides, all three |
|---|---|---|---|---|---|
| KRvkrb | 0.21 / 0.79 | 0.116 | 0.047 | 0.039 | **0.086 (11.6×)** |
| KBBvkn | 0.27 / 0.73 | 0.207 | 0.095 | 0.036 | **0.131 (7.6×)** |
| KQvkqq | 0.23 / 0.77 | 0.179 | 0.082 | 0.063 | **0.145 (6.9×)** |
| KPvkqp | 0.26 / 0.74 | 0.199 | 0.106 | 0.032 | **0.138 (7.2×)** |
| KBNPvk | 0.22 / 0.78 | 0.190 | 0.085 | 0.060 | **0.145 (6.9×)** |
| KBvkqqn (6p) | 0.34 / 0.66 | 0.316 | 0.172 | 0.037 | **0.209 (4.8×)** |

- Btm only (KBvkqqn): 0.053 + 0.010 = **0.063 (15.8×)**.
- Exact counts kept but filled + z19: 0.59–0.68 — lossless options top out around 1.5×.
- Counts capped at 15 (4-bit): 0.038 vs 0.010 for c2.
- Level matters more than block size (z3 64K 0.106 → z19 64K 0.067 → z19 1M 0.053).
- Order-0 entropy coding per block is 2–5× worse than zstd: a dead end without context modelling.
- Legal cells only (perfect index bound) vs fill: within 10 %.
- Interleaving dtm+cnt per cell is worse than separate planes.
- Index axis order: current near best; king pair last is 2–3× worse.
- zstd 19 at 1 MiB ≈ 64 MB/s over 16 threads: about 8 min to recompress a six-piece table.
- Illegal cells 13–82 % per plane; `count==1` 0.4–5 % of solvable cells; `count==255` 29–84 %.

## Options ranked

| # | Option | Size effect | Probe cost | Generation | Compat | Effort |
|---|---|---|---|---|---|---|
| 1 | 2-bit count class + fill | table 2.5–4× smaller at z3 | `--count n≥3`, `shape_of` on "3+" need an on-demand count | RAM −37 % if used in generation | v4; convert by streaming | M |
| 2 | Don't-care fill of illegal cells | DTM −20…−50 % | legality computed, `mine` re-checks | none | v4 flag | S |
| 3 | zstd 19, 256 KiB–1 MiB blocks | DTM ≈ −45 %, counts ≈ −40 % | cold probe ≈ 0.25–1 ms (est.) | +8 min per 6p write | none | XS |
| 1+2+3 | "A", both sides | **4.8–11.6×**, corpus ≈ 45–70 GiB | as above | as above | v4 + converter | M |
| 4 | Btm only, wtm optional extra file | 6p 15.8×, corpus est. 20–30 GiB | wtm probe ×20–40, `lines` 2-ply steps, odd-DTM mining expensive | none | v4 planes field | M |
| 5 | Exact counts as optional extra file | +0.17–0.6 on top of A | none when present | none | additive | S |
| 6 | Nalimov/Syzygy index | disk ≤ −10 %, RAM 1.25–2.5× | rank/unrank | RAM −20…−60 % | new table identity | L |
| 7 | Per-table piece order | few % | none | search at write | header field | S–M |
| 8 | Re-Pair + Huffman | est. −10…−30 % vs z19 | fast tiny blocks | slow compressor | new codec | L |
| 9 | Partial don't-care for capture-optimal cells | unknown | captures-only 1-ply | — | v4 | M |
| 10 | Counts in the scan pass, 2-bit RAM | — | — | 4 → 2.5 B/cell, one pass less | — | M |
| 11 | Bitmap frontier generator | — | — | ≈ 1 B/cell: 6p pawnless ≈ 7 GiB | unchanged | L |
| 12 | Retrograde (unmove) generator | — | — | est. 2–5× faster | unchanged | XL |
| 13 | Out-of-core per-KK-slice files | per-slice download | none | enables 7 pieces | new layout | XL |

## Recommended roadmap

1. **Quick win, no format change:** recompress to zstd 19 / 256 KiB blocks (≈ −15…−20 %),
   validating probe/mine latency with bigger blocks.
2. **Format v4 (core):** planes-present bitmap, count encoding (exact / c2), fill flag; probe and
   mine compute legality; on-demand capped count for `--count n≥3`; `compact --to-v4` converts;
   verify hashes canonical decoded content on legal cells. Expected 5–12× smaller. Measure 2–3
   one-pawn six-piece tables first.
3. **Two download tiers:** core = btm dtm + btm c2 (≈ 16×), extra = wtm planes and exact counts.
4. **Generator RAM:** #10, then #11 — every six-piece class within 32 GiB.
5. **Long term:** #6 or #12 only for seven pieces; #8 only if size is still the bottleneck.

## Open questions

- Is h#n.5 / wtm mining (odd DTM, `set-play`) important enough to keep wtm in the default download?
- Are exact counts beyond "3+" worth a 2–5× larger file, or is an on-demand capped count enough?
- One-pawn six-piece tables were not measured.
- How much better is an optimal (Syzygy-style) don't-care fill than the naive forward fill?
- Probe/mine latency with 256 KiB / 1 MiB z19 blocks is not benchmarked
  (`tools/bench_compression.py`).

## Sources

Repo: `src/core/format/table_file.{h,cpp}`, `block_codec.cpp`, `src/core/indexing/slice_index.cpp`,
`kk.cpp`, `src/core/generator/generator.cpp`, `src/core/probe/tablebase.cpp`, `mine_set.cpp`,
`src/core/themes/registry.cpp`, `docs/INTERNALS.md`, `docs/COOPERATIVE-TABLEBASE.md`.

External: https://github.com/syzygy1/tb · https://www.chessprogramming.org/Syzygy_Bases ·
https://github.com/jdart1/Fathom · https://www.chessprogramming.org/Nalimov_Tablebases ·
https://centaur.reading.ac.uk/4562/ · https://github.com/michiguel/Gaviota-Tablebases ·
https://chessprogramming.org/Lomonosov_Tablebases ·
https://link.springer.com/article/10.3103/S0278641916010076 ·
https://archive.org/details/thompson86endgame · https://archive.org/details/thompson96endgame ·
https://github.com/lichess-org/op1 · https://www.chessprogramming.org/Scorpio_Bitbases ·
https://webdocs.cs.ualberta.ca/~jonathan/publications/ai_publications/checksolved.pdf ·
https://arxiv.org/pdf/2010.09271. Lomonosov and Bourzutschky internals are not public beyond
abstracts.

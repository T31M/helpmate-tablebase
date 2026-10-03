# Extending the tablebase to other stipulations

Research report, 2026-10-03. Analysis only, nothing was implemented. Backlog entry:
`docs/ROADMAP.md`, "Major question 2". A toy prototype (python-chess, explicit move graph) was
used to check the recurrences; it is not kept in the repo.

## Executive summary

- **The generator is already close to general.** `SliceGen::scan_pass` is a forward-scan fixed
  point: each pass examines every unresolved cell's legal moves and their successors, it never
  generates moves backwards. Switching a side from MIN (some successor at d-1) to MAX (all
  successors resolved at ≤ d-1, at least one at d-1) changes about three lines. The adversarial
  genres (#, s#, r#, =, s=) need no unmove generator to be correct, only to be fast on deep
  classes.
- **Four parameters describe almost every orthodox stipulation:** the goal (which colour is
  mated or stalemated), the aggregation per colour (MIN wants the goal, MAX resists), the move
  schedule (alternating, or series by one side), and obligations (reflex "must mate in 1", the
  series rule "no check except on the last move"). Popeye's `sstipulation` grammar shows the
  decomposition covers the field.
- **"Number of solutions" depends on the genre.** Codex Art. 13(2): help-play (h#, hs#, h=,
  series movers) is unsound if dualized, so today's whole-line count (`count==1`) carries over.
  Direct play (#, s#, r#) is sound with a unique key and no short solution (Art. 9–11); duals
  after the key are flaws. There the stored count should be local: the number of optimal moves
  at that node.
- **Recommendation:** genre layer with helpmate as genre 0 (byte-identical), then h= / hs#
  (predicate changes only, prove the plumbing), then **ser-h#** (best value for the effort),
  then # (exhaustively checkable against Gaviota/Nalimov) as the validation vehicle for **s#**
  (highest novelty: no public selfmate tablebase found).
- **Prototype:** the forward-scan min/max recurrence reproduces the known KRvk maximum #16
  (31 plies) and counts all 368,452 legal KQvk positions; ser-h# on KQvk gives 29,580 solvable
  Black-to-move positions (unreduced board), longest ser-h#12. Unique-key share for KRvk #n
  falls from 85 % at #2 to 0 % at #16.

## Genres

Notation: V(p, stm) in plies, goal state = 0. A MIN cell resolves to d if some allowed successor
has d-1; a MAX cell resolves to d if it has an allowed move, every allowed successor is resolved
≤ d-1 and at least one equals d-1. Dead terminals (wrong mate, stalemate, no moves) stay
unresolved, as today.

### Selfmate s#n

- **Rules:** White moves first and forces Black to mate White within n moves; Black resists and
  mates only when he has no other legal move (Codex fn. 9(c)).
- **Value:** adversarial; White MIN, Black MAX; goal = White to move and checkmated.
- **Recurrence:** init `dtm_wtm=0` where White is mated (today's init with colours swapped;
  `init_pass` hard-codes Black). Same index, same 4 planes, same capture/promotion closure, but
  the sub-tables must be s# tables. Helpmate data of `flip(M)` gives an admissible lower bound
  (forced ≥ cooperative) to skip cells.
- **Counts:** `cnt_wtm` = number of optimal White moves; at an exact root `dtm_wtm==2n-1 &&
  cnt==1` means a unique key. Dual-freeness is tree-wide and budget-dependent: compute on
  demand per mined candidate.
- **Prune:** empty if Black is a bare king (reverse of today's rule).
- **Cost:** same RAM as helpmate; pass count = maximal s# depth (unknown, possibly deep).

### Series helpmate ser-h#n

- **Rules:** Black plays n moves in a row, then White mates in one. Black may not give check
  except on the last series move; a final double step can enable an en-passant mate.
- **Value:** single-player shortest path, in Black moves.
- **Recurrence:** one plane (btm). S(p)=1 if some Black move reaches a position where White
  mates in one — exactly the existing helpmate wtm plane with dtm==1 (via `eval_board`, en
  passant included). Otherwise S(p)=1+min S(q') over non-checking Black moves, q' with Black to
  move again. The closure follows only Black captures and promotions. Pass d reads and writes the
  same plane: use relaxed `std::atomic_ref<uint8_t>` or commit each pass from a bitmap, and
  re-prove 1-thread vs N-thread byte identity.
- **Counts:** sum over optimal Black moves, times the number of White mating moves at the end;
  move orders count as different solutions, so `count==1` means sound, as today.
- **Cost:** 2 B/cell, one movegen side, ≤ ½ of helpmate. Siblings ser-#, ser-h=, ser-= use the
  same engine.

### Direct mate #n

- **Rules:** White to move mates within n moves against any defence; no 50-move rule, no castling.
- **Value:** classic minimax DTM; init and parity as today.
- **Context:** Nalimov, Gaviota and Lomonosov store DTM; Syzygy stores WDL+DTZ. DTM is not new
  data — new would be key counts (uniqueness), mining for sound #n, problem themes.
- **Free oracle:** every # table up to 5 pieces can be checked exhaustively against Gaviota
  (python-chess `chess.gaviota`).
- **Byte limit:** the deepest 6-man mate is KRNvKNN #262 (523 plies) > `DTM_MAX=252`. Options: a
  depth cap stored in the header with a `BEYOND` sentinel (recommended; exact up to the cap if
  every sub-table uses the same cap), or 16-bit planes (format bump).
- **Cost:** the forward scan rescans every unresolved cell per pass and draws stay unresolved:
  hundreds of passes for some 6-man classes. Remedies: the cap, helpmate lower-bound skipping,
  a retrograde unmove generator with per-cell counters (O(edges); the counter can borrow the
  `cnt` plane). The `misses<2` stop rule stays valid.

### Other genres, briefly

- **Reflexmate r# / semi-r#:** like s# plus an "allowed moves" filter: if the mover can mate in
  one, only mating moves are allowed (both sides in r#, Black only in semi-r#). Needs a
  mate-in-1 bit per cell.
- **Helpselfmate hs#n:** cooperative MIN/MIN until Black is forced to mate (s#1) — today's
  generator with a new init predicate.
- **Series selfmate / reflexmate ser-s#, ser-r#:** series engine with a per-cell terminal bit.
- **Stalemate goals = / h= / s= / hs= / ser-h=:** goal predicate becomes stalemate; prune rules
  change (Kvkp can be h=, KvK cannot).
- **Proof games:** not position-valued (unique game from the initial array); solved by guided
  search (Natch, Euclide, Popeye). Not tablebase-able; retro problems likewise.
- **Fairy conditions/pieces:** out of scope — Circe breaks the acyclic material DAG and the
  symmetries, Madrasi/Andernach change legality; needs a pluggable movegen and cyclic closure
  (the roadmap's fairy track). Popeye has no licence file: usable as an external oracle only.

## Common abstraction

```
struct Genre {
  Goal goal;            // {MATE|STALEMATE} x mated colour
  Agg agg[2];           // per colour: MIN | MAX
  Schedule sched;       // ALTERNATE | SERIES(side)
  bool reflex[2];       // obliged to mate in 1 (r#: both; semi-r#: Black)
  bool series_no_check; // non-final series moves may not check
  Terminal terminal;    // in-state predicate, or lookup (ser-h#: hm_wtm==1)
  CountRule count;      // LINES (help/series) | LOCAL (direct play)
  uint8_t cap;          // depth cap (BEYOND above)
  Prune prune;          // empty-material rule
};
```

`init_pass` evaluates goal/terminal, `scan_pass(d)` picks mover and plane from the schedule and
applies MIN or MAX over the allowed moves, `count_sweep` switches on the count rule. For a MAX
side the en-passant branch of `eval_board` must be merged with max, not min (a bug trap). Keep
the genre a template parameter (`SliceGen<Genre>`) so helpmate's hot loop compiles as today.

| genre | value | planes | reuse of existing data |
|---|---|---|---|
| h# (today) | min/min | 4 | — |
| h=, hs#, hs= | min/min | 4 | same engine, new predicate |
| ser-h#, ser-h= | min (one player) | 2 | helpmate wtm plane is the terminal |
| ser-#, ser-= | min (one player) | 2 | helpmate btm dtm==0 is the terminal |
| ser-s#, ser-r# | min (one player) | 2 | per-cell terminal bit |
| #, = | min/max | 4 | helpmate as lower bound; Gaviota as oracle |
| s#, r#, semi-r#, s= | min/max (+reflex) | 4 | helpmate of flip(M) as lower bound |

No genre can be derived value-for-value from another, but series genres and hs# consume
helpmate tables as terminal oracles, so the helpmate corpus becomes a dependency and verify
must record which corpus version was used.

## Data, format and site implications

- **Header:** `genre_id` and `cap` in `reserved[9]`; non-helpmate files as format version 4 so old
  readers reject them instead of misreading them; helpmate files stay v3 (hashes, manifest and
  verify unchanged). Metadata gains `genre`, `cap`, `count_rule`, `depends_on`.
- **Names:** material names collide across genres, and `#` is a URL fragment. Per-genre
  directories with URL-safe slugs: `tables/` stays helpmate, new genres under e.g.
  `genres/selfmate/`, `genres/ser-helpmate/`, `genres/directmate-c126/`. The colour-flip
  fallback in `Tablebase` is only valid for colour-relative genres.
- **Hugging Face:** same repo, one subfolder per genre, one manifest with a `genre` field;
  markers per genre (prune verdicts differ).
- **Verify per genre:** generalised internal oracle (min/max, series), Popeye as sampled
  external oracle, exhaustive python-chess BFS on small materials, exhaustive Gaviota for #,
  1-thread vs N-thread identity.
- **Probe/line/mine/themes:** help and series genres return a line as today; adversarial genres
  return a tree (key, each defence, continuations within the budget). `mine --genre`; `count==1`
  = unique line (help/series) or unique key (direct). Series themes: Excelsior, switchback,
  rundlauf. Direct-play themes (tries, refutations, changed mates) are new and tree-based.
- **Site:** genre dimension in material pages, DEEPEST per genre, stipulation label from genre
  plus depth.

## Recommended order

| phase | content | effort | value |
|---|---|---|---|
| 0 | Genre struct, templated generator, v4 header, paths, manifest, `Tablebase` genre parameter; helpmate regenerates byte-identically | M | enabling |
| 1 | h= and hs# (predicate + prune), oracle and python-chess cross-check, site label | S | medium |
| 2 | Series engine: ser-h#, then ser-#, ser-h=, ser-=; atomic same-plane writes; Popeye sampling | M | **high** |
| 3 | Adversarial engine: # with cap (exhaustive Gaviota check), tree-shaped line, key counts | M–L | medium |
| 4 | s#, semi-r#, r#, =, s=; helpmate-flip lower bound; dual-free check on demand | M | **high novelty** |
| 5 | ser-s#, ser-r#; unmove generator if 6-piece adversarial runs are wanted | L | niche |
| — | Proof games never; fairy on its own track | — | — |

If only one genre is built, make it **ser-h#**. If the adversarial engine is wanted, build #
first purely as the validation vehicle for s#.

## Open questions

1. The Codex tolerates final-move promotion duals (Q/R, Q/B) in help-play; today's count treats
   them as distinct solutions, so some count==2 helpmates are sound. Collapse them?
2. hs# and s#: are several mating choices on Black's final move duals? (Proposed: no.)
3. Depth cap for # and s#: which n?
4. Genres colour-relative or absolute (decides the flip fallback)?
5. Same Hugging Face repo or one per genre? Does a `depends_on` field block contributions?
6. Public selfmate or series tablebases missed? None found (moderate confidence).
7. Popeye licence: external oracle fine, embedding not settled.

## Sources

- WFCC Codex for Chess Composition (Art. 5 fn. 9, Art. 8–13): https://www.wfcc.ch/rules/codex/ ;
  Harkola, *Handbook of Chess Composition*: https://www.wfcc.ch/wp-content/uploads/2013/05/hcc51.pdf
- Popeye `py-engl.txt` (stipulation grammar): https://github.com/thomas-maeder/popeye
- Wikipedia: Seriesmover, Chess problem, Reflexmate, Selfmate, Helpmate, Endgame tablebase
- Chessprogramming wiki: Retrograde Analysis, Endgame Tablebases
- Syzygy WDL/DTZ vs DTM: https://python-chess.readthedocs.io/en/latest/syzygy.html
- KRNvKNN #262: https://en.chessbase.com/post/just-one-of-17-823-400-766-positions ; Lomonosov
  DTM: https://tb7.chessok.com/articles/Top8DTM_eng
- Z. Zhang, complexity of selfmate and reflexmate problems: https://arxiv.org/abs/2208.05376 ;
  complexity of retrograde and helpmate problems: https://arxiv.org/pdf/2010.09271
- Repo: `src/core/generator/generator.cpp`, `eval.h`, `src/core/format/table_file.h`,
  `src/core/probe/tablebase.cpp`, `docs/COOPERATIVE-TABLEBASE.md`, `docs/INTERNALS.md`

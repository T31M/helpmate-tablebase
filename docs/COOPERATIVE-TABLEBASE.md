# A tablebase for a cooperative game

*How the helpmate tablebases are indexed, generated, stored and checked, for
people who already know what Syzygy does. The long version is
[INTERNALS.md](INTERNALS.md); the code is
[osick/helpmate-tablebase](https://github.com/osick/helpmate-tablebase) and
the tables are on
[Hugging Face](https://huggingface.co/datasets/osick/helpmate-tables).*

Every endgame tablebase you have used solves an adversarial game: one side
tries to win, the other tries not to lose, and retrograde analysis alternates
between "any move wins" and "every move loses". A helpmate is not that game.
Black moves first and *helps* White deliver mate as fast as possible. Both
sides want the same thing, so the position value is a plain shortest path
through the move graph: `dtm(p) = 1 + min over successors`, mate is distance
zero, and a position nobody can reach mate from is unsolvable. There is no
minimax anywhere in the generator.

Composers publish these as `h#n` problems, and a problem is only worth
something if the solution is *unique*. That gives the table a second field
adversarial tablebases never needed: the **number of distinct optimal
solutions**. For every legal position in a material class the table stores
distance to mate and how many shortest mating lines tie. `count = 1` is a
sound problem; anything else is a dual. The corpus is currently complete
through five pieces, with 31 of the 645 six-piece classes done.

```
$ helpmate mine KQvk --dtm 2 --count 1 --max 3
8/8/8/8/8/8/8/k1KQ4 b - - 0 1
8/8/8/8/8/2Q5/8/k1K5 b - - 0 1
8/8/8/8/4Q3/8/8/k1K5 b - - 0 1
```

Three of the h#1 positions in KQvk with exactly one solution, enumerated
rather than searched for.

## Indexing

One file per material class, one dense integer per position. The two kings
are indexed jointly through a precomputed table of legal, non-adjacent king
pairs: 462 states for pawnless material, where the full 8-fold board symmetry
puts the white king in the a1-d1-d4 triangle, and 1806 states when a pawn is
present, because pawns kill the diagonal symmetries and only the left-right
mirror survives. Every further piece multiplies by 64, a pawn by 48. So a
pawnless six-piece class has 462 × 64⁴ ≈ 7.75 billion cells per side, and a
six-piece class with one pawn has 1806 × 48 × 64³ ≈ 22.7 billion. Pawns make
the tables bigger, not smaller. That is the opposite of most people's
intuition and it is the reason the 32 GiB tier of unsolved material is the
pawnless one.

En passant is not indexed. Wherever a double pawn push next to an enemy pawn
is reachable, the value is folded in at probe and generation time as
`min(table value, 1 + value after the EP capture)`, looked up in the sub-class
the capture lands in. Castling is out of scope, as it is for every tablebase.

## Generation

Building material `M` first builds the closure of every class reachable from
it by capture or promotion, in topological order, because the forward scan of
`M` looks up capture and promotion successors in those tables. Then an init
pass marks illegal cells and every Black-to-move checkmate as `dtm = 0`, and
the fixed-point passes run: pass `d` visits every still-unresolved cell,
generates its legal moves, and assigns `dtm = d` if any successor sits at
`d − 1`. The passes stop when one assigns nothing. A second sweep in
increasing `dtm` order computes the count, `count(p) = Σ count(s)` over
exactly the successors that achieve the minimum, saturating at 255.

Both sweeps parallelise over the index range. Pass `d` only writes cells that
are still unresolved and only reads values below `d`, so chunks never race,
and the test suite asserts that a run with N threads is byte-identical to a
run with one. That determinism is not a nicety. It is what lets a stranger
regenerate a table and compare a sha256 instead of trusting it.

Generation holds four bytes per cell resident, so **peak RAM equals the raw
file size**: 28.9 GiB for any pawnless six-piece class, up to 84.7 GiB with
pawns. The last three six-piece classes each took between six and fourteen
hours on ten threads of a desktop. Compression is applied on the way out and
never during generation.

## Storage

A table is a 64-byte header, a JSON metadata blob, and four byte planes:
DTM and count, each for both sides to move. Readers mmap the file, so a probe
costs a page fault, not a load, and a query lazily opens whichever sub-class
tables the line descends through. Four bytes per cell, no bit packing, no
don't-care elimination: the raw format trades size for a probe that is one
memory read, and leaves the size problem to the compressor.

Real tables are block-compressed: the planes are cut into 64 KiB blocks and
each block is a separate zstd frame with its content checksum enabled, so a
probe decompresses one block into a bounded LRU cache and a flipped bit fails
loudly instead of returning a plausible wrong DTM. The corpus compresses
9.84×, from 494 GiB of planes to 50 GiB on disk. The five most recent
six-piece tables ranged from 7.5× to 19×, which tracks how much of the class
is illegal or unsolvable. Random access stays cheap enough that solution
enumeration on a compressed table costs about 1.14× the raw table, and a full
plane scan about 2.3×.

## What the data says

Across the 317 tables there are 713.9 billion plane cells. Just over half are
illegal positions the dense index has to reserve room for, 10.0 % are legal
but unsolvable, 39.3 % have a helpmate, and of those 6.4 % have a unique
solution. The fifteen KRB six-piece tables are more than half of all cells,
so they pull these shares their way: with the extra white pieces far more
positions can be mated. Across the first 302 tables the figures were
343.0 billion cells, 20.7 % unsolvable, 27.7 % with a helpmate, and 2.9 %
of those unique.

The deepest mate is h#17, shared by KBvkqp, KRBvkqp and KRBvkrp. In KBvkqp:

```
8/8/1p6/8/8/8/Bq6/1k1K4 b - - 0 1
Ka1 Ke1 Qc1+ Ke2 Kb2 Kf2 Kc2 Ke2 b5 Kf2 Kd1 Kf1 b4 Kg1 Ke1 Kh1 Kf1 Kh2
b3 Kh1 b2 Kh2 b1=N Kh1 Nd2 Kh2 Nf3+ Kg3 Kg1 Bc4 Kh1 Bf1 Ng1 Bg2#
```

Its count is saturated at 255. That is the pattern everywhere: in all 233
non-trivial classes the deepest *sound* problem is shallower than the class
maximum, by 4.4 plies on average and by 20 in KRBvkp, whose longest helpmate
is h#16 and whose longest unique one is h#6. The longest helpmates have
hundreds of ways to reach mate, which is exactly what disqualifies them as
compositions. [DEEPEST.md](DEEPEST.md) lists the deepest sound problem in
every class.

## How it is checked

A tablebase is worth what your reason to trust it is worth, so the generator
does not grade its own homework. A second solver, a from-scratch cooperative
iterative-deepening search that shares only the move generator, re-solves
sampled positions from every generated class and checks both DTM and the
enumerated count; any mismatch fails the build. A third implementation, a
plain BFS written against python-chess with no helpmate code involved,
enumerates all 368,452 legal KQvk positions and asserts agreement on both
fields for every one of them. And the single-thread versus multi-thread
byte-identity test runs on KPvkp, the class where en passant successors are
actually reachable.

What is *not* checked is the full correctness of a donated table, because
proving it means regenerating it. That is stated plainly in
[CONTRIBUTING-TABLES.md](CONTRIBUTING-TABLES.md), together with what can be
checked cheaply.

## Limits, and the open call

Seven pieces need about 2 TB resident and an out-of-core generator that does
not exist. Six pieces need a machine, not a redesign: **614 six-piece classes
have never been computed, and 269 of them fit in 32 GiB and take about a day
each.** Contributions arrive as pull requests on the dataset
(`helpmate-tables push --create-pr`), and every merged table is credited.
Regenerating an existing class and reporting whether the sha256 matches is a
contribution too. It turns a trusted table into a verified one.

- Code, CLI, Python bindings, HTTP API and dashboard:
  https://github.com/osick/helpmate-tablebase
- The tables: https://huggingface.co/datasets/osick/helpmate-tables

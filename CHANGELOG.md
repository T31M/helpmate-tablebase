# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
version numbers follow [Semantic Versioning](https://semver.org/) (0.x: minor
bumps may change behavior).

## [Unreleased]

## [0.20.0] - 2026-09-26

### Data
- **Fifteen new six-piece tables, contributed by T31M — the project's first
  outside contribution. Thank you.** King, rook and bishop against every
  three-man Black set: KRBvkqq, KRBvkqr, KRBvkqb, KRBvkqn, KRBvkrr, KRBvkrb,
  KRBvkrn, KRBvkbb, KRBvkbn, KRBvknn, KRBvkqp, KRBvkrp, KRBvkbp, KRBvknp,
  KRBvkpp (claim #41, dataset PR #1 on `osick/helpmate-tables`), generated
  with 0.19.0 on a 192-thread, 369 GiB machine; the five pawn tables need
  about 85 GiB of RAM each. The corpus grows from 302 tables and 52.2 GiB to
  **317 tables and 172.5 GiB**, six-piece coverage from 16 to 31 of 645
  classes, and the plane cells from 343.0 to 713.9 billion. KRBvkqp and
  KRBvkrp tie KBvkqp for the deepest mate, h#17. Still missing at six
  pieces: 614 tables, 269 of them in the 32 GiB pawnless tier. README,
  CONTRIBUTING-TABLES, COOPERATIVE-TABLEBASE and the dataset card carry the
  new figures and credit the contributor; DEEPEST and the showcase site
  pick up the new tables in a later regeneration.

### Added
- **Three line-play themes: `indian`, `maslar`, `maslar:black-white`;
  registry 30 → 33 entries.** All three share one skeleton: a critical move
  (a queen, rook or bishop moves over a square c) followed by an
  interference on c while the line piece stays put. `indian`: the
  interferer is of the line piece's own colour and later leaves c giving
  discovered check along the line through c (Loveday's Indian, either
  colour). `maslar`, from the glossary text: a white line piece's critical
  move, a black interference, the black king arriving on the line beyond c,
  and the line piece capturing the interferer with check. `maslar:black-white`:
  Black's critical move, White's interference, and the black line piece
  capturing the interferer. The catalogue had tiered both Indian and Maslar
  D ("critical square", "interference"); with these definitions they need
  only ply squares plus one attack test, so both move to A. Castling themes
  remain impossible: no table holds a castling move. Real examples in
  USAGE: the textbook Indian in `KRBvk` (1.Ra8 Kb4 2.Ba7 Ka3 3.Bc5#) and
  a unique-solution Maslar in `KRvkb` (1.Rh1 Bg1 2.Ka2 Kc1 3.Kb3 Kb1
  4.Rxg1#), and a shallower one at h#2.5 in `KQvkr` (1.Qa8 Ra4 2.Kc1 Ka2
  3.Qxa4#, one of 211 solutions); `maslar:black-white` needs five units
  and is fixture-verified only.
- **A page per material on the static showcase, and a corpus-wide theme
  index.** `tools/build_problems.py` (run by hand against a corpus, output
  committed) finds, per material, up to three deepest positions with a
  unique solution and up to three deepest positions with exactly two
  solutions that differ in both their first and last move (a "strict dual"),
  with every problem's themes attached. `tools/render_site.py` (run by
  `make site`, standard library only, no corpus needed) turns that into
  `site/material/<NAME>.html` for all 302 materials -- including the 68
  markers where no helpmate exists -- and `site/themes.html`, which links
  every theme to every problem across the corpus that shows it. A material's
  deepest strict dual is usually one ply shallower than its deepest dual
  overall, since the two solutions at the very deepest dual depth almost
  always share a first or a last move; the page states both depths rather
  than quietly showing the shallower one.
- **`tools/published_problems.py`: cross the DEEPEST showcase with a database
  of published helpmates.** Parses the plain-text format (German piece
  letters, one block per problem), matches positions under every mirroring
  (all eight board symmetries when pawnless, the two that keep pawns moving
  up otherwise), writes `published` (author, sources, stipulation, id) into
  DEEPEST.json for every showcase entry the database contains, and for each
  such entry asks the tablebase for an unpublished position of the same
  material and depth with a unique solution, stored as `alternative` and
  rendered as card "No. N b" in DEEPEST.md and the booklet. Against a
  database of 23,807 published helpmates (h#2 to h#13), 26 of the 234
  showcase problems turn out to be published (Sheglow, Elkies, Bán, Maslar,
  Kotesovec, Paliulionis and others); they now carry their author and
  source, and 16 of them are followed by an unpublished sibling of the same
  material and stipulation. The database's TeX umlauts (`Jen"o`) are decoded.
  `sampledata/` is git-ignored.
- **Every showcase position is graded as a chess problem.** Three weaknesses
  are detected: the solution begins with a capture, the side to move is in
  check in the diagram, and the diagram has no legal last move (decided
  exactly for one retraction: quiet moves, uncaptures of any piece and
  unpromotions, with or without capture; en passant not retracted). An
  unpublished showcase position with a weakness is swapped for the
  best-ranked cleaner unique position of the same material and depth the
  tablebase offers (ranking: flawless, check only, capture only, both;
  illegal diagrams are never offered); published positions stay and their
  sibling is chosen the same way. A remaining weakness is stated in a *Note*
  on the card and in the booklet. The index tables gain a *published by*
  column (`Sheglow (1998)`).

- **An authorship statement** (`docs/AUTHORSHIP.md`, linked from the README
  and the site): these positions were enumerated, not composed; no
  authorship is claimed, none will enter a composing tourney, and a
  generated database anticipates nobody (#36).

### Changed
- **Setup instructions for contributors** in CONTRIBUTING-TABLES, written
  for a fresh cloud instance (#42, by T31M), and BUILD documents virtual
  environments and why `pipx install ./src/packages/api` fails (#33).
- **The theme index is collapsed per theme**, 37,000 px → 1,900 px (#38).
  The site's theme note counts the engine's 28 themes in 33 registry
  entries (was 26 / 30).

### Fixed
- **The generated site pages had no stylesheet** (#35).

## [0.19.0] - 2026-09-11

### Added
- **`docs/DEEPEST.pdf` is committed and attached to every release.** The
  A5 booklet is the easy thing to hand around; `make booklet` rebuilds it
  from DEEPEST.tex and copies it into `docs/`.
- **DEEPEST as problem cards, with themes.** Every problem in DEEPEST.md is
  now one card: a real diagram (a per-class SVG under `docs/images/deepest/`,
  Cburnett's pieces from the vendored cm-chessboard sprite) on the left; on
  the right its number, stipulation, a *solve* link into the Helpmate
  Analyzer, the statistics, the solution, the themes it shows as tags, and
  the FEN. The ASCII diagram and the dangling "Solve on the Helpmate
  Analyzer" line are gone. The booklet carries the same numbers (shared
  ordering in `deepest_lib.ordered`), the solve link in the title line, a
  Themes line, and no FEN line. `deepest_showcase.py` records the themes in
  DEEPEST.json (`probe --themes` per entry).
- **Site: every puzzle carries the themes it shows, and a Theme filter.**
  `tools/build_site_data.py` asks `helpmate probe --themes` once per puzzle
  and writes a `themes` array into `site/data/puzzles.json`; the puzzle
  screen gains a Theme dropdown (each theme with its puzzle count) and shows
  a solved or revealed puzzle's themes as tags -- not before, since a mate
  picture's name is a spoiler. The set grew from 930 to 1071 puzzles
  (`mine_puzzles.py --per-bucket 22`, same ladder, same seed).

### Changed
- **Corpus: 302 tables.** `KBvkqqn` (six-piece, 29 GB raw, 2.0 GB compressed,
  deepest unique h#9.5 with 341 such positions) and the all-unsolvable marker
  `KBvkqqq` joined the compressed corpus and the Hugging Face dataset;
  DEEPEST.json/.md/.tex regenerated (234 entries), README, the dataset card
  and CONTRIBUTING-TABLES updated (16 of 645 six-piece classes done, 629
  outstanding, 279 in the 32 GiB tier).

## [0.18.1] - 2026-09-10

### Added
- **`mine --jsonl`, and `save FILE.jsonl` in the shell: JSON Lines for
  results too large to parse as one document.** A header line (material,
  filter, max), then one object per position, byte-for-byte the record
  `--json` puts in `positions[]`, then a footer line with `positions` and
  `skipped_saturated`. On the command line it streams: each hit is probed,
  annotated and written as the scan finds it and nothing is held, so a
  `--max infinity` scan runs in constant memory; the counts sit in the footer
  because that is when a streaming writer knows them, and a missing footer
  marks a truncated file. `--json` and `--jsonl` are mutually exclusive.
  `MineSet` gained `make_hit`/`enrich` (the streaming building blocks) and
  `jsonl_header`/`jsonl_record`/`jsonl_footer`/`to_jsonl`; the `--json`
  record is now built in one place shared by both formats.

## [0.18.0] - 2026-09-10

### Added
- **`mine` holds its result: `--json`, `--themes`, `--solutions`, `--max
  infinity`, and an `--interactive` shell.** `--max infinity` (or `inf`)
  lifts the cap. `--themes` annotates every hit with all non-parametric
  themes it shows, `--solutions` with every optimal solution; in text mode
  these print as indented lines under the FEN, and `--json` emits one
  document (`material`, `filter`, `max`, `skipped_saturated`,
  `positions[]`). `--interactive` (alias `--tui`) opens a prompt over the
  held set: `theme`/`not theme`/`count`/`starts`/`ends` narrow it without
  rescanning, `back`/`reset` undo, `list`/`show` inspect, `themes` tallies
  every theme over the current set, `save FILE` writes JSON or FENs. Backed
  by a new core unit, `MineSet` (`probe/mine_set.h`), plus a stream-driven
  `run_mine_shell`, both unit-tested with Catch2; `Tablebase` gained
  `shows_theme` so a parametric theme can be checked on one position. The
  Python bindings and the HTTP API are unchanged.

### Changed
- `mine --themes` is now a real flag (it used to be rejected as a typo for
  `--theme`). `probe --theme` is still rejected.
- A position whose optimal-solution count is saturated (unenumerable) now
  says so in `--json` as `"exhaustive": false`, with no `starts`/`ends`,
  instead of reporting the shape of the first 100 solutions as if it were
  the whole set; the text output notes it under the solutions.
- `--max` now rejects a negative value (exit 3) instead of silently
  behaving like `--max 0`, which read as "nothing matched".

## [0.17.0] - 2026-09-09

### Added
- **Six new themes and the first parametric theme; registry 24 → 30
  entries.** `umnov` (a unit moves onto the square the opponent's previous
  move vacated) and `umnov-mate` (the mating move does it); `klasinc` (a unit
  leaves a square, a line piece of either colour passes over it, the unit
  returns — the catalogue had tiered Klasinc D as "line geometry", but with
  this definition it is ply geometry alone); `zilahi` (two solutions in
  which two white units swap the mating and the captured role, units
  identified by diagram square via the new `themes/identity.h` helper);
  `allumwandlung` (the four promotion types occur across the solution set,
  the coverage reading the 2026-08-08 design fixed); and
  `promotions:<types>`, asked with a value — `--theme promotions:qrr` needs
  at least one queen and two rook promotions among the promotions of all
  optimal solutions taken together (q and r in one solution and r in
  another, or all three in one), further promotions allowed; a multiset the
  server canonicalises. `probe --themes` prints the position's combined
  multiset as one `promotions:<value>`. The parametric mechanism is one
  registry descriptor (`ThemeParam`) plus `resolve_theme`, which every
  surface now uses: the CLI (`helpmate themes` prints a `parameter` line;
  `--theme promotions` alone, `promotions:qx`, and the singular typo
  `promotion:qrr` are all errors naming the fix, the last never falling
  through to the boolean `promotion`), the Python binding (`themes()`
  entries carry `parameter`, new `check_theme(name)`), `/v1/themes` and
  `/v1/mine` (400 `invalid_theme` with the resolver's message), and the
  dashboard (a text box under the theme picker, sent as
  `theme=promotions:<value>`; the Themes screen shows the parameter).
  `zilahi` refuses a set of one; `allumwandlung` is the same question as
  `promotions:qrbn`; `umnov-mate` needs the dtm-0 guard.
- **Two set-wide themes, `nocapture` and `nocheck`; registry 22 → 24
  entries.** `nocapture` — no unit is captured in any optimal solution (en
  passant included); `nocheck` — no move gives check in any optimal solution
  except the last move of each solution, the mate itself. Both need
  `solutions`. Unlike every other solution theme, which matches when *any*
  one solution shows it, these two hold only when **every** optimal solution
  qualifies: one capturing (or checking) line is enough to break them. That
  is a new adapter in the registry, `all_of<>`, next to the existing
  `any_of<>`; the AND-across-themes rule and the three surfaces are
  unchanged, and `helpmate themes`, `GET /v1/themes`, `helpmate.themes()`
  and the dashboard's Themes screen all pick the two up from the registry
  (the Themes screen lists them under "The structure of the solution"). An
  empty solution set shows neither, so a position whose solutions could not
  be enumerated never reads as capture-free by vacuity; on a saturated
  position the existing first-100-solutions truncation note applies to
  them too. `mine --theme`, the `--theme` help text, `docs/USAGE.md`'s
  match-semantics section and the Python API docs say which themes are
  `every` and which are `any`.
- **A static showcase site**, `site/`, published to GitHub Pages at
  https://osick.github.io/helpmate-tablebase/ by `.github/workflows/pages.yml`.
  Four screens: the front page with the corpus numbers and the deepest sound
  six-piece problem playing on a board; the 233 deepest sound problems from
  `docs/DEEPEST.json`, filterable by piece count, each stepped through on the
  board; the dashboard's 930 unique-solution puzzles in the dashboard's solve
  mode (drag out the whole line, both colours, graded against the one
  solution); and the corpus table by table. No server, no build tools, no
  chess logic in the browser: `tools/build_site_data.py` expands every
  solution ply by ply (SAN, UCI, FEN after) with python-chess once, and the
  JSON under `site/data/` is committed. The board is the dashboard's vendored
  cm-chessboard, copied in by `make site`; `make test-site` runs the site's
  `node --test` suite and syntax-checks every module, and the Pages workflow
  gates on it. Tested end to end with Playwright before the first deploy.
- **`tools/verify_corpus.py`** — decodes every zstd block of every
  block-compressed table in a directory (or one table) and reports any frame
  that fails its content checksum, decodes to a length the block index does
  not promise, or is cut short. Read-only, pure Python, parallel over tables.
  Written to run down the intermittent "Restored data doesn't match checksum"
  that `tools/deepest_showcase.py` retried around since 2026-08-21: on
  2026-09-07 the error did not reproduce in ~550 CLI runs, all 8,099,259
  blocks of the 233-table corpus decoded cleanly, and the reader code had not
  changed between the two dates. A checksum failure that comes and goes on
  identical bytes is not something the reader produces on its own, so the
  tool is the first thing to run if it is ever seen again — a table that fails
  it is corrupt on disk, one that passes and still fails in `helpmate` points
  at the machine. Tested in `tests/repo/test_verify_corpus.py` against a
  synthetic table with a flipped byte, a lying index and a truncated file.

### Fixed
- The repository is `osick/helpmate-tablebase`; the one remaining reference
  to the old `8pieces-helpmate` name in a living document (ADR 0001) is gone.

## [0.16.0] - 2026-08-20

### Added
- **`helpmate-tables push --create-pr`** opens a pull request on the dataset
  instead of writing to it directly — the route for contributors who have no
  write access. The table and its sidecar go up as a *single* commit, because
  `upload_file(create_pr=True)` opens one pull request per call and would
  otherwise split a contribution into halves a maintainer has to merge in
  lockstep. The path deliberately touches no `manifest.json`, remote or local:
  the maintainer regenerates it after merging, and a pull request that edited
  it would conflict with every other open one.
- `docs/CONTRIBUTING-TABLES.md` — how to contribute generated tablebases:
  what is missing and what it costs in RAM, how to claim a material, and the
  verification the project can and cannot currently do.
- `docs/INTERNALS.md` — indexing, generation, storage format, verification
  story and limits, moved out of the README.

### Changed
- The README is now a front page rather than a manual: 865 lines to 167, with
  the reference material relocated to `docs/`. Stale claims corrected —
  compression has existed since v0.7.5, six-piece tables need 28.9–84.7 GiB
  rather than "14–28 GB", and seven pieces is bounded by an out-of-core
  generator that does not exist rather than being "out of scope".

## [0.15.0] - 2026-08-14

Dashboard polish for a public deployment: the chrome stays where you left it,
and the site can now explain itself.

### Added
- **About, Technique and Privacy screens.** About is on the nav; Technique
  (indexing, generation, storage, and why the numbers are trustworthy) and
  Privacy have no nav button and are reached from About and the footer.
  `panels.js` derives its panel list from the DOM, so all three needed no
  registration. The explorer also carries a short About card under its primer.
- A delegated handler for in-page `a[data-panel]` links, so following one
  **keeps the position you were looking at** rather than dropping the `fen`
  parameter when the hash is rewritten.
- `--header-h` / `--pin-top`: the header's measured height, published from
  `js/chrome.js` via a `ResizeObserver`, with a CSS fallback. The header wraps
  to two lines between roughly 860px and 1100px, so a constant would put the
  board behind it at one width and leave a gap at the other.

### Changed
- **The header is sticky**, and the board, the material list and the search
  form now pin below it instead of at the top of the viewport. The board
  already stuck; everything around it scrolled away, which left it jammed
  against the window edge with its piece tray clipped.
- The board is **lifted off the rail** with a three-layer shadow (hairline
  edge, contact, cast), all in the palette's existing achromatic ink.
- **The three footer placeholders are real links**: Source and Licence to the
  repository, plus About and Privacy. `Dataset` is gone rather than dead — the
  tables are not published yet, and About says so in a sentence.

## [0.14.0] - 2026-08-13

### Changed
- **Position search (`/v1/mine`) is now off by default** and must be enabled
  with `helpmate-server --enable-mine`. A disabled server answers
  `503 mining_disabled`. A scan cannot be interrupted by `SIGTERM`, its
  timeout is not deterministic under concurrent load, and nothing bounds how
  many run at once — so it is not safe to expose until that work is done. The
  dashboard reads `mining_enabled` from `/v1/health` and omits the Search
  screen entirely when it is off. The CLI `helpmate mine` is unaffected.
- **CORS is opt-in per origin.** `--cors-origin ORIGIN` is repeatable; with
  none given no CORS middleware is installed, where previously every origin
  was allowed. Same-origin use, including the dashboard, is unaffected.

### Added
- `mining_enabled` on `/v1/health`.

## [0.13.0] - 2026-08-13

Puzzles, a motif reference, and a round of correctness/polish fixes to the
dashboard shell underneath them.

### Added
- **A puzzle screen.** A session of ten one-solution positions, one per
  difficulty rung (mate length first, piece count second) and easiest first,
  drawn from a committed, hand-editable EPD file
  (`src/packages/web/helpmate_web/static/puzzles.epd`, 930 positions; see
  [USAGE.md](docs/USAGE.md#puzzle-set-epd) for the format and
  `tools/mine_puzzles.py` for regenerating it). Solving means playing the
  whole line, both colours — a helpmate is cooperative, so proving the
  solution means supplying Black's moves too. Each ply gets a check or a
  cross; a wrong move reveals the correct one; exceeding the error budget
  reveals the rest of the line. The session is filtered to materials this
  installation actually has tables for, and when none match it names them
  and the `helpmate gen` command that builds one.
- **A motif documentation screen**, rendered straight from `/v1/themes` —
  never a hard-coded list — covering all 22 registered motifs in five
  groups (the mate picture, how a unit travels, pawns and promotion, where
  the mate happens, the structure of the solution), each introduced by a
  sentence, plus an "other" group that catches anything the registry adds
  later. Every entry states its `needs` value and what that means for a
  position whose solution count has saturated at 255.
- A prominent page title, a footer with a live corpus line and clearly
  marked placeholder links (Source, Dataset, Licence — real destinations
  once this project is public), and a drag ghost that is transparent,
  borderless and smaller than the tray button it's dragged from.

### Fixed
- **Two data-loss bugs.** `render()`'s `ApiError` branch left the move
  lookup stale, so a drag after a failed evaluation replayed the previous
  position's move list — discarding the user's edit and printing a
  confident verdict for a position they never built. The same bug existed
  on the "downloading" path, where it needed no coincidence at all: any
  click on the still-visible stale list did it. Two further instances of
  the same class — a failed `/v1/probe`, a `/v1/line` 404 — left previous
  content on screen instead of being replaced.
- **The page no longer jumps.** `render()` used to empty the move list
  before awaiting the fetch that refilled it, so everything below leapt up
  ~286px for ~22ms. It now builds the replacement and swaps it in
  atomically.
- **A new `400 unprobeable_position` error, split out of `404
  unknown_material`.** `/v1/probe`, `/v1/moves`, and `/v1/line` used to
  report every position the tablebase index couldn't address as "no table
  for X" — including a position that is simply illegal (the two kings
  adjacent, reachable in one drag on the explorer's board), which told the
  user to generate a table the Materials screen was already listing as
  local. That case is now `400 unprobeable_position`, distinct from `404
  unknown_material`'s "there is no table for this material at all"; see
  [USAGE.md](docs/USAGE.md#get-v1probe) for the full contract.

### Removed
- **The colour-theme control.** The three-state (system/light/dark) toggle,
  its stored `localStorage` preference, the pre-paint script that applied
  it before first paint, that script's own drift test, and both dark CSS
  token blocks are gone — one palette now, net −200 lines.

## [0.12.0] - 2026-08-13

Dashboard UX round 2: no modes, and say the shared fact once.

### Changed
- **The board has no editing modes.** A drag matching a legal move plays it,
  any other drag relocates the piece, and a drag off the board deletes it —
  including a drag started on either piece tray, which places. **Erase**,
  **Arrange** and **Done — evaluate** are gone, along with click-to-place and
  the armed-state ring. Back undoes a relocation exactly as it undoes a move.
  The accepted risk: relocating a piece onto a square that happens to be a
  legal destination for it will play that move, not merely place it there.
  Two plain clicks on a piece also relocate it, as a side effect of the same
  handling. With click-to-place gone there is no keyboard path to placing a
  tray piece; the FEN field, which applies on Enter, is the keyboard route to
  an arbitrary position.
- **The piece trays flank the board** — black above, white below, each on the
  side of the board its colour occupies, swapping when the board is flipped.
  Below the board, the FEN field keeps a row to itself (the longest datum
  here, and the one field anyone might select or paste into); **To move**,
  **Flip**, **Clear board** and **Back** share the row beneath it — two
  deliberate rows, not the one line an earlier commit message on this branch
  claimed before a follow-up fix corrected the layout itself.
- **Slower and no-mate moves render as chips under a distance band.** Within
  one distance every badge read the same string; the distance is now stated
  once. The optimal group keeps its rows, because its per-move solution count
  is what the list exists to show.
- **The explorer's table band is one line** — the material, its deepest mate
  and how much of it is solvable — with a link to Materials, where the
  histograms already live, instead of repeating them under every position.
- **Weight marks what you can act on**: actionable controls are 600, inert
  text is not, and **Flip** and **Clear board** drop their borders now that
  weight alone carries the affordance.

## [0.11.0] - 2026-08-12

Dashboard UX: one skeleton for all three screens.

### Added
- Drag a piece from the palette onto the board, drag it to another square, or
  drag it off the board to remove it. Click-to-place is unchanged and remains
  the keyboard and touch path. Edit mode gains a visible **Done — evaluate**.
- The explorer shows the statistics of the table the position came from, in a
  band below the board and the move list.
- Materials lands on **All tables** — the whole corpus at once, including the
  materials that contain no helpmate and the generator versions that built the
  rest. The table list scrolls inside its rail, filters on substring, and is
  grouped by piece count.
- The search screen has a **Stop** button and shows elapsed time against the
  server's `--mine-timeout` budget.
- `GET /v1/stats` returns the corpus aggregate. `/v1/probe` and `/v1/moves`
  report the `material` whose table answered. `/v1/health` reports
  `mine_timeout`.

### Changed
- Every screen is a grey rail beside a white readout: grey is what you
  manipulate, white is what the tables say. No new colours — both surfaces are
  aliases over the existing palette.

### Fixed
- The board no longer overlaps the move list between 860px and ~1150px. It was
  sized from the viewport while its column was sized from the grid; at 960px
  that put a 460px board in a 368px column.
- A material with no helpmate said "longest mate h#127.5" — the stored
  `DTM_UNSOLVABLE` sentinel divided by two. 67 of the 295 tables in the
  reference corpus are in that state.
- A timed-out search reported "0 position(s) (truncated — raise max results
  for more)" instead of naming the timeout.

## [0.10.0] - 2026-08-11

### Changed

- **The web dashboard is redesigned end to end** — a professionalization pass
  aimed at publishing it, benchmarked against syzygy-tables.info's UX.
  - **The move list is grouped and sorted, not left in generator order.**
    Three groups — Optimal, Slower, No mate — each with a counted header. The
    optimal group sorts by ascending child `count`: `dtm` is constant across
    the whole group (every optimal move leads to a child at `dtm = D − 1`),
    so it cannot discriminate; `count` says how forcing the move is, which is
    also the property composers care about, so the ordering doubles as the
    advice. The slower group sorts by `dtm`, then `count`, then SAN; the dead
    group sorts by SAN alone. Row one is always the recommended move.
  - **A saturated `count` renders `255+`, never `255`.** The whole project
    treats a saturated count as "cannot be enumerated," so presenting the
    ceiling as a bare number would misreport it as a measurement. This
    applies everywhere a count is shown, including the position summary
    line, which is derived from the same ceiling as its children (a
    position's own `count` is `min(255, sum of its optimal children's
    counts)`, so the moment one child badge saturates the position's own
    count necessarily has too).
  - **The palette is lichess's shipped theme, not the old warm-cream/
    terracotta pairing.** Grounds carry one hue at 5–10% saturation; ink and
    rules are exactly achromatic; the one accent (`#1b78d0` light /
    `#3692e7` dark) is confined to links, focus rings and hover borders —
    never a fill, header, or list colour.
  - **The Optimal → Slower → No mate ordinal carries no hue.** It is one
    ranked axis, encoded by luminance and weight (filled → outlined → faded
    and struck through), the same device syzygy-tables.info uses for its own
    win/draw/loss scale. The qualifier ("only reply" vs. several
    continuations) is a ring, not a colour, so nothing on the page is
    encoded by hue alone.
  - **A responsive two-column shell**, mobile-first, with the board pane
    fixed and only the answer pane scrolling above an 860px breakpoint — a
    long move list never drags the board out of view.
  - **The primer and legend copy show only on the landing position** and get
    out of the way once the user has a real position, matching the
    benchmark's treatment of its own About/Download material.
  - **A three-state theme toggle** (system / light / dark): the choice
    persists across reloads and is applied before first paint, so a
    dark-mode user never sees a white flash on load.
  - **Search results are numbered.** `/v1/mine` returns no per-row data
    beyond the FEN, so a table (as originally scoped) would have every
    column constant across every row; the result list keeps its `<ul>` and
    gains a row index instead. A genuine table needs `/v1/mine` to return
    per-row values, which is an API change left to its own cycle.

### Fixed

- **`make test-web` now reinstalls the web package before running the UI
  suite.** `helpmate-web` installs as a copy into site-packages, not
  editable, and the target used to run `pytest` straight against whatever
  was already installed — so a regression in the dashboard could pass
  silently against a stale copy, while only a brand-new test would fail
  loudly. The target now reinstalls first.

## [0.9.1] - 2026-08-09

### Fixed

- **`set-play`'s definition — a behaviour change to a theme released in
  v0.9.0.** It used to mean "the same position with the other side to move is
  solvable, at any distance," which is nearly vacuous (it matched **423 of
  580**, 72.9%, `KQvk --dtm 2` positions) and conflated two opposite things:
  a sibling solvable one move *sooner* (the mate is already available; the
  side to move merely delays it — this is set play) and a sibling solvable
  one move *longer* (flipping the side to move makes the mate take longer —
  the opposite of set play, but v0.9.0 reported it as a match anyway). It now
  means **the sibling plane is solvable at exactly dtm = D − 1**, where D is
  the position's own stored dtm: **183 of 580** (31.6%) on the same query.
  Both directions, worked:
  - `8/8/8/8/8/8/8/k1KQ4 b` is dtm=2 (`Ka2 Qa4#`); its sibling
    `8/8/8/8/8/8/8/k1KQ4 w` is dtm=1 (`Qa4#`) — D − 1, `set-play` fires, as
    before.
  - `8/8/8/8/8/8/k7/2K1Q3 b` is dtm=2 (`Ka1 Qa5#`); its sibling
    `8/8/8/8/8/8/k7/2K1Q3 w` is dtm=3 (`Kc2 Ka3 Qa5#`, 28 solutions) — D + 1.
    v0.9.0 reported `set-play` here; v0.9.1 correctly does not.
  - `ThemeInput` gained a `value` field (the position's own stored
    dtm/count) so the detector can compare the sibling against it, not just
    check the sibling's bare solvability. Both production construction
    sites (`Tablebase::mine`'s scan loop, `Tablebase::themes_of`) were
    updated.
  - The looser "sibling solvable at any shorter distance" reading some
    compositional literature also calls set play is a separate notion (the
    Helpmate Analyzer glossary's *Short set play*) and remains unimplemented.

## [0.9.0] - 2026-08-09

### Added

- **Six new themes, registry 16 → 22 entries.** `helpmate themes` is the
  authoritative source (definitions below are copied verbatim from its real
  output on this checkout):
  - `set-play` (needs: plane) — "Set play: the same position with the other
    side to move is also solvable."
  - `kniest` (needs: solutions) — "Kniest: a unit is captured on the square
    where the black king is later mated."
  - `zajic` (needs: solutions) — "Zajic: a unit is captured on the square
    where the black king is mated, and the king recaptures there."
  - `phoenix` (needs: solutions) — "Phoenix: a unit is captured and a pawn of
    the same colour later promotes to that same type."
  - `schnoebelen` (needs: solutions) — "Schnoebelen: a promoted unit is
    captured on its promotion square without ever having moved."
  - `pendulum` (needs: solutions) — "Pendulum: a unit oscillates between
    exactly two squares, returning at least twice."

### Changed

- **Detector signature: `ThemeInput` instead of a bare `Solution`.** Every
  detector now takes a `ThemeInput` (the diagram, the sibling side-to-move
  plane's value, and the solutions) and declares which of those three it
  actually reads via a `needs` field (`Position`, `Plane`, or `Solutions`).
  The CLI, Python bindings, and the dashboard all report each theme's
  `needs`; `GET /v1/themes` needed no source change since it already passes
  the registry through verbatim.
- **`mine` no longer enumerates solutions when every requested theme needs
  only the diagram or the plane.** Previously `mine --theme NAME` always
  enumerated a candidate's optimal solutions before running any detector,
  which caps out at a saturated (255+) solution count and silently skips
  that position. The plane-only theme (`set-play`) now answers without
  enumerating, so it also answers on positions whose solution count
  saturates — positions every solutions-needing theme (`pure`, `model`, …)
  still skips. A `Needs::Position` theme (the diagram alone, no table access)
  would get the same treatment, but every candidate considered for this
  release turned out not to be invariant under the tablebase index's
  symmetry group — see the branch review fix for `homebase`'s removal,
  below. **This is a capability change, not a speed-up**: it does not make
  `mine --theme set-play` "scan speed" — evaluating the sibling plane still
  requires materialising the position (decode + `Board::from_pieces`), so
  its floor is decode speed, not scan speed. Measured on `KRvkbn --dtm 8`
  (31.5M candidates, zero matches): 26 seconds, down from an initial 51
  seconds once `fen` construction was made lazy for the non-matching path.
  The comparison that matters is against actually enumerating those same
  candidates' solutions, measured at over 100 hours — `set-play` makes
  queries answerable on saturated material that were previously unanswerable
  at any speed, not merely faster.

### Fixed (branch review)

- **`homebase` removed: not invariant under the tablebase index's symmetry
  group.** Added earlier in this same unreleased version, then removed
  before release. `mine`'s index quotients positions by a symmetry group —
  a cell stores an *equivalence class*, not a position — and the White
  king's file in the stored representative is always confined to files a-d
  (`src/core/indexing/kk.cpp`), with no inverse transform on decode
  (`slice_index.cpp`). `homebase` is not invariant under that group (the
  file mirror maps the king's e-file to d and the queen's d-file to e), so
  the answer would depend on which representative was decoded — in practice
  `mine --theme homebase` returned zero rows on every material. This is
  deeper than a missing case, and not fixable by special-casing the decode:
  a `Needs::Position` theme must be invariant under the index's symmetry
  group, or it cannot be mined at all. All other themes in this release were
  checked against this constraint and are invariant.

## [0.8.2] - 2026-08-08

### Added

- **`helpmate stats` with no MATERIAL summarises a whole table directory** —
  what is on disk, in what format, and what is in it. Covers the roadmap's
  `helpmate list <dir>` backlog item. Header fields (format, block size,
  plane size, `max_dtm`) come from each `.hm`; cell counts come from the
  `<Material>.stats.json` sidecars. Reports files by format and piece count,
  on-disk size, the whole-corpus compression ratio against `4 × plane_size`
  of logical planes, the invalid/unsolvable/solvable/unique breakdown, the
  deepest mate, the largest tables, and the generator versions that produced
  them. `helpmate stats <MATERIAL>` is unchanged.

  Three deliberate honesty properties, because a summary that quietly
  under-reports is worse than no summary: markers are counted separately
  (they have no payload to measure); a table whose sidecar is missing still
  contributes its size and format but is excluded from the cell breakdown,
  **and the header says how many such tables there were**; and an empty or
  nonexistent `--tables` is an error (exit 3), not a report of a zero-table
  corpus.

- **`tools/compress-corpus.sh`** — converts a directory of raw tables into
  compressed ones in a *different* directory. `compact --compress` only works
  in place, so there was previously no way to do this without moving files by
  hand. Stages one table at a time on the destination's filesystem, so peak
  extra disk is one table plus its output rather than the size of the corpus.
  The source is only ever read and nothing is deleted, and it applies the
  same one-hour rule `compact --compress` uses, so a table a generation run
  is still writing is never even opened.

### Changed

- `--block-size`'s CLI help no longer repeats the `~6.5x` mining claim
  withdrawn in 0.8.1; it points at `docs/USAGE.md` for the measured
  ratio/speed trade-off instead.
- Query acceleration (indexing so `mine` stops scanning) is recorded in
  `docs/ROADMAP.md` and specified in
  `docs/superpowers/specs/2026-08-08-query-acceleration-design.md`, and is
  **not scheduled**. The spec exists so the research behind it is not
  repeated: no database should hold the cell array (SQLite, DuckDB, Parquet,
  RocksDB, LMDB and ClickHouse were each measured out — the key is already
  the array offset, and each charges 16-19 bytes of per-row structure for a
  4-byte row), and zone maps and skip indexes are dead here because matching
  cells do not cluster.

## [0.8.1] - 2026-08-07

### Fixed

- **Mining a block-compressed table is no longer several times slower than
  mining the raw equivalent.** Measured on a real 462 MiB `KRvkbn` (70.8 MiB
  compressed), `taskset -c 0-3`, warm: a full plane scan went from **14.2x
  raw to 2.3x**, and solution enumeration (`mine --dtm 8 --theme model
  --max 200`) from **11.8x raw to 1.14x**. Two independent causes, neither
  of them block size — which is what the v0.7.5 experiment had suspected and
  correctly acquitted:

  - **`mine`'s plane scan read one byte per block-cache call.** It walked
    the DTM and count planes cell by cell through `TableReader::get()`, and
    on a compressed table each such call takes the cache mutex and copies a
    single byte. Over a whole plane that, not the decompression, was the
    cost: decompressing both planes accounts for ~0.2s of the 9.06s the scan
    took. New `TableReader::read_values()` reads a span of cells with one
    lock and one memcpy per block touched; `mine` and `compact`'s
    all-unsolvable scan both use it. `compact`'s scan additionally passes a
    null count buffer, so it no longer decompresses the count planes it
    never reads.
  - **The block cache was smaller than the enumeration working set.**
    `--theme`/`--starts`/`--ends` probe cells at effectively random indices,
    and with the 4 MB budget shipped through v0.8.0 nearly every probe paid
    a full block decompression to read one byte. The budget is now 64 MB,
    capped per table at its own logical size so a closure of small
    sub-slices cannot each claim the full amount. It is a ceiling, not a
    reservation — the LRU only allocates blocks actually touched, and the
    theme run above peaked at 62 MB RSS in total. 16 MB already reached
    parity; 64 MB leaves headroom for larger materials.

  Verified byte-identical: `mine` output over raw and compressed tables
  matches for `--dtm`/`--count`, `--starts` and `--theme` queries, and the
  row counts match the generator's own `uniqueness` histogram in the stats
  sidecar for five different `(dtm, count)` pairs on `KRvkbn`.

### Changed

- The `~6.5x` mining penalty documented in v0.7.5 is withdrawn from
  `README.md` and `docs/USAGE.md`. Its benchmark
  (`mine KRvkbn --dtm 8 --count 1 --max 20000`) **exits as soon as it has
  20000 hits and never scans the plane**, understating the real scan cost by
  3x; a full scan measured 14.2x. The advice to mine against raw tables for
  large theme searches no longer applies.

## [0.8.0] - 2026-08-03

### Added

- **Theme detection**: `mine`, `probe` and the HTTP API can now search and
  annotate by named theme. Sixteen registry entries cover twelve themes —
  four mate-position themes computed from the final board alone (`pure`,
  `model`, `ideal`, `mirror`) and eight computed from one solution's plies
  (`promotion`, `underpromotion`, `excelsior` [+ `:white`/`:black` colour
  variants], `switchback`, `closed-walk`, `self-block`, `single-piece` [+
  `:white`/`:black`], `en-passant`). Naming follows the Helpmate Analyzer
  glossary (<https://helpman.komtera.lt/themes.html>) wherever a name already
  exists there. See docs/USAGE.md's new "Themes" section for every
  definition, the match semantics, and the performance and correctness
  caveats below.
  - **CLI**: `helpmate mine <MATERIAL> --dtm N --theme NAME` (repeatable),
    `helpmate probe <FEN> --themes` (annotate one position), `helpmate
    themes` (list the registry with its definitions — the same vocabulary
    `--theme`/`--themes` accept, discoverable without the docs).
  - **API**: `GET /v1/themes` (the registry as JSON), repeatable `theme=` on
    `GET /v1/mine` (unknown name → `400 invalid_theme` listing every valid
    name), opt-in `themes=true` on `GET /v1/probe` (adds a `themes` array;
    `null` + `themes_note` for a color-flipped probe, since the detectors are
    hard-coded to the black king).
  - **Dashboard**: a theme multi-select on the Search panel, populated from
    `/v1/themes`; the Explorer shows the current position's themes beside its
    dtm/count.
  - **Python bindings**: `helpmate.themes()` (the registry as a list of
    `{"name", "doc"}` dicts); `tb.themes(fen, max=-1)` (theme names for one
    position — `max=-1`, the default, means "the position's own solution
    count", the same cap the CLI uses); `tb.mine(...)`/`tb.mine_with_stats(...)`
    both gained a `themes=[]` keyword argument (same `any`-within-a-theme,
    `AND`-across-themes semantics as the CLI/API; unknown name raises
    `ValueError`). See docs/USAGE.md's Python API reference.
- **Match semantics**: a position matches `--theme X` when **at least one**
  of its optimal solutions shows `X` (not all of them); naming several themes
  ANDs them, but not necessarily within the same solution. A saturated
  position (255+ solutions) can't be enumerated and never matches a theme
  filter — `mine` counts these in its existing skipped-saturated tally rather
  than dropping them silently.

### Changed

- `mine` given more than one positional argument now exits 3 (`error: mine
  takes exactly one MATERIAL argument; unexpected extra argument(s): ...`)
  instead of the previous silent `pos[0]`-only behavior, which ignored every
  extra argument and exited 0. Upgrade-visible for any script that (by
  accident or habit) passed more than one positional to `mine`.

### Performance

Theme detection forces solution enumeration — the same work `--starts`/
`--ends` already pay, not new cost the detectors themselves introduce.
Measured on `KQvk` at `--dtm 2` (a shallow query, few solutions per matched
position), ms/query: process floor 3.12, plain `--dtm` 4.06, `--starts 1`
(enumerates solutions, zero detectors) 13.12, `--theme mirror` 13.20, four
`--theme` flags 14.46 — the detectors cost under 1% of the added work at
this depth (scoped to this measurement: on deeper positions of the same
table, `solutions()` 5.59 ms vs. `detect()` 0.34 ms at count 160 (5.8%), and
7.42 / 0.42 ms at count 218 (5.4%) — low single digits generally, not
uniformly under 1%). The qualitative point still holds throughout: the cost
is enumeration, not the detectors. On scan work alone (excluding the process
floor) a `--dtm 2` theme query runs at roughly 10.7x a plain `--dtm` scan,
and this compounds with the ~6.5x mining penalty on block-compressed tables
measured in v0.7.5. Mine against raw tables for large theme searches.

### Known limitations

- **Colour-flipped positions cannot be annotated.** Every detector is
  hard-coded to the black king, so a `probe` answered via the color-flip
  fallback (see docs/USAGE.md's "Symmetry reduction") reports themes as
  unavailable rather than risk a swapped colour-labelled result. Twelve of
  the sixteen registry entries are in fact flip-invariant and could, in
  principle, still be answered — a known follow-up, not shipped here.
- **Verification against published problems was deferred by explicit
  decision.** These definitions are this project's own, stated precisely
  enough to be argued with, not certified against the Helpmate Analyzer or
  any other authority. A detector subtly at odds with composition convention
  will return a confident, wrong result, and nothing in this project's test
  suite would catch that.

## [0.7.5] - 2026-08-02

### Added

- **Block-compressed tables** (`version 3`, `encoding 2`): the four planes are
  addressed as one logical byte range, cut into fixed-size blocks compressed
  independently with zstd, with a `uint64` offset index and a bounded cache of
  decompressed blocks. Random access is preserved — a probe decompresses one
  block. Measured 14.5× on a 128 MB sample of a real 6-piece plane at 64
  KB/level 3. Realized whole-table numbers vary with table size and block
  size: a real 5-piece table (`KBvkbn`) went from 462 MiB to 50 MiB end to end
  (9.22×) at 64 KB, while a 146 KB `KQvk` only reaches 2.0× — small tables
  compress poorly because fixed per-file overhead (header, JSON, a block
  index covering just a couple of blocks) dominates a file too small to give
  zstd much to work with.
- **`helpmate gen --compress`** and **`helpmate compact --compress`**. The
  converter rewrites tables already on disk one at a time via a temp file and
  atomic rename, and skips markers, already-compressed tables, and anything
  written in the last hour, so a running generation is never disturbed.
- **libzstd** is now a build prerequisite (`libzstd-devel` on openSUSE,
  `libzstd-dev` on Debian/Ubuntu).
- **`--block-size N`** on `gen --compress` and `compact --compress` (KiB;
  4-16384, i.e. 4 KiB-16 MiB), default **64 KiB** (`kDefaultBlockSize`).
  Real-world use found `helpmate mine --count`/`--starts` — which probes
  child positions effectively at random — ~6.5× slower on a compressed table
  than raw, regardless of block size. A 16 KiB default was tried on the
  theory that smaller blocks (cheaper to decompress per miss) would cut the
  regression; isolated per-block-miss measurements looked promising (16
  KiB/level 3 = 11.4×/~11µs vs. 64 KiB/level 3 = 14.5×/~38µs). Reproducing
  the regression end to end on a real 462 MiB `KRvkbn` table falsified it:
  raw 0.05s vs. ~0.32s compressed at *both* 64 KiB and 16 KiB (~6.5× either
  way), and 16 KiB compressed *worse* (5.94× / 77.8 MiB vs. 6.53× / 70.8
  MiB) — 8% more disk for no speed benefit. Decompression is evidently not
  the bottleneck; the per-miss overhead in `BlockCache` is the suspect, but
  that's unconfirmed and needs profiling, not another guessed block size.
  See docs/USAGE.md's Table format section for the full numbers.
- **`compact --compress` can now re-block an already-compressed table** to a
  different `--block-size` in place, streaming through the reader's own
  bounded block cache rather than a decompress-to-disk round trip or
  regenerating from scratch (`TableReader::read_range`, works for raw and
  compressed sources alike). At the same block size it stays a true no-op.
  Verified byte-identical to a direct raw→target-size compression (`md5sum`
  match on a real table).
- `helpmate.generate()` (Python bindings) gained `compress` and `block_size`
  keyword arguments, matching the CLI's `--compress`/`--block-size` in the
  same unit, KiB — see docs/USAGE.md's Python API reference.

### Changed

- Raw tables remain the default for `gen`. The default flips in a later
  version, once the performance gate has been run at scale.
- Compressed tables carry `version = 3` as well as `encoding = 2`, so binaries
  released before this format report "written by a newer helpmate … upgrade
  this build" rather than "unreadable table".
- The default block size for `gen --compress`/`compact --compress` stays 64
  KiB. A 16 KiB default was tried and measured (see Added, above) to compress
  worse while not measurably helping the `mine --count`/`--starts`
  regression, so it was reverted before release. The golden fixture committed
  at 64 KiB is unaffected either way — block size is read from each file's
  own header, not the build's default.

## [0.7.2] - 2026-08-01

### Added

- **Every pull request is gated.** `ruff`, `mypy`, `node --check`,
  `clang-format` on changed lines, and the full C++/Python/browser suites run
  on each PR, and `main` requires them to pass before a merge is allowed.
- **`make lint`, `make typecheck`, `make format-check`** reproduce every gate
  locally; `make format` fixes the C++ ones.
- **The release workflow verifies that a pushed `v*` tag matches `VERSION`**,
  closing the last place the version could drift unguarded.
- **`docs/CONTRIBUTING.md`** — the required checks, how to run each locally,
  and the reasoning behind the linter configuration.

### Changed

- Ruff's E701/E702/E401 are disabled project-wide, with the reasoning
  recorded: all 55 findings under them are deliberate paired statements and
  combined imports, not defects. Every other default rule is enabled and
  passes on the whole tree, with no grandfathered violations.
- C++ formatting is enforced on changed lines only. A stock style would
  rewrite 3715 lines of the 4365-line core; the tuned config still 971. The
  tree converges as it is edited rather than in one unreviewable commit.

### Fixed

- **`ctest` could pass while testing a stale binary.** The v0.7.1 CMake split
  moved the built executables into subdirectories. `ctest` resolves target
  paths itself, so it kept passing, but a pre-split build had left stale
  binaries at the old top-level paths, and `./build/helpmate_tests
  "~[slow]"` kept answering — from a binary built before the change it was
  meant to verify. Five tasks' worth of that gate were therefore meaningless.
  Fixed in v0.7.1 by `CMAKE_RUNTIME_OUTPUT_DIRECTORY`; this release adds the
  CI step that asserts the binaries exist at their documented paths, so a
  future layout change fails loudly in one place instead of silently
  everywhere.
- **`make format-check` reported success whenever it could not run.**
  `git clang-format` writes errors to stderr, `tee` captured only stdout, and
  with no `pipefail` the recipe's exit status was `tee`'s — always 0. An
  unresolvable base ref, a missing `clang-format`, or an unwritable temp path
  all produced a green check. On a shallow CI checkout this would have made
  the formatting gate a permanent no-op. Every condition that prevents the
  check from running now exits non-zero.
- **`node --check` does not validate ES modules.** Node's CommonJS-first
  auto-detection short-circuits at the first `import`/`export`, so any syntax
  error after that line was silently accepted. Every dashboard module has an
  import within its first nine lines, so the JS gate was validating almost
  nothing. Each file is now checked through a temporary `.mjs` copy, which
  forces unambiguous ESM parsing.
- Four unused imports, two ambiguous `l` variable names, one lambda bound to
  a name, and two mypy findings — one of which was a `# type: ignore` naming
  the wrong error code, so it had been silencing nothing.

## [0.7.1] - 2026-08-01

### Changed

- **The repo is now three separately installable distributions.**
  `helpmate` (C++ core, the `helpmate` CLI binary, and the Python bindings),
  `helpmate-api` (the FastAPI service and `helpmate-tables`), and
  `helpmate-web` (the dashboard). Each has its own `pyproject.toml` or
  `CMakeLists.txt` and owns its own test suite under
  `src/packages/<name>/tests/`. `make install` installs all three in
  dependency order.
- **`pip install helpmate` now puts the `helpmate` command on PATH.** The
  wheel carries the compiled binary, so using the CLI no longer requires a
  C++ toolchain on the target machine.
- **The API locates the dashboard by importing `helpmate_web`**, with
  `--web-root DIR` to override and `--no-web` to serve the API alone. The
  previous version guessed between two filesystem layouts and served nothing
  when it guessed wrong.
- **One `VERSION` file** feeds CMake, `version.h` and the `cli_version` test
  regex; a repo-level test asserts the three `pyproject.toml` literals,
  `helpmate.__version__`, `helpmate_server.__version__` and
  `helpmate --version` all agree with it.

### Migration

`pip install ".[server]"` no longer exists — the server is a different
distribution. Use `make install`, or
`pip install . ./src/packages/api ./src/packages/web` **in that order**
(`helpmate-api` requires `helpmate`, and nothing is published to PyPI yet).

## [0.7.0] - 2026-08-01

### Added

- **Web dashboard**: `helpmate-server` now also serves a static single-page
  dashboard at `/` (mounted after every `/v1` route, so the API is never
  shadowed) — no separate process or build step, just
  `helpmate-server --tables <dir>` and open `http://127.0.0.1:8642/`.
  - **Explorer** panel: an interactive board (drag a piece to play a legal
    move, with a promotion dialog when needed) showing the position's
    dtm/count/h#n and every optimal move, click a move to advance and push
    history, `Back` to undo, `Flip` to change orientation, a FEN box to jump
    to any position, and a "Download PGN" export of the current line. The
    current position lives in the URL (`#fen=...`), so any explorer view is
    a shareable link that opens directly to that position in a fresh tab.
  - **Position editor**: a piece palette under the board places pieces by
    clicking squares, with `Erase`, `Clear board` and a `To move` selector.
    Editing deliberately does not probe on every click — a half-built
    position is illegal by definition — so the value appears when the
    editing session ends. A position with no king, or two of one colour, is
    reported directly instead of spending a request to be told
    `invalid_fen`.
  - **Materials** panel: browse every catalogued material class and its
    generation-time stats — where the cells went (solvable / no mate /
    illegal), a mate-length histogram split by side to move, a histogram of
    how many distinct optimal solutions positions have (exact for 1–4, then
    bucketed by octave, with the saturated 255+ bucket called out), and the
    deepest and deepest-unique sample positions, each clickable into the
    explorer.
  - **Search** panel: the `mine` scan (material, dtm, optional
    count/starts/ends/max) with truncation and skipped-saturated reporting,
    plus "Download FENs" (plain text) and "Download CSV" exports of the
    result set.
  - No CDN dependencies: the board library (`cm-chessboard`) is vendored
    under `web/vendor/`, so the dashboard works fully offline.
- **`GET /v1/moves`**: given a `fen`, returns the position's own
  dtm/count/notation/flipped (or `solvable: false`) plus every legal move
  annotated with its resulting FEN, dtm, count, notation, and whether it is
  one of the optimal moves — the data the explorer's move list and
  click-to-advance are built on. See
  [USAGE.md](docs/USAGE.md#get-v1moves) for the response shape and a real
  captured example.
- **Browser test suite** (`tests/ui/`, Playwright + headless Chromium): 11
  end-to-end tests driving a real `helpmate-server` process against a
  freshly generated `KQvk` closure — the golden position's dtm/count/move
  count, click-to-advance plus `Back`, a `#fen=` link opening the exact
  position in a fresh tab, panel exclusivity, both stats histograms and
  their agreement with the cell tiles, a full palette editing session, the
  missing-kings report, the server chip, and the mine panel's
  truncation/validation behavior. Wired into CI as a new `ui` job (installs
  the `dev`+`server` extras, caches and installs headless Chromium, runs the
  pure-JS helper tests and the Playwright suite).
- **Pure JS helpers** (`web/js/lib/`) covered by `node --test
  tests/js/*.test.js` (`make jstest`), independent of the browser suite: URL
  state encode/decode, FEN/PGN/CSV export formatting, FEN composition and
  king validation for the editor, and the histogram/cell-summary shaping the
  materials panel draws.

### Fixed

- **Every dashboard panel rendered at once**: `#panel-explorer { display:
  flex }` is an id selector and outranks the user-agent `[hidden]` rule, so
  hiding a panel did nothing and the three screens stacked. `[hidden] {
  display: none !important }` restores the intent; a browser test now
  asserts panel exclusivity, which the previous suite could not catch
  because it only checked that elements inside the target panel were
  visible.
- **`Tablebase::moves` threw on a king capture**: a capture of the king is
  a "legal move" only from an already illegal position (the side not to move
  is in check) — reachable from the new position editor — and probing the
  resulting position raised `invalid_argument`, so a whole `/v1/moves`
  request failed with an `invalid_fen` naming a FEN the caller never sent,
  while `/v1/probe` answered the same input fine. Such a move is now
  reported as having no value, like a move into a material with no table,
  and the move list stays complete.
- **`wheel.packages` didn't ship `web/`**: a non-editable `pip install`
  built a server with no dashboard to serve. `web/` is now included in
  `[tool.scikit-build] wheel.packages`, and `create_app`'s static-mount
  lookup checks both the installed-wheel layout (`web/` as a sibling
  package of `helpmate_server` in `site-packages`) and the source-checkout
  layout (`web/` at the repo root), so the dashboard is served either way.
- **`tests/ui/conftest.py` server fixture hardening**: the env dict literal
  used to let a pre-existing `HELPMATE_TABLES` in the environment silently
  win over the freshly generated scratch tables dir; a stuck server on
  teardown could raise `TimeoutExpired` and leak an orphan process holding
  the port; and a startup crash was swallowed by `DEVNULL`, surfacing only
  as a generic "server did not start" after the poll timeout. All three
  fixed: the scratch tables dir always wins, teardown falls back to `kill()`
  on a timeout, and captured subprocess output is included in the startup
  error so a CI failure is diagnosable.

## [0.6.2] - 2026-07-31

### Added

- **`mine` shape filters, `--starts`/`--ends`**: narrow a `mine` scan to
  positions with an exact number of distinct first moves (`--starts N`) and/or
  distinct mating moves (`--ends N`) among their optimal solutions, on top of
  the existing exact `--dtm`/`--count` match — enough to distinguish, say, a
  4-solution position with 2 tries that each finish 2 ways (`starts=2,
  ends=4`) from one with 4 completely independent lines (`starts=4, ends=4`).
  Available on all three surfaces:
  - CLI: `helpmate mine <MATERIAL> --dtm D [--count C] [--starts N] [--ends N]`.
    Both must be `>= 1` and, when `--count` is also given, `<= --count`;
    violating either is a usage error (exit 3), including a literal `-1`
    (otherwise a value the flags could take, so it can't be treated as
    "unset"). `mine` now also tallies positions it had to skip because their
    stored solution count is saturated (255+, unenumerable — see below) and
    prints the count to stderr on exit.
  - HTTP API: `GET /v1/mine` gains optional `starts`/`ends` query params
    (same exact-match, same `>= 1`/`<= count` validation, `400
    invalid_filter` on violation) and every response gains a
    `skipped_saturated` integer field with the same meaning as the CLI's
    stderr tally.
  - Python: `Tablebase.mine` gained `starts`/`ends` parameters; a new
    `Tablebase.mine_with_stats` returns `(fens, skipped_saturated)` for
    callers that want the tally (the plain `mine` return shape is
    unchanged).
  See [USAGE.md](docs/USAGE.md#mine--scan-for-composition-candidates) and
  [USAGE.md](docs/USAGE.md#get-v1mine) for worked examples.
- **`Tablebase::mine` takes a `MineFilter`**: the `dtm`/`count`/`starts`/`ends`
  scan criteria are now grouped into one `MineFilter{dtm, count, starts,
  ends}` struct instead of separate parameters, with `starts`/`ends`
  evaluated (via the new pure `shape_of(count, lines)` helper, also exposed
  as `Tablebase::solution_shape(fen)`) only for candidates that already
  passed `dtm`/`count` — no wasted work enumerating lines for positions that
  were never going to match. `shape_of` reports `exhaustive: false` instead
  of a `starts`/`ends` count when the stored solution count is saturated,
  which is what lets `mine` (and the API/CLI tallies above) recognize and
  skip those positions instead of guessing at an undercount.

### Fixed

- **A table written by a newer helpmate now reports "upgrade this build",
  not "no table"**: `TableReader::open` gained an `OpenError` out-parameter
  (`NotFound` / `Unreadable` / `UnsupportedVersion`) so callers can tell a
  genuinely missing/corrupt table apart from one whose format `version` this
  build doesn't understand yet. `Tablebase::load` now throws a distinct,
  actionable error for the latter case (`table ... was written by a newer
  helpmate (unsupported table format version); upgrade this build`) instead
  of the same generic "missing table" diagnosis it used to give both cases.

## [0.6.1] - 2026-07-30

### Added

- **Prune provably-unsolvable slices at generation time**: `gen` now skips
  writing a full table for a slice it can prove contains no helpmate at all —
  either the mating side (White, by the index convention) is a bare king
  (`Material::mating_side_is_bare_king()`, e.g. `Kvk`, `Kvkq`, `Kvkr`), or
  every successor slice reached by a capture/promotion is itself already
  proven dead and the slice has no checkmate position of its own
  (`slice_has_any_mate()`). Enabled by default (`GenOptions::prune`, default
  `true`); an oracle test pins the project's known-unsolvable classes.
- **Marker tables (format version 2)**: a pruned slice is written as a tiny
  marker — header + JSON metadata only, no value planes at all — instead of
  a full-size table of all-`DTM_UNSOLVABLE` cells. Every cell of a marker
  reads back as unsolvable when probed, identically to a fully-generated
  all-unsolvable table. `TableReader` accepts both version 1 (ordinary
  tables) and version 2 (markers) transparently; no reader needs to change.
- **`helpmate compact <DIR> [--dry-run]`**: rewrites existing all-unsolvable
  `.hm` tables (e.g. ones generated before this release) into version-2
  markers in place, atomically, reclaiming disk space with no change in
  queryable results. Tables with any solvable cell, and tables that are
  already markers, are left untouched; `--dry-run` is a true no-op that only
  reports what would be rewritten. See [USAGE.md](docs/USAGE.md#compact--reclaim-disk-space-in-already-unsolvable-tables)
  for a worked example.

### Fixed

- **`helpmate-tables push` hashed every file twice**: the local
  `manifest.json` build and the remote-manifest merge each independently
  called `build_manifest`, so every push sha256-hashed the whole `--tables`
  directory twice. Now hashed once and reused for both the local manifest
  write and the merge — real time saved at 6-piece table sizes, no change in
  the manifest's content.

## [0.6.0] - 2026-07-30

### Added

- **`server` extra and `helpmate_server` package** (`pip install ".[server]"`,
  adds `fastapi`, `uvicorn`, `huggingface_hub`): a read-only HTTP API and a
  Hugging Face sync CLI on top of the existing generator/probe library.
- **Storage layer** (`helpmate_server.storage`): `LocalDir` (one on-disk
  tables directory), `RemoteSource` (a Hugging Face dataset repo with a local
  download cache, size-checked catalog entries, background fetch with
  `absent`/`fetching`/`cached`/`failed` state tracking, sha256-verified
  downloads), and `ChainSource` (searches local dirs in order, then falls
  back to the remote).
- **`helpmate-server` CLI**: serves `/v1/*` routes over one or more
  `--tables` directories plus an optional `--hf-repo`/`--cache` remote;
  `--host`/`--port` (default `127.0.0.1:8642`), `--mine-cap`/`--mine-timeout`
  bound the cost of `/v1/mine` queries.
- **API routes**: `GET /v1/health`, `/v1/materials` (catalog),
  `/v1/materials/{name}/stats`, `/v1/probe` (JSON `dtm`/`count`/`flipped`/
  `notation`, or `{"solvable": false}`), `/v1/line` (`?all=true` for every
  optimal line), `/v1/mine` (dtm/count-filtered FEN scan, capped and
  timed out server-side). All errors share one envelope,
  `{"error": {"code", "message", "hint"}}`, including framework-generated
  404/405s and uncaught exceptions.
- **202-fetching semantics**: a query against a material that exists only in
  the remote manifest triggers a background download and returns
  `202 {"status": "fetching", ...}` until it completes (then `200`) or fails
  (`502 fetch_failed`); a material in neither local dirs nor the remote
  manifest is a plain `404 unknown_material`.
- **`helpmate-tables push`/`pull`** CLI: pushes a scoped or full set of
  `.hm`/`.stats.json` files to a Hugging Face dataset repo, merging into
  (never discarding entries from) any existing remote `manifest.json`; pull
  defaults to every material advertised in the remote manifest when
  `--material` is omitted, and sha256-verifies each downloaded file before
  accepting it. Exit codes: `0` success, `1` failure after starting
  (network/verification error), `2` bad usage.
- **`tests/server`**: 51 tests covering storage (local/remote/chain), the
  manifest builder/writer/verifier, every API route (catalog, probe, mine,
  202-fetching), the CLI, and package metadata; wired into CI alongside
  `tests/python`.

### Fixed

Hardening rounds found and closed during development, before any release:

- A failed remote download no longer leaves the material stuck at
  `502 fetch_failed` until server restart: the request that observes the
  failure re-triggers the download, so the client's retry sees `202` and
  then `200` — matching the hint text's promise.
- `verify_file` now correctly returns `False` (not a crash) for a file the
  manifest lists but that is missing on disk.
- The remote fetch state machine was hardened against re-fetching an
  already-cached slice, left cleaning up both `.hm` and `.stats.json` on any
  failure, and made to size-check cached files against the manifest before
  trusting them.
- Framework-generated 404/405 responses now carry the same
  `{"error": {...}}` envelope as application errors, instead of Starlette's
  bare `{"detail": ...}`.
- Empty/whitespace FENs are rejected with `400 invalid_fen` instead of
  falling through to a confusing 500 or 404.
- `push` now fails loudly (exit 1, nothing uploaded) if fetching the
  existing remote manifest errors, rather than silently uploading a
  manifest that forgets previously-pushed materials; `fetch_manifest`
  returning `None` is the explicit, documented "remote has no manifest yet"
  contract (as opposed to a fetch error).
- `pull` now defaults to every material in the remote manifest when
  `--material` is omitted, and reports errors (missing manifest, download
  failure, sha256 mismatch) without leaking a Python traceback to stderr.

## [0.5.0] - 2026-07-30

Initial release.

### Added

- **Tablebase generator** for helpmate (cooperative mate) chess endgames:
  exhaustive fixed-point search over whole material classes (any combination
  of the six piece types, 2-8 pieces, underpromotions and exact en passant
  included; castling out of scope), computing distance-to-mate and the number
  of distinct optimal lines per position. Builds the full capture/promotion
  sub-slice closure in topological order; multithreaded (`--threads`), with
  byte-identical output to single-threaded runs (enforced by tests).
- **Compact, mmap-backed table format** (`.hm`): four 1-byte planes per slice
  (dtm/count x side-to-move) behind a versioned header plus a JSON metadata
  blob, written atomically; a `.stats.json` sidecar per slice (dtm histogram,
  uniqueness histogram, deepest and deepest-uniquely-solved positions).
- **Probe library and CLI** (`helpmate`): `gen`, `probe`, `line` (one or all
  optimal SAN lines), `stats`, and `mine` (scan a class for composition
  candidates by exact dtm/solution count); color-flip fallback for probes,
  clear exit codes, `--version`.
- **Progress and verbosity for `gen`**: `--verbose` per-slice lifecycle lines
  and `--progress` per-pass heartbeat on stderr (stdout stays scriptable),
  with zero hot-loop overhead.
- **RAM guard for `gen`**: refuses, before allocating anything, a slice whose
  planes exceed `MemAvailable`, costing the whole closure upfront;
  `--force-ram` overrides.
- **Python bindings** (`pip install .`, pybind11 + scikit-build-core):
  `helpmate.generate()` and `helpmate.Tablebase` (probe/line/lines/mine/stats).
- **Verification suite**: an independent cooperative-DFS oracle re-solving
  sampled positions from every generated slice; exhaustive python-chess
  cross-validation of the full KQvk class (368,452 positions, dtm and count);
  golden compositions; multithreaded-determinism tests; 6-piece index
  roundtrip tests.
- **Hardened generator lookup paths** (bug #21): every cross-slice/EP lookup
  failure surfaces as a contextual `GeneratorLookupError` (slice, cell, depth,
  FEN) instead of undefined behavior or a bare `map::at`.
- **CI and docs**: GitHub Actions pipeline (build + fast suite + tag release),
  detailed build (`docs/BUILD.md`) and usage (`docs/USAGE.md`) guides,
  coverage tooling (`make coverage`, 91.6% line coverage on `src/`).

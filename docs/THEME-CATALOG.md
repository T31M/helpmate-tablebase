# Theme catalogue: what this project could detect

Every one of the **295 themes** named in the [Helpmate Analyzer
glossary](https://helpman.komtera.lt/themes.html) (Viktoras Paliulionis),
classified against what a tablebase can actually compute. The glossary is the
authority for what each name *means*; the tier is this project's own
assessment of its own machinery, written 2026-08-03 against v0.8.0. Nothing
here is a promise that a theme will be implemented, and no tier assignment has
been validated by writing the detector — a tier is a claim about which
*primitives* a detector would need, not about how hard the detector is.

The claim worth making up front is narrow. A tablebase is not a better
analyser than a single-problem analyser; it is a different one. It knows every
optimal solution of a position without searching, it knows both sides-to-move
planes of every position it stores, and it can answer any other legal position
of the same material in O(1). That makes a small family of themes — set play,
move-order choice, dual avoidance, tempo — cheap here and awkward elsewhere.
It does nothing at all for the large family of themes built on line geometry,
where the analyser's vocabulary (pin, interference, battery, critical square)
is exactly what this project lacks.

## What a detector can see today

A detector is a pure function of a `Solution` (`src/core/probe/solution.h`):
the starting board, and per ply the mover, from/to, captured type, promotion
type, en-passant and check flags, and the full board after the ply.
`themes::trajectories()` chains plies into per-unit paths;
`themes::attackers_of()` and `themes::king_field()` give square-attack counts
and the king's field. There is no notion of a line of action, a pin, or a
piece supporting another. Two format facts bound the catalogue permanently:
**castling is not supported** (`Board::from_fen` rejects castling rights) and
**en passant is** (exactly, folded in at generation and probe time).

## Tiers

- **A — computable now, no new machinery.** Readable from a single position,
  from the already-stored second (side-to-move) plane, or as a set/count
  operation over the solutions `solutions()` already returns.
- **B — cross-solution comparison.** Solutions compared against each other
  using only facts already in `Ply`/`Solution`/`trajectories()`. No
  line-geometry analysis.
- **C — extra tablebase probing.** Computable only by querying positions
  *other* than the one asked about: swapped move orders, skipped moves,
  removed units, mates that must be shown not to work. Cheap here because a
  probe is O(1); genuinely expensive for a searching analyser.
- **D — strategic-motif engine.** Needs line-piece geometry the project has no
  notion of: pins, half-pins, interference, batteries, critical squares,
  clearance, doubling, unpinning.
- **E — twinning.** Needs a modified diagram — a piece changed, moved, added
  or removed. Often a table the project has already generated, but it needs
  its own vocabulary before it can be asked for.
- **X — impossible or out of scope.** Requires castling (permanently
  impossible), needs retro-analysis, or is a composer- or tourney-specified
  pattern rather than a general theme.

Themes whose glossary entry is a bare cross-reference are tiered as their
target and marked "alias of X" in the note.

## Summary

| Tier | Themes | Share |
|---|---|---|
| A — computable now | 81 | 27% |
| B — cross-solution | 64 | 22% |
| C — extra probing | 21 | 7% |
| D — motif engine | 100 | 34% |
| E — twinning | 4 | 1% |
| X — out of scope | 25 | 8% |
| **Total** | **295** | |

A and B together are 142 themes — just under half — and neither needs anything
the codebase does not already have. D alone is 103 themes, and they are one
piece of machinery, not 103.

## The catalogue

Sorted alphabetically (case-insensitive), so it can be used as a lookup. The
note says why the tier, or what the theme needs; it is deliberately not a
paraphrase of the definition — follow the glossary link above for that.

| Theme | Tier | Note |
|---|---|---|
| 100 Dollar theme | A | white and black excelsior with knight promotions, all inside one solution |
| Abdurahmanovic 1 theme | X | tourney-specified compound pattern |
| Abdurahmanovic 3 theme | X | tourney-specified compound pattern |
| Abdurahmanovic 4 theme | X | tourney-specified compound pattern |
| Active sacrifice | A | a unit moves to a square where a later ply captures it |
| Albino | B | union of one white pawn's four home-square moves across phases |
| Allumwandlung | B | implemented, as set coverage across the solutions |
| Amazon theme | A | every white ply moved by the queen |
| Ambush | D | needs the battery / line-opening notion |
| Analogy | D | compares arrival and departure motifs between phases |
| Annihilation | A | capture then vacate; the "positive effect" qualifier stays approximate |
| Anti-Albino | B | union of a white pawn's moves arriving on its fourth rank |
| Anti-Bristol | D | line closure toward another piece |
| Anti-critical move | D | critical squares |
| Anti-Levman mate | D | masked guard lines |
| Anti-Loshinsky theme | B | collinearity plus from/to arithmetic across phases |
| Anti-magnet | B | same, with the distance growing phase by phase |
| Anti-Pickaninny | B | union of a black pawn's moves arriving on its fourth rank |
| Anticipatory anti-Bristol | D | alias of Anti-Bristol |
| Anticipatory Bristol | D | line clearance |
| Anticipatory half-pin | D | half-pin |
| Anticipatory interference | D | interference |
| Anticipatory pin | D | pin lines |
| Anticipatory self-pin | D | pin lines |
| Anticipatory self-unpin | D | pin lines |
| Anticipatory unpin | D | pin lines |
| AntiZielElement | D | a motif carrying a sign; needs the motif vocabulary |
| Apparent mate | A | the other plane of the diagram mates in one |
| Areal cycle | A | one unit's trajectory |
| Arrival effect | D | the motif vocabulary itself |
| Artificial castling | A | ordinary moves onto the post-castling squares; no castling rights involved |
| ASP | D | alias of Anticipatory self-pin |
| Asymmetry | A | axis symmetry of the diagram, then a mirror test per solution |
| Authier theme | D | unpins on a check line |
| AUW | B | alias of Allumwandlung |
| Avanta | B | union of two pawns' four non-capturing home-square moves |
| AZE | D | alias of AntiZielElement |
| Azemmour 10 theme | X | tourney-specified pattern |
| Azemmour 11 theme | X | tourney-specified pattern, though the flight count itself is trivial |
| Azemmour 12 theme | X | tourney-specified pattern |
| Azemmour 6 theme | X | tourney-specified pattern |
| Azemmour 7 theme | X | tourney-specified pattern |
| Azemmour 8 theme | X | tourney-specified pattern |
| Azemmour 9 theme | X | tourney-specified pattern |
| Babson task | B | promotion types and squares matched pawn for pawn across phases |
| Bajtay theme | D | chained self-pins and unpins |
| Balbo theme | A | piece types of the movers, ply by ply |
| Baltic theme | B | shared departure square and shared mating square across phases |
| Big cross | B | union of one unit's destinations |
| Big star | B | union of one unit's destinations |
| Bivalve | D | one move opening one line and closing another |
| BK moves only | A | implemented as single-piece:black |
| Blocking piece replacement | A | diagram against mating board on one flight square |
| Boros theme | D | indirect pin on the mating move |
| Brasil theme | D | anti-critical moves and guard lines |
| Bristol | D | line clearance |
| Brixi theme | D | guards by pinned units |
| Brochettes theme | B | same movers in the same order in every phase |
| Brunner-Loyd clearance | D | clearance |
| Brunner-Turton doubling | D | doubling |
| Brunner-Zepler doubling | D | doubling |
| Bukovina theme | A | attack count on a flight, its capture, a later self-block there |
| Bukovinszky theme | C | set play plus two "threatened" mates that only a probe can confirm |
| Bukovinszky-Garai theme | C | same machinery, one mate deeper |
| Carra theme | B | allumwandlung by a single white pawn across the branches |
| Castling | X | the format has no castling rights |
| Chameleon echo-mates | B | mating boards compared, plus the colour of the king's square |
| Changed blocks | B | different blockers on one square across phases |
| Changed motivation | E | a twin whose solution is unchanged |
| Changed promotions | B | promotion type per pawn and square across phases |
| Check prevention | C | needs the position in which the move was not made |
| Cheney-Loyd theme | D | critical move with permanent interception |
| Chernous theme | D | self-pin by interference, then unpin |
| Choice of move order | C | probe the swapped order |
| Chumakov theme | B | captured in one phase, self-blocking in another |
| Closed chain of Umnov | A | every ply lands on a just-vacated square |
| Closed walk | A | implemented |
| Compass theme | B | occupancy of two squares compared across four solutions |
| Complete helpmate | C | needs the phases in which one side has no move |
| Consecutive Bristol | D | chained clearance |
| Consecutive checks | A | the is_check flag |
| Consecutive Umnov | A | from/to chain |
| Corner-to-corner | A | one from/to, or one unit's trajectory |
| Critical move | D | critical squares |
| Cross | B | union of one unit's destinations |
| Crosscheck | A | check answered by a non-capturing check |
| Crusader theme | A | every white ply by one knight |
| Cycle of captures | A | capture chain inside one solution |
| Cycle of double pins | D | pins in the mating positions |
| Cycle of functions | B | cyclic roles, as far as capture / mate / block roles reach |
| Cycle of moves | B | move sequences compared across phases |
| Cycle of pieces | B | movers compared across phases |
| Cycle of promotions | B | promotion types across phases |
| Cycle of squares | B | key squares across phases |
| Cycle of unpins | D | unpins |
| Cyclic place exchange | A | trajectory endpoints inside one solution |
| Cyclic Zilahi | B | captured and mating units across three or more phases |
| Daisy | B | union of a queen's eight destinations |
| Delayed Umnov | A | square history inside one solution |
| Departure effect | D | the motif vocabulary itself |
| Distant self-block | A | self-block plus the king field of the square the king reaches |
| Dolginovich theme | B | mover types compared between phases |
| Double Zilahi | B | two independent Zilahi pairs |
| Dual avoidance | C | probe the mate that does not work |
| Durbar theme | A | every white ply by the king |
| Echo mates | B | mating boards compared up to shift, rotation and mirror |
| En passant | A | implemented; the format supports ep exactly |
| Enabling hideaway | C | hideaway needs a removed-unit probe |
| Enabling tempo | C | tempo needs a skipped-move probe |
| Epaulette interferences | D | interference |
| Excelsior | A | implemented |
| Exchange of functions | B | two units of one colour swap roles between phases |
| Exchange of moves | B | the same two moves, reversed, in two phases |
| Exchange of promotions | B | promotion types swapped between phases |
| Extended Albino | B | union of one white pawn's eight moves |
| Extended cross | B | union of one unit's destinations |
| Extended cyclic Zilahi | B | three-phase capture-and-mate cycle |
| Extended Pickaninny | B | union of one black pawn's eight moves |
| Extended star | B | union of one unit's destinations |
| Feather 2 theme | A | sacrifice in the king field, pawn capture, self-block |
| Feather mechanism | D | two white lines crossing the black queen's square |
| Feather theme | A | move paths crossing the initial black king square |
| Festina lente | A | two single steps from a pawn's home square |
| FML | A | repeated arrival on the square one enemy unit just left |
| Forsberg twins | E | twinning by changing a piece's type |
| Four corners | B | union of one unit's destinations |
| Gamage theme | D | direct unpin of a pinned black piece |
| Garai theme | C | mates that fail only for want of a black tempo move |
| Gate-opening | D | vacating a line so a slider can cross it |
| Goethart theme | D | indirect unpin, battery mate |
| Grimshaw | D | mutual interference |
| Guidelli theme | D | unpin under check |
| Half-pin | D | half-pin |
| Helledie theme | D | needs the motive of a move, not just the move |
| Helpmate | A | the stipulation itself, not a theme |
| Helpmate of the future | D | alias of HOTF |
| Helsinki theme | A | sacrifice then two vacations, all inside one solution |
| Herlin | D | peri-critical move |
| Hesitation | C | probe the immediate alternative |
| Hidden tempo-try | C | tempo tries |
| Hideaway | C | probe with the unit removed, i.e. another material's table |
| Hideaway maneuver | C | same, spread over two or more moves |
| Holzhausen interference | D | interference |
| Home-coming | A | mating board against the game-array squares |
| Homebase | A | the diagram alone |
| HOTF | D | needs motifs grouped into themes before pairs can be compared |
| Hyvinkaa theme | A | every ply of one solution lands on one square |
| Iceland theme | D | alias of Island theme |
| Ideal mate | A | implemented |
| Illegal position | X | retro analysis; the project has none and wants none |
| Indian | A | implemented; retiered from D: critical move over c, own-colour interference on c, discovered check through c -- ply squares plus one attack test |
| Island theme | D | a square's guard lines closed from both ends |
| JT Navon 90 theme | X | tourney-specified pattern |
| JT Onkoud 50 theme | X | tourney-specified pattern |
| Kindergarten problem | A | material of the diagram |
| Klasinc theme | A | implemented; retiered from D: a unit vacates a square, a line piece passes over it, the unit returns -- ply from/to geometry, no line notion needed |
| Kluver 10 theme | D | ambush and gate-opening |
| Kniest 1 theme | B | promoting colour in the set-play plane against the solution |
| Kniest theme | A | capture on the square where the king is later mated |
| Knight wheel | B | union of a knight's eight destinations |
| Kozhakin theme | A | first and last white ply on the same square |
| Kubbel-Grimshaw | D | mutual interference |
| Lacny cycle | B | mate mapped to black move over six phases |
| Larsson theme | B | final boards of set play and solution compared |
| Leibovici interference | D | Pelle move plus interference |
| Lindner 1 theme | C | waiting moves |
| Lindner 2 theme | C | set-play "threats" that only a probe can confirm |
| Linear cycle | A | one unit's trajectory |
| Loewenton theme | B | promotion types swapped between set play and solution |
| Long-trip | A | one officer moving three or more times |
| Loshinsky magnet | B | collinear follow, from/to arithmetic |
| Loyd's clearance | D | clearance |
| Loyd-Turton doubling | D | doubling |
| Loyd-Zepler doubling | D | doubling |
| Magnet | D | a bicoloured Bristol, so clearance |
| Many-ways | B | same endpoints, different routes, three phases |
| Maslar theme | A | implemented, with the Black-White form; retiered from D: critical move, interference, capture of the interferer -- ply squares plus one attack test |
| Mates on same square | A | group solutions by the last ply's destination |
| Mating piece | A | the last ply's mover; battery cases are genuinely ambiguous |
| Mating square | A | the last ply's destination, or the mated king's square |
| Meerane theme | A | first and last ply compared inside one solution |
| Mihajloski theme | A | collinear order swapped twice inside one solution |
| Mirror mate | A | implemented |
| Mixed Phoenix | A | capture on a promotion square, then a like promotion |
| Model mate | A | implemented |
| Monkey theme | A | the two sides' move sequences compared |
| Mutual interference | D | interference |
| Mutually exclusive tempo | C | tempo |
| Nagnibida theme | A | alias of Bukovina theme |
| Nesic theme | D | mutual interference |
| Nissl theme | A | sacrifice, then promotion to the same type |
| Obtrusive piece | A | static reading of the diagram's pawn structure |
| Octopus theme | B | alias of Rosette |
| ODT | D | alias of Orthogonal-diagonal transformation |
| Onkoud 2 theme | X | composer-specified pattern |
| Onkoud theme | X | composer-specified pattern |
| Onkoud-St German theme | X | composer-specified pattern |
| Organ pipes | D | four Grimshaw pairs |
| Orthogonal-diagonal transformation | D | needs effects classified by line direction |
| Oudot task | A | three black queen promotions in one solution; the table could settle it for reachable material |
| Paros theme | D | paired bivalves |
| Pawn-Zajic | A | Zajic with a pawn as the capturing unit |
| Pelle move | D | pin line |
| Pendulum | A | one unit's trajectory |
| Peri-critical move | D | critical square |
| Phoenix | A | capture, then promotion to the same type |
| Pickabish | D | mutual interference |
| Pickaninny | B | union of one black pawn's four home-square moves |
| Pin restoration theme | D | pins |
| Pin-mate | D | pins in the mating position |
| Pin/self-unpin | D | pins |
| Pin/unpin | D | pins |
| Pinning | D | pins |
| Piran theme | D | the same pin exploited in set play and solution |
| Place exchange | A | trajectory endpoints inside one solution |
| Place exchange in final positions | B | mating boards compared |
| Play on same square | B | same move number, same destination, different movers |
| Promoted force | A | static reading of the diagram |
| Promotion | A | implemented |
| Pseudo Albino | B | a queen's four pawn-like moves across phases |
| Pseudo Bristol | D | clearance |
| Pseudo Pickaninny | B | a queen's four pawn-like moves across phases |
| Pseudo Rehm theme | D | peri-manoeuvre |
| Pseudo Zilahi | D | needs the battery's rear piece identified as the mater |
| Reciprocal batteries | D | batteries |
| Reciprocal battery transformation | D | batteries |
| Reciprocal Bristol | D | clearance |
| Reciprocal captures | B | capturer and captured swapped between phases |
| Rehm theme | D | peri-manoeuvre and anti-critical move |
| Roentgen theme | D | pin |
| Rope theme | B | mover kinds swapped between phases |
| Rosette | B | union of a king's eight destinations |
| Rovno theme | B | two like units of opposite colour swap squares across phases |
| Sabra 25 theme | X | tourney-specified pattern |
| Sabra 26 theme | X | tourney-specified pattern |
| Sabra 27 theme | X | tourney-specified pattern |
| Sabra 28 theme | X | tourney-specified pattern |
| Sabra 29 theme | X | tourney-specified pattern |
| Sacrificial Bristol | D | clearance |
| Sacrificial clearance | D | alias of Sacrificial Bristol |
| Sankt Petersburg theme | B | promotion type matched to the type Black offers |
| Schnoebelen theme | A | promoted unit captured before it ever moves |
| Segenreich theme | C | a mate available a move early, plus a waiting move |
| Self-block | A | implemented |
| Self-pin/self-unpin | D | pins |
| Self-pin/unpin | D | pins |
| Self-unpin/pin | D | pins |
| Self-unpin/self-pin | D | pins |
| Set play | A | the other plane of the same position |
| Sharp theme | D | a battery built, then abandoned |
| Shifted Babson task | B | promotions matched cyclically across phases |
| Short set play | A | the other plane, at a shorter distance |
| Siers battery | D | battery |
| Skittles | A | the diagram alone |
| Slow Excelsior | A | excelsior that opens with a single step |
| Somov mate | D | guard lines closed in the mate |
| Square-clearance by capture | A | capture, vacate, enemy unit follows onto the square |
| Staircase | A | trajectory shape |
| Star | B | union of one unit's destinations |
| Stavrinides theme | B | trajectories of both colours compared between phases |
| Step-by-step Bristol | D | clearance |
| Stocchi blocks | C | repeated blocks plus dual avoidance |
| String theme | B | move lengths growing along one line across phases |
| Striptease theme | E | successive twins made by removal |
| Super Durbar | A | both sides move only their kings |
| Switchback | A | implemented |
| Tempo maneuver | C | probe the position with the moves skipped |
| Tempo move | C | probe the position with the move skipped |
| Tempo play | C | alias of tempo move and tempo manoeuvre |
| Transferred pin | D | pin lines |
| Turton doubling | D | doubling |
| Umnov mate | A | implemented |
| Umnov move | A | implemented |
| Unblocking sacrifice | A | capture, vacate, enemy unit captures on the square |
| Uncastling | X | castling |
| Unpin | D | pins |
| Unpin/pin | D | pins |
| Unpin/self-pin | D | pins |
| Valladao task | X | requires a castling move |
| Valve | D | one move opening and closing lines of one piece |
| Visserman | D | pins and checks |
| WCCT-12 theme | X | tourney-specified pattern |
| White constant | B | white's move sequence held constant across phases |
| White Kniest theme | A | capture on the square the white king later occupies |
| White Zajic theme | A | from/to and captures beside the white king |
| Wigwag | A | a slider recrossing its own start square along one line |
| Witztum challenge | D | paired interferences |
| Wurzburg-Plachutta | D | interference between like-moving pieces |
| Zabunov theme | D | a battery's front piece becoming a rear piece |
| Zagoruiko theme | E | three twins with changed mates; the solution-group variant is B |
| Zajic theme | A | capture on the mating square, then recapture by the king |
| Zalokotsky theme | B | three squares revisited in reverse order in another phase |
| Zepler doubling | D | doubling |
| Zigzag | A | trajectory shape |
| Zilahi | B | implemented, two-solution form |

Row count: **295**, one per glossary entry.

## What v0.8.0 already has

Sixteen registry entries (`src/core/themes/registry.cpp`) cover twelve themes;
four exist in both a broad and a colour-specific form. Ten of the twelve carry
a glossary name:

| Registry entry | Glossary theme |
|---|---|
| `model` | Model mate |
| `ideal` | Ideal mate |
| `mirror` | Mirror mate |
| `promotion` | Promotion |
| `excelsior`, `excelsior:white`, `excelsior:black` | Excelsior |
| `switchback` | Switchback |
| `closed-walk` | Closed walk |
| `self-block` | Self-block |
| `single-piece:black` | BK moves only (with the king); also Durbar, Amazon, Crusader in their white forms |
| `en-passant` | En passant |

Two entries have no glossary counterpart: `pure` (the glossary defines pure
mate only inside its Model mate entry) and `underpromotion` (a move property,
not a named theme).

So the delta is **68 further tier-A themes** reachable with the primitives
already in `src/core/themes/`, before any new machinery at all.

## Where the value is

**Tier A, cheapest first.** Four clusters account for most of it, and each is
one shared helper plus a handful of registry entries:

- *Trajectory shapes* — Staircase, Zigzag, Pendulum, Linear cycle, Areal
  cycle, Long-trip, Corner-to-corner, Wigwag, Place exchange. All are
  predicates over `trajectories()`, which already exists and is already
  tested.
- *The Umnov family* — Umnov move, Umnov mate, Consecutive Umnov, Delayed
  Umnov, Closed chain of Umnov, FML. All are "did this ply land on a square
  something just left", one square-history walk shared between them.
- *The capture-and-square family* — Zajic, Pawn-Zajic, White Zajic, Kniest,
  White Kniest, Bukovina, Square-clearance by capture, Unblocking sacrifice,
  Active sacrifice, Annihilation. All from/to plus `captured` plus the mating
  square.
- *Pawn and promotion patterns inside one solution* — Phoenix, Mixed Phoenix,
  Nissl, Schnoebelen, Festina lente, Slow Excelsior, Oudot task, 100 Dollar
  theme. These are the ones where `mine()` earns its keep: a task like Oudot's
  is a search over a whole material class, which is exactly what this project
  does and a single-problem analyser cannot do at all.

**Tier B needs one abstraction, not sixty-four detectors.** Almost every
tier-B theme is the same shape: take the solution set as a set of *phases*,
project each phase to a small tuple (mover, from, to, promotion type, mating
square, captured unit, final board), and look for a permutation — identity,
swap, or cycle — across phases. Build that projection-and-permutation layer
once and Zilahi and its five relatives, the cycle themes, the changed and
exchanged themes, the Albino/Pickaninny/wheel unions, and the echo-mate
comparison all fall out as configurations of it. This is the single highest-
leverage piece of work in the catalogue: ~64 themes for one abstraction, with
no new chess knowledge required.

**Tier C is the differentiator, and it is small.** Twenty-one themes, all of
them "show that some *other* position does not work": move order, dual
avoidance, tempo, hideaway, the set-play threat themes. Each is a handful of
O(1) probes here and a fresh search elsewhere. Two of them (Hideaway,
Enabling hideaway) probe a position with a unit removed, which is a different
material and therefore a different table — cheap only if that table has been
generated.

**Tier D is one engine.** 103 themes — over a third of the glossary — need the
same missing layer: for each line piece, its lines of action; for each line,
which units lie on it and in what order; and from that, pin, half-pin,
interference, battery, critical square, clearance, doubling, guard line. That
is a single module of perhaps the size of `attack.cpp`, and it is the only
thing standing between this project and Grimshaw, Turton, Indian, Bristol,
the whole pin/unpin lattice, and the Zilahi variants that depend on
identifying a battery's rear piece. Nothing else in the catalogue comes close
to that ratio. It is also the point at which this project would stop being a
tablebase with theme labels and start being an analyser, which is a decision
about scope, not only about effort.

**Tier E is cheap but unclaimed.** Only four themes, but twinning is a
vocabulary the CLI and API do not have: naming a modified diagram, resolving
it to a material, and probing it. Worth doing when a twin-aware query surface
is wanted for its own sake, not for these four.

**Tier X will not move.** Three of the 25 are castling (Castling, Uncastling,
Valladao task) and one is retro-legality (Illegal position); those are
permanent. The other 21 are composer- or tourney-specified compounds
(Abdurahmanovic, Azemmour, Sabra, Onkoud, JT, WCCT). Some of them are
mechanically checkable — Azemmour 11 is a flight count — but they specify a
tournament's entry conditions rather than a general theme, and a general
engine is the wrong place for them.

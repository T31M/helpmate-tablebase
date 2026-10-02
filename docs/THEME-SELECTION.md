# Theme selection -- every theme, grouped by the machinery it needs

Generated from `docs/THEME-CATALOG.md` on 2026-08-08. That file assigns each
theme a feasibility tier; this one regroups the same **295** themes by *what
would have to be built*, which is the axis that matters when choosing what to
implement next.

Nothing here is a commitment, and no grouping has been validated by writing a
detector. The glossary (<https://helpman.komtera.lt/themes.html>) is the
authority on what each name means; the notes are this project's own assessment
of what a detector would need.

## Groups at a glance

| Group | What it needs | Themes |
|---|---|---|
| **DONE** | Already shipped | 23 |
| **A1** | Diagram only | 5 |
| **A2** | Mating position only | 4 |
| **A3** | The other side-to-move plane (set play) | 2 |
| **A4** | Within one solution | 36 |
| **A5** | Within one solution | 9 |
| **A6** | Set operations the catalogue tiered as A | 2 |
| **A7** | Not a theme | 1 |
| **B1** | Across the solution set | 58 |
| **B2** | Set play compared against the solution | 3 |
| **C1** | Extra probing | 20 |
| **E1** | Twinning | 4 |
| **D1** | Motif engine | 93 |
| **X1** | Out of scope | 25 |
| **ALIAS** | Aliases | 11 |
| | **Total** | **295** |

## DONE -- Already shipped  (23)

Twenty-three of the glossary's names. Five more shipped detectors -- `pure`, `underpromotion`, `nocapture`, `nocheck` and the parametric `promotions:<types>` -- are **not** glossary entries, so they do not appear anywhere in this document; that is 28 detectors, 33 registry entries counting the colour and role variants.

| Theme | Tier | Note |
|---|---|---|
| BK moves only | A | implemented as single-piece:black |
| Closed walk | A | implemented |
| En passant | A | implemented; the format supports ep exactly |
| Excelsior | A | implemented |
| Allumwandlung | B | implemented as `allumwandlung`: all four types across the solutions, either colour -- the same question as the parametric `promotions:qrbn` |
| Ideal mate | A | implemented |
| Indian | D→A | implemented as `indian`, either colour; the catalogue tiered it D for "critical square and temporary shut-off", but the structural reading used (a line piece crosses c, a unit of its own colour interferes on c, that unit leaves c giving discovered check along the line through c) is decidable from ply squares plus one attack test |
| Klasinc theme | D→A | implemented as `klasinc`; the catalogue tiered it D for "line geometry", but the definition used (a unit vacates a square, a line piece passes over it, the unit returns) is decidable from ply from/to squares alone |
| Kniest theme | A | implemented |
| Maslar theme | D→A | implemented as `maslar` (white critical move, black interference, black king arrives on the line, the line piece captures the interferer with check) and `maslar:black-white` (black critical move, white interference, black captures); definitions from the glossary text, decidable from ply squares plus one attack test |
| Mirror mate | A | implemented |
| Model mate | A | implemented |
| Pendulum | A | implemented |
| Phoenix | A | implemented |
| Promotion | A | implemented |
| Schnoebelen theme | A | implemented |
| Self-block | A | implemented |
| Set play | A | implemented; needs: plane (answers on saturated positions without enumerating solutions) |
| Switchback | A | implemented |
| Umnov mate | A | implemented as `umnov-mate` |
| Umnov move | A | implemented as `umnov` |
| Zajic theme | A | implemented |
| Zilahi | B | implemented as `zilahi`, the two-solution form; units identified by diagram square, the mover of the mating ply is the mating unit; cyclic and double Zilahi remain in B1 |

## A1 -- Diagram only -- no solutions needed  (5)

Readable from the starting position alone. Note corrected 2026-08: this does *not* run at "scan speed" -- evaluating a diagram theme still requires materialising the position (decode + `Board::from_pieces`), so the floor is decode speed, not scan speed. What it does deliver is answering on saturated positions where every solutions-needing theme today gives up.

| Theme | Tier | Note |
|---|---|---|
| Homebase | A | built and then **removed** 2026-08: the tablebase index quotients positions by a symmetry group (see `src/core/indexing/kk.cpp`), and Homebase is not invariant under it -- a cell stores an equivalence class, not a position, so the answer would depend on which mirror representative was decoded. A `Needs::Position` theme must be invariant under the index's symmetry group, or it cannot be mined at all; Homebase is the only one of the four in this group known to fail that test |
| Kindergarten problem | A | material of the diagram |
| Obtrusive piece | A | static reading of the diagram's pawn structure |
| Promoted force | A | static reading of the diagram |
| Skittles | A | the diagram alone |

## A2 -- Mating position only  (4)

Needs one solution, but only its last ply and final board -- not the whole set.

| Theme | Tier | Note |
|---|---|---|
| Blocking piece replacement | A | diagram against mating board on one flight square |
| Home-coming | A | mating board against the game-array squares |
| Mating piece | A | the last ply's mover; battery cases are genuinely ambiguous | Y |
| Mating square | A | the last ply's destination, or the mated king's square | Y |

## A3 -- The other side-to-move plane (set play)  (2)

One O(1) table lookup. Cheap here precisely because both side-to-move planes are stored, and awkward for an analyser that has to search.

| Theme | Tier | Note |
|---|---|---|
| Apparent mate | A | the other plane of the diagram mates in one |
| Short set play | A | the other plane, at a shorter distance |

## A4 -- Within one solution -- plies, captures, promotions  (36)

Exactly the pattern of the eight ply-detectors already shipped. No new machinery of any kind.

| Theme | Tier | Note |
|---|---|---|
| 100 Dollar theme | A | white and black excelsior with knight promotions, all inside one solution |
| Active sacrifice | A | a unit moves to a square where a later ply captures it |
| Amazon theme | A | every white ply moved by the queen |
| Annihilation | A | capture then vacate; the "positive effect" qualifier stays approximate |
| Artificial castling | A | ordinary moves onto the post-castling squares; no castling rights involved |
| Balbo theme | A | piece types of the movers, ply by ply |
| Bukovina theme | A | attack count on a flight, its capture, a later self-block there |
| Closed chain of Umnov | A | every ply lands on a just-vacated square |
| Consecutive checks | A | the is_check flag |
| Consecutive Umnov | A | from/to chain |
| Crosscheck | A | check answered by a non-capturing check |
| Crusader theme | A | every white ply by one knight |
| Cycle of captures | A | capture chain inside one solution |
| Delayed Umnov | A | square history inside one solution |
| Distant self-block | A | self-block plus the king field of the square the king reaches |
| Durbar theme | A | every white ply by the king |
| Feather 2 theme | A | sacrifice in the king field, pawn capture, self-block |
| Feather theme | A | move paths crossing the initial black king square |
| Festina lente | A | two single steps from a pawn's home square |
| FML | A | repeated arrival on the square one enemy unit just left |
| Helsinki theme | A | sacrifice then two vacations, all inside one solution |
| Hyvinkaa theme | A | every ply of one solution lands on one square |
| Kozhakin theme | A | first and last white ply on the same square |
| Meerane theme | A | first and last ply compared inside one solution |
| Mihajloski theme | A | collinear order swapped twice inside one solution |
| Mixed Phoenix | A | capture on a promotion square, then a like promotion |
| Monkey theme | A | the two sides' move sequences compared |
| Nissl theme | A | sacrifice, then promotion to the same type |
| Oudot task | A | three black queen promotions in one solution; the table could settle it for reachable material |
| Pawn-Zajic | A | Zajic with a pawn as the capturing unit |
| Slow Excelsior | A | excelsior that opens with a single step |
| Square-clearance by capture | A | capture, vacate, enemy unit follows onto the square |
| Super Durbar | A | both sides move only their kings |
| Unblocking sacrifice | A | capture, vacate, enemy unit captures on the square |
| White Kniest theme | A | capture on the square the white king later occupies |
| White Zajic theme | A | from/to and captures beside the white king |

## A5 -- Within one solution -- trajectory shape  (9)

Shape predicates over one unit's path. `themes::trajectories()` already exists and already chains plies per unit.

| Theme | Tier | Note |
|---|---|---|
| Areal cycle | A | one unit's trajectory |
| Corner-to-corner | A | one from/to, or one unit's trajectory |
| Cyclic place exchange | A | trajectory endpoints inside one solution |
| Linear cycle | A | one unit's trajectory |
| Long-trip | A | one officer moving three or more times |
| Place exchange | A | trajectory endpoints inside one solution |
| Staircase | A | trajectory shape |
| Wigwag | A | a slider recrossing its own start square along one line |
| Zigzag | A | trajectory shape |

## A6 -- Set operations the catalogue tiered as A  (2)

Genuinely need the whole solution set despite the tier, so they arrive with the B1 signature rather than before it.

| Theme | Tier | Note |
|---|---|---|
| Asymmetry | A | axis symmetry of the diagram, then a mirror test per solution |
| Mates on same square | A | group solutions by the last ply's destination |

## A7 -- Not a theme  (1)

Kept so the arithmetic reconciles.

| Theme | Tier | Note |
|---|---|---|
| Helpmate | A | the stipulation itself, not a theme |

## B1 -- Across the solution set -- the tier-B unlock  (58)

**All of these come from one change**: a detector signature over `std::vector<Solution>` instead of a single `Solution`. `solutions()` already returns the set. For a helpmate a "phase" is one optimal solution, which is what puts this whole tier within reach.

| Theme | Tier | Note |
|---|---|---|
| Albino | B | union of one white pawn's four home-square moves across phases |
| Anti-Albino | B | union of a white pawn's moves arriving on its fourth rank |
| Anti-Loshinsky theme | B | collinearity plus from/to arithmetic across phases |
| Anti-magnet | B | same, with the distance growing phase by phase |
| Anti-Pickaninny | B | union of a black pawn's moves arriving on its fourth rank |
| Avanta | B | union of two pawns' four non-capturing home-square moves |
| Babson task | B | promotion types and squares matched pawn for pawn across phases |
| Baltic theme | B | shared departure square and shared mating square across phases |
| Big cross | B | union of one unit's destinations |
| Big star | B | union of one unit's destinations |
| Brochettes theme | B | same movers in the same order in every phase |
| Carra theme | B | allumwandlung by a single white pawn across the branches |
| Chameleon echo-mates | B | mating boards compared, plus the colour of the king's square |
| Changed blocks | B | different blockers on one square across phases |
| Changed promotions | B | promotion type per pawn and square across phases |
| Chumakov theme | B | captured in one phase, self-blocking in another |
| Compass theme | B | occupancy of two squares compared across four solutions |
| Cross | B | union of one unit's destinations |
| Cycle of functions | B | cyclic roles, as far as capture / mate / block roles reach |
| Cycle of moves | B | move sequences compared across phases |
| Cycle of pieces | B | movers compared across phases |
| Cycle of promotions | B | promotion types across phases |
| Cycle of squares | B | key squares across phases |
| Cyclic Zilahi | B | captured and mating units across three or more phases |
| Daisy | B | union of a queen's eight destinations |
| Dolginovich theme | B | mover types compared between phases |
| Double Zilahi | B | two independent Zilahi pairs |
| Echo mates | B | mating boards compared up to shift, rotation and mirror |
| Exchange of functions | B | two units of one colour swap roles between phases |
| Exchange of moves | B | the same two moves, reversed, in two phases |
| Exchange of promotions | B | promotion types swapped between phases |
| Extended Albino | B | union of one white pawn's eight moves |
| Extended cross | B | union of one unit's destinations |
| Extended cyclic Zilahi | B | three-phase capture-and-mate cycle |
| Extended Pickaninny | B | union of one black pawn's eight moves |
| Extended star | B | union of one unit's destinations |
| Four corners | B | union of one unit's destinations |
| Knight wheel | B | union of a knight's eight destinations |
| Lacny cycle | B | mate mapped to black move over six phases |
| Loshinsky magnet | B | collinear follow, from/to arithmetic |
| Many-ways | B | same endpoints, different routes, three phases |
| Pickaninny | B | union of one black pawn's four home-square moves |
| Place exchange in final positions | B | mating boards compared |
| Play on same square | B | same move number, same destination, different movers |
| Pseudo Albino | B | a queen's four pawn-like moves across phases |
| Pseudo Pickaninny | B | a queen's four pawn-like moves across phases |
| Reciprocal captures | B | capturer and captured swapped between phases |
| Rope theme | B | mover kinds swapped between phases |
| Rosette | B | union of a king's eight destinations |
| Rovno theme | B | two like units of opposite colour swap squares across phases |
| Sankt Petersburg theme | B | promotion type matched to the type Black offers |
| Shifted Babson task | B | promotions matched cyclically across phases |
| Star | B | union of one unit's destinations |
| Stavrinides theme | B | trajectories of both colours compared between phases |
| String theme | B | move lengths growing along one line across phases |
| White constant | B | white's move sequence held constant across phases |
| Zalokotsky theme | B | three squares revisited in reverse order in another phase |

## B2 -- Set play compared against the solution  (3)

Needs A3's plane lookup *and* the solution set.

| Theme | Tier | Note |
|---|---|---|
| Kniest 1 theme | B | promoting colour in the set-play plane against the solution |
| Larsson theme | B | final boards of set play and solution compared |
| Loewenton theme | B | promotion types swapped between set play and solution |

## C1 -- Extra probing  (20)

Needs positions other than the one asked about: swapped move orders, skipped moves, removed units, mates that must be shown not to work. Each probe is O(1) here, which is why this family is cheap for a tablebase and hard for a searching analyser. Breaks the current rule that a detector never touches the table.

| Theme | Tier | Note |
|---|---|---|
| Bukovinszky theme | C | set play plus two "threatened" mates that only a probe can confirm |
| Bukovinszky-Garai theme | C | same machinery, one mate deeper |
| Check prevention | C | needs the position in which the move was not made |
| Choice of move order | C | probe the swapped order |
| Complete helpmate | C | needs the phases in which one side has no move |
| Dual avoidance | C | probe the mate that does not work |
| Enabling hideaway | C | hideaway needs a removed-unit probe |
| Enabling tempo | C | tempo needs a skipped-move probe |
| Garai theme | C | mates that fail only for want of a black tempo move |
| Hesitation | C | probe the immediate alternative |
| Hidden tempo-try | C | tempo tries |
| Hideaway | C | probe with the unit removed, i.e. another material's table |
| Hideaway maneuver | C | same, spread over two or more moves |
| Lindner 1 theme | C | waiting moves |
| Lindner 2 theme | C | set-play "threats" that only a probe can confirm |
| Mutually exclusive tempo | C | tempo |
| Segenreich theme | C | a mate available a move early, plus a waiting move |
| Stocchi blocks | C | repeated blocks plus dual avoidance |
| Tempo maneuver | C | probe the position with the moves skipped |
| Tempo move | C | probe the position with the move skipped |

## E1 -- Twinning  (4)

Needs a modified diagram -- often a table already generated, but it needs its own vocabulary first.

| Theme | Tier | Note |
|---|---|---|
| Changed motivation | E | a twin whose solution is unchanged |
| Forsberg twins | E | twinning by changing a piece's type |
| Striptease theme | E | successive twins made by removal |
| Zagoruiko theme | E | three twins with changed mates; the solution-group variant is B |

## D1 -- Motif engine -- blocked  (93)

Needs line-piece geometry the project has no notion of: pins, half-pins, interference, batteries, critical squares, clearance, doubling, unpinning. One piece of machinery rather than 96 separate problems, but a large one, and none of it exists.

| Theme | Tier | Note |
|---|---|---|
| Ambush | D | needs the battery / line-opening notion |
| Analogy | D | compares arrival and departure motifs between phases |
| Anti-Bristol | D | line closure toward another piece |
| Anti-critical move | D | critical squares |
| Anti-Levman mate | D | masked guard lines |
| Anticipatory Bristol | D | line clearance |
| Anticipatory half-pin | D | half-pin |
| Anticipatory interference | D | interference |
| Anticipatory pin | D | pin lines |
| Anticipatory self-pin | D | pin lines |
| Anticipatory self-unpin | D | pin lines |
| Anticipatory unpin | D | pin lines |
| AntiZielElement | D | a motif carrying a sign; needs the motif vocabulary |
| Arrival effect | D | the motif vocabulary itself |
| Authier theme | D | unpins on a check line |
| Bajtay theme | D | chained self-pins and unpins |
| Bivalve | D | one move opening one line and closing another |
| Boros theme | D | indirect pin on the mating move |
| Brasil theme | D | anti-critical moves and guard lines |
| Bristol | D | line clearance |
| Brixi theme | D | guards by pinned units |
| Brunner-Loyd clearance | D | clearance |
| Brunner-Turton doubling | D | doubling |
| Brunner-Zepler doubling | D | doubling |
| Cheney-Loyd theme | D | critical move with permanent interception |
| Chernous theme | D | self-pin by interference, then unpin |
| Consecutive Bristol | D | chained clearance |
| Critical move | D | critical squares |
| Cycle of double pins | D | pins in the mating positions |
| Cycle of unpins | D | unpins |
| Departure effect | D | the motif vocabulary itself |
| Epaulette interferences | D | interference |
| Feather mechanism | D | two white lines crossing the black queen's square |
| Gamage theme | D | direct unpin of a pinned black piece |
| Gate-opening | D | vacating a line so a slider can cross it |
| Goethart theme | D | indirect unpin, battery mate |
| Grimshaw | D | mutual interference |
| Guidelli theme | D | unpin under check |
| Half-pin | D | half-pin |
| Helledie theme | D | needs the motive of a move, not just the move |
| Herlin | D | peri-critical move |
| Holzhausen interference | D | interference |
| HOTF | D | needs motifs grouped into themes before pairs can be compared |
| Island theme | D | a square's guard lines closed from both ends |
| Kluver 10 theme | D | ambush and gate-opening |
| Kubbel-Grimshaw | D | mutual interference |
| Leibovici interference | D | Pelle move plus interference |
| Loyd's clearance | D | clearance |
| Loyd-Turton doubling | D | doubling |
| Loyd-Zepler doubling | D | doubling |
| Magnet | D | a bicoloured Bristol, so clearance |
| Mutual interference | D | interference |
| Nesic theme | D | mutual interference |
| Organ pipes | D | four Grimshaw pairs |
| Orthogonal-diagonal transformation | D | needs effects classified by line direction |
| Paros theme | D | paired bivalves |
| Pelle move | D | pin line |
| Peri-critical move | D | critical square |
| Pickabish | D | mutual interference |
| Pin restoration theme | D | pins |
| Pin-mate | D | pins in the mating position |
| Pin/self-unpin | D | pins |
| Pin/unpin | D | pins |
| Pinning | D | pins |
| Piran theme | D | the same pin exploited in set play and solution |
| Pseudo Bristol | D | clearance |
| Pseudo Rehm theme | D | peri-manoeuvre |
| Pseudo Zilahi | D | needs the battery's rear piece identified as the mater |
| Reciprocal batteries | D | batteries |
| Reciprocal battery transformation | D | batteries |
| Reciprocal Bristol | D | clearance |
| Rehm theme | D | peri-manoeuvre and anti-critical move |
| Roentgen theme | D | pin |
| Sacrificial Bristol | D | clearance |
| Self-pin/self-unpin | D | pins |
| Self-pin/unpin | D | pins |
| Self-unpin/pin | D | pins |
| Self-unpin/self-pin | D | pins |
| Sharp theme | D | a battery built, then abandoned |
| Siers battery | D | battery |
| Somov mate | D | guard lines closed in the mate |
| Step-by-step Bristol | D | clearance |
| Transferred pin | D | pin lines |
| Turton doubling | D | doubling |
| Unpin | D | pins |
| Unpin/pin | D | pins |
| Unpin/self-pin | D | pins |
| Valve | D | one move opening and closing lines of one piece |
| Visserman | D | pins and checks |
| Witztum challenge | D | paired interferences |
| Wurzburg-Plachutta | D | interference between like-moving pieces |
| Zabunov theme | D | a battery's front piece becoming a rear piece |
| Zepler doubling | D | doubling |

## X1 -- Out of scope  (25)

Castling (permanently impossible -- the format rejects castling rights), retro-analysis, or tourney-specified compound patterns.

| Theme | Tier | Note |
|---|---|---|
| Abdurahmanovic 1 theme | X | tourney-specified compound pattern |
| Abdurahmanovic 3 theme | X | tourney-specified compound pattern |
| Abdurahmanovic 4 theme | X | tourney-specified compound pattern |
| Azemmour 10 theme | X | tourney-specified pattern |
| Azemmour 11 theme | X | tourney-specified pattern, though the flight count itself is trivial |
| Azemmour 12 theme | X | tourney-specified pattern |
| Azemmour 6 theme | X | tourney-specified pattern |
| Azemmour 7 theme | X | tourney-specified pattern |
| Azemmour 8 theme | X | tourney-specified pattern |
| Azemmour 9 theme | X | tourney-specified pattern |
| Castling | X | the format has no castling rights |
| Illegal position | X | retro analysis; the project has none and wants none |
| JT Navon 90 theme | X | tourney-specified pattern |
| JT Onkoud 50 theme | X | tourney-specified pattern |
| Onkoud 2 theme | X | composer-specified pattern |
| Onkoud theme | X | composer-specified pattern |
| Onkoud-St German theme | X | composer-specified pattern |
| Sabra 25 theme | X | tourney-specified pattern |
| Sabra 26 theme | X | tourney-specified pattern |
| Sabra 27 theme | X | tourney-specified pattern |
| Sabra 28 theme | X | tourney-specified pattern |
| Sabra 29 theme | X | tourney-specified pattern |
| Uncastling | X | castling |
| Valladao task | X | requires a castling move |
| WCCT-12 theme | X | tourney-specified pattern |

## ALIAS -- Aliases  (11)

Bare cross-references, tiered as their target.

| Theme | Tier | Note |
|---|---|---|
| Anticipatory anti-Bristol | D | alias of Anti-Bristol |
| ASP | D | alias of Anticipatory self-pin |
| AUW | B | alias of Allumwandlung |
| AZE | D | alias of AntiZielElement |
| Helpmate of the future | D | alias of HOTF |
| Iceland theme | D | alias of Island theme |
| Nagnibida theme | A | alias of Bukovina theme |
| Octopus theme | B | alias of Rosette |
| ODT | D | alias of Orthogonal-diagonal transformation |
| Sacrificial clearance | D | alias of Sacrificial Bristol |
| Tempo play | C | alias of tempo move and tempo manoeuvre |

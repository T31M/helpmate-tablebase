#include "themes/registry.h"

#include "themes/line_themes.h"
#include "themes/mate_themes.h"
#include "themes/position_themes.h"
#include "themes/set_themes.h"

namespace hm::themes {

const std::vector<ThemeDef>& theme_registry() {
    static const std::vector<ThemeDef> kRegistry = {
        {"set-play", &has_set_play,
         "Set play: the same position with the other side to move is solvable one move "
         "sooner (sibling dtm == this position's dtm - 1) -- the mate is already "
         "available and the side to move merely delays it. A sibling one move LONGER "
         "is the opposite of set play, not set play.",
         Needs::Plane},
        {"pure", &any_of<&is_pure>,
         "Pure mate: every square of the black king's field is unavailable for "
         "exactly one reason, and the king's square is attacked exactly once "
         "(so double check is impure).",
         Needs::Solutions},
        {"model", &any_of<&is_model>,
         "Model mate: pure, and every white unit except the king and pawns "
         "participates -- attacks the king's square or a field square, or "
         "stands on one.",
         Needs::Solutions},
        {"ideal", &any_of<&is_ideal>,
         "Ideal mate: model with no exemptions -- the white king and white "
         "pawns must participate too, and every black unit other than the king "
         "must stand on a field square.",
         Needs::Solutions},
        {"mirror", &any_of<&is_mirror>,
         "Mirror mate: every square adjacent to the black king is empty, of "
         "either colour.",
         Needs::Solutions},
        {"promotion", &any_of<&has_promotion>, "A pawn promotes during the solution.", Needs::Solutions},
        {"underpromotion", &any_of<&has_underpromotion>, "A pawn promotes to rook, bishop or knight.",
         Needs::Solutions},
        {"excelsior", &any_of<&has_excelsior>,
         "A pawn standing on its own second rank at the start of the solution "
         "promotes during it (either colour).",
         Needs::Solutions},
        {"excelsior:white", &any_of<&has_excelsior_white>, "Excelsior by a white pawn.", Needs::Solutions},
        {"excelsior:black", &any_of<&has_excelsior_black>, "Excelsior by a black pawn.", Needs::Solutions},
        {"switchback", &any_of<&has_switchback>,
         "A unit leaves a square and returns to it, having visited exactly one "
         "intermediate square.",
         Needs::Solutions},
        {"closed-walk", &any_of<&has_closed_walk>,
         "Rundlauf: a unit returns to its departure square having visited two "
         "or more distinct intermediate squares, so it traverses a circuit "
         "rather than retracing its path.",
         Needs::Solutions},
        {"self-block", &any_of<&has_self_block>,
         "A black unit other than the king moves onto a square of its own "
         "king's field and stands there unattacked in the mating position, "
         "blocking a flight square.",
         Needs::Solutions},
        {"single-piece", &any_of<&is_single_piece>,
         "Every move by one side is made by the same unit (either side).", Needs::Solutions},
        {"single-piece:white", &any_of<&is_single_piece_white>, "Every white move is made by the same unit.",
         Needs::Solutions},
        {"single-piece:black", &any_of<&is_single_piece_black>,
         "Every black move is made by the same unit; with the king, this is "
         "the Analyzer's 'BK moves only'.",
         Needs::Solutions},
        {"en-passant", &any_of<&has_en_passant>, "A ply is an en-passant capture.", Needs::Solutions},
        {"kniest", &any_of<&has_kniest>,
         "Kniest: a unit is captured on the square where the black king is later "
         "mated.",
         Needs::Solutions},
        {"zajic", &any_of<&has_zajic>,
         "Zajic: a unit is captured on the square where the black king is mated, "
         "and the king recaptures there.",
         Needs::Solutions},
        {"phoenix", &any_of<&has_phoenix>,
         "Phoenix: a unit is captured and a pawn of the same colour later promotes "
         "to that same type.",
         Needs::Solutions},
        {"schnoebelen", &any_of<&has_schnoebelen>,
         "Schnoebelen: a promoted unit is captured on its promotion square without "
         "ever having moved.",
         Needs::Solutions},
        {"pendulum", &any_of<&has_pendulum>,
         "Pendulum: a unit oscillates between exactly two squares, returning at "
         "least twice.",
         Needs::Solutions},
        // The two entries below use all_of<>, not any_of<>: they hold only
        // when EVERY optimal solution qualifies. A negative theme ("no
        // capture") with `any` semantics would match a position as soon as
        // one of its solutions happened to be quiet, which is not what a
        // composer means by a capture-free problem.
        {"nocapture", &all_of<&is_capture_free>,
         "No capture: no unit is captured in any optimal solution (en passant "
         "included). Holds only when EVERY solution is capture-free, unlike the "
         "themes above, which match when any one solution shows them.",
         Needs::Solutions},
        {"nocheck", &all_of<&is_check_free>,
         "No check: no move gives check in any optimal solution except the last "
         "move of each solution, the mate itself. Holds only when EVERY solution "
         "is check-free before its final move, unlike the themes above, which "
         "match when any one solution shows them.",
         Needs::Solutions},
        {"umnov", &any_of<&has_umnov>,
         "Umnov: a unit moves onto the square the opponent's immediately preceding "
         "move vacated.",
         Needs::Solutions},
        {"umnov-mate", &any_of<&has_umnov_mate>,
         "Umnov mate: the mating move lands on the square Black's last move vacated.", Needs::Solutions},
        {"klasinc", &any_of<&has_klasinc>,
         "Klasinc: a unit leaves square a, a line piece (queen, rook or bishop, "
         "either colour) later moves along a line that passes over a, and after "
         "that the first unit returns to a.",
         Needs::Solutions},
        // Set-wide: these compare solutions with each other, so they are plain
        // functions on the whole set, like set-play, not any_of/all_of.
        {"zilahi", &has_zilahi,
         "Zilahi: two solutions and two white units X and Y such that X gives mate "
         "in one solution and is captured in the other, while Y gives mate in the "
         "second and is captured in the first. Units are identified by their "
         "diagram square; a promoted pawn keeps its identity; in a battery mate "
         "the unit that moved is the mating unit. On a saturated position only "
         "the first 100 solutions are compared.",
         Needs::Solutions},
        {"allumwandlung", &has_allumwandlung,
         "Allumwandlung (AUW): across the position's optimal solutions, pawns "
         "promote to all four types -- queen, rook, bishop and knight -- either "
         "colour, in any number of solutions. The same question as "
         "promotions:qrbn.",
         Needs::Solutions},
        {"promotions", nullptr,
         "Promotions: taking the promotions of all optimal solutions together, "
         "at least these types occur, with multiplicity, either colour -- "
         "promotions:qrr needs one queen and two rooks among them (q and r in one "
         "solution and r in another, or all three in one), and further "
         "promotions may occur. Letters q r b n in any order; a multiset, not a "
         "sequence. probe prints the position's full combined multiset as one "
         "promotions:<types> entry. On a saturated position only the first 100 "
         "solutions are counted.",
         Needs::Solutions, &kPromotionsParam},
        {"indian", &any_of<&has_indian>,
         "Indian: a line piece crosses a critical square, a unit of its own colour "
         "then interferes on that square, and later that unit moves away giving "
         "discovered check from the line piece along the line through the square. "
         "Either colour.",
         Needs::Solutions},
        {"maslar", &any_of<&has_maslar>,
         "Maslar: a white line piece plays a critical move along the thematic "
         "line, a black unit interferes on the crossed square, the black king then "
         "arrives on the line beyond it, and the white piece captures the "
         "interfering unit giving check (or mate).",
         Needs::Solutions},
        {"maslar:black-white", &any_of<&has_maslar_black_white>,
         "Black-White Maslar: Black makes the critical move with a line piece, "
         "White interferes on the crossed square, and the black line piece "
         "finally captures the interfering white unit.",
         Needs::Solutions},
    };
    return kRegistry;
}

std::string display_name(const ThemeDef& t) {
    if (!t.param) return std::string(t.name);
    return std::string(t.name) + ":<" + std::string(t.param->name) + ">";
}

bool ResolvedTheme::eval(const ThemeInput& in) const {
    return def->param ? def->param->eval(in, value) : def->fn(in);
}

std::string ResolvedTheme::name() const {
    return def->param ? std::string(def->name) + ":" + value : std::string(def->name);
}

std::optional<ResolvedTheme> resolve_theme(std::string_view name, std::string* error) {
    auto fail = [&](std::string msg) {
        if (error) *error = std::move(msg);
        return std::optional<ResolvedTheme>{};
    };
    if (const ThemeDef* t = find_theme(name)) {
        if (!t->param) return ResolvedTheme{t, ""};
        return fail("theme \"" + std::string(name) + "\" needs a value, e.g. " + std::string(t->name) + ":" +
                    std::string(t->param->example));
    }
    const size_t colon = name.find(':');
    if (colon == std::string_view::npos) return fail("unknown theme \"" + std::string(name) + "\"");
    const std::string_view base = name.substr(0, colon), raw = name.substr(colon + 1);
    const ThemeDef* t = find_theme(base);
    if (!t || !t->param) {
        // The singular typo must never fall through to the boolean `promotion`
        // with its value discarded -- the --end/--ends lesson.
        for (const auto& cand : theme_registry())
            if (cand.param && cand.name.size() == base.size() + 1 && cand.name.substr(0, base.size()) == base)
                return fail("unknown theme \"" + std::string(name) + "\"; did you mean " +
                            std::string(cand.name) + ":" + std::string(raw) + "?");
        return fail("unknown theme \"" + std::string(name) + "\"");
    }
    auto canon = t->param->canon(raw);
    if (!canon)
        return fail("theme " + std::string(t->name) + " does not accept the value \"" + std::string(raw) +
                    "\" (" + std::string(t->param->name) + ": " + std::string(t->param->doc) + ")");
    return ResolvedTheme{t, *canon};
}

const ThemeDef* find_theme(std::string_view name) {
    for (const auto& t : theme_registry())
        if (t.name == name) return &t;
    return nullptr;
}

std::vector<std::string> detect(const ThemeInput& in) {
    std::vector<std::string> out;
    for (const auto& t : theme_registry()) {
        if (t.param) {
            for (const auto& v : t.param->values(in)) out.push_back(std::string(t.name) + ":" + v);
        } else if (t.fn(in)) {
            out.emplace_back(t.name);
        }
    }
    return out;
}

}  // namespace hm::themes

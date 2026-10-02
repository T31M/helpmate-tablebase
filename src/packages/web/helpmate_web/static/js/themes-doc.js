// The motif documentation screen: what each motif the tablebase's theme
// detector knows means, and what it needs to answer.
//
// Rendered straight from /v1/themes -- never a hardcoded list -- so this
// screen cannot drift from the binary it is talking to. That endpoint is
// the core registry serialised verbatim (see helpmate_server/app.py's
// /v1/themes handler and pymodule.cpp's `themes()` binding): every entry
// carries {name, doc, needs}.
import { api, ApiError } from "./api.js";
import { el } from "./stats-view.js";
import { whenPanelShown } from "./panels.js";

// Fixed groups, each introduced by a sentence before its members. Read off
// every theme's own `doc` string in the live registry (src/core/themes/
// registry.cpp) rather than assumed from memory -- the first version of
// this table named 11 of the build's then 22 registered motifs and left the
// other 11 to fall into "other" wholesale. All 33 group cleanly into the
// five below; nothing should land in "other" on a build that still matches
// this registry.
//
// A name the API returns that is not listed in any group here still falls
// into the trailing "other" group instead of being dropped -- see
// renderThemes() below, which never special-cases an unrecognised name,
// only ones it recognises. That is what lets a future motif appear on this
// screen with no edit to this file, and it is exactly the behaviour that
// caught this table's own first-draft gap.
const GROUPS = [
  {
    title: "The mate picture",
    intro: "What the mating position itself looks like, judged by the "
         + "black king's field.",
    members: ["pure", "model", "ideal", "mirror", "self-block", "indian", "maslar"],
  },
  {
    title: "How a unit travels",
    intro: "What path an individual piece traces through the solution, "
         + "not just where it starts and ends.",
    members: ["switchback", "closed-walk", "pendulum", "excelsior", "umnov", "klasinc"],
  },
  {
    title: "Pawns and promotion",
    intro: "What a pawn does on its way to becoming something else, and "
         + "what becomes of whatever it captures or replaces along the way.",
    members: ["promotion", "underpromotion", "promotions:<types>", "allumwandlung", "phoenix",
              "schnoebelen", "en-passant"],
  },
  {
    title: "Where the mate happens",
    intro: "What happened earlier at the exact square the king is finally "
         + "mated on.",
    members: ["kniest", "zajic", "umnov-mate"],
  },
  {
    title: "The structure of the solution",
    intro: "What shape the position or its solution set has, independent "
         + "of the mate picture or the moves that reach it. nocapture and "
         + "nocheck are set-wide: they hold only when EVERY solution "
         + "qualifies, where the other motifs need just one.",
    members: ["set-play", "single-piece", "nocapture", "nocheck", "zilahi"],
  },
];

const OTHER_TITLE = "Other";
const OTHER_INTRO = "Motifs this build detects that do not belong to one of "
  + "the groups above.";

// A one-line explanation of what a `needs` value means for a saturated
// position -- the stored solution count caps at 255, and only a
// Needs::Solutions detector (needs === "solutions") is silently skipped on
// one, because it has to walk the full solution set to answer.
function needsExplanation(needs) {
  if (needs === "solutions")
    return "reads the full solution set, so it is silently skipped on a "
         + "position whose stored solution count has saturated at 255.";
  if (needs === "plane")
    return "reads only the mating position's geometry (the king's field), "
         + "so it still answers even when the solution count has saturated "
         + "at 255.";
  if (needs === "position")
    return "reads the position alone, so it still answers even when the "
         + "solution count has saturated at 255.";
  // Defensive: a `needs` value this screen does not recognise still gets an
  // entry, just without a caveat this file cannot honestly write.
  return "";
}

// One motif's entry: name, definition, and what it needs to answer, with
// any colour-labelled variants (e.g. excelsior:white) nested inside rather
// than listed as their own top-level entries.
function renderEntry(theme, variants) {
  const entry = el("article", "theme-entry");
  entry.dataset.theme = theme.name;
  entry.appendChild(el("h3", null, theme.name));
  entry.appendChild(el("p", "theme-def", theme.doc));
  const expl = needsExplanation(theme.needs);
  entry.appendChild(el("p", "theme-needs",
    expl ? `needs: ${theme.needs} — ${expl}` : `needs: ${theme.needs}`));
  // A parametric motif says what goes after the colon, e.g. promotions:qrr.
  if (theme.parameter) {
    const base = theme.name.slice(0, theme.name.indexOf(":"));
    entry.appendChild(el("p", "theme-param",
      `parameter ${theme.parameter.name} (e.g. ${base}:${theme.parameter.example}): ${theme.parameter.doc}`));
  }
  if (variants && variants.length) {
    const box = el("div", "theme-variants");
    for (const v of variants) box.appendChild(renderEntry(v));
    entry.appendChild(box);
  }
  return entry;
}

// Splits the API's flat theme list into the fixed groups plus "other", with
// colour variants (a name containing ":") attached to their base motif's
// entry when that base is itself present, and rendered where the API put
// them (i.e. under "other" too) when it is not.
function renderThemes(container, themes) {
  const byName = new Map(themes.map((t) => [t.name, t]));
  const placed = new Set();

  const variantsOf = (baseName) => themes.filter((t) => {
    const i = t.name.indexOf(":");
    return i !== -1 && t.name.slice(0, i) === baseName && byName.has(baseName);
  });

  const renderGroup = (title, intro, memberNames) => {
    const names = memberNames.filter((n) => byName.has(n) && !placed.has(n));
    if (!names.length) return;
    const section = el("section", "theme-group");
    section.appendChild(el("h2", null, title));
    section.appendChild(el("p", "theme-group-intro", intro));
    for (const name of names) {
      // Re-checked INSIDE the loop, not only in the filter above. `names` is
      // a snapshot, and a name later in it can be placed by a name earlier
      // in it -- which is precisely what happens in the "other" group, whose
      // member list is the API's own leftovers and therefore contains bases
      // AND their colour variants. `pin` nests pin:white and pin:black under
      // itself and marks them placed; without this check the snapshot then
      // rendered both again as top-level entries. Harmless for GROUPS, whose
      // member lists are hand-written and hold no variants; broken for the
      // one case the fallback exists for.
      if (placed.has(name)) continue;
      const variants = variantsOf(name);
      section.appendChild(renderEntry(byName.get(name), variants));
      placed.add(name);
      for (const v of variants) placed.add(v.name);
    }
    container.appendChild(section);
  };

  for (const g of GROUPS) renderGroup(g.title, g.intro, g.members);

  // Everything left over, in the order the API returned it: unknown base
  // motifs, and any colour variant whose base was not itself in the API (so
  // it was never attached to anything above).
  const leftover = themes.filter((t) => !placed.has(t.name)).map((t) => t.name);
  renderGroup(OTHER_TITLE, OTHER_INTRO, leftover);
}

// Deferred to the themes panel's first activation, like the explorer's and
// the puzzle screen's own first paint: /v1/themes is already fetched at page
// load by mine.js, to fill the search screen's theme picker, and fetching it
// a second time for a panel nobody has opened doubled that request for
// nothing. See panels.js's whenPanelShown.
export function initThemesDoc() {
  whenPanelShown("themes", () => { loadThemesDoc(); });
}

async function loadThemesDoc() {
  const box = document.getElementById("themes-doc");
  box.textContent = "";
  box.appendChild(el("p", "help", "Loading motifs…"));

  let body;
  try {
    ({ body } = await api.themes());
  } catch (err) {
    // A failed fetch degrades to a message on this screen. NOT because a
    // throw would take the other screens down: index.html's init*() calls
    // are async functions, so one rejecting cannot stop a sibling. The
    // reason is narrower and this screen's own -- an unhandled rejection
    // would leave "Loading motifs…" on screen permanently, with nothing
    // saying why, and __themesDocReady never set.
    box.textContent = "";
    box.appendChild(el("p", "empty",
      err instanceof ApiError
        ? (err.hint ? `${err.message} — ${err.hint}` : err.message)
        : "Could not load the motif list."));
    window.__themesDocReady = true;
    return;
  }

  box.textContent = "";
  box.appendChild(el("p", "help",
    "Every motif this build's tablebase detects, straight from /v1/themes "
  + "-- the same registry the binary itself uses, so nothing here can name "
  + "a motif the build does not actually know."));
  renderThemes(box, body.themes);
  window.__themesDocReady = true;
}

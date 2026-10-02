# Materials and contributors on the site — design

Date: 2026-10-01. Status: implemented. Builds on
`2026-09-30-contribution-pipeline-design.md` (PR #47, same branch).

## Why

`docs/MATERIALS.md` lists all 1000 materials with state and contributor, but
it lives in the repository, it is a long static page, and its state is only as
fresh as the last `sync`. The showcase at
https://osick.github.io/helpmate-tablebase/ already has a Materials page — for
the 302 tables it was last built from (the corpus has 317). The user wants one
place: the site.

## Agreed decisions (user, 2026-10-01)

- `docs/MATERIALS.md` is removed; its content moves to the site's Materials
  page. Links point to `https://osick.github.io/helpmate-tablebase/#/materials`.
- The Materials page is **one long list** of every material, extended by
  **state** and **contributor**, **filterable**, with no separate checklists.
- Every material gets a **priority**: fewer White pieces → typically longer,
  deeper helpmates → higher priority. Six pieces: `K*vk***` first, then
  `K**vk**`, `K***vk*`, `K****vk`.
- The front page (`#/`) gets a **contributor section**.
- State freshness: **daily, built at deploy**. The Pages workflow builds the
  state file at deploy time (daily schedule + on demand); nothing is committed
  for it and the browser calls no third party.

## Terms

- **Priority** of a material = the number of White non-king pieces (1–4), shown
  as P1–P4. `Kvk…` (bare White king) has no priority: no helpmate can exist,
  state "not needed". The same rule applies to 3–5 pieces (all done).
- **State**: done / in review / claimed / open / not needed, derived exactly as
  `claims.material_status` does today.

## Components

### 1. `site/data/materials.json` (committed)

All 1000 universe materials, plus any table present in the corpus outside the
universe (`Kvk`), one row each:
`material, pieces, pawns, ram_gib, priority (1–4 | null), done (bool),
page (bool: a material page exists), max_dtm, solvable, unique, size_bytes`
(the last four null when not done). Row construction and the corpus summary
move into the package (`helpmate_server/contrib/site_data.py`) so that
`helpmate-tables sync` writes `materials.json` and `corpus.json`, and
`tools/build_site_data.py` reuses the same functions for its full build.
`corpus.json` keeps its current shape, computed over done rows only.

### 2. `site/data/status.json` (built at deploy, never committed)

`helpmate-tables site-status --out FILE` writes
`{generated_at, materials: {name: {state, contributor, hf_pr, claim}},
contributors: [{display, hf, github, anonymous, tables, materials}],
counts: {state: n}}` for every material whose state is not `open`. Inputs: HF
manifest and open PRs, GitHub claim issues, `data/contributions.json`.
Anonymous contributors (registry flag or claim-form box) appear as
"anonymous" with no profile links.

### 3. Pages workflow

`pages.yml` gains `schedule` (daily) next to `push` and `workflow_dispatch`,
`issues: read` permission, and a step before `make test-site`: install
`huggingface_hub`, run `site-status` from the checkout (no C++ build). The step
is `continue-on-error`: without `status.json` the site still deploys.

### 4. Materials page (`#/materials`)

- Columns: material (linked when a page exists), men, priority, state,
  contributor, RAM, longest mate, positions with a helpmate, with a unique
  one, table size.
- Filters: men, state, priority, pawns, contributor, and a name search that
  accepts `?` wildcards (`KQvk???`). Filters live in the hash
  (`#/materials?state=open&prio=1`) so a view can be linked; the router splits
  `?` off before choosing the screen.
- Default order: open first, then priority, then pawns ascending, then name.
  Every column header still sorts.
- Header: "state as of <time> UTC" and counts per state; if `status.json` is
  missing: "state unavailable — showing done from the last build".
- Pure logic (priority, wildcard match, merge, filter, sort, hash query) lives
  in `site/js/lib/materials.js` with node tests.

### 5. Front page contributor section

A "Contributors" block on `#/`: one card per contributor (display name, HF and
GitHub links unless anonymous, number of tables, link to the Materials page
filtered by that contributor), six-piece progress (done / in review / claimed /
open of 645), a link to the open P1 materials and a "Claim a material" button
(the GitHub issue form). Without `status.json` the block shows the six-piece
done count only. `status.json` is fetched as an optional file: a 404 is not an
error.

### 6. Removing `docs/MATERIALS.md`

`sync` stops writing it and writes the two site files instead; `accept`'s list
of generated paths swaps `docs/MATERIALS.md` for `site/data/materials.json` and
`site/data/corpus.json`. The claim form, CONTRIBUTING-TABLES, CHANGELOG entry,
`accept`/`sync` messages and the bot's texts link to the site page.

## Error handling

- `site-status` failure in CI → no `status.json` → fallback rendering (above).
- A malformed `status.json` is treated like a missing one (logged to console).
- Unknown hash parameters are ignored.

## Testing

- Python: `site_data` rows (1000 + Kvk, priorities, done stats equal the old
  `material_row`), corpus summary unchanged for the same input; `site-status`
  against fakes (states, anonymous, counts); `sync` writes the site files and
  no `docs/MATERIALS.md`.
- Node: priority, wildcard match, merge/fallback, filters, default order, hash
  query round trip.
- Playwright (headless Chromium, `--no-sandbox`): Materials page and front page
  at 1280 px and 390 px, with and without `status.json`; filter by state and
  contributor; no horizontal scroll at 390 px.

## Out of scope

- Live (in-browser) state; per-material pages for tables that have no
  `site/data/material/<M>.json` yet (that needs the existing 80-minute
  `build_problems` run, which stays manual).

# Corpus statistics: Parquet on Hugging Face and a Statistics screen on the site

Status: draft for review, 2026-10-03. Backlog origin: "Access and reach" ideas in `docs/ROADMAP.md`.

## Goal

1. **Parquet on Hugging Face.** All per-table statistics in two Parquet files in the dataset, shown
   in the Hugging Face dataset viewer and readable with one `pd.read_parquet("hf://…")`.
2. **Statistics screen on the site.** Charts of the DTM distribution and the share of unique
   positions, for the whole corpus and for any single material (decision B: overview plus a
   material picker; no charts embedded in the material pages).
3. **Always current.** Both are rebuilt by every `helpmate-tables accept` without an extra step.
   A manual command exists for catching up and for the first upload.

## Source of truth

The `.stats.json` sidecars next to the tables (419 today, 17 MB). They already hold everything:
`material`, `plane_size`, `max_dtm`, `generator_version`, `cells.invalid/unsolvable` per side to
move, `dtm_histogram` per side, and `uniqueness[stm][dtm][count] = cells` (the joint DTM ×
solution-count histogram, counts saturating at 255). Contributor attribution comes from
`data/contributions.json` (tables without an entry are the maintainer's). Nothing new is
computed from the tables themselves.

## Components

### 1. `helpmate_server/contrib/corpus_stats.py` (new)

Pure functions over a tables directory, no Hugging Face or GitHub access:

- `collect(tables: Path, registry: Registry) -> CorpusStats` — reads every `*.stats.json` whose
  `.hm` exists (the same rule as `site_data.material_rows`), sorted by (pieces, name).
- `materials_rows(cs) -> list[dict]` — one row per table:

  | column | type | notes |
  |---|---|---|
  | material | string | canonical name |
  | pieces, pawns | int8 | |
  | white, black | string | pieces besides the kings, e.g. `RB`, `qp` (empty for a bare king) |
  | marker | bool | marker table (provably no helpmate) |
  | max_dtm | int16, null for markers | |
  | plane_size | int64 | cells per side to move |
  | invalid_wtm, invalid_btm, unsolvable_wtm, unsolvable_btm | int64 | |
  | solvable, unique | int64 | both sides, as on the Materials page |
  | size_bytes | int64 | compressed `.hm` size |
  | generator_version | string | |
  | contributor | string | display name from the registry, `maintainer` otherwise |
  | hf_pr | int32, null | dataset PR that delivered it |
  | merged | date32, null | |

- `histogram_rows(cs) -> list[dict]` — lossless long form of `uniqueness`: one row per
  material × stm × dtm × count with `material` (string), `pieces` (int8), `stm` (`"wtm"`/`"btm"`),
  `dtm` (int16), `count` (int16, 255 = "255 or more"), `cells` (int64). Markers have no rows.
  About 760,000 rows today.
- `write_parquet(cs, out_dir) -> dict[str, bytes]` — `stats/materials.parquet` and
  `stats/histogram.parquet`, zstd-compressed, rows sorted, schema fixed as above. pyarrow is
  imported inside the function, so `helpmate-tables` stays importable without it.
- `site_stats(cs) -> dict` — the compact JSON for the site (below).

### 2. Site data: `site/data/stats.json`

Written by `site_data.write_site_data` next to `materials.json` and `corpus.json`, so every
existing caller produces it: `helpmate-tables sync`, `accept`'s docs step and
`tools/build_site_data.py`. Committed like the other site data (Pages has no tables). Shape:

```json
{"materials": {"KRvkrb": {"pieces": 5, "max_dtm": 14,
                          "wtm": [[dtm, cells, unique], ...], "btm": [[dtm, cells, unique], ...]}},
 "total":     {"wtm": [[dtm, cells, unique], ...], "btm": [...]},
 "by_pieces": {"3": {"solvable": n, "unique": n, "tables": n}, ...}}
```

`unique` = cells with count 1. Markers appear with empty arrays. Estimated ≤ 400 KB; a test bounds it
at 1 MB.

### 3. Statistics screen `#/stats` and `#/stats/<material>`

- `site/index.html`: a nav entry "Statistics" and `<section id="screen-stats">`.
- `site/js/stats.js`: a screen module like the others (`data: ["stats"]`, `init`, `show(arg)`).
- `site/js/lib/charts.js`: pure functions returning SVG strings (bar chart with optional stacked
  segment, linear/log y axis, axis labels, accessible `<title>` per bar). No chart library; colours
  come from the existing CSS variables, so dark mode works.
- Content:
  1. **DTM distribution, whole corpus:** cells per depth, unique cells as a highlighted segment;
     switch Black to move / White to move; linear/log switch (the counts span six orders of magnitude).
  2. **Unique share by piece count:** bars of `unique / solvable` for 3, 4, 5, 6 pieces.
  3. **Materials per maximum DTM:** how many tables have max DTM = d, filterable by piece count;
     below it the ten deepest materials, linking to their material pages.
  4. **One material:** a picker (text input with a datalist of done materials); for the chosen
     material its DTM distribution with the unique segment, and the unique share per depth. The URL
     follows the choice (`#/stats/KRvkrb`). Markers show "no helpmate in this material".
- `site/js/materials.js`: each done row gets a small "stats" link to `#/stats/<material>`.

### 4. Hugging Face

- Files `stats/materials.parquet` and `stats/histogram.parquet` in the dataset repo.
- `docs/hf-dataset-card.md` front matter: `viewer: false` is replaced by

  ```yaml
  configs:
    - config_name: materials
      data_files: stats/materials.parquet
      default: true
    - config_name: histogram
      data_files: stats/histogram.parquet
  ```

  so the viewer shows only the two Parquet files and never tries the `.hm` tables. The card gets a
  "Statistics" section: the two files, their columns, and a pandas example.
- **`accept`, card step:** the same commit that uploads the card now also carries the two Parquet
  files, built from `--tables` after the local step. The commit message becomes
  "Dataset card and statistics".
- **`helpmate-tables stats-push --tables DIR [--dry-run]`** (new): builds the Parquet files,
  checks completeness (below), compares their *content* with the files on Hugging Face (pyarrow
  table equality, not bytes, since bytes differ between pyarrow versions), and uploads them
  together with main's card only if something changed. `--dry-run` prints the row counts and
  what would change. Used once after merge for the first upload, and to catch up by hand.

### Completeness rule

Statistics must never describe a partial corpus. Both paths compare the set of local
`*.stats.json` (with `.hm`) against the dataset manifest's `.hm` files:

- `stats-push` refuses with a list of the missing and extra materials.
- `accept` skips only the statistics in the card step with a clear message ("statistics not
  uploaded: N tables missing locally; run helpmate-tables stats-push after syncing") and still
  uploads the card. The accept itself never fails because of statistics.

`site/data/stats.json` follows the same local rule as `materials.json` today (it is built from
whatever `--tables` holds); `sync` already prints when local tables are missing.

## Freshness guarantee: every delivery updates both, and staleness is caught

Requirement: after every PR that adds tables, the statistics on GitHub (site) and on Hugging
Face (Parquet) describe the new corpus. Every table delivery goes through `accept`, which updates
both (docs step: `stats.json`; card step: Parquet). Two guards make a missed update visible
instead of silent:

- **GitHub, at PR time (blocking).** A repo test (`tests/repo/test_site_stats_fresh.py`, runs in
  CI on every PR) requires `site/data/stats.json` to cover exactly the done materials of
  `site/data/materials.json`, with the same `max_dtm`, `solvable` and `unique` per material. A docs
  PR that updates the materials list but not the statistics cannot be merged.
- **Hugging Face, after merge (alerting).**
  - `accept` checks after the card step that the uploaded `materials.parquet` lists exactly the
    manifest's tables and prints the result. On a mismatch it fails the step, so a rerun
    resumes there.
  - A scheduled workflow (`.github/workflows/stats-check.yml`, daily and after each Pages run) reads
    the public manifest and `stats/materials.parquet` without a token. It fails, which notifies the
    maintainer, when they differ, naming the missing materials and the fix
    (`helpmate-tables stats-push --tables ~/tb`). The same check is available locally as
    `helpmate-tables stats-push --check`.

## Dependencies

pyarrow (≥ 14) is added to the optional `verify` extra of `helpmate-api`, which `accept` and the
CI tests already install. No new browser dependencies.

## Testing

- **Python** (`src/packages/api/tests/test_contrib_corpus_stats.py`): fixture sidecars (a real
  table, a marker, a pawn table) → exact `materials_rows` / `histogram_rows`; Parquet round trip
  with the fixed schema; `site_stats` shape and the 1 MB bound against the committed corpus data;
  contributor lookup with and without registry entry.
- **`stats-push`:** fake hub — refuses on incomplete corpus, uploads when content differs, uploads
  nothing when equal, `--dry-run` uploads nothing.
- **`accept`:** the card commit contains README plus both Parquet files; an incomplete local corpus
  skips the statistics with the message and still uploads the card.
- **Card:** front matter parses, has both configs, no `viewer: false`.
- **Freshness:** the repo test fails when `stats.json` lacks a done material or disagrees with
  `materials.json` (checked by breaking it on purpose); the HF check (`stats-push --check`, used by
  `stats-check.yml`) fails against a fake manifest with an extra table and passes when they match;
  the accept post-check fails the card step on a mismatch.
- **Site:** `node --test` for `charts.js` (SVG structure, log scale, empty data) and the stats
  data transforms; `node --check`; a Playwright check (`--no-sandbox`) that `#/stats` and
  `#/stats/KRvkrb` render charts without console errors.
- Coverage of the new Python code ≥ 80 %; ruff, mypy as for the rest of `contrib`.

## Rollout

1. Merge the PR (CI green). Pages deploys the Statistics screen from the committed `stats.json`.
2. The maintainer runs `helpmate-tables stats-push --tables ~/tb` once: first Parquet upload and the
   card with the viewer configuration.
3. From then on every `accept` updates both; the PR test and the daily check catch a missed update.

## Out of scope

Charts inside the material pages (decision B); per-position data; statistics for markers beyond
their existence; automatic updates from CI (CI has no tables and no Hugging Face write token).

## Risks

- **The Hugging Face viewer** can take minutes to index after an upload, and may still try other
  files despite `configs`. If so, the fallback is a separate small dataset repo for the statistics.
  This would be checked right after the first upload.
- **Contributors are attributed** from the registry at build time. A later registry correction
  takes effect with the next accept or `stats-push`.

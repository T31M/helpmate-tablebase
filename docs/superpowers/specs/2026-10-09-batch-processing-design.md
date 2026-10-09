# Batch processing of dataset PRs: per-file staging, delta verify, confirmations, deferred pages

Status: draft for review, 2026-10-09. Origin: 39 open dataset PRs (#19–#57, 152 tables, 892 GiB) with 25
materials delivered twice (popeye37 and T31M, identical content), and the cost seen on PR #18 (one changed
table forced a full re-download and re-verification).

## Goals

1. A changed PR costs only its changed files: downloads and checks of unchanged tables are reused.
2. Long verify runs show progress per table and check.
3. A table that is content-identical to an already published one is a **confirmation**, not an error:
   only the new files are merged, and **both authors are credited** everywhere credits appear.
4. Accepting a wave takes minutes: material pages can be built later, in bulk and in parallel.

Non-goals: changing what V2–V7 check, the table format, or the claim rules; parallel verification of
several tables at once.

## Background: the checks

- V1 PR hygiene (only canonical table + sidecar pairs, nothing deleted)
- V2 header and identity · V3 block integrity · V4 sidecar recomputed from the payload
  (V1–V4: the file is sound)
- V5 deepest positions probe as recorded · V6 local consistency with successors and sub-tables ·
  V7 independent python-chess solver (V5–V7: the chess content is right; most of the time)

## 1. Per-file staging

Today `verify._stage` deletes `staging/pr-N/files` whenever the PR head changes.

- `staging/pr-N/files/.files.json` records, per staged file, the HF LFS `sha256` (from `Hub._tree(head)`)
  and size, plus the head it was fetched for. It replaces the `.head` marker (an existing `.head` without
  `.files.json` is treated as "nothing known": files are re-checked against the new head's sha by hashing
  them once, then recorded).
- On a new head: files whose sha is unchanged stay; changed files are re-downloaded; files no longer in the
  PR are removed. The `to download:` plan shows only what is really fetched.
- Integrity: a staged file is trusted only if its size matches and its recorded sha equals the head's sha;
  a partially downloaded file (size mismatch) is re-downloaded.
- `_verified_files` / overlay logic keeps working: "staged for head X" now means `.files.json` head == X.

## 2. Delta verify

- `report.json` gains per table: `hm_sha256`, `stats_sha256` (the LFS shas of the verified files),
  `payload_sha256` (section 3), `seed`, and per check `reused_from` (the head of the report a result was
  taken from, absent for fresh results). Top level keeps `head`, `tool`, `settings`.
- On `verify --pr N`, if `staging/pr-N/report.json` exists from a previous run: a table's previous results
  are reused when **all** hold: its `hm_sha256` and `stats_sha256` are unchanged, it passed, the previous
  `tool` equals the current tool, and the previous `settings` (samples, oracle_samples, oracle_plies) equal
  the current ones. Otherwise the table is verified fresh. V1 is always run fresh.
- `--full` disables reuse.
- The new report covers the current head and all its tables (fresh + reused); `accept` keeps requiring a
  passing report for the current head, unchanged. The markdown report marks reused results
  ("reused from <head7>").
- The previous report is kept as `report.prev.json` for one run (debugging).

## 3. Confirmations (identical duplicates)

### Payload hash
`payload_sha256` = SHA-256 over the concatenated hex SHA-256 digests of the four decompressed planes (planes 0..3 in file order), so V4 can compute it from the chunks it already reads. It is
independent of the header and the embedded metadata (generator version), so two builds of the same
material compare equal exactly when their content is equal. V4 already decodes every block
(`checks.recompute_stats`); the hash is computed in the same pass (`BlockReader.plane_chunks`), no extra read.
Marker tables: `payload_sha256` = SHA-256 of the canonical JSON of the sidecar's `cells` (markers have no
payload).

### Verify
- V1 no longer fails for a table whose material is already published. Instead the table is classified as
  **duplicate** and listed as such in V1's detail.
- A duplicate runs V2–V4 (computing `payload_sha256`), then a new check **V8 "identical to the published
  table"**: the published table's payload hash is computed from the local corpus copy
  (`--tables`, same function) and cached in `<tables>/.payload-sha256.json` keyed by material and the
  published `.hm` sha256 (manifest). Equal → V8 pass, V5–V7 skipped ("confirmed: identical to the published
  table"). Different → V8 fail ("content differs from the published table"), which fails the PR.
- A published table missing from `--tables` → usage error (corpus incomplete), like a missing sub-table.
- Non-duplicates are unchanged (V2–V7); their report still records `payload_sha256`.

### Accept
- For each PR, at accept time (after merges of earlier PRs in the same run): materials already in the
  manifest are duplicates. Each needs `payload_sha256` in the report equal to the published table's payload
  hash (from the cache, recomputed if the published sha changed). Mismatch → accept stops before merging
  that PR, with an error.
- The PR's **new** files are merged with `Hub.merge_by_copy(num, head, new_files, …)`; the PR is closed
  with a comment listing the merged tables and the confirmations. A PR consisting only of duplicates is not
  merged: it is closed with a thank-you comment. (Two open PRs with the same material: whichever is accepted
  first is published; the order is chosen by the maintainer per wave.)
- Registry (`data/contributions.json`): per table a new optional list
  `confirmed_by: [{contributor, hf_pr, date, generator_version}]`. A contributor with only confirmations is
  added to `contributors` like any other. `Registry.confirmations_of(key)` lists a contributor's confirmed
  materials.
- The local step does not move duplicate files into `--tables` (the published file stays); their staging
  files are deleted with the rest of the PR's staging after a successful accept.

### Credits (both authors named everywhere)
- `site_status.build_status` → `status.json`: per done material `contributor` stays the author;
  new `confirmed_by: [names]`. Each contributor entry gets `confirmations` (count) next to `tables`.
- Site: Materials page contributor cell "popeye37 · confirmed by T31M"; the contributor filter matches
  author or confirmer; front-page contributor cards "N tables, M independent confirmations".
- `docs_sync.render_contributors` (README / CONTRIBUTING-TABLES / dataset card): a "confirmations" column.
  `.all-contributorsrc`: contributors with only confirmations are listed.
- CHANGELOG line written by accept: "… (confirmed by T31M: KQvkqqq, …)".
- Parquet `materials.parquet`: new column `confirmed_by` (string, comma-separated names, empty if none).
- Claim comments (accept's claims step): a claimer whose claimed material was confirmed by someone else
  is thanked normally; a confirmer's claim lists the confirmed materials as done.

## 4. Progress lines

`verify` prints, unbuffered, one line per table start and per check end:
`[3/20] KQvkqqq V4 sidecar recomputed … pass (2m14s)`, plus `reused` / `skipped` markers. The markdown
report and posted comments are unchanged apart from the reused/confirmed notes.

## 5. Deferred material pages

- `helpmate-tables accept --no-pages`: skips `build_material_pages` and its post-check; the docs PR is
  written without pages (`materials.json` page flag false for those materials). Everything else unchanged.
- New `helpmate-tables pages --tables DIR (--missing | --material M ...) [--jobs N] [--binary PATH]
  [--checkout PATH]`:
  - `--missing`: every done material (materials.json) without `site/data/material/<M>.json`.
  - Builds pages with `tools/build_problems.py`, N jobs at a time (`--jobs`, default 1). The materials are
    split round-robin into N lists; each job is its own process with its own `--material` list and its own
    output directory `staging/pages-<date>/job-<i>` (holding a copy of `materials.json` and no index /
    themes file), so no two processes write the same file. build_problems' end-of-run read-merge-write of
    `index.json` / `themes.json` would race if jobs shared `site/data`; this layout avoids that.
  - When all jobs are done, `pages` moves each job's `material/*.json` into `site/data/material/` and folds
    each job's `index.json` / `themes.json` into the real ones, one after another, with build_problems' own
    `merge_index` / `merge_themes` (imported from the checkout's `tools/build_problems.py`).
  - A failed material (build_problems reports it and exits 1) is listed at the end; the other pages are
    kept, and the run exits non-zero before opening a PR unless `--allow-failures` is given.
  - Then `write_site_data` (page flags), a docs branch + PR, waits for CI and squash-merges, using the same
    `Git` helper and resume-state pattern as `accept` (state file `staging/pages-<date>.json`).
- The site freshness test (stats.json vs materials.json) is unaffected.

## Testing

- Staging: head change with one changed file → only that file re-downloaded; removed file deleted;
  legacy `.head` marker; partial file re-downloaded.
- Delta verify: reuse when shas/tool/settings equal; fresh when any differs; `--full`; failed tables re-run;
  report marks reused results; accept still requires the current head.
- Payload hash: equal for two files that differ only in embedded metadata (generator version) — a test
  writes the same planes with two versions; different when one cell differs; markers.
- V8: equal → pass and V5–V7 skipped; different → fail; published table missing → usage error; cache hit and
  invalidation when the published sha changes.
- Accept: mixed PR (new + duplicate) → only new files merged, registry `confirmed_by`, CHANGELOG line, PR
  closed with comment; duplicate-only PR → closed, nothing merged; mismatch → stops before merging.
- Credits: status.json, site (node tests), docs_sync table, Parquet column, contributor with only
  confirmations.
- `pages --missing` with a fake runner: picks exactly the materials without page; `--jobs 2` splits them;
  resumes from its state file.
- Progress lines appear (capsys).
- Real data check (manual, read-only): payload hash of popeye37's and T31M's KQvkqqq (HF #19 and #22) are
  equal.
- Coverage of changed modules ≥ 80 %; ruff, mypy, node tests.

## Rollout

1. Merge; reinstall the CLI.
2. Waves (order: KN/KNN → popeye37's KQvk → T31M's KR → KP and mixed): `verify --pr …` per wave,
   `accept … --no-pages` per wave.
3. `pages --missing --jobs N` overnight after the waves.

## Risks

- Payload hashing adds CPU to V4 (one SHA-256 pass over the decompressed data, ~1–2 GB/s per core) —
  small next to decompression.
- `merge_by_copy` with a file subset must keep the `.gitattributes`-only conflict fallback working
  (existing tests extended).
- Parallel page building: each job has its own output directory and the merge is sequential (section 5),
  so index.json / themes.json cannot be corrupted by concurrent writes.

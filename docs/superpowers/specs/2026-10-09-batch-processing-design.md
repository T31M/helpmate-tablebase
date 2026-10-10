# Batch processing of dataset PRs: per-file staging, delta verify, duplicates and claims, deferred pages

Status: draft for review, 2026-10-09; duplicates and claims rule added 2026-10-10. Origin: 39 open dataset PRs (#19–#57, 152 tables, 892 GiB) with 25
materials delivered twice (popeye37 and T31M, identical content), and the cost seen on PR #18 (one changed
table forced a full re-download and re-verification).

## Goals

1. A changed PR costs only its changed files: downloads and checks of unchanged tables are reused.
2. Long verify runs show progress per table and check.
3. A table that two contributors deliver with identical content is an **independent reproduction**, not an
   error and not a dispute: it is stored once, and **all producers are credited equally** everywhere credits
   appear (section 3, "Duplicates and claims").
4. Accepting a wave takes minutes: material pages can be built later, in bulk and in parallel.

Non-goals: changing what V2–V7 check or the table format; parallel verification of several tables at once.
The claim rules change only as section 3 describes (claims choose the published file and hold back new
material; they no longer block identical deliveries).

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

## 3. Duplicates and claims

### The rule

Two deliveries of the same material with identical content are an independent reproduction. That makes the
table more trustworthy, so it is treated as a joint result, not as a conflict:

1. **Equal credit.** Every contributor whose delivery of a material passed and matched is a **producer** of
   that table, listed in order of delivery (HF PR creation time). Nobody is "author" and nobody is
   "confirmer". Counts never split: each producer counts the table fully.
2. **Which file is published.** The content is identical; only the sidecar and the embedded generator version
   differ. The published file is the **claim holder's** delivery; if no producer holds a valid claim for the
   material, the **earliest delivery**. A file already published is never replaced: if the claim holder
   delivers after another producer's file was published, the claim holder becomes a producer and the
   published file stays.
3. **Claims no longer block identical deliveries.** A delivery of a material claimed by someone else is
   accepted when its content equals the claim holder's delivery or the published table (it adds a producer).
4. **Claims still protect new material.** A delivery of a claimed material that is neither published nor
   delivered by the claim holder is **held**: verify passes it, accept skips it (listed as "held for claim
   #N"), and it stays open until the claim holder delivers (then rule 2 applies) or the claim stops covering
   the material (closed, released, or edited). The maintainer can override per material with
   `accept --release M` after asking the claim holder.
5. **Different content is not a duplicate.** If two deliveries of a material differ in content, V8 fails for
   the later one and accept stops for that material; the oracle checks decide which is wrong. No credit is
   given until it is resolved.
6. **Valid claim** means: an open claim issue that covers the material (explicitly or by wildcard) and is the
   earliest open claim covering it (the existing "first claim wins" rule in `claims.py`).

### Claims bot

- **Effective coverage.** A wildcard claim excludes materials that an earlier open claim already covers. The
  bot's status table shows them as "claimed in #N by X" and the header says "covers N materials (M excluded:
  claimed earlier by others)". Explicit names that overlap an earlier claim keep the `claim-conflict` label.
- **Coordination.** When a new claim overlaps an earlier one, the bot's comment mentions both authors once
  ("@a @b — these materials overlap; the earlier claim holds them; identical deliveries are credited to both").
- **Confirmation claims (optional).** A claim whose body starts with `confirm:` declares a deliberate
  reproduction: it never conflicts, it is listed as "confirming", and its deliveries are expected to be
  duplicates (rule 1). Nothing is held for it.
- Status rows gain "produced by X and Y" for materials with several producers, and "held for claim #N" for
  held deliveries.

### Payload hash
`payload_sha256` = SHA-256 over the concatenated hex SHA-256 digests of the four decompressed planes (planes 0..3 in file order), so V4 can compute it from the chunks it already reads. It is
independent of the header and the embedded metadata (generator version), so two builds of the same
material compare equal exactly when their content is equal. V4 already decodes every block
(`checks.recompute_stats`); the hash is computed in the same pass (`BlockReader.plane_chunks`), no extra read.
Marker tables: `payload_sha256` = SHA-256 of the canonical JSON of the sidecar's `cells`, prefixed `marker:` (markers have no
payload).

### Verify
- V1 no longer fails for a table whose material is already published. Instead the table is classified as
  **duplicate** and listed as such in V1's detail.
- A duplicate runs V2–V4 (computing `payload_sha256`), then a new check **V8 "identical to the published
  table"**: the published table's payload hash is computed from the local corpus copy
  (`--tables`, same function) and cached in `<tables>/.payload-sha256.json` keyed by material and the
  published `.hm` sha256 (manifest). Equal → V8 pass, V5–V7 skipped ("independent reproduction: identical to
  the published table"). Different → V8 fail ("content differs from the published table"), which fails the PR.
- A published table missing from `--tables` → usage error (corpus incomplete), like a missing sub-table.
- Two open PRs delivering the same unpublished material: the later one (by creation time) compares against
  the earlier one's staged copy when that PR is verified too (same cache, keyed by PR head and file sha);
  otherwise it runs V2–V7 like a new table and the comparison happens at accept time.
- Non-duplicates are unchanged (V2–V7); their report still records `payload_sha256`.
- V1's detail lists, per material, "new", "duplicate of published", "duplicate of HF PR #N", or "held for
  claim #N" (rule 4).

### Accept

- `accept` processes the given PRs in **creation order** and decides per material:
  - **published already** → its `payload_sha256` must equal the published table's (cache, recomputed if the
    published sha changed); the PR's contributor is added as a producer. Mismatch → accept stops before
    merging that PR.
  - **delivered in several PRs of this run** → contents must be equal (else stop for that material); the file
    published is the claim holder's delivery, else the earliest (rule 2); every delivering contributor becomes
    a producer.
  - **claimed by someone else, not published, not delivered by the claim holder** → held (rule 4), unless
    `--release M` is given.
  - otherwise → new, published as today.
- Merging: the PR's files that are published are merged with `Hub.merge_by_copy(num, head, files, …)`; the PR
  is closed with a comment listing published tables, reproductions ("identical to the published table,
  credited as co-producer") and held materials. A PR with nothing to publish and nothing held is closed with a
  thank-you comment; a PR with held materials stays open with a comment naming the claim.
- `accept` no longer refuses a PR because its material is claimed by someone else (today's
  `ownership_conflict` check applies only to the PR's own identity clues: claim number and GitHub login in the
  description).
- Registry (`data/contributions.json`): per table, `producers: [{contributor, hf_pr, date,
  generator_version}]` in delivery order, and `published_from: hf_pr` (which delivery's file is published).
  The existing top-level `contributor`/`hf_pr` fields stay for compatibility and name the published file's
  delivery; readers use `producers`. Migration: existing entries get `producers` with their one contributor.
  A contributor with only reproductions is added to `contributors` like any other.
- The local step moves only published files into `--tables`; the other deliveries' staged files are deleted
  with the rest of the PR's staging after a successful accept.

### Credits (all producers named equally)

- `site_status.build_status` → `status.json`: per done material `producers: [names]` (delivery order); each
  contributor entry gets `tables` (all tables they produced) and `reproduced` (how many of those have more
  than one producer).
- Site: Materials page contributor cell "popeye37 · T31M" with a "✓ reproduced" mark when a table has several
  producers; the contributor filter matches any producer; front-page contributor cards "N tables, M
  independently reproduced".
- `docs_sync.render_contributors` (README / CONTRIBUTING-TABLES / dataset card): "tables" counts every table a
  contributor produced, plus a "reproduced" column. `.all-contributorsrc` lists every producer.
- CHANGELOG line written by accept: "… KQvkqqq (independently reproduced by popeye37 and T31M), …".
- Parquet `materials.parquet`: `contributor` becomes the comma-separated producers in delivery order; new
  columns `producers_count` (int8) and `published_from_pr` (int32).
- Claim comments (accept's claims step): every producer's claim lists the material as done; a reproduction
  is thanked as "independently reproduced — credited to both".

## 4. Progress lines

`verify` prints, unbuffered, one line per table start and per check end:
`[3/20] KQvkqqq V4 sidecar recomputed … pass (2m14s)`, plus `reused` / `skipped` markers. The markdown
report and posted comments are unchanged apart from the reused / reproduced / held notes.

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
- Accept: mixed PR (new + duplicate) → only published files merged, registry `producers`, CHANGELOG line, PR
  closed with comment; duplicate-only PR → closed, nothing merged; mismatch → stops before merging.
- Duplicates and claims: published + identical delivery → producer added, nothing merged; two PRs in one run
  with the same material → claim holder's file published, both producers; no claim → earliest delivery's
  file; claimed new material from someone else → held, PR stays open with comment; `--release M` publishes
  it; claim holder delivering after another producer's file was published → producer added, file kept;
  different content → stop for that material; `ownership_conflict` no longer triggered by someone else's
  claim.
- Claims bot: wildcard coverage excludes earlier claims (status rows and header counts); overlap comment
  mentions both authors once; `confirm:` claims never conflict and hold nothing; "produced by" and "held for"
  rows.
- Credits: status.json, site (node tests), docs_sync table, Parquet columns, contributor with only
  reproductions; registry migration adds `producers` to existing entries.
- `pages --missing` with a fake runner: picks exactly the materials without page; `--jobs 2` splits them;
  resumes from its state file.
- Progress lines appear (capsys).
- Real data check (manual, read-only): payload hash of popeye37's and T31M's KQvkqqq (HF #19 and #22) are
  equal.
- Coverage of changed modules ≥ 80 %; ruff, mypy, node tests.

## Rollout

1. Merge; reinstall the CLI.
2. Post a short note in claims #40, #65 and #67 explaining the rule (text approved by the maintainer).
3. Waves: `verify --pr …` per wave, `accept … --no-pages` per wave, in this order:
   - KN (HF #20) — no overlap.
   - KQvk: popeye37's #19 and #46 together with T31M's KQ/KR/KP PRs #22–#57. popeye37 holds claim #40, so
     his files are published for the overlapping KQ materials and T31M is a co-producer where the content is
     identical; T31M's KR and KP tables are published normally.
   - KNN (HF #21, T31M, no claim) against popeye37's claim #65: the KNN tables are **held** (rule 4). Ask
     popeye37 first: if his KNN tables are computed, he delivers them and both are producers (his files
     published as claim holder); if not, `accept 21 --release KNNvk…` publishes T31M's files and popeye37's
     claim shows them as done.
4. `pages --missing --jobs N` overnight after the waves.

## Risks

- Payload hashing adds CPU to V4 (one SHA-256 pass over the decompressed data, ~1–2 GB/s per core) —
  small next to decompression.
- `merge_by_copy` with a file subset must keep the `.gitattributes`-only conflict fallback working
  (existing tests extended).
- Parallel page building: each job has its own output directory and the merge is sequential (section 5),
  so index.json / themes.json cannot be corrupted by concurrent writes.

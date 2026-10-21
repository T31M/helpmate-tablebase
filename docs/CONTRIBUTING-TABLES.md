# Contributing tablebases

This project needs CPU and RAM more than it needs code.

The corpus is **complete through five pieces** — all 220 five-piece classes,
plus everything below them. At six pieces there are **<!-- contrib:six-total -->715<!-- /contrib --> material classes**, and
**<!-- contrib:six-done -->306<!-- /contrib --> are done**, of which <!-- contrib:six-empty -->75<!-- /contrib --> are proven empty (marker
tables: no helpmate exists in that class, so there is nothing to compute). The
<!-- contrib:six-open -->409<!-- /contrib --> still to go are more than one desk can do: the
pawnless ones need a 32 GiB machine, the ones with pawns 64 to 96 GiB.

If you have a machine with 32 GiB of RAM and a few hours where it would
otherwise idle, you can compute one of the tables that are still open.

> For contributing *code*, see [CONTRIBUTING.md](CONTRIBUTING.md) — that one
> is about CI checks and pull requests against the source tree.

## What is missing

<!-- contrib:six-open -->409<!-- /contrib --> six-piece tables. Peak RAM equals the raw table size, because generation
holds four bytes per cell resident:

| pawns | tables missing | RAM needed | machine |
| --- | --- | --- | --- |
| **0** | **<!-- contrib:six-open-p0 -->174<!-- /contrib -->** | **28.9 GiB** | **32 GiB — the accessible tier** |
| 3 | <!-- contrib:six-open-p3 -->20<!-- /contrib --> | 47.6 GiB | 64 GiB |
| 4 | <!-- contrib:six-open-p4 -->3<!-- /contrib --> | 35.7 GiB | 64 GiB |
| 2 | <!-- contrib:six-open-p2 -->68<!-- /contrib --> | 63.5 GiB | 96 GiB (64 is too tight) |
| 1 | <!-- contrib:six-open-p1 -->144<!-- /contrib --> | 84.7 GiB | 96 GiB |

Start with the pawnless tier. It is the largest single group, it fits on
ordinary hardware, and every table in it is 28.9 GiB raw — about 1–6 GiB once
compressed. A pawnless table takes about 40 minutes on a 16-thread machine
(KBvkqrb: 41 minutes, and 13.5 minutes on 32 threads, where it took 4 h 28 min
before 0.21). Tables with pawns have up to three times the cells and have not
been timed since 0.21; they also need other six-piece tables first (step 2).

Seven pieces is not open: a 7-piece class needs about 2 TB resident and an
out-of-core generator that does not exist yet.

## How to contribute one

**1. Claim it first.** Open an issue with the **Claim a material** form
([new claim](https://github.com/osick/helpmate-tablebase/issues/new?template=claim.yml))
before you start, so that two people do not compute the same table by
accident (a deliberate reproduction is welcome, see
[Duplicates and claims](#duplicates-and-claims)). Fill in the Hugging Face
username your token belongs to: a claim whose form names another HF account
does not speak for your pull request. List one material per line; patterns
such as `KQvk???` are allowed. A bot keeps the status of every claim in one
comment on your issue. To hand a material over, strike its name through
(`~~KRRvkpp~~`). The
[materials list](https://osick.github.io/helpmate-tablebase/#/materials) on
the site, filterable, shows priority, state and contributor of every
material. Priority P1 means one White piece besides the king: the longest,
deepest problems. Every P1 class is done, so start with P2. Claims lapse after
three weeks of silence.

**2. Pull the published sub-tables first.** `gen` builds the full closure of
sub-slices reachable by captures and promotions, and leaves any table that
already exists alone; without the published sub-tables it regenerates the
whole closure first. Every capture leads to five pieces or fewer, and all of
those are published, about 24 GiB. **Do not run `pull` without `--material`:
it downloads the whole corpus, 1.2 TiB.** Pull the tables of five pieces or
fewer by name instead:

**For more detailed setup instructions see [Setup](#setup) at the bottom of the file**

```bash
git clone https://github.com/osick/helpmate-tablebase
cd helpmate-tablebase
python3 -m venv .venv && source .venv/bin/activate   # make install runs `python -m pip`
make install                                          # builds the C++ core, installs the CLIs
mkdir -p tables
# every published table of five pieces or fewer, ~24 GiB
mapfile -t M < <(python3 -c 'import json; [print(r["material"]) for r in json.load(open("site/data/materials.json")) if r["done"] and r["pieces"] <= 5]')
helpmate-tables pull --tables ./tables --repo osick/helpmate-tables "${M[@]/#/--material=}"
```

A promotion does not reduce the piece count, so a table with pawns also needs
the six-piece tables its pawns promote into: KRPvkbb needs KQRvkbb, KRRvkbb,
KRBvkbb and KRNvkbb. Pull the published ones with `--material` as well. `gen`
builds any that are missing before the table itself, at their own cost: as of
0.21 that is one to four tables for a one-pawn class, 9 to 24 for two pawns,
and more for three or four. Claim those too and push them with your table.
With `--verbose`, the first lines `gen` prints are the closure and the number
of slices it will build; stop it with Ctrl-C if that is more than you claimed.

(There is no PyPI release yet, so it is a source build — see
[BUILD.md](BUILD.md) if `make install` gives you trouble.)

**3. Generate, writing compressed directly.** No separate conversion step:

```bash
helpmate gen KBBBvkb --tables ./tables --threads $(nproc) --compress --progress
```

`--threads` defaults to 1, so give it every core. Leave headroom: the
generator checks available memory before allocating and refuses rather than
inviting the OOM killer. Do not run it under `--force-ram` to get around that.

**4. Sanity-check your own output** before submitting, with the same checks
the maintainer runs:

```bash
pip install './src/packages/api[verify]'    # once; `make install` already does it
helpmate-tables verify --tables ./tables --material KBBBvkb
```

`--tables` must hold the table and every published sub-table it needs, for
a table with pawns including the six-piece tables it promotes into (`verify`
exits with status 2 and names the missing one otherwise). It runs
checks V2 to V7 below; expect a few minutes for a pawnless six-piece table. A
❌ means do not submit: fix the cause (or regenerate) and run it again.
`--report FILE` also writes the JSON report.

**5. Open a pull request on the dataset.** Contributions land as PRs against
[huggingface.co/datasets/osick/helpmate-tables](https://huggingface.co/datasets/osick/helpmate-tables),
so nothing transits anyone's laptop and review happens where the data lives:

```bash
hf auth login                  # once; stores an HF token
helpmate-tables push --tables ./tables --repo osick/helpmate-tables \
                     --material KBBBvkb --create-pr \
                     --claim 47 --github your-login
```

```
proposed KBBBvkb.hm
proposed KBBBvkb.stats.json
opened pull request: https://huggingface.co/datasets/osick/helpmate-tables/discussions/12
```

`--create-pr` sends the table and its sidecar as a **single** pull request,
and deliberately does not touch `manifest.json` — the maintainer regenerates
that after merging, and a PR that edited it would conflict with every other
open PR. Push only the material you generated: without `--material`, `push`
proposes every table in `--tables`, the pulled corpus included. `--material`
takes one name, so repeat it for a table and the promotion tables you
generated with it (`--material KRPvkbb --material KQRvkbb`); they go into one
pull request. Pass the claim that covers the material as `--claim`.

### Who you are, on two different sites

The two halves of a contribution live on two services with **no shared
identity**:

| | how you authenticate | what it is used for |
| --- | --- | --- |
| **Hugging Face** | an API token — `hf auth login`, or the `HF_TOKEN` environment variable | the dataset pull request. It is authored by whichever HF account owns the token. |
| **GitHub** | your normal GitHub account | the claim issue, and code contributions |

`helpmate-tables` never sees a GitHub credential, and GitHub never sees your
HF token. A pull request on the dataset shows only an HF username. Three
things link it to you, in this order: the `GitHub:` line in its description,
the contributor registry (`data/contributions.json`, which maps your HF
account to your GitHub login once a delivery of yours has been accepted), and
the claim that covers the material, unless its form names another HF account.

**Closing the loop:** `--claim <issue>` (the number of your claim issue) and
`--github <your login>` write both into the HF pull request description, so
verify and accept credit you without guessing. Run `hf auth whoami` if you
are unsure which account your token belongs to — it is easy to be logged in
as an old one.

### Duplicates and claims

Two deliveries of the same material with identical content are an independent
reproduction. That makes the table more trustworthy, so it is a joint result,
not a conflict:

1. **Equal credit.** Everyone whose delivery passed and matched is a
   *producer* of that table, listed in order of delivery (dataset PR number).
   Nobody is "author" and nobody is "confirmer"; every producer counts the table
   fully.
2. **Which file is published.** The content is identical, only the sidecar and
   the generator version differ. The published file is the claim holder's
   delivery; if no producer holds a valid claim, the earliest delivery. A file
   that is already published is never replaced; a claim holder who delivers
   later becomes a producer.
3. **A claim does not block an identical delivery.** Someone else's delivery of
   a claimed material is accepted when it equals the claim holder's delivery or
   the published table; it adds a producer.
4. **A claim still protects new material.** Someone else's delivery of a claimed
   material that is neither published nor delivered by the claim holder is
   *held*: it passes verify, `accept` skips it ("held for claim #N") and the PR
   stays open until the claim holder delivers, the claim ends, or the
   maintainer releases the material after asking the claim holder.
5. **Different content is not a duplicate.** If two deliveries differ, V8 fails
   for the later one and nothing is accepted for that material until it is
   resolved.
6. **A valid claim** is an open claim issue that covers the material, directly
   or by pattern, and is the earliest open claim covering it.

To reproduce a table on purpose, open a claim whose first line is `confirm:`
(then the list of materials). A confirming claim never holds or conflicts with
anything. A pattern claim such as `KQvk???` leaves out every material that an
earlier claim already covers; the status comment lists them as "excluded:
claimed earlier by others". Explicit overlaps are still flagged as a
conflict. Every overlap with an earlier claim, explicit or by pattern, gets one
notice that names both authors; there is none between two claims of the same
author, and a material the earlier claim struck through does not count.

## What gets checked before a merge

Being blunt about the state of this: **a donated table is currently reviewed,
not proven.** `helpmate-tables verify` runs seven checks, cheapest first, plus V8 for duplicates. You
run V2 to V7 with `--material`; the maintainer runs V1 to V7 (and V8) on your pull
request with `--pr`. If V4 or V5 fails, V6 and V7 are skipped.

- **V1 PR hygiene.** Only `<M>.hm` plus `<M>.stats.json` pairs with safe file
  names at the top level of the dataset, at least one of them; nothing deleted;
  every material canonical. A material already in the manifest is labelled a
  duplicate of the published table and goes on to V8. A missing claim link is
  a warning, not a failure.
  The files are the difference between the pull request and the commit it
  branched from, so other changes landing on `main` meanwhile never count.
- **V2 header.** Magic, block-compressed encoding, embedded material equals the
  file name, `plane_size` equals the index size, generator version not newer
  than the verifier.
- **V3 block integrity.** Every zstd frame decodes; its checksum and length
  match the block index.
- **V4 sidecar.** The four planes are recomputed block by block; invalid and
  unsolvable counts, the DTM histogram and `max_dtm` must equal the sidecar
  and the header exactly.
- **V5 deepest.** Every FEN the sidecar lists as deepest probes to `max_dtm`.
- **V6 local consistency.** Random positions (seeded, seed in the report) obey
  the recurrence the generator solves: dtm is 1 plus the minimum over
  successors, the count is the saturating sum over the minimising successors,
  with captures and promotions read from the published sub-tables.
- **V7 independent oracle.** Shallow positions are re-solved by a python-chess
  search that shares no code with the generator and must reproduce dtm and
  count. By default that is up to 20 positions for each DTM from 0 to 3 plies
  plus up to 20 of V6's positions, so at most 100 positions, all at most 3
  plies deep (`--oracle-samples`, `--oracle-plies`). The limit is runtime:
  python-chess needs minutes per six-piece position at 5 plies. The report
  records the settings used.

- **V8 identical to the published table.** Only for a material that is already
  published or delivered by an earlier PR in the same run: the payload hash
  (SHA-256 of the four plane hashes) must equal the other copy. A duplicate of a
  published table is checked with V2 to V4 and V8; V5 to V7 are skipped as
  "independent reproduction". A duplicate of an earlier PR in the same run is
  checked with V2 to V5 and V8: its sidecar may be the one that gets published
  (the claim holder's delivery, or a release), so its deepest positions are
  probed; only V6 and V7 are skipped.

**What is not checked is full correctness.** Proving a donated table right
means regenerating it, which costs exactly what the donation saved. The
honest position is that a contributed table is trusted on the basis of
structural consistency, spot checks, and the contributor's reputation.

What would move it closer is a deeper oracle. V7 stops at 3 plies because
python-chess needs minutes per six-piece position at 5. A C++ oracle already
exists (`src/core/generator/oracle.cpp`, a from-scratch cooperative
iterative-deepening solver sharing only the move generator with the real
generator), but it is reachable only from the C++ tests. Exposing it through
the Python bindings would let V7 re-solve deep positions too, for contributed
tables and for anyone auditing a published one.

That is the single most valuable code contribution available to this project
right now. If you would rather write C++ than spend CPU time, write that.

## Determinism, and why it matters here

Generation is required to be byte-identical whether run with one thread or
many, and that is asserted by tests; the faster generator of 0.21 writes the
same tables and sidecars as the one before it. So two people generating the
same material produce the same table. V8 compares the payload (the four
planes), not the file, so block size and header metadata do not matter. If
you have spare capacity and no appetite for a fresh material, **reproducing a
published table is a real contribution** — it converts a trusted table into a
verified one. Open a claim whose first line is `confirm:`, generate the table
into a tables directory that does not hold the published copy (`gen` leaves an
existing table alone), and push it like any other; V8 checks it against the
published table, and you are credited as a producer.

## Credit

Every merged table is credited by material and contributor in
the [materials list](https://osick.github.io/helpmate-tablebase/#/materials), the README and the dataset card. If you would rather not be named, tick
*Do not name me in the credits* on the claim form.

The first outside contribution came from **T31M**: fifteen tables, KRBvkqq
through KRBvkpp (issue #41, dataset PR #1), computed on a 192-thread,
369 GiB machine — including five one- and two-pawn tables from the 96 GiB
tier. The setup instructions below are theirs too (#42).

## For the maintainer

```bash
helpmate-tables status                                  # what is waiting
helpmate-tables verify --tables ~/tb --pr 2 3 4         # asks before downloading; posts reports
helpmate-tables accept 2 3 4 --tables ~/tb --plan       # what accept would do; writes nothing
helpmate-tables accept 2 3 4 --tables ~/tb              # merge, manifest, credits, docs PR
```

- `verify --pr` lists the PR files and sizes and asks before downloading
  (`--yes` skips the question, `--plan-only` stops after the list, `--no-post`
  keeps the report off HF and GitHub). Downloads are staged in `~/tb-staging`,
  per file (`files/.files.json`), and a rerun downloads only the files that changed
  or are incomplete. It exits with status 2
  if `--tables` lacks a sub-table the PR needs. Without a terminal (`nohup`,
  `systemd-run`, a cron job) it cannot ask: pass `--yes`, or it stops with a usage
  error. Files staged by an older helpmate-tables (only `files/.head`) are listed as
  "already downloaded, will be checked" when their size matches; their checksums are
  compared before verifying and a mismatching file is downloaded again.
- Delta verify: a table whose file and settings (`samples`, `oracle_samples`,
  `oracle_plies`) are unchanged since the last report reuses its result
  ("reused from <head>"); a killed run resumes from `report.partial.json`;
  `--full` re-checks everything. Progress lines read
  `[i/n] <material> <check> ... <status> (<time>)`. V1 labels each material new,
  duplicate of published, duplicate of HF PR #N, or held for claim #N;
  `--no-post` still reads the claims. Run it from the checkout (or pass `--checkout`):
  the contributor registry tells V1 who sent a PR that has no `GitHub:` line.
- `accept N... --plan` runs everything accept checks before its first write (open
  PRs, report heads, staged files, contributors, claims, decisions) and prints, per
  PR, the contributor, one line per material (`publish from #N`, `reproduction of
  published table -> producer`, `co-producer (file published from #M)`, `held for
  claim #K by @holder` or `CONFLICT: ...`) and what happens to the PR (merge,
  partial copy + close, partial copy and stays open, comment only, close with
  thank-you), then the producers and CHANGELOG lines it would add. It writes
  nothing: no Hub or GitHub write, no checkout change, no state file. Exit 1 means
  a conflict, 2 an error accept would stop with. Run it before every real accept
  of a batch, with the same `--release` and `--contributor` arguments.
- `accept` publishes the claim holder's file, else the earliest, never replaces a
  published one, and adds identical deliveries as producers. It skips held
  deliveries (the PR stays open with a comment); `accept --release M` publishes
  someone else's delivery of claimed material after you asked the claim holder.
  Differing content stops it before anything is merged. A reproduction of your
  own table credits "maintainer" plus the reproducer. `accept --no-pages` leaves
  out the site pages.
- `helpmate-tables pages --tables ~/tb (--missing | --material M...) [--jobs N]`
  mines the missing site pages in parallel jobs, resumable, and ships a docs PR.
- `accept` refuses a PR that changed since its passing verification, and needs
  a clean checkout on its first run. Steps: merge the HF PR, regenerate and
  push the manifest, move the files into `--tables`, open a docs PR
  (`contributions.json`, the site's materials data, README and card figures, CHANGELOG,
  all-contributors) and wait for the required CI checks (not the informational coverage
  job) before squash-merging it, upload the dataset
  card once that PR is merged (together with the statistics,
  `stats/materials.parquet` and `stats/histogram.parquet`, checked against the
  manifest; skipped with a message if `--tables` is incomplete), then comment on and close the finished claims. It
  is resumable: rerun the same command after a failure. Use
  `--contributor LOGIN` when neither the PR description nor the claim issue
  names one; it applies to every PR of a run, so accept that PR on its own.
  The docs PR also carries the accepted materials' site pages
  (`site/data/material/<M>.json`, mined by `tools/build_problems.py`), so accept
  needs the `helpmate` binary on `PATH` (`--binary PATH` to point elsewhere).
- `helpmate-tables sync --tables ~/tb` regenerates the counts and the site's
  materials data (`site/data/materials.json`, `corpus.json`; Kvk (two bare
  kings) is listed last, with no priority) and closes finished claims
  (`--no-close` to skip); it refuses when `--tables` lacks sidecars the
  manifest lists. The Claims workflow only
  updates status comments and never closes issues.
- `helpmate-tables stats-push --tables ~/tb [--dry-run]` computes the per-table
  statistics and uploads the two Parquet files plus main's dataset card, only when
  their content changed; it refuses an incomplete local corpus (`--tables` must hold
  every table the manifest lists). `--dry-run` only prints the row counts and what
  it would upload. `helpmate-tables stats-push --check` compares the published
  `stats/materials.parquet` with the manifest (read-only, no token) and exits 1 when
  it is stale; the Stats check workflow runs it daily, so it fails until the first
  `stats-push` after 0.21.0, the release that introduced statistics: run
  `stats-push --tables ~/tb` right after merging it (after reinstalling the CLI).
  Once, after 0.21.0, open the dataset page and check
  that the viewer shows `materials` and `histogram`; `accept` keeps them current
  from then on. The site's `site/data/stats.json` is committed data, refreshed by
  `sync` and `accept`'s docs step.
- When `status` reports enough new tables, refresh DEEPEST, the site and the
  booklet:

```bash
python3 tools/deepest_showcase.py --tables ~/tb && make docs-deepest \
  && python3 tools/build_site_data.py --tables ~/tb
```

## Setup

### Tablebase

These instructions are examples using Ubuntu 24.04 and should be easily applicable to other Linux distributions
(the build needs GCC 13 or newer; Ubuntu 22.04 ships GCC 11, see [BUILD.md](BUILD.md#prerequisites))
**Note** this assumes a minimal fresh installation (e.g. AWS EC2 instance)

```bash
# minimal requirements for building (add other packages as you please)
sudo apt update && sudo apt install python3-venv python3-dev build-essential libzstd-dev -y
git clone https://github.com/osick/helpmate-tablebase && cd helpmate-tablebase
python3 -m venv --prompt tablebase .venv && source .venv/bin/activate && make install && mkdir -p tables
# the tables of five pieces or fewer, ~24 GiB; `pull` without --material downloads all 1.2 TiB
mapfile -t M < <(python3 -c 'import json; [print(r["material"]) for r in json.load(open("site/data/materials.json")) if r["done"] and r["pieces"] <= 5]')
export HF_TOKEN=<if you want to> && helpmate-tables pull --tables ./tables --repo osick/helpmate-tables "${M[@]/#/--material=}"
```

### Huggingface

Official documentation: https://huggingface.co/docs/huggingface_hub/guides/cli

`make install` installs `huggingface_hub` (a dependency of `helpmate-api`),
which ships the `hf` command since huggingface_hub 0.34; run
`pip install -U huggingface_hub` in the venv if `hf` is missing. The older
`huggingface-cli` no longer works in huggingface_hub 1.x.

```bash
# should prompt / already login if HF_TOKEN is set
hf auth login
hf auth whoami
# example push for table
helpmate-tables push --tables ./tables --repo osick/helpmate-tables \
                     --material KBBBvkb --create-pr --claim 47 --github your-login
```
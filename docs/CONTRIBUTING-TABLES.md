# Contributing tablebases

This project needs CPU and RAM more than it needs code.

The corpus is **complete through five pieces** — all 220 five-piece classes,
plus everything below them. At six pieces there are **645 material classes
that need a real table**, and **31 are done**. The rest is roughly six hundred
machine-days of work, and it is not going to come from one desk.

If you have a machine with 32 GiB of RAM and a week where it would otherwise
idle, you can produce something nobody has ever computed.

> For contributing *code*, see [CONTRIBUTING.md](CONTRIBUTING.md) — that one
> is about CI checks and pull requests against the source tree.

## What is missing

614 six-piece tables. Peak RAM equals the raw table size, because generation
holds four bytes per cell resident:

| pawns | tables missing | RAM needed | machine |
| --- | --- | --- | --- |
| **0** | **269** | **28.9 GiB** | **32 GiB — the accessible tier** |
| 3 | 28 | 47.6 GiB | 64 GiB |
| 4 | 4 | 35.7 GiB | 64 GiB |
| 2 | 97 | 63.5 GiB | 96 GiB (64 is too tight) |
| 1 | 216 | 84.7 GiB | 96 GiB |

Start with the pawnless tier. It is the largest single group, it fits on
ordinary hardware, and every table in it is 28.9 GiB raw — about 1–3 GiB once
compressed. Expect roughly a day per table on four modern cores.

Seven pieces is not open: a 7-piece class needs about 2 TB resident and an
out-of-core generator that does not exist yet.

## How to contribute one

**1. Claim it first.** Open an issue on
[github.com/osick/helpmate-tablebase](https://github.com/osick/helpmate-tablebase/issues)
titled `claim: KBBBvkb` before you start. A day of CPU wasted on a duplicate
helps nobody. Claims lapse after three weeks of silence.

**2. Pull the existing corpus first.** This is not optional — it is the
difference between a day and a week. `gen` builds the full closure of
sub-slices reachable by captures and promotions, and leaves any table that
already exists alone. Every sub-slice of a 6-piece class is 5 pieces or
fewer, and all of those are already published:

**For more detailed setup instructions see [Setup](CONTRIBUTING-TABLES.md#Setup) at the bottom of the file**

```bash
git clone https://github.com/osick/helpmate-tablebase
cd helpmate-tablebase && make install       # builds the C++ core, installs the CLIs
helpmate-tables pull --tables ./tables --repo osick/helpmate-tables   # ~55 GiB
```

(There is no PyPI release yet, so it is a source build — see
[BUILD.md](BUILD.md) if `make install` gives you trouble.)

**3. Generate, writing compressed directly.** No separate conversion step:

```bash
helpmate gen KBBBvkb --tables ./tables --threads 4 --compress --progress
```

Leave headroom: the generator checks available memory before allocating and
refuses rather than inviting the OOM killer. Do not run it under `--force-ram`
to get around that.

**4. Sanity-check your own output** before submitting:

```bash
helpmate stats KBBBvkb --tables ./tables
helpmate probe "<some FEN in that material>" --tables ./tables
helpmate line  "<the same FEN>" --tables ./tables --all --max 5
```

`plane_size` in the stats output must match the index size for that material,
`max_dtm` should be a plausible small number (nothing in the published corpus
exceeds 34), and the lines must actually be legal mates.

**5. Open a pull request on the dataset.** Contributions land as PRs against
[huggingface.co/datasets/osick/helpmate-tables](https://huggingface.co/datasets/osick/helpmate-tables),
so nothing transits anyone's laptop and review happens where the data lives:

```bash
huggingface-cli login          # once; stores an HF token
helpmate-tables push --tables ./tables --repo osick/helpmate-tables \
                     --material KBBBvkb --create-pr
```

```
proposed KBBBvkb.hm
proposed KBBBvkb.stats.json
opened pull request: https://huggingface.co/datasets/osick/helpmate-tables/discussions/12
```

`--create-pr` sends the table and its sidecar as a **single** pull request,
and deliberately does not touch `manifest.json` — the maintainer regenerates
that after merging, and a PR that edited it would conflict with every other
open PR. Push only the material you generated.

### Who you are, on two different sites

The two halves of a contribution live on two services with **no shared
identity**, and nothing links them automatically:

| | how you authenticate | what it is used for |
| --- | --- | --- |
| **Hugging Face** | an API token — `huggingface-cli login`, or the `HF_TOKEN` environment variable | the dataset pull request. It is authored by whichever HF account owns the token. |
| **GitHub** | your normal GitHub account | the claim issue, and code contributions |

`helpmate-tables` never sees a GitHub credential, and GitHub never sees your
HF token. So a maintainer looking at a pull request sees an HF username and
has no way to connect it to the person who claimed the material.

**Close the loop yourself:** put your GitHub handle in the HF pull request
description, and paste the pull request URL back into your claim issue. Run
`huggingface-cli whoami` if you are unsure which account your token belongs
to — it is easy to be logged in as an old one.

## What gets checked before a merge

Being blunt about the state of this: **a donated table is currently reviewed,
not proven.** The checks that run today are these, in ascending cost.

- **Structural.** The reader rejects a file whose embedded material name does
  not match its filename, or whose `plane_size` disagrees with the index size
  computed for that material — the same identity check the generator applies
  to sub-tables before trusting them for a prune decision. A truncated or
  mislabelled file cannot survive this.
- **Block integrity.** `python3 tools/verify_corpus.py <TABLE>` decodes every
  zstd block of a compressed table and checks each frame's content checksum
  and length against the block index. It proves the bytes are sound, nothing
  more, and it is cheap: a 4 GB six-piece table takes under a minute. Run it
  on your own table before opening the pull request.
- **Statistical.** The `stats.json` sidecar is compared against the bytes it
  claims to describe: cell counts, the dtm histogram, `max_dtm`. A table
  generated from a different material, or at a different symmetry, does not
  produce a consistent sidecar.
- **Spot checks.** Random positions probed and their optimal lines replayed
  for legality and for actually being mate, plus shallow positions
  cross-checked against an independent python-chess search.

**What is not checked is full correctness.** Proving a donated table right
means regenerating it, which costs exactly what the donation saved. The
honest position is that a contributed table is trusted on the basis of
structural consistency, spot checks, and the contributor's reputation.

One piece of tooling would change that, and it does not exist yet:

**`helpmate verify <TABLE>`** — a command running the structural and
statistical checks plus an oracle sample. The independent oracle
(`src/core/generator/oracle.cpp`, a from-scratch cooperative
iterative-deepening solver sharing only the move generator with the real
generator) already exists and already re-solves sampled positions during
generation, but it is reachable only from C++ tests. Exposing it would let
contributors verify their own work before submitting, and let anyone audit a
published table without regenerating it.

That is the single most valuable code contribution available to this project
right now. If you would rather write C++ than burn a week of CPU, write that.

## Determinism, and why it matters here

Generation is required to be byte-identical whether run with one thread or
many, and that is asserted by tests. So two people generating the same
material on the same version should produce identical files. If you have
spare capacity and no appetite for a fresh material, **regenerating an
existing table and reporting whether the sha256 matches the manifest is a
real contribution** — it converts a trusted table into a verified one.

## Credit

Every merged table is credited by material and contributor in the dataset
card. If you would rather not be named, say so in the claim issue.

The first outside contribution came from **T31M**: fifteen tables, KRBvkqq
through KRBvkpp (issue #41, dataset PR #1), computed on a 192-thread,
369 GiB machine — including five one- and two-pawn tables from the 96 GiB
tier. The setup instructions below are theirs too (#42).

## Setup

### Tablebase

These instructions are examples using Ubuntu and should be easily applicable to other Linux distributions
**Note** this assumes a minimal fresh installation (e.g. AWS EC2 instance)

```bash
# minimal requirements for building (add other packages as you please)
sudo apt update && sudo apt install python3-venv python3-dev build-essential libzstd-dev -y
git clone https://github.com/osick/helpmate-tablebase && cd helpmate-tablebase
python3 -m venv --prompt tablebase .venv && source .venv/bin/activate && make install && mkdir -p tables
export HF_TOKEN=<if you want to> && helpmate-tables pull --tables ./tables --repo osick/helpmate-tables  # ~55 GiB
```

### Huggingface

Official documentation: https://huggingface.co/docs/huggingface_hub/guides/cli

```bash
# install "hf" cli
curl -LsSf https://hf.co/cli/install.sh | bash
# should prompt / already login if HF_TOKEN is set
hf auth login
hf auth whoami
# example push for table
helpmate-tables push --tables ./tables --repo osick/helpmate-tables \
                     --material KBBBvkb --create-pr
```
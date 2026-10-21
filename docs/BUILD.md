# Building helpmate

Everything needed to build the C++ CLI/library, run the test suites, measure
coverage, and build the Python package — including the offline/pre-fetched
dependency workflow for machines whose git configuration rewrites GitHub HTTPS
URLs to SSH.

## Prerequisites

| Requirement | Version | Used for |
|---|---|---|
| GCC (`g++`) | ≥ 13 | C++20 compiler for the core, tests and CLI |
| libzstd | any recent (`libzstd-devel` on openSUSE, `libzstd-dev` on Debian/Ubuntu) | block-compressed tables (v0.7.5+) |
| CMake | ≥ 3.24 (`cmake_minimum_required` in `CMakeLists.txt`) | build system |
| GNU make | any recent | convenience targets (`make build`, `make test`, …) |
| git | any recent | first-configure `FetchContent` clone of the three dependencies |
| Python | ≥ 3.9 | optional: the `helpmate` Python package (`pip install .`) |
| gcovr + `gcov-13` | any recent gcovr | optional: `make coverage` |
| pytest, python-chess ≥ 1.10 | — | optional: the Python test suite (installed by `pip install -e .[dev]`) |
| zstandard ≥ 0.22, numpy ≥ 1.24, python-chess ≥ 1.10, pyarrow ≥ 14 | — | `helpmate-tables verify` and the corpus statistics (the `verify` extra of `helpmate-api`, installed by `make install`) |

The build is developed and tested with GCC 13 on Linux. On distributions whose
default `g++`/`cc` predate GCC 13 (e.g. openSUSE Leap, where this project was
developed), point the build at a newer compiler explicitly:

```bash
CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13 make test
```

If your distribution's CMake is older than 3.24, a user-local CMake works fine
(e.g. `pip install cmake`, or a binary release on your `PATH` — the development
box uses one in `~/.local/bin`).

## Dependencies (FetchContent)

The first CMake configure fetches three pinned dependencies with
`FetchContent` into `build/_deps/`:

| Dependency | Pin | Role |
|---|---|---|
| [osick/ChessMG](https://github.com/osick/ChessMG) | commit `efbe11d9fe85ce186aadfbefa813818c03ae2c18` | move generation core |
| [Catch2](https://github.com/catchorg/Catch2) | `v3.5.4` | C++ test framework |
| [nlohmann/json](https://github.com/nlohmann/json) | `v3.11.3` | stats sidecar and Python-facing JSON |

After that first fetch, rebuilds are fully offline — the sources stay under
`build/_deps/` and nothing is re-cloned.

### Offline / pre-fetched builds (and the HTTPS→SSH gitconfig pitfall)

On machines whose `~/.gitconfig` rewrites `https://github.com/` to SSH (via
`url.….insteadOf`), any fresh `FetchContent` clone triggers an SSH passphrase
prompt — including the *separate* CMake configure that `pip install` runs (see
[Python package](#python-package-pip)). Two ways around it:

1. **Reuse already-fetched sources** (preferred; this is exactly what
   `make coverage` does). Point CMake at an existing `build/_deps` from any
   earlier configure:

   ```bash
   cmake -S . -B <builddir> \
     -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
     -DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src \
     -DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src \
     -DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src
   ```

   With `FETCHCONTENT_FULLY_DISCONNECTED=ON` CMake never touches the network
   (or git) for these dependencies.

2. **One-off fetch with the rewrite disabled**: run the first configure with
   `GIT_CONFIG_GLOBAL=/dev/null` so the `insteadOf` rewrite doesn't apply, then
   build normally (rebuilds are offline anyway).

On CI runners and ordinary machines without such rewrites, plain HTTPS cloning
works out of the box and none of this is needed.

## Package layout

The C++ tree lives under `src/core/` (the engine: generator, indexing,
probe, storage) with the CLI and Python bindings as thin consumers in
`src/packages/cli/` and `src/packages/bindings/`. Above that, three
separately installable distributions, each with its own
`pyproject.toml`/`CMakeLists.txt` and its own test suite under
`src/packages/<name>/tests/`:

| Distribution | Path | Contains |
|---|---|---|
| `helpmate` | root `pyproject.toml` (builds `src/core` + `src/packages/cli` + `src/packages/bindings`) | the compiled `helpmate` CLI binary and the `helpmate` Python module |
| `helpmate-api` | `src/packages/api/` | the FastAPI service (`helpmate-server`) and `helpmate-tables` |
| `helpmate-web` | `src/packages/web/` | the static dashboard, served by `helpmate-server` when installed |

`helpmate-api` depends on `helpmate`, and nothing is published to PyPI yet,
so they must install in dependency order — `make install` does this for all
three:

```bash
make install
# equivalent to:
python -m pip install .
python -m pip install './src/packages/api[verify]' ./src/packages/web
```

The `verify` extra (zstandard, numpy, python-chess, pyarrow) is what
`helpmate-tables verify` and the statistics (`stats-push`, `accept`) need;
without it they stop with an error naming the missing package and the
`pip install './src/packages/api[verify]'` that fixes it.

## Makefile targets

The Makefile is a thin wrapper over CMake; every target can be prefixed with
`CXX=… CC=…` as shown above. Variables: `BUILD` (default `build`), `COVBUILD`
(default `build-cov`), `GCOV` (default `gcov-13`).

### `make configure`

Runs `cmake -S . -B build`. `CMAKE_BUILD_TYPE` defaults to `Release` (set in
`CMakeLists.txt` when unspecified).

### `make build`

Configures (if needed) and runs `cmake --build build -j`. Produces:

- `build/helpmate` — the CLI binary,
- `build/helpmate_tests` — the Catch2 test binary,
- static libraries `helpmate_core` and `chessmg_core`.

### `make test`

Builds, then runs the **fast suite** via
`ctest --test-dir build --output-on-failure`: the Catch2 cases *not* tagged
`[slow]` (the CMake test discovery uses the spec `~[slow]`) plus the CLI
integration tests (`cli_gen`, `cli_probe`, …). Note ctest is run without `-j`;
keep it sequential — a pre-existing shared-temp-dir race in `test_probe.cpp`
shows up only under parallel ctest.

### `make slowtest`

Runs `./build/helpmate_tests "[slow]"` — the exhaustive/multithreaded
determinism cases excluded from `make test` (full KPvkp closure generation,
N-thread vs 1-thread byte-identity; tens of minutes each).

### `make stress TABLES=<dir> [ITERS=n]`

Regression stress for the 5-piece generation crash investigation (bug #21):
repeatedly runs the oversubscribed `KNvkqr` root-slice generation via
`tests/stress_oversubscribed_gen.sh` (default `ITERS=5`). Requirements:

- `TABLES` must point at a directory already holding the cached sub-slice
  tables for `KNvkqr` (generate them once first);
- `taskset` must be available (which is why this cannot be a ctest case);
- use a **stock Release build** — instrumented/sanitizer builds mask the
  original fault (see the script header).

### `tools/bench_compression.py` — the block-compression performance gate

`docs/ROADMAP.md` makes v0.7.5's block-compressed table format conditional on
three measured numbers (compression ratio, warm-probe latency, generation
wall-clock — see `docs/superpowers/specs/2026-08-02-block-compression-design.md`
and the [Table format](USAGE.md#table-format) section of `docs/USAGE.md` for
the numbers that cleared the gate). Re-run it with:

```bash
taskset -c 0-3 python3 tools/bench_compression.py --material KQvk
taskset -c 0-3 python3 tools/bench_compression.py --material KRvk
```

For a table large enough to actually exercise the reader's decompressed-block
cache, point `--tables` at a directory holding an existing real table (copied
out of `~/tb` first — the script refuses to run with `--tables` under `~/tb`
directly, see its `--help`) and skip regenerating it:

```bash
cp ~/tb/KBvkbn.hm ~/tb/KBvkbn.stats.json /path/to/staging/
taskset -c 0-3 python3 tools/bench_compression.py --material KBvkbn \
    --tables /path/to/staging --skip-gen
```

It reports the compressed/raw ratio, median warm- and cold-probe latency
(raw vs. compressed, via the `helpmate` Python bindings — rebuild the
extension first if it predates your working tree, the script warns if it
looks stale), and `helpmate gen` wall-clock with and without `--compress` on
the same material into fresh `mktemp -d` directories. Every scratch directory
it creates is removed on exit unless `--keep-scratch` is given, and every
subprocess it launches (`helpmate gen`/`compact`) runs under `taskset -c
0-3` regardless of how the script itself was invoked.

### `make coverage`

Line/function/branch coverage of `src/` with gcovr. It:

1. configures a *separate* tree `build-cov/` with `-DHELPMATE_COVERAGE=ON
   -DCMAKE_BUILD_TYPE=Debug` (adds `--coverage -O0 -g` to `helpmate_core`
   only; the normal `build/` tree is untouched),
2. reuses the dependency sources already under `build/_deps` via
   `FETCHCONTENT_FULLY_DISCONNECTED` + `FETCHCONTENT_SOURCE_DIR_*` — so **run
   `make build` or `make test` at least once first**; it never clones anything,
3. runs the fast suite in the coverage tree,
4. runs gcovr and prints the summary, writing an HTML report to
   `build-cov/coverage/index.html` and the text summary to
   `build-cov/coverage-summary.txt`.

Prerequisite: `pip install gcovr` into whatever Python environment provides
your dev tooling.

**`GCOV=gcov-13`**: gcovr must invoke the `gcov` binary matching the GCC
version that compiled the coverage build. The distro's default `gcov` is often
an older system-GCC version and hard-errors with "Version mismatch gcc/gcov"
against a GCC-13 build; the Makefile therefore defaults to `GCOV=gcov-13`.
Override with `make coverage GCOV=/path/to/gcov-N` if you compile with a
different GCC. The recipe also passes `--gcov-ignore-parse-errors=all`: GCC's
coverage counters are not thread-safe (upstream GCC bug 68080), and the
multithreaded generator tests can produce "suspicious hit" records that would
otherwise abort gcovr (see the Coverage section of the README for the honest
interpretation of the resulting numbers).

### `make clean`

Removes `build/`, `build-cov/` and `build-booklet/`.

### `make install`

`python -m pip install .` then `python -m pip install
'./src/packages/api[verify]' ./src/packages/web` — all three distributions,
in the order `helpmate-api` requires, with the `verify` extra that
`helpmate-tables verify` needs.

If this hangs with no output and no error, see "`pip install .` hangs with no
output and no error at all" under [Troubleshooting](#troubleshooting) — it's
the HTTPS→SSH gitconfig pitfall, and `make install
GIT_CONFIG_GLOBAL=/dev/null` (GNU Make passes command-line variables through
to the recipe's environment) works around it without editing global git
config.

### `make install-dev`

Same three distributions, each installed with its `[dev]` extra
(`.[dev]`, `./src/packages/api[dev,verify]`, `./src/packages/web[dev]`), so
`make install-dev && make test-api` (or `test-web`, `test-bindings`,
`test-repo`) has pytest/httpx/playwright available — plain `make install`
installs no dev extras and those targets fail on a missing `pytest`. Subject
to the same `GIT_CONFIG_GLOBAL` note as `make install` above.

### `make install-bin` — the CLI binary alone, no Python

`make install` above puts `helpmate` on `PATH` as part of the wheel, which is
the right answer if you also want the Python bindings, the API server or the
dashboard. If you want **only** the command-line binary — a system package, a
container layer, a machine with no Python — install it natively:

```bash
sudo make install-bin                 # /usr/local/bin/helpmate (GNU default)
make install-bin PREFIX=$HOME/.local  # rootless; already on PATH on most distros
make install-bin DESTDIR=/tmp/stage   # stage into a package root
```

`PREFIX` defaults to `/usr/local`, so the bare form needs root. `DESTDIR` is
prepended to the prefix in the usual packaging two-step, giving
`/tmp/stage/usr/local/bin/helpmate`.

This is a thin wrapper over `cmake --install $(BUILD) --prefix ...` — the
install rule lives in `src/packages/cli/CMakeLists.txt` and is the same one
scikit-build-core uses when building the wheel, just with a different
destination. There is deliberately no bespoke install script: one would be a
second source of truth to keep in sync with the build.

The binary is the only installed artifact and it is self-contained — the
dependencies are static, and tables are located at runtime via `--tables`, so
nothing else needs installing. `make uninstall-bin` removes it (honouring the
same `PREFIX`/`DESTDIR`); CMake generates no uninstall rule of its own, and a
hand-rolled manifest-walking one is how packaging accidents happen.

Note this installs the binary built by whatever compiler configured `build/`.
On a distribution whose default `g++` predates GCC 13, configure with the
newer compiler first (see [Prerequisites](#prerequisites)) or the binary will
not build at all.

### Per-package test targets

Each installable distribution owns its own test suite; these wrap the
commands the CI jobs run:

- `make test-core` — builds, then `$(BUILD)/helpmate_tests "~[slow]"` (the
  same Catch2 cases `make test`'s ctest run drives, invoked directly).
- `make test-cli` — builds, then `ctest --test-dir $(BUILD) -R "^cli_"` (just
  the CLI integration tests).
- `make test-api` — `pytest src/packages/api/tests` (requires `helpmate` and
  `helpmate-api` installed with the `dev` extra). Two cases in
  `test_static.py` additionally need a resolvable dashboard — with
  `helpmate-web` installed they assert it is served; without it they skip
  rather than fail, since a package must be independently verifiable without
  the rest of the repo.
- `make test-web` — `make jstest` then `pytest src/packages/web/tests/ui`
  (requires `helpmate`, `helpmate-api` and `helpmate-web` installed with the
  `dev` extra — the UI conftest imports `helpmate` directly and calls
  `generate()` to build the fixture closure it drives Playwright against).
- `make test-bindings` — `pytest src/packages/bindings/tests`.
- `make test-repo` — `pytest tests/repo`, the repo-level checks (e.g. that
  `VERSION` agrees with every `pyproject.toml` and `helpmate --version`).
- `make test-all` — `test` (the C++/CLI ctest suite, which subsumes
  `test-core` and `test-cli` above) plus the four package-level targets
  (`test-api`, `test-web`, `test-bindings`, `test-repo`) and `test-site` (see
  [Static showcase](#static-showcase-site)).

### `make format-check` / `make format`

`make format-check` runs `git clang-format --diff` against `BASE` (the merge
base with `origin/main`, same as CI) and fails if any changed C++ line isn't
formatted per `.clang-format`; `make format` applies the fix in place. This is
enforced on **changed lines only**, never on the whole tree: measured at
0.21.0 with clang-format 22.1.8 (`clang-format --style='{BasedOnStyle:
Google}' --output-replacements-xml $(git ls-files 'src/**/*.cpp' 'src/**/*.h')
| grep -c '<replacement '`, 78 files, 14,900 lines of C++), stock Google
style (`ColumnLimit: 80`, the default) makes 12,868 replacements. Adding just
`ColumnLimit: 100` to that same stock style (`--style='{BasedOnStyle:
Google, ColumnLimit: 100}'`) brings it down to 11,493 — the difference is
line-wrapping. The tuned `.clang-format` committed here still makes 494
(same command, no `--style` override needed since clang-format picks up
the committed file) — reformatting anywhere near that much of the most
carefully reviewed code in one commit would be churn, not review. A PR is
required to format the lines it touches; the rest of the tree converges as it
is naturally edited.

## Plain CMake (without make)

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j
ctest --test-dir build --output-on-failure   # fast suite
./build/helpmate_tests "[slow]"              # slow suite, explicitly
```

Options: `-DHELPMATE_COVERAGE=ON` (coverage instrumentation on
`helpmate_core`), `-DHELPMATE_PYTHON=ON` (build the pybind11 module; normally
you never set this by hand — `pip install` does).

## Python package (pip)

```bash
pip install .            # or: pip install -e .[dev] for the pytest/python-chess dev extras
```

`helpmate` (the root `pyproject.toml`) is the only one of the three
distributions that compiles anything — `helpmate-api` and `helpmate-web`
(`src/packages/api/`, `src/packages/web/`) are plain hatchling wheels with no
C++ involved. Install all three, in dependency order, with `make install` or

```bash
pip install . './src/packages/api[verify]' ./src/packages/web
```

(`helpmate-api` depends on `helpmate`, and nothing is published to PyPI yet,
so installing out of order sends pip looking for the name upstream).

### Virtual environments, and why `pipx install ./src/packages/api` fails

A venv is the ordinary way to install the three distributions without
touching the system Python. The order is the only thing that matters:

```bash
python3 -m venv ~/.venvs/helpmate && source ~/.venvs/helpmate/bin/activate
make install        # pip install .  then  pip install './src/packages/api[verify]' ./src/packages/web
```

`pipx` is a reasonable thing to reach for, because `helpmate-api` ships two
console scripts (`helpmate-server`, `helpmate-tables`). It fails on this
repository unless you tell it about `helpmate`:

```
$ pipx install ./src/packages/api
pip seemed to fail to build package: fastapi>=0.110
ERROR: Could not find a version that satisfies the requirement
       helpmate<0.20,>=0.19.0 (from helpmate-api) (from versions: none)
```

**The FastAPI line is a red herring.** pipx guesses at the culprit from
where pip's output stopped, and pip happened to be collecting FastAPI when
the resolution failed. The real message is the one below it: `from versions:
none` means the index has no project of that name at all, because `helpmate`
is built from this tree and is not on PyPI. pipx makes the usual fix
insufficient: it puts every application in its **own** isolated venv, so a
`helpmate` installed globally, or in the venv you happen to be standing in,
is invisible to it.

Install the root distribution into that same isolated venv first, with
`--preinstall` (repeatable; take the dashboard too if you want
`helpmate-server` to serve it):

```bash
pipx install ./src/packages/api \
  --preinstall "$PWD" \
  --preinstall "$PWD/src/packages/web"
```

That compiles the C++ core a second time, inside pipx's venv, which takes a
few minutes and needs the same CMake and compiler as an ordinary build — and
it re-runs `FetchContent`, so the hang described below applies here too
(`GIT_CONFIG_GLOBAL=/dev/null pipx install …`).

Packaging of `helpmate` itself is via scikit-build-core + pybind11 (build
requirements are fetched from PyPI over HTTPS). `pip install` runs **its
own** CMake configure with `-DHELPMATE_PYTHON=ON` — entirely separate from
the plain-CMake `build/` tree — and compiles the same `helpmate_core` C++
sources into the extension module `helpmate._helpmate`. Requires Python ≥
3.9 plus the same CMake ≥ 3.24 and GCC ≥ 13 (export `CC`/`CXX` if your
defaults are older).

Because that configure is separate, it re-runs `FetchContent` — on a machine
with the HTTPS→SSH gitconfig rewrite, pre-seed the dependency sources exactly
as in the offline workflow above, passed through `SKBUILD_CMAKE_ARGS`
(semicolon-separated):

```bash
SKBUILD_CMAKE_ARGS="-DFETCHCONTENT_FULLY_DISCONNECTED=ON;\
-DFETCHCONTENT_SOURCE_DIR_CHESSMG=$PWD/build/_deps/chessmg-src;\
-DFETCHCONTENT_SOURCE_DIR_CATCH2=$PWD/build/_deps/catch2-src;\
-DFETCHCONTENT_SOURCE_DIR_JSON=$PWD/build/_deps/json-src" \
  pip install -e .[dev]
```

(run an ordinary `make build` first so `build/_deps` is populated; optionally
also set `SKBUILD_BUILD_DIR=<dir>` to keep and reuse scikit-build-core's build
tree between installs.)

**Named symptom: `pip install .` hangs with no output and no error**, not
even a passphrase prompt you can answer. This is a different failure mode
from the SSH-prompt case above, and easy to misdiagnose because there is
nothing on stderr to search for. `pip`'s isolated build environment inherits
`HOME`, so a `~/.gitconfig` with `url."git@github.com:".insteadOf =
https://github.com/` still applies to the `FetchContent` clone inside the
pip build — but the clone runs from a subprocess with no attached terminal,
so instead of an SSH passphrase prompt on stdin, it pops a **GUI** passphrase
dialog (`ssh-askpass` or similar). On a headless box, over SSH, or on a CI
runner, that dialog never appears anywhere you can see or answer it, and the
install just sits there indefinitely — no timeout, no error. If `pip
install .` (or `pip install -e .[dev]`) hangs with no output for more than a
few seconds and `build/_deps` isn't already populated, this is almost
certainly it. Fix: bypass the global gitconfig for the install, the same as
the plain-CMake case —

```bash
GIT_CONFIG_GLOBAL=/dev/null pip install .
```

— or pre-seed `build/_deps` and pass `SKBUILD_CMAKE_ARGS` as above so the
pip build's CMake configure never touches the network at all.

Run the Python tests with:

```bash
pytest src/packages/bindings/tests              # fast (~seconds)
pytest src/packages/bindings/tests --run-slow   # + exhaustive KQvk cross-check (~10 min)
```

## Static showcase (site/)

Two stages, run in that order. `site/data/*.json` is committed (the Pages
workflow has no tables); `site/material/*.html` and `site/themes.html` are
generated on every build and git-ignored.

### Stage 1: mining problem data from the corpus

```bash
python3 tools/build_problems.py --tables ~/tb [--binary ./build/helpmate] \
    [--out site/data] [--material NAME ...]
```

`make site-data` runs exactly this, with `TABLES` defaulting to `~/tb`;
override it on the command line (`make site-data TABLES=/path/to/tables`)
for a different corpus location.

Needs a real corpus -- 592 tables, 1204.7 GiB block-compressed, as of 0.21.
A full run took 80 minutes on this machine when the corpus had 302 tables:
the sixteen six-piece tables dominated it at roughly 150 seconds each,
five-piece tables averaged about 14 seconds, and four-piece and smaller were
negligible. The corpus now holds 306 six-piece tables, and a full run at 592
tables has not been timed. The script runs one `mine` at a time and does not
pass `mine --threads`, so for new materials use `--material`, or
`helpmate-tables pages --tables ~/tb --missing --jobs N`, which mines the
missing pages in parallel jobs and ships them as a docs PR (see
[CONTRIBUTING-TABLES.md](CONTRIBUTING-TABLES.md#for-the-maintainer)).
Materials are processed alphabetically and six-piece names sort first, so a
full run looks alarmingly slow at first before it accelerates -- that is
normal, not a hang.

Per material, two calls to `helpmate mine --jsonl --themes --solutions` find
up to three deepest positions with a unique solution and up to three deepest
positions with exactly two solutions that differ in both their first and
last move (a "strict dual"); the depths themselves come from the stats
sidecar's `uniqueness` map and are exact, so nothing needs scanning to find
them. Output: one document per material at `site/data/material/<NAME>.json`
(592 of them as of 0.21, including the 140 markers -- material in which no
helpmate exists) plus the two aggregate files `site/data/themes.json` and
`site/data/index.json`. The last full run, at 302 materials, reported `wrote
302 materials, 24 themes, 0 failure(s)`; the committed data is now 6.0 MB of
material documents, `themes.json` 1.9 MB and `index.json` 73 KB.

`--material NAME` (repeatable) scopes a run to specific materials. A scoped
run merges into the two aggregate files rather than replacing them -- each
touched material's prior contribution is dropped from `themes.json` first,
then its new one added -- so a partial run never wipes the rest of the corpus
out of the site index.

Worth a note on the depths: the deepest strict dual is usually one ply
shallower than the deepest dual overall, because at the very deepest depth
where a dual exists at all, the two solutions almost always share a first or
a last move. Both depths are recorded (`deepest_dual_dtm`,
`strict_dual_dtm` in the stats), and the material page states both and
explains the difference rather than quietly showing the shallower number.

### Stage 2: rendering the pages (`make site`)

```bash
python3 tools/render_site.py --data site/data --out site
```

Reads only the JSON stage 1 committed -- no corpus, no network, and
deliberately no third-party Python: `.github/workflows/pages.yml` builds the
site with `actions/setup-node` and no pip step, so anything `render_site.py`
imported beyond the standard library would simply not be there in CI. It
writes `site/material/<NAME>.html` (one per material, including the
markers) and `site/themes.html`, a corpus-wide index of every theme linking
to every problem that shows it. Boards step through the `{san, uci, fen}`
triples the JSON already carries, so these pages need no chess logic of
their own. Output is derived and deterministic, so it is git-ignored rather
than committed, and rebuilt on every `make site`.

**Editing page markup never needs the corpus.** Changing `render_site.py`'s
HTML only needs `make site` against whatever JSON is already committed;
only regenerating the problem data itself needs stage 1 and a real corpus.

`make test-site` runs `make site` and then the site's node tests
(`site/tests/*.test.js`, plus `node --check` on every `site/js` file); it is
part of `make test-all` and the Pages CI gate.

## Continuous integration

`.github/workflows/ci.yml` runs on every push to `main` and every pull
request: the C++ Release build + fast suite + a gen/probe smoke test, the
Python package install + pytest, the dashboard and showcase browser tests,
lint (ruff, `node --check`), mypy, the changed-lines C++ format check, and an
informational gcovr coverage summary. Every job but the coverage summary is a
required check (see [CONTRIBUTING.md](CONTRIBUTING.md)).
`.github/workflows/release.yml` runs on `v*` tags: build, fast tests, and a
GitHub Release with a `helpmate-<tag>-linux-x86_64.tar.gz` binary tarball,
its `.sha256` and `docs/DEEPEST.pdf`. `pages.yml` builds the showcase and
deploys it to GitHub Pages (on pushes that touch it, daily, and after each
Claims run), `claims.yml` keeps the status comment on every claim issue
current, and `stats-check.yml` checks daily, and after each Pages run, that
the published statistics cover every table of the manifest.

## Troubleshooting

- **"Version mismatch" from gcov during `make coverage`** — your `gcov` doesn't
  match the compiling GCC; pass `GCOV=gcov-13` (default) or the matching
  `gcov-N`.
- **SSH passphrase prompt during configure or `pip install`** — your gitconfig
  rewrites GitHub HTTPS URLs to SSH and `FetchContent` is trying to clone; use
  the pre-fetched `_deps` workflow (`FETCHCONTENT_FULLY_DISCONNECTED` +
  `FETCHCONTENT_SOURCE_DIR_*`, via `SKBUILD_CMAKE_ARGS` for pip) or a one-off
  `GIT_CONFIG_GLOBAL=/dev/null` configure.
- **`pip install .` hangs with no output and no error at all** — not an SSH
  prompt, a *silent* hang: pip's isolated build environment inherits `HOME`,
  so the same gitconfig rewrite above triggers a GUI passphrase dialog
  (`ssh-askpass`) instead of a terminal prompt, and that dialog is invisible
  and unanswerable over SSH or in CI. See [Python package
  (pip)](#python-package-pip) for the full explanation; fix is the same
  `GIT_CONFIG_GLOBAL=/dev/null pip install .`, or pre-seed `build/_deps`.
- **C++20 errors / unknown flags at configure time** — the default compiler is
  too old; export `CXX=/usr/bin/g++-13 CC=/usr/bin/gcc-13` (adjust paths) and
  wipe the build dir before re-configuring.
- **`cmake` too old (< 3.24)** — install a user-local CMake (`pip install
  cmake` or a binary release) and put it first on `PATH`.
- **`make coverage` fails with missing `build/_deps/...-src`** — the coverage
  tree reuses sources from the normal tree; run `make build` (or `make test`)
  once first.
- **Flaky failures when running ctest with `-j`** — known `test_probe.cpp`
  shared-temp-dir race under parallel ctest only; run ctest sequentially (as
  `make test` does).
- **`gcovr: command not found`** — `pip install gcovr` into the Python
  environment on your `PATH`.

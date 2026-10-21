# Contributing

> Donating CPU time or tables rather than code? See
> [CONTRIBUTING-TABLES.md](CONTRIBUTING-TABLES.md).

`main` is protected: every pull request must pass six required checks before
the merge button unlocks. A red check blocks the merge however trivial the
change looks; only a repository admin can override it.

## The six required checks

These are CI jobs from `.github/workflows/ci.yml` — every job except
`Coverage summary (informational)`, which is `continue-on-error: true` and
exists to print a gcovr summary in the log, not to gate anything.

| Check (job name) | What it runs |
| --- | --- |
| `C++ build, fast tests, CLI smoke` | Configures and builds the C++ core in Release, runs the fast Catch2 suite (`~[slow]` — the exhaustive closures are excluded), then an end-to-end `gen`/`probe` smoke test against the real `helpmate` binary. |
| `Python bindings` | Installs all three distributions (`helpmate`, `helpmate-api`, `helpmate-web`, in that dependency order) and runs the bindings, API, and repo-consistency test suites. |
| `Dashboard (browser tests)` | Installs the three distributions plus Playwright's Chromium, runs the pure-JS helper tests (`make jstest`), then the Playwright UI suite against the dashboard, then renders the showcase (`make site`) and runs its browser tests. |
| `Lint (ruff, node --check)` | `make lint` — `ruff check .` plus a `node --check` syntax gate over every dashboard JS file (each is checked through a temp `.mjs` copy so Node's CJS/ESM auto-detection doesn't stop parsing early — see the Makefile's `lint` target for why). |
| `Type check (mypy)` | `make typecheck` — `python -m mypy` over the Python sources, with the compiled `helpmate` extension covered by `ignore_missing_imports` rather than actually built (a C++ build would make a type-check job take ten minutes for no reason). |
| `C++ format (changed lines)` | `make format-check BASE=<merge-base with the PR's base branch>` — `git clang-format` restricted to the lines the PR actually touches, not the whole tree. See below for why. |

## Reproducing every check locally

One line each:

```bash
make lint         # ruff + node --check
make typecheck    # mypy
make format-check # clang-format, changed lines only (see below)
make test         # C++ build + fast ctest suite (the "cpp" job)
make test-all     # everything: test + test-api + test-web + test-bindings + test-repo + test-site
```

`make test-all` is the local equivalent of the `Python bindings` and
`Dashboard (browser tests)` jobs combined, plus the core C++ suite. Prefix any
of these with `taskset -c 0-3` if you're on a machine where you want to keep
the build off certain cores — CI doesn't need this, it's a local-machine
convenience only.

## Why ruff's E701/E702/E401 are disabled

Three of ruff's default rules are turned off project-wide in `ruff.toml`:
`E701`/`E702` (multiple statements on one line) and `E401` (combined imports).
All 55 findings they produced on this codebase were deliberate — paired setup
lines like `hub_dir.mkdir(); cache.mkdir()`, and combined imports like
`import pytest, helpmate` — not defects, so they're a permanent ruleset
decision, not a baseline of grandfathered violations. Every other default
rule stays enabled and passes clean on the whole tree; if you're tempted to
re-enable one of these three, read the comment above `ignore = [...]` in
`ruff.toml` first.

## Why C++ formatting only checks changed lines

`clang-format` under a stock Google style makes 12,868 replacements in the
14,900 lines of C++ under `src/` (clang-format 22.1.8, measured at 0.21.0;
the command is in [BUILD.md](BUILD.md#make-format-check--make-format)), in
the most carefully reviewed code in the project. Even after tuning indent
width, column limit, access-modifier offset, short-form allowances, and
pointer alignment (`.clang-format`), it still makes 494. Enforcing that as a
single whole-tree reformat would produce one unreviewable commit, so instead
`make format-check` (and the CI job) diffs only the lines a change actually
touches against the merge base, via `git clang-format --diff`. The tree
converges toward the style as it's edited, not all at once.

`make format-check` distinguishes two different kinds of failure, which read
differently in the log:
- **It could not run at all** — `clang-format` isn't installed, or `BASE`
  doesn't resolve to a commit (e.g. a shallow checkout without the base
  branch fetched). This always exits with status 2, and the message says
  "format-check: ... " naming exactly what's missing. This means your local
  environment is broken, not your patch.
- **It ran and found misformatted lines.** It prints the diff and exits 1
  with `C++ formatting: run 'make format' and commit`. This means your patch
  needs `make format` (which reformats only the lines `BASE` bounds, same as
  the check) and a commit.

Note that GNU Make itself always reports a failed recipe as exit code 2
regardless of what the recipe underneath exited with, so from the shell alone
`make format-check`'s own exit code cannot tell you which of the two cases
happened — the message text is what to read.

## The `GIT_CONFIG_GLOBAL=/dev/null` install trap

If `pip install` (or a fresh CMake configure) hangs with no output and no
error, it's very likely this: pip's isolated build environment inherits
`HOME`, so if your `~/.gitconfig` rewrites `https://github.com/` to SSH (via
`url.….insteadOf`), CMake's `FetchContent` clone goes out over SSH instead of
HTTPS and can pop an invisible GUI passphrase dialog with no timeout and no
error on the terminal. Fix it by bypassing the global gitconfig for the one
invocation that builds C++:

```bash
GIT_CONFIG_GLOBAL=/dev/null python -m pip install -e . --no-build-isolation
```

This isn't hardcoded into the Makefile or `pyproject.toml` because it would
also disable legitimate global config (proxies, credential helpers) for
everyone, including people without the rewrite. See
[Offline / pre-fetched builds (and the HTTPS→SSH gitconfig pitfall)](BUILD.md#offline--pre-fetched-builds-and-the-httpsssh-gitconfig-pitfall)
for the full explanation and the alternative of reusing an already-fetched
`build/_deps` tree instead.

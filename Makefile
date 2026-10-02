BUILD ?= build
COVBUILD ?= build-cov
# Where `make booklet` puts the typeset PDF and LaTeX's intermediate files.
BOOKLET ?= build-booklet
# gcov binary matching the GCC version the coverage build is compiled with (the
# distro's default `gcov` is typically an older system-GCC version and hard-errors
# with "Version mismatch gcc/gcov" against a GCC-13 build); override with
# `make coverage GCOV=/path/to/gcov-N` if your compiler isn't gcc-13.
GCOV ?= gcov-13
.PHONY: configure build test slowtest stress coverage clean jstest \
	install install-dev install-bin uninstall-bin test-core test-cli test-api test-web test-bindings test-repo test-all \
	lint typecheck format-check format docs-deepest site-data booklet
configure:
	cmake -S . -B $(BUILD)
build: configure
	cmake --build $(BUILD) -j
test: build
	ctest --test-dir $(BUILD) --output-on-failure

# Install all three distributions from this tree, in dependency order:
# helpmate-api requires helpmate, and nothing is on PyPI yet, so installing
# them out of order sends pip looking for the name upstream.
#
# If this hangs with no output and no error: see docs/BUILD.md's entry with
# that exact symptom. Short version: pip's isolated build env inherits HOME,
# so if ~/.gitconfig rewrites https://github.com/ to git@github.com:, CMake
# FetchContent's clone goes over SSH and can pop an invisible GUI passphrase
# dialog. Not hardcoded here because it would also disable legitimate global
# config (proxies, credential helpers); opt in per-invocation instead --
# GNU Make exports command-line variable assignments to the recipe's
# environment automatically, so this needs no plumbing in the recipe itself:
#   make install GIT_CONFIG_GLOBAL=/dev/null
install:
	python -m pip install .
	python -m pip install './src/packages/api[verify]' ./src/packages/web

# Same three distributions, with each one's [dev] extra so `make install-dev
# && make test-api` (etc.) has pytest/httpx/playwright available. Same
# GIT_CONFIG_GLOBAL note as `install` applies.
install-dev:
	python -m pip install ".[dev]"
	python -m pip install "./src/packages/api[dev,verify]" "./src/packages/web[dev]"

# Install just the `helpmate` CLI binary, with no Python involved. `make
# install` above already puts it on PATH as part of the wheel, so this is for
# people who want the binary alone -- a system package, a container layer, or
# a machine with no Python.
#
# PREFIX defaults to /usr/local (the GNU convention), which needs root:
#
#   sudo make install-bin                  # /usr/local/bin/helpmate
#   make install-bin PREFIX=$$HOME/.local  # rootless; already on PATH on most distros
#   make install-bin DESTDIR=/tmp/stage    # stage into a package root
#
# This wraps `cmake --install`, which is the mechanism -- there is no bespoke
# install script to keep in sync with the build. DESTDIR is honoured by cmake
# --install directly, so packagers get the usual two-step.
PREFIX ?= /usr/local

install-bin: build
	cmake --install $(BUILD) --prefix "$(PREFIX)"

# CMake generates no uninstall rule, and inventing one that deletes paths from
# a manifest is how packaging accidents happen. The binary is the only
# installed artifact, so removing it is a one-liner:
uninstall-bin:
	rm -f "$(DESTDIR)$(PREFIX)/bin/helpmate"

test-core: build
	$(BUILD)/helpmate_tests "~[slow]"
test-cli: build
	ctest --test-dir $(BUILD) --output-on-failure -R "^cli_"
# conftest.py imports `helpmate_server` directly (`from helpmate_server.app
# import create_app`), which resolves from site-packages, not the source
# tree, and the wheel is a copy rather than an editable install. Without this
# refresh a regression in existing API behaviour passes silently against a
# stale copy -- a new test would fail loudly on a missing symbol, but an old
# one would keep passing against old code. Same hazard as test-web below,
# same fix.
# GIT_CONFIG_GLOBAL=/dev/null: this machine's gitconfig rewrites HTTPS to SSH,
# and a stray fetch hangs on an invisible passphrase prompt.
# This install is a real side effect on whatever Python this runs under: fine
# in CI and in a venv, but on a PEP-668 externally-managed Python outside a
# venv it now hard-fails where it previously just ran the (possibly stale)
# suite -- run this target inside a venv on such a system.
test-api:
	GIT_CONFIG_GLOBAL=/dev/null python -m pip install -q ./src/packages/api
	python -m pytest src/packages/api/tests -v
# The UI fixture serves the INSTALLED helpmate_web package, not the source
# tree (conftest.py starts uvicorn, which imports it from site-packages), and
# the wheel is a copy rather than an editable install. Without this refresh a
# regression in the dashboard passes silently against a stale copy -- a new
# test would fail loudly, but an old one would keep passing on old assets.
# GIT_CONFIG_GLOBAL=/dev/null: this machine's gitconfig rewrites HTTPS to SSH,
# and a stray fetch hangs on an invisible passphrase prompt.
# This install is a real side effect on whatever Python this runs under: fine
# in CI and in a venv, but on a PEP-668 externally-managed Python outside a
# venv it now hard-fails where it previously just ran the (possibly stale)
# suite -- run this target inside a venv on such a system.
test-web: jstest
	GIT_CONFIG_GLOBAL=/dev/null python -m pip install -q ./src/packages/web
	python -m pytest src/packages/web/tests/ui -v
test-bindings:
	python -m pytest src/packages/bindings/tests -v
test-repo:
	python -m pytest tests/repo -v
test-all: test test-api test-web test-bindings test-repo test-site

# `node --check` on a plain `.js` file does automatic CommonJS/ESM detection:
# it tries a CJS parse first, and as soon as it hits the file's first
# `import`/`export` it concludes "this is a module" and stops validating --
# it does NOT then fully parse the rest of the file as ESM. Every dashboard
# JS file has its first import/export within the first ~9 lines, so a syntax
# error anywhere after that point is silently accepted (verified: an
# unterminated string appended to a copy of each file still exits 0 as
# `.js`, but exits 1 -- correctly -- once the same content is checked as
# `.mjs`, which forces unambiguous ESM parsing). So each file is copied to a
# temp `.mjs` path and checked there. Names are flattened (not just
# basename) so js/foo.js and js/lib/foo.js can't collide, and node's error
# output -- which names the temp path, not the real one -- has the temp path
# substituted back to the real source path before printing.
# `git ls-files` alone only lists tracked files, so a brand-new .js dropped
# into the tree and never `git add`-ed is invisible to it -- lint would exit
# 0 having checked nothing of the new file. `--others --exclude-standard`
# adds untracked-but-not-.gitignore'd files to the tracked set, so a new
# module is checked before it is ever staged.
lint:
	ruff check .
	@tmp="$$(mktemp -d)" || { echo "lint: cannot create a temp dir"; exit 2; }; \
	status=0; \
	for f in $$(git ls-files --cached --others --exclude-standard 'src/packages/web/helpmate_web/static/js/*.js' 'src/packages/web/helpmate_web/static/js/lib/*.js'); do \
	  copy="$$tmp/$$(echo "$$f" | tr '/' '_').mjs"; \
	  cp "$$f" "$$copy"; \
	  if ! err="$$(node --check "$$copy" 2>&1)"; then \
	    echo "lint: JS syntax error in $$f"; \
	    echo "$$err" | sed "s#$$copy#$$f#g" >&2; \
	    status=1; \
	  fi; \
	done; \
	rm -rf "$$tmp"; \
	exit $$status
typecheck:
	python -m mypy

# Formatting is enforced on the lines a change touches, not on the whole tree
# (see docs/BUILD.md for the measurement). Every condition that prevents the
# check from doing its job must exit non-zero: a gate that silently passes is
# worse than no gate.
#
# git-clang-format's --diff follows the `git diff --exit-code` convention:
# 0 = no differences, 1 = differences found (it ran fine either way), and
# only its own die() helper (bad BASE, missing clang-format binary, a failed
# internal git call, ...) exits >= 2 -- verified against the installed
# implementation (~/.local/lib/python3*/site-packages/clang_format/
# git_clang_format.py: print_diff() returns `git diff --exit-code`'s
# returncode; die() is sys.exit(2)). So status 0/1 both mean "ran
# successfully"; only >= 2 means "could not run".
BASE ?= $(shell git merge-base origin/main HEAD 2>/dev/null || echo HEAD~1)
format-check:
	@command -v clang-format >/dev/null 2>&1 || { \
	  echo "format-check: clang-format is not installed (pip install clang-format)"; exit 2; }
	@git rev-parse --verify -q "$(BASE)^{commit}" >/dev/null || { \
	  echo "format-check: BASE '$(BASE)' does not resolve to a commit"; exit 2; }
	@out="$$(mktemp)" || { echo "format-check: cannot create a temp file"; exit 2; }; \
	git clang-format -q --diff "$(BASE)" -- '*.cpp' '*.h' >"$$out" 2>"$$out.err"; st=$$?; \
	if [ $$st -ge 2 ]; then \
	  echo "format-check: git clang-format failed (exit $$st):"; cat "$$out.err" >&2; \
	  rm -f "$$out" "$$out.err"; exit 2; \
	fi; \
	if [ -s "$$out" ]; then \
	  cat "$$out"; rm -f "$$out" "$$out.err"; \
	  echo "C++ formatting: run 'make format' and commit"; exit 1; \
	fi; \
	rm -f "$$out" "$$out.err"
format:
	git clang-format $(BASE) -- '*.cpp' '*.h'

# Pure JS helpers (helpmate_web/static/js/lib) via Node's built-in test
# runner. No npm packages. A bare directory arg isn't recursed by `node
# --test` on the Node version this repo targets, so the JS test files are
# globbed explicitly.
jstest:
	node --test src/packages/web/tests/js/*.test.js

# Catch2 cases tagged [slow] (full KPvkp closure generation, KNvkq invariant sweep).
# Excluded from `make test` / ctest by catch_discover_tests' "~[slow]" spec.
slowtest: build
	$(BUILD)/helpmate_tests "[slow]"

# Task 21 regression stress: the oversubscribed KNvkqr root-slice run that is the only
# configuration ever observed to reproduce the crash. Needs taskset (so it cannot be a
# ctest case) and a tables dir already holding the 7 cached sub-slices; see the script
# header for why instrumented/sanitizer builds must NOT be used here.
#   make stress TABLES=/path/to/tables [ITERS=5]
TABLES ?=
ITERS ?= 5
stress: build
	@test -n "$(TABLES)" || { echo "usage: make stress TABLES=<dir with cached sub-slices> [ITERS=n]"; exit 2; }
	tests/stress_oversubscribed_gen.sh "$(TABLES)" $(ITERS)

# Line-coverage report for src/, in its own build dir (build-cov) so the
# normal optimized build is untouched. Reuses the sources FetchContent
# already vendored under $(BUILD)/_deps (run `make build` or `make test`
# at least once first) via FETCHCONTENT_FULLY_DISCONNECTED, so this never
# triggers a network git clone. Requires gcovr (pip install gcovr).
coverage:
	cmake -S . -B $(COVBUILD) -DHELPMATE_COVERAGE=ON -DCMAKE_BUILD_TYPE=Debug \
	  -DFETCHCONTENT_FULLY_DISCONNECTED=ON \
	  -DFETCHCONTENT_SOURCE_DIR_CHESSMG=$(CURDIR)/$(BUILD)/_deps/chessmg-src \
	  -DFETCHCONTENT_SOURCE_DIR_CATCH2=$(CURDIR)/$(BUILD)/_deps/catch2-src \
	  -DFETCHCONTENT_SOURCE_DIR_JSON=$(CURDIR)/$(BUILD)/_deps/json-src
	cmake --build $(COVBUILD) -j2
	ctest --test-dir $(COVBUILD) --output-on-failure
	mkdir -p $(COVBUILD)/coverage
	gcovr --root . --filter 'src/core/' --filter 'src/packages/cli/' \
	  --exclude '.*/tests/.*' --exclude '.*_deps.*' \
	  --gcov-executable $(GCOV) --gcov-ignore-parse-errors=all \
	  --html-details $(COVBUILD)/coverage/index.html \
	  --print-summary $(COVBUILD) | tee $(COVBUILD)/coverage-summary.txt
# Re-render the deepest-sound-problem showcase from docs/DEEPEST.json. Both
# outputs come from the same JSON, so they never need to be regenerated
# separately. Refreshing the JSON itself needs the tables:
#   python3 tools/deepest_showcase.py --tables ./tables
docs-deepest:
	python3 tools/render_deepest.py --data docs/DEEPEST.json --out docs/DEEPEST.md
	python3 tools/deepest_booklet.py --data docs/DEEPEST.json --out docs/DEEPEST.tex

# The per-material problem data behind the site's material pages. Needs a
# corpus, like docs-deepest -- the output is committed because the Pages
# workflow has no tables. TABLES defaults to ~/tb; a target-specific
# assignment (not the global "?=" the stress target already uses at line
# 195) so the two defaults don't fight over which one wins first.
site-data: TABLES = $(HOME)/tb
site-data: build
	python3 tools/build_problems.py --tables $(TABLES) --binary $(BUILD)/helpmate \
	  --out site/data

# Typeset the booklet. Twice: the index carries page references, which are
# only correct once the .aux from the first pass exists. Needs chessboard.sty
# -- TeX Live ships it in texlive-games.
booklet: docs-deepest
	@kpsewhich chessboard.sty >/dev/null || \
	  { echo "chessboard.sty not found -- install TeX Live's texlive-games"; exit 1; }
	mkdir -p $(BOOKLET)
	pdflatex -interaction=nonstopmode -halt-on-error \
	  -output-directory=$(BOOKLET) docs/DEEPEST.tex >/dev/null
	pdflatex -interaction=nonstopmode -halt-on-error \
	  -output-directory=$(BOOKLET) docs/DEEPEST.tex >/dev/null
	cp $(BOOKLET)/DEEPEST.pdf docs/DEEPEST.pdf
	@echo "wrote docs/DEEPEST.pdf (build dir: $(BOOKLET))"

clean:
	rm -rf $(BUILD) $(COVBUILD) $(BOOKLET)

# --- static showcase (site/), published to GitHub Pages by .github/workflows/pages.yml
# The board component is the dashboard's vendored cm-chessboard, copied in
# rather than duplicated in git; site/vendor is ignored. Data under site/data
# is committed and regenerated by hand:  python3 tools/build_site_data.py --tables ~/tb
.PHONY: site test-site serve-site
site:
	rm -rf site/vendor && mkdir -p site/vendor
	cp -r src/packages/web/helpmate_web/static/vendor/cm-chessboard site/vendor/cm-chessboard
	cp src/packages/web/helpmate_web/static/vendor/README.md site/vendor/README.md
	python3 tools/render_site.py --data site/data --out site

test-site: site
	node --test site/tests/*.test.js
	@for f in site/js/*.js site/js/lib/*.js; do node --check "$$f" || exit 1; done

serve-site: site
	cd site && python3 -m http.server 8650

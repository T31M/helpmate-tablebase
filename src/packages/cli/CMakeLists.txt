# The `helpmate` command-line client, and the end-to-end ctest cases that
# drive the real binary. These are the only tests that exercise argument
# parsing, exit codes and the printed output a user actually sees.
add_executable(helpmate main.cpp)
target_link_libraries(helpmate PRIVATE helpmate_core)

# Two install destinations, never both: SKBUILD_SCRIPTS_DIR is defined only
# when scikit-build-core is building a wheel, and puts the binary on PATH for
# `pip install helpmate`. A plain `cmake --install` uses bin/ as before.
if(DEFINED SKBUILD_SCRIPTS_DIR)
  install(TARGETS helpmate RUNTIME DESTINATION ${SKBUILD_SCRIPTS_DIR})
else()
  install(TARGETS helpmate RUNTIME DESTINATION bin)
endif()

# Test-support only (not installed): writes a legacy-format all-unsolvable
# table so `helpmate compact`'s ctest coverage has a real rewrite target --
# see tests/mk_legacy_table.cpp for why `helpmate gen` can no longer produce
# this fixture itself.
add_executable(mk_legacy_table tests/mk_legacy_table.cpp)
target_link_libraries(mk_legacy_table PRIVATE helpmate_core)

set(CLI_TT ${CMAKE_BINARY_DIR}/cli_tables)
add_test(NAME cli_gen COMMAND helpmate gen KQvk --tables ${CLI_TT})
add_test(NAME cli_probe COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_line COMMAND helpmate line "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${CLI_TT})
add_test(NAME cli_stats COMMAND helpmate stats KQvk --tables ${CLI_TT})
add_test(NAME cli_mine COMMAND helpmate mine KQvk --dtm 2 --count 1 --max 3 --tables ${CLI_TT})
# v0.6.2: shape filters. mine prints CANONICAL FENs, so assert against the
# golden position's canonical form 8/8/8/8/8/2K5/7Q/1k6 b - - 0 1 (dtm 2,
# count 4; lines Ka1 Qb2#, Kc1 Qg1#, Kc1 Qh1#, Kc1 Qc2# -> starts 2, ends 4).
add_test(NAME cli_mine_shape COMMAND helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 4 --max 200 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_miss COMMAND helpmate mine KQvk --dtm 2 --count 4 --starts 3 --ends 4 --max 200 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_badrange COMMAND helpmate mine KQvk --dtm 2 --count 2 --starts 5 --tables ${CLI_TT})
add_test(NAME cli_mine_shape_zero COMMAND helpmate mine KQvk --dtm 2 --starts 0 --tables ${CLI_TT})
# --ends is held at its true value (4) in both cli_mine_shape (PASS) and
# cli_mine_shape_miss (FAIL) above, varying only --starts -- so a regression
# that ignored --ends filtering entirely would slip past both. This case
# varies --ends instead, holding --starts at its true value (2).
add_test(NAME cli_mine_shape_ends_miss COMMAND helpmate mine KQvk --dtm 2 --count 4 --starts 2 --ends 3 --max 200 --tables ${CLI_TT})
# Regression test: -1 is a value a user can literally type with --starts/--ends,
# not just the "not given" sentinel used internally -- it must be rejected like
# any other value < 1, not silently treated as "not given" and skip filtering.
add_test(NAME cli_mine_shape_negative COMMAND helpmate mine KQvk --dtm 2 --starts -1 --tables ${CLI_TT})
# --starts is legal without --count; the golden position has starts 2.
add_test(NAME cli_mine_shape_no_count COMMAND helpmate mine KQvk --dtm 2 --starts 2 --max 200 --tables ${CLI_TT})
# cli_mine_theme: PASS_REGULAR_EXPRESSION "b - - 0 1" alone matches every mined
# FEN, so it used to pass even with the filter silently ignored entirely (the
# Critical-2 defect below) -- it would not have caught that bug. Verified via
# a script that pins the exact, independently-measured counts instead (see
# verify_mine_theme_filters.cmake): 580 unfiltered, 477 with `mirror`.
add_test(NAME cli_mine_theme COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         -DTABLES=${CLI_TT}
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/verify_mine_theme_filters.cmake)
set_tests_properties(cli_mine_theme PROPERTIES DEPENDS cli_gen)

# v0.18.0: output modes. One script pins them all against the same table so
# the numbers (580 dtm=2 positions) are shared with verify_mine_theme_filters.
add_test(NAME cli_mine_outputs COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         -DTABLES=${CLI_TT}
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/verify_mine_outputs.cmake)
set_tests_properties(cli_mine_outputs PROPERTIES DEPENDS cli_gen)

# v0.18.0: `--interactive` end-to-end. Drives the shell through a piped
# stdin session and pins what a user sees (prompt, narrowing tallies,
# histogram, list/show/save) plus a second session proving errors don't
# end the loop.
add_test(NAME cli_mine_shell COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         -DTABLES=${CLI_TT}
         -DSESSION=${CMAKE_CURRENT_SOURCE_DIR}/tests/mine_shell_session.txt
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/verify_mine_shell.cmake)
set_tests_properties(cli_mine_shell PROPERTIES DEPENDS cli_gen)

# An unknown theme must fail loudly and name the alternatives -- the --end/--ends
# lesson: a silently discarded filter returns positions that do not match what
# was asked for, with nothing to indicate it. WILL_FAIL alone only pins
# "nonzero exit" (a segfault would pass too), and PASS_REGULAR_EXPRESSION alone
# ignores the exit code -- pin both together via the shared script.
add_test(NAME cli_mine_theme_unknown COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=mine KQvk --dtm 2 --theme nosuch --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=unknown theme \"nosuch\""
         "-DPATTERN2=valid themes"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_mine_theme_unknown PROPERTIES DEPENDS cli_gen)

# Parametric themes: `promotions:q` is a valid name (KQvk has no pawn, so the
# scan simply finds nothing and exits 0); a bad value and the bare name must
# fail naming the fix; the singular typo `promotion:q` must NOT fall through
# to the boolean `promotion` with its value silently discarded.
add_test(NAME cli_mine_theme_param COMMAND helpmate mine KQvk --dtm 2 --theme promotions:q --max 3 --tables ${CLI_TT})
set_tests_properties(cli_mine_theme_param PROPERTIES DEPENDS cli_gen)
add_test(NAME cli_mine_theme_param_bad_value COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=mine KQvk --dtm 2 --theme promotions:qx --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=does not accept the value \"qx\""
         "-DPATTERN2=valid themes"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_mine_theme_param_bad_value PROPERTIES DEPENDS cli_gen)
add_test(NAME cli_mine_theme_param_missing COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=mine KQvk --dtm 2 --theme promotions --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=needs a value"
         "-DPATTERN2=promotions:qrr"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_mine_theme_param_missing PROPERTIES DEPENDS cli_gen)
add_test(NAME cli_mine_theme_param_singular_typo COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=mine KQvk --dtm 2 --theme promotion:q --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=did you mean promotions:q"
         "-DPATTERN2=valid themes"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_mine_theme_param_singular_typo PROPERTIES DEPENDS cli_gen)

# The mirror-image mix-up: `probe --theme` (singular, mine's flag) must also
# be rejected, naming the right flag (--themes). Rejection happens while
# scanning flags, before the FEN is ever parsed, so the FEN need not even be
# well-formed here -- quoted anyway so this stays a faithful, copy-pasteable
# repro of the real command.
add_test(NAME cli_probe_theme_rejected COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=probe \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --theme mirror --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=probe has no"
         "-DPATTERN2=did you mean \"--themes\""
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_probe_theme_rejected PROPERTIES DEPENDS cli_gen)

# `mine` used to silently ignore any positional beyond pos[0] -- a stray extra
# argument changed nothing about what got printed, with no indication it was
# dropped (the same class of bug as the --theme/--themes mix-up above).
# PASS_REGULAR_EXPRESSION alone would ignore the exit code: a build that
# printed the message and then died, or that returned 0, would still pass --
# recreating the very weakness the helper exists to close.
add_test(NAME cli_mine_extra_positional COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=mine KQvk extra --dtm 2 --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=extra argument"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_mine_extra_positional PROPERTIES DEPENDS cli_gen)

add_test(NAME cli_probe_themes COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --themes --tables ${CLI_TT})
set_tests_properties(cli_probe_themes PROPERTIES PASS_REGULAR_EXPRESSION "themes:" DEPENDS cli_gen)

# Important-3 regression: probe's color-flip fallback (see cli_probe's own
# color-flip coverage below) used to break `--themes` -- tb.solutions() walks
# the ORIGINAL (unflipped) FEN, which has no table of its own when probe only
# answered via the flip, so it threw MissingTableError and turned a working
# probe into a half-printed answer plus exit 2. Now it must print a note and
# still exit 0. Only KQvk is generated into CLI_TT, not its flip Kvkq, so this
# FEN (White king mated by a lone black queen) is guaranteed to hit the flip
# path -- same FEN as test_probe.cpp's "probe color-flipped position".
add_test(NAME cli_probe_themes_flipped COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=probe \"6q1/8/8/8/8/5k2/7K/8 w - - 0 1\" --themes --tables ${CLI_TT}"
         -DEXPECTED_RC=0
         "-DPATTERN1=note:.*color-flipped"
         "-DPATTERN2=dtm=2.*colors flipped"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_probe_themes_flipped PROPERTIES DEPENDS cli_gen)
# I-4 (pre-merge review): --theme/--themes used to be rejected only on
# probe/mine respectively -- every OTHER command (line, stats, gen, ...)
# silently discarded them, exit 0, nothing said so. `stats --theme` is the
# exact class of bug this branch already fixed for `mine --themes`; `line
# --themes` is the likeliest typo of all, since the docs teach `probe
# --themes` and `line` is its neighbour on this list.
add_test(NAME cli_line_themes_rejected COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=line \"8/7k/5K2/8/8/8/8/6Q1 b - - 0 1\" --themes --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=line has no"
         "-DPATTERN2=\"probe\" prints"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_line_themes_rejected PROPERTIES DEPENDS cli_gen)

add_test(NAME cli_stats_theme_rejected COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=stats KQvk --theme mirror --tables ${CLI_TT}"
         -DEXPECTED_RC=3
         "-DPATTERN1=stats has no"
         "-DPATTERN2=\"mine\" filters"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_stats_theme_rejected PROPERTIES DEPENDS cli_gen)

# I-1 (pre-merge review): `probe --themes` used to print `dtm=... count=...`
# and only THEN discover (via solutions() walking a capture into material
# this --tables dir lacks) that detection can't proceed -- a half-printed
# answer followed by exit 2, the exact failure shape the color-flip branch's
# comment (see cmd_probe) already exists to prevent, just reached from a
# partial table set instead of a color flip. THEME_PARTIAL_TT holds ONLY
# KQvk.hm (copied out of CLI_TT, not Kvk.hm), so a queen-capture branch of
# this saturated (count=255) position's solution tree hits a missing table.
set(THEME_PARTIAL_TT ${CMAKE_BINARY_DIR}/theme_partial_tables)
add_test(NAME cli_theme_partial_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${THEME_PARTIAL_TT})
add_test(NAME cli_theme_partial_fixture_copy COMMAND ${CMAKE_COMMAND} -E copy
         ${CLI_TT}/KQvk.hm ${CLI_TT}/KQvk.stats.json ${THEME_PARTIAL_TT})
set_tests_properties(cli_theme_partial_fixture_copy PROPERTIES
    DEPENDS "cli_gen;cli_theme_partial_fixture_mkdir")
add_test(NAME cli_probe_themes_missing_subtable COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=probe \"8/6kQ/8/8/8/8/8/K7 b - - 0 1\" --themes --tables ${THEME_PARTIAL_TT}"
         -DEXPECTED_RC=0
         "-DPATTERN1=dtm=12.*count=255"
         "-DPATTERN2=themes: \\(unavailable"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_probe_themes_missing_subtable PROPERTIES DEPENDS cli_theme_partial_fixture_copy)

add_test(NAME cli_themes COMMAND helpmate themes)
set_tests_properties(cli_themes PROPERTIES PASS_REGULAR_EXPRESSION "closed-walk")
# Task 10: every entry's `needs` (Position/Plane/Solutions) must be printed --
# it is how a user tells which themes answer without enumerating solutions,
# and so still answer on positions whose stored solution count saturates.
# `needs: plane` is asserted, not `needs: solutions`: `set-play` is the only
# non-Solutions entry in the registry (homebase, the one Needs::Position
# theme, was removed by the branch review -- see CHANGELOG -- because it is
# not invariant under the tablebase index's symmetry group), so `plane` is
# the value most likely to silently vanish from the printed output if this
# field regressed, exactly like `position` was before the removal.
add_test(NAME cli_themes_shows_needs COMMAND helpmate themes)
set_tests_properties(cli_themes_shows_needs PROPERTIES
    PASS_REGULAR_EXPRESSION "needs: plane")
add_test(NAME cli_missing COMMAND helpmate probe "8/8/8/8/3n4/4k3/8/4K3 w - - 0 1" --tables ${CLI_TT})
# v0.5.0: --verbose lifecycle lines go to stderr (ctest matches merged output);
# on a re-run every slice is already on disk, so "cached" must appear.
add_test(NAME cli_gen_verbose COMMAND helpmate gen KQvk --tables ${CLI_TT} --verbose)
add_test(NAME cli_version COMMAND helpmate --version)
add_test(NAME cli_badfen COMMAND helpmate probe "garbage" --tables ${CLI_TT})
# review fix round: malformed and out-of-range numeric flags must not crash
# (std::stoi throwing std::invalid_argument/std::out_of_range uncaught ->
# SIGABRT); both must exit 3 with a clear message instead.
add_test(NAME cli_badint_malformed COMMAND helpmate mine KQvk --dtm abc --tables ${CLI_TT})
add_test(NAME cli_badint_range COMMAND helpmate gen KQvk --threads 99999999999999999999 --tables ${CLI_TT})
# review fix round: `line --all` on an already-mated (dtm=0) position must
# give the same "no line to print" message as the non---all branch, not a
# silent blank line (tb.lines() returns one *empty* line here, so a naive
# ls.empty() check misses it).
add_test(NAME cli_line_already_mate COMMAND helpmate line "8/8/8/8/8/8/8/kQK5 b - - 0 1" --tables ${CLI_TT} --all)
# v0.6.1: `compact` rewrites all-unsolvable tables already on disk as tiny
# markers. `helpmate gen` itself now prunes every provably-unsolvable slice
# to a marker at generation time (see generator.cpp's opt.prune path), so
# gen's own output never gives compact anything left to do -- compact exists
# for tables written by OLDER binaries, before that pruning feature existed.
# mk_legacy_table fabricates exactly that: an ordinary (version 1) table,
# fully populated, whose every cell happens to read DTM_UNSOLVABLE.
set(COMPACT_TT ${CMAKE_BINARY_DIR}/compact_tables)
add_test(NAME cli_compact_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${COMPACT_TT})
add_test(NAME cli_compact_fixture_write COMMAND mk_legacy_table ${COMPACT_TT}/Kvk.hm Kvk)
add_test(NAME cli_compact_dry COMMAND helpmate compact ${COMPACT_TT} --dry-run)
add_test(NAME cli_compact COMMAND helpmate compact ${COMPACT_TT})
# Final-review fix: compact must refuse (not touch) a table whose FILE NAME and
# header material disagree, rather than deriving the sidecar path from the
# (untrusted) header name. Fabricate exactly that: a legitimate legacy table
# for material Kvk, renamed to KQvk.hm so its filename no longer matches its
# own header.
set(COMPACT_MISMATCH_TT ${CMAKE_BINARY_DIR}/compact_mismatch_tables)
add_test(NAME cli_compact_mismatch_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${COMPACT_MISMATCH_TT})
add_test(NAME cli_compact_mismatch_fixture_write COMMAND mk_legacy_table ${COMPACT_MISMATCH_TT}/Kvk.hm Kvk)
add_test(NAME cli_compact_mismatch_fixture_rename COMMAND ${CMAKE_COMMAND} -E rename ${COMPACT_MISMATCH_TT}/Kvk.hm ${COMPACT_MISMATCH_TT}/KQvk.hm)
add_test(NAME cli_compact_mismatch COMMAND helpmate compact ${COMPACT_MISMATCH_TT})
add_test(NAME cli_compact_mismatch_no_sidecar COMMAND ${CMAKE_COMMAND}
         -DABSENT_PATH=${COMPACT_MISMATCH_TT}/KQvk.stats.json
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_absent.cmake)
# Final-review fix: compact must diagnose a table written by a newer helpmate
# (TableReader::OpenError::UnsupportedVersion) with the same clear "newer
# helpmate ... upgrade this build" message the rest of the tool uses, not the
# generic "unreadable table" message that a single-argument TableReader::open
# call would produce.
set(COMPACT_FUTURE_TT ${CMAKE_BINARY_DIR}/compact_future_tables)
add_test(NAME cli_compact_future_fixture_mkdir COMMAND ${CMAKE_COMMAND} -E make_directory ${COMPACT_FUTURE_TT})
add_test(NAME cli_compact_future_fixture_write COMMAND mk_legacy_table ${COMPACT_FUTURE_TT}/Kvk.hm Kvk --future)
add_test(NAME cli_compact_future COMMAND helpmate compact ${COMPACT_FUTURE_TT})
# count=4 (not 1): four optimal replies tie at dtm=2 here -- see Task 8's
# corrected golden (test_probe.cpp), reconfirmed by running the built CLI.
set_tests_properties(cli_probe PROPERTIES PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=4" DEPENDS cli_gen)
# legal_moves() ordering deterministically yields Kh6 Qh2# as the first optimal
# line for `line` (no --all); reconfirmed by running the built CLI.
set_tests_properties(cli_line  PROPERTIES PASS_REGULAR_EXPRESSION "Kh6 Qh2#" DEPENDS cli_gen)
set_tests_properties(cli_stats PROPERTIES PASS_REGULAR_EXPRESSION "max_dtm" DEPENDS cli_gen)
set_tests_properties(cli_mine  PROPERTIES PASS_REGULAR_EXPRESSION "b - - 0 1" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape PROPERTIES PASS_REGULAR_EXPRESSION "8/8/8/8/8/2K5/7Q/1k6 b - - 0 1" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_miss PROPERTIES FAIL_REGULAR_EXPRESSION "8/8/8/8/8/2K5/7Q/1k6 b" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_badrange PROPERTIES PASS_REGULAR_EXPRESSION "error.*--starts" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_zero PROPERTIES PASS_REGULAR_EXPRESSION "error.*--starts" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_ends_miss PROPERTIES FAIL_REGULAR_EXPRESSION "8/8/8/8/8/2K5/7Q/1k6 b" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_negative PROPERTIES PASS_REGULAR_EXPRESSION "error.*--starts" DEPENDS cli_gen)
set_tests_properties(cli_mine_shape_no_count PROPERTIES PASS_REGULAR_EXPRESSION "8/8/8/8/8/2K5/7Q/1k6 b" DEPENDS cli_gen)
set_tests_properties(cli_missing PROPERTIES PASS_REGULAR_EXPRESSION "helpmate gen" DEPENDS cli_gen)
set_tests_properties(cli_badfen PROPERTIES PASS_REGULAR_EXPRESSION "error")
set_tests_properties(cli_gen_verbose PROPERTIES PASS_REGULAR_EXPRESSION "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\\.[0-9][0-9][0-9]Z cached Kvk" DEPENDS cli_gen)
# Every generator log line starts with an ISO-8601 UTC timestamp with
# milliseconds (2026-10-03T16:44:07.123Z). A fresh directory makes gen build
# KQvk, so the progress lines appear too.
set(CLI_STAMP_TT ${CMAKE_BINARY_DIR}/cli_stamp_tables)
add_test(NAME cli_gen_stamp_clean COMMAND ${CMAKE_COMMAND} -E rm -rf ${CLI_STAMP_TT})
add_test(NAME cli_gen_stamp COMMAND helpmate gen KQvk --tables ${CLI_STAMP_TT} --progress --verbose)
set_tests_properties(cli_gen_stamp_clean PROPERTIES FIXTURES_SETUP cli_stamp)
set_tests_properties(cli_gen_stamp PROPERTIES FIXTURES_REQUIRED cli_stamp
    PASS_REGULAR_EXPRESSION "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\\.[0-9][0-9][0-9]Z   KQvk: pass d=1 resolved")
# The finalize steps report like passes: the last one names the written table.
set(CLI_FINAL_TT ${CMAKE_BINARY_DIR}/cli_final_tables)
add_test(NAME cli_gen_final_log_clean COMMAND ${CMAKE_COMMAND} -E rm -rf ${CLI_FINAL_TT})
add_test(NAME cli_gen_final_log COMMAND helpmate gen KQvk --tables ${CLI_FINAL_TT} --progress --compress)
set_tests_properties(cli_gen_final_log_clean PROPERTIES FIXTURES_SETUP cli_final)
set_tests_properties(cli_gen_final_log PROPERTIES FIXTURES_REQUIRED cli_final
    PASS_REGULAR_EXPRESSION "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]\\.[0-9][0-9][0-9]Z   KQvk: table written \\([0-9.]+ s, [0-9]+ blocks, [0-9]+ bytes\\)")
# Regex-escape the dots so 0.7.1 does not also match 0X7Y1.
string(REPLACE "." "\\." HELPMATE_VERSION_RE "${PROJECT_VERSION}")
set_tests_properties(cli_version PROPERTIES PASS_REGULAR_EXPRESSION "helpmate ${HELPMATE_VERSION_RE}")
set_tests_properties(cli_badint_malformed PROPERTIES PASS_REGULAR_EXPRESSION "error.*--dtm")
set_tests_properties(cli_badint_range PROPERTIES PASS_REGULAR_EXPRESSION "error.*--threads")
set_tests_properties(cli_line_already_mate PROPERTIES PASS_REGULAR_EXPRESSION "already mate" DEPENDS cli_gen)
set_tests_properties(cli_compact_fixture_write PROPERTIES DEPENDS cli_compact_fixture_mkdir)
set_tests_properties(cli_compact_dry PROPERTIES PASS_REGULAR_EXPRESSION "would rewrite" DEPENDS cli_compact_fixture_write)
set_tests_properties(cli_compact PROPERTIES PASS_REGULAR_EXPRESSION "rewrote|already compact" DEPENDS cli_compact_dry)
set_tests_properties(cli_compact_mismatch_fixture_write PROPERTIES DEPENDS cli_compact_mismatch_fixture_mkdir)
set_tests_properties(cli_compact_mismatch_fixture_rename PROPERTIES DEPENDS cli_compact_mismatch_fixture_write)
# helpmate compact exits 3 on a name/header mismatch (verified manually: `helpmate
# compact <dir>; echo $?` -> 3); PASS_REGULAR_EXPRESSION below additionally pins the
# error message (ignores exit code, hence the manual note -- same idiom as cli_badfen).
set_tests_properties(cli_compact_mismatch PROPERTIES
    PASS_REGULAR_EXPRESSION "error:.*is for material 'Kvk'.*expected 'KQvk'"
    DEPENDS cli_compact_mismatch_fixture_rename)
set_tests_properties(cli_compact_mismatch_no_sidecar PROPERTIES DEPENDS cli_compact_mismatch)
set_tests_properties(cli_compact_future_fixture_write PROPERTIES DEPENDS cli_compact_future_fixture_mkdir)
# helpmate compact exits 3 on an unsupported table version too; PASS_REGULAR_EXPRESSION
# ignores exit code (same idiom as cli_compact_mismatch above), so it alone pins this.
set_tests_properties(cli_compact_future PROPERTIES
    PASS_REGULAR_EXPRESSION "error:.*newer helpmate"
    DEPENDS cli_compact_future_fixture_write)

# v0.7.5: `gen --compress` writes block-compressed tables directly, and
# `compact --compress` rewrites already-raw tables in place. cli_probe_compressed
# is the one that matters: it proves the golden position gives the same answer
# through a compressed table as cli_probe gets through a raw one.
set(COMPRESS_TT ${CMAKE_BINARY_DIR}/compress_tables)
add_test(NAME cli_gen_compressed COMMAND helpmate gen KQvk --tables ${COMPRESS_TT} --compress)
add_test(NAME cli_probe_compressed COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${COMPRESS_TT})
add_test(NAME cli_compact_compress_noop COMMAND helpmate compact ${COMPRESS_TT} --compress)
set_tests_properties(cli_probe_compressed PROPERTIES
    PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=4" DEPENDS cli_gen_compressed)
set_tests_properties(cli_compact_compress_noop PROPERTIES
    PASS_REGULAR_EXPRESSION "already compressed|0 rewritten" DEPENDS cli_gen_compressed)

# The one-hour skip is the load-bearing part of `compact --compress`: a long
# generation run may be writing into the target directory right now, and
# rewriting a table mid-write would corrupt it. Prove both halves -- a
# fresh-mtime table is skipped and left byte-for-byte untouched, and a
# 2-hour-old one is actually converted and shrinks -- with a real mtime
# (`touch -d`), not just inspection of the code.
set(COMPRESS_SKIP_TT ${CMAKE_BINARY_DIR}/compress_skip_tables)
add_test(NAME cli_compact_compress_skip_recent COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         -DMK_LEGACY_TABLE=$<TARGET_FILE:mk_legacy_table>
         -DDIR=${COMPRESS_SKIP_TT}
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/verify_compress_skip_recent.cmake)
set_tests_properties(cli_compact_compress_skip_recent PROPERTIES
    PASS_REGULAR_EXPRESSION "one-hour skip verified")

# --block-size validation: below the 4 KiB floor and above kMaxBlockSize (16
# MiB = 16384 KiB) must both be rejected before anything is generated.
add_test(NAME cli_block_size_too_small COMMAND helpmate gen KQvk --tables ${CLI_TT} --compress --block-size 1)
add_test(NAME cli_block_size_too_big COMMAND helpmate gen KQvk --tables ${CLI_TT} --compress --block-size 20000)
add_test(NAME cli_block_size_zero COMMAND helpmate gen KQvk --tables ${CLI_TT} --compress --block-size 0)
set_tests_properties(cli_block_size_too_small PROPERTIES PASS_REGULAR_EXPRESSION "error.*--block-size")
set_tests_properties(cli_block_size_too_big PROPERTIES PASS_REGULAR_EXPRESSION "error.*--block-size")
set_tests_properties(cli_block_size_zero PROPERTIES PASS_REGULAR_EXPRESSION "error.*--block-size")

# Re-blocking: compact --compress must convert an already-compressed table to
# a DIFFERENT block size in place (the trap this whole task closes -- a
# tunable block size must not become a "regenerate from scratch" trap), stay
# a true no-op at the SAME block size, and the reader must answer identically
# after the conversion.
set(REBLOCK_TT ${CMAKE_BINARY_DIR}/reblock_tables)
# `gen` leaves existing files alone (tested deliberately elsewhere), so a
# re-run of this suite against a build dir left over from a previous run
# would find KQvk.hm already at the target block size and never exercise the
# re-block path at all. Force a clean directory every time instead of relying
# on ctest being run exactly once per build.
add_test(NAME cli_gen_reblock_fixture_clean COMMAND ${CMAKE_COMMAND} -E rm -rf ${REBLOCK_TT})
add_test(NAME cli_gen_reblock_source COMMAND helpmate gen KQvk --tables ${REBLOCK_TT} --compress --block-size 4)
set_tests_properties(cli_gen_reblock_source PROPERTIES DEPENDS cli_gen_reblock_fixture_clean)
# compact --compress skips anything written in the last hour (see
# verify_compress_skip_recent.cmake above) -- gen just wrote these, so
# back-date their mtimes past that window before exercising the re-block
# path, same idiom as the skip-recent test.
add_test(NAME cli_gen_reblock_source_age COMMAND touch -d "2 hours ago" ${REBLOCK_TT}/KQvk.hm ${REBLOCK_TT}/Kvk.hm)
add_test(NAME cli_compact_reblock COMMAND helpmate compact ${REBLOCK_TT} --compress --block-size 8)
add_test(NAME cli_compact_reblock_noop COMMAND helpmate compact ${REBLOCK_TT} --compress --block-size 8)
add_test(NAME cli_probe_reblocked COMMAND helpmate probe "8/7k/5K2/8/8/8/8/6Q1 b - - 0 1" --tables ${REBLOCK_TT})
set_tests_properties(cli_gen_reblock_source_age PROPERTIES DEPENDS cli_gen_reblock_source)
set_tests_properties(cli_compact_reblock PROPERTIES
    PASS_REGULAR_EXPRESSION "re-blocked KQvk|1 rewritten \\(0 compressed, 1 re-blocked\\)"
    DEPENDS cli_gen_reblock_source_age)
set_tests_properties(cli_compact_reblock_noop PROPERTIES
    PASS_REGULAR_EXPRESSION "already compressed at this block size|0 rewritten"
    DEPENDS cli_compact_reblock)
set_tests_properties(cli_probe_reblocked PROPERTIES
    PASS_REGULAR_EXPRESSION "dtm=2 .*h#1.*count=4" DEPENDS cli_compact_reblock_noop)

# `stats` with no MATERIAL summarises every table in --tables DIR. CLI_TT holds
# the KQvk closure gen wrote for cli_gen: KQvk (a real table) plus Kvk (an
# all-unsolvable marker), which is exactly the mix the summary has to separate.
add_test(NAME cli_stats_corpus COMMAND helpmate stats --tables ${CLI_TT})
set_tests_properties(cli_stats_corpus PROPERTIES
    PASS_REGULAR_EXPRESSION "all-unsolvable marker" DEPENDS cli_gen)
# The cell breakdown must be present and grouped, not raw digits.
add_test(NAME cli_stats_corpus_cells COMMAND helpmate stats --tables ${CLI_TT})
set_tests_properties(cli_stats_corpus_cells PROPERTIES
    PASS_REGULAR_EXPRESSION "unique \\(count==1\\)" DEPENDS cli_gen)
# A directory with no .hm at all is an error, not an empty report claiming a
# zero-table corpus -- the likeliest cause is a mistyped --tables.
add_test(NAME cli_stats_corpus_empty_dir COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=stats --tables ${CMAKE_CURRENT_BINARY_DIR}"
         -DEXPECTED_RC=3
         "-DPATTERN1=no readable"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
# And a --tables that isn't a directory must say so rather than report nothing.
add_test(NAME cli_stats_corpus_not_a_dir COMMAND ${CMAKE_COMMAND}
         -DHELPMATE=$<TARGET_FILE:helpmate>
         "-DARGS=stats --tables ${CLI_TT}/KQvk.hm"
         -DEXPECTED_RC=3
         "-DPATTERN1=not a directory"
         -P ${CMAKE_CURRENT_SOURCE_DIR}/tests/assert_exit_and_output.cmake)
set_tests_properties(cli_stats_corpus_not_a_dir PROPERTIES DEPENDS cli_gen)

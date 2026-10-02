# The helpmate core: board representation, symmetry-reduced indexing, the
# table format, the generator and the probe library. Everything else in the
# repo is a client of this.
set(HELPMATE_SOURCES chess/board.cpp chess/san.cpp indexing/material.cpp indexing/kk.cpp indexing/slice_index.cpp format/table_file.cpp format/block_codec.cpp format/block_cache.cpp generator/oracle.cpp generator/generator.cpp probe/tablebase.cpp themes/attack.cpp themes/mate_themes.cpp themes/trajectory.cpp themes/line_themes.cpp themes/position_themes.cpp themes/identity.cpp themes/set_themes.cpp themes/registry.cpp probe/mine_set.cpp probe/mine_shell.cpp)  # tasks append here
add_library(helpmate_core STATIC ${HELPMATE_SOURCES})

configure_file(${CMAKE_CURRENT_SOURCE_DIR}/version.h.in
               ${CMAKE_BINARY_DIR}/generated/version.h @ONLY)

target_include_directories(helpmate_core PUBLIC
  ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_BINARY_DIR}/generated)
target_link_libraries(helpmate_core PUBLIC chessmg_core nlohmann_json::nlohmann_json Threads::Threads PkgConfig::ZSTD)
target_compile_options(helpmate_core PRIVATE -O2 -Wall -Wextra)

if(HELPMATE_COVERAGE)
  target_compile_options(helpmate_core PRIVATE --coverage -O0 -g)
  target_link_options(helpmate_core PUBLIC --coverage)
endif()

add_executable(helpmate_tests
  tests/test_sanity.cpp tests/test_board.cpp tests/test_san.cpp
  tests/test_material.cpp tests/test_kk.cpp tests/test_slice_index.cpp
  tests/test_table_file.cpp tests/test_oracle.cpp tests/test_generator_init.cpp
  tests/test_generator_kqvk.cpp tests/test_generator_pawns.cpp
  tests/test_counts.cpp tests/test_stats.cpp tests/test_threads.cpp
  tests/test_probe.cpp tests/test_generator_lookup_guards.cpp
  tests/test_ram_guard.cpp tests/test_slice_index_6piece.cpp
  tests/test_generator_prune.cpp tests/test_block_codec.cpp tests/test_solutions.cpp
  tests/test_attack.cpp tests/test_mate_themes.cpp tests/test_line_themes.cpp
  tests/test_position_themes.cpp
  tests/test_identity.cpp
  tests/test_themes_registry.cpp
  tests/test_mine_set.cpp
  tests/test_mine_shell.cpp)
target_link_libraries(helpmate_tests PRIVATE helpmate_core Catch2::Catch2WithMain)
target_compile_definitions(helpmate_tests PRIVATE
  HM_TEST_FIXTURES="${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures")
list(APPEND CMAKE_MODULE_PATH ${catch2_SOURCE_DIR}/extras)
include(Catch)
# Slow cases (full KPvkp closure generation) are excluded from ctest here.
# Run them with: ./build/helpmate_tests "[slow]"
catch_discover_tests(helpmate_tests TEST_SPEC "~[slow]")

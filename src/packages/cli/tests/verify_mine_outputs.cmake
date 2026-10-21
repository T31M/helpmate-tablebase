# Test-support script (not installed): pins the v0.18.0 mine output modes
# against the KQvk table. Required: -DHELPMATE=<binary> -DTABLES=<dir>
foreach(v HELPMATE TABLES)
  if(NOT DEFINED ${v})
    message(FATAL_ERROR "verify_mine_outputs.cmake: -D${v}=... is required")
  endif()
endforeach()

function(run_helpmate outvar rcvar)
  execute_process(COMMAND "${HELPMATE}" ${ARGN} OUTPUT_VARIABLE out ERROR_VARIABLE err RESULT_VARIABLE rc)
  set(${outvar} "${out}" PARENT_SCOPE)
  set(${rcvar} "${rc}" PARENT_SCOPE)
  set(last_err "${err}" PARENT_SCOPE)
endfunction()

# 1. --max infinity and --max inf lift the cap: 580 dtm=2 positions.
foreach(word infinity inf)
  run_helpmate(out rc mine KQvk --dtm 2 --max ${word} --tables "${TABLES}")
  if(NOT rc EQUAL 0)
    message(FATAL_ERROR "--max ${word} failed (${rc}): ${last_err}")
  endif()
  string(REGEX MATCHALL "\n" nl "${out}")
  list(LENGTH nl n)
  if(NOT n EQUAL 580)
    message(FATAL_ERROR "--max ${word}: expected 580 lines, got ${n}")
  endif()
endforeach()

# 2. A bad --max word is rejected, naming the accepted words. (Matching bare
# "infinity" would also pass against the usage text alone, which prints
# "--max N|infinity" regardless of this error path, so pin the actual error
# message and the quoted "inf" alternative instead.)
run_helpmate(out rc mine KQvk --dtm 2 --max all --tables "${TABLES}")
if(NOT rc EQUAL 3 OR NOT "${last_err}" MATCHES "--max expects an integer" OR NOT "${last_err}" MATCHES "\"inf\"")
  message(FATAL_ERROR "--max all: expected exit 3 naming the accepted words, got ${rc}: ${last_err}")
endif()

# 2a. A negative --max is rejected too: it parses as an integer, so it used
# to sail past the word check and then behave exactly like --max 0, which
# reads as "no positions match" rather than "that is not a cap".
run_helpmate(out rc mine KQvk --dtm 2 --max -1 --tables "${TABLES}")
if(NOT rc EQUAL 3 OR NOT "${last_err}" MATCHES "--max must be 0 or more")
  message(FATAL_ERROR "--max -1: expected exit 3 rejecting the negative cap, got ${rc}: ${last_err}")
endif()

# 3. --json with both facets: the documented keys, in order.
run_helpmate(out rc mine KQvk --dtm 2 --max 2 --json --themes --solutions --tables "${TABLES}")
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "--json failed (${rc}): ${last_err}")
endif()
foreach(key "\"material\": \"KQvk\"" "\"filter\"" "\"max\": 2" "\"skipped_saturated\": 0" "\"positions\""
            "\"fen\": \"8/8/8/8/8/8/8/k1KQ4 b - - 0 1\"" "\"count\": 1" "\"starts\": 1" "\"ends\": 1"
            "\"solutions\"" "\"Qa4#\"")
  if(NOT "${out}" MATCHES "${key}")
    message(FATAL_ERROR "--json output lacks ${key}:\n${out}")
  endif()
endforeach()
# 3a. "themes" is checked separately, restricted to the part of the output from
# the first "positions" occurrence onward: the top-level "filter" block
# always carries its own "themes" key (the --theme name list, independent
# of the --themes facet), so matching it against the whole output would be
# vacuous. Same technique as check 4 below.
string(FIND "${out}" "\"positions\"" pos_positions_3)
string(SUBSTRING "${out}" ${pos_positions_3} -1 after_positions_3)
if(NOT "${after_positions_3}" MATCHES "\"themes\"")
  message(FATAL_ERROR "--json output lacks the themes facet in positions:\n${out}")
endif()
string(FIND "${out}" "\"material\"" pos_m)
string(FIND "${out}" "\"positions\"" pos_p)
if(NOT pos_m LESS pos_p)
  message(FATAL_ERROR "--json: material must precede positions")
endif()
find_program(PYTHON3 python3)
if(PYTHON3)
  file(WRITE "${TABLES}/mine_out.json" "${out}")
  execute_process(COMMAND "${PYTHON3}" -c "import json,sys; d=json.load(open(sys.argv[1])); assert len(d['positions'])==2; assert d['max']==2" "${TABLES}/mine_out.json" RESULT_VARIABLE prc)
  if(NOT prc EQUAL 0)
    message(FATAL_ERROR "--json output does not parse as JSON")
  endif()
else()
  message(STATUS "python3 not found: JSON parse check skipped")
endif()

# 4. --json alone: minimal record, no facets. The filter object always
# carries its own "themes" key (the --theme name list, independent of the
# --themes facet), so only the "positions" section -- where a facet's keys
# actually land -- may be checked for them.
run_helpmate(out rc mine KQvk --dtm 2 --max 1 --json --tables "${TABLES}")
string(FIND "${out}" "\"positions\"" pos_positions)
string(SUBSTRING "${out}" ${pos_positions} -1 after_positions)
if(NOT rc EQUAL 0 OR "${after_positions}" MATCHES "\"themes\"" OR "${after_positions}" MATCHES "\"solutions\"")
  message(FATAL_ERROR "--json alone must not carry facets:\n${out}")
endif()

# 4a. --max 0 with --json: an empty match, not an error.
run_helpmate(out rc mine KQvk --dtm 2 --max 0 --json --tables "${TABLES}")
if(NOT rc EQUAL 0 OR NOT "${out}" MATCHES "\"positions\": \\[\\]")
  message(FATAL_ERROR "--max 0 --json: expected exit 0 with an empty positions array, got ${rc}:\n${out}")
endif()

# 4b. --max infinity with --json: max recorded as "infinity" and every one
# of the 580 dtm=2 positions present.
run_helpmate(out rc mine KQvk --dtm 2 --max infinity --json --tables "${TABLES}")
if(NOT rc EQUAL 0 OR NOT "${out}" MATCHES "\"max\": \"infinity\"")
  message(FATAL_ERROR "--max infinity --json: expected exit 0 with max recorded as infinity, got ${rc}:\n${out}")
endif()
string(REGEX MATCHALL "\"fen\":" fens "${out}")
list(LENGTH fens n_fens)
if(NOT n_fens EQUAL 580)
  message(FATAL_ERROR "--max infinity --json: expected 580 \"fen\": occurrences, got ${n_fens}")
endif()

# 5. Text --solutions: FEN, indented line, blank line. And --themes is accepted by mine now.
run_helpmate(out rc mine KQvk --dtm 2 --max 2 --solutions --themes --tables "${TABLES}")
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "--solutions --themes failed (${rc}): ${last_err}")
endif()
if(NOT "${out}" MATCHES "^8/8/8/8/8/8/8/k1KQ4 b - - 0 1\n  themes:[^\n]*mirror[^\n]*\n  Ka2 Qa4#\n\n8/8/8/8/8/2Q5/8/k1K5 b - - 0 1\n")
  message(FATAL_ERROR "--solutions --themes text layout is wrong:\n${out}")
endif()

# 6. Default output is unchanged: bare FENs.
run_helpmate(out rc mine KQvk --dtm 2 --max 2 --tables "${TABLES}")
if(NOT "${out}" STREQUAL "8/8/8/8/8/8/8/k1KQ4 b - - 0 1\n8/8/8/8/8/2Q5/8/k1K5 b - - 0 1\n")
  message(FATAL_ERROR "default mine output changed:\n${out}")
endif()

# 7. --jsonl: header line, one compact record per hit, footer line with the
# counts. Every line is its own JSON document; the header has no "fen", the
# footer has no "fen", every record has one.
run_helpmate(out rc mine KQvk --dtm 2 --max 2 --jsonl --themes --solutions --tables "${TABLES}")
if(NOT rc EQUAL 0)
  message(FATAL_ERROR "--jsonl failed (${rc}): ${last_err}")
endif()
string(REGEX MATCHALL "\n" nl "${out}")
list(LENGTH nl n)
if(NOT n EQUAL 4)
  message(FATAL_ERROR "--jsonl --max 2: expected 4 lines (header, 2 records, footer), got ${n}:\n${out}")
endif()
string(REPLACE "\n" ";" jl "${out}")
list(GET jl 0 l0)
list(GET jl 1 l1)
list(GET jl 3 l3)
if(NOT "${l0}" MATCHES "^{\"material\":\"KQvk\",\"filter\":" OR "${l0}" MATCHES "\"fen\"")
  message(FATAL_ERROR "--jsonl header wrong: ${l0}")
endif()
if(NOT "${l1}" MATCHES "^{\"fen\":\"8/8/8/8/8/8/8/k1KQ4 b - - 0 1\",\"dtm\":2,\"count\":1,\"themes\":\\[" OR NOT "${l1}" MATCHES "\"solutions\":\\[\\[\"Ka2\",\"Qa4#\"\\]\\]}$")
  message(FATAL_ERROR "--jsonl record wrong: ${l1}")
endif()
if(NOT "${l3}" STREQUAL "{\"positions\":2,\"skipped_saturated\":0}")
  message(FATAL_ERROR "--jsonl footer wrong: ${l3}")
endif()
# 7a. --jsonl streams the whole scan: 580 records + 2.
run_helpmate(out rc mine KQvk --dtm 2 --max infinity --jsonl --tables "${TABLES}")
string(REGEX MATCHALL "\n" nl "${out}")
list(LENGTH nl n)
if(NOT rc EQUAL 0 OR NOT n EQUAL 582)
  message(FATAL_ERROR "--jsonl --max infinity: expected 582 lines, got ${n} (rc ${rc})")
endif()
if(NOT "${out}" MATCHES "\n{\"positions\":580,\"skipped_saturated\":0}\n$")
  message(FATAL_ERROR "--jsonl footer after a full scan wrong:\n${out}")
endif()
# 7b. --json and --jsonl together is a usage error.
run_helpmate(out rc mine KQvk --dtm 2 --json --jsonl --tables "${TABLES}")
if(NOT rc EQUAL 3 OR NOT "${last_err}" MATCHES "--json and --jsonl")
  message(FATAL_ERROR "--json --jsonl: expected exit 3 naming both flags, got ${rc}: ${last_err}")
endif()

# 8. --threads does not change any output: --jsonl annotates on the scan
# workers, --json on the set's workers, and a --max stop must cut both at the
# same record as one thread.
foreach(fmt --jsonl --json)
  foreach(max infinity 7 0)
    run_helpmate(one rc1 mine KQvk --dtm 4 --max ${max} ${fmt} --themes --solutions --threads 1 --tables "${TABLES}")
    run_helpmate(four rc4 mine KQvk --dtm 4 --max ${max} ${fmt} --themes --solutions --threads 4 --tables "${TABLES}")
    if(NOT rc1 EQUAL 0 OR NOT rc4 EQUAL 0)
      message(FATAL_ERROR "${fmt} --max ${max}: failed (${rc1}/${rc4}): ${last_err}")
    endif()
    if(NOT "${one}" STREQUAL "${four}")
      message(FATAL_ERROR "${fmt} --max ${max}: --threads 4 output differs from --threads 1")
    endif()
  endforeach()
endforeach()

message(STATUS "mine output modes verified (--max infinity/inf, --json, --jsonl, --themes, --solutions, --threads)")

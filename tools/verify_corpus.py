"""Decompress every block of every block-compressed table and report the ones
that do not come back clean.

    python3 tools/verify_corpus.py ~/tb              # a directory
    python3 tools/verify_corpus.py ~/tb/KBvkqbn.hm   # one table
    python3 tools/verify_corpus.py ~/tb -j 4         # four tables at a time

Read-only. Nothing about the tables is interpreted -- no positions, no DTM
semantics -- only that each zstd frame decodes, that its content checksum
matches (every block is written with one; see compress_block in
src/core/format/block_codec.cpp), and that it decodes to the length the block
index promises. Markers (format version 2) and raw tables (version 1) have no
blocks and are reported as skipped.

Why this exists: on 2026-08-21 tools/deepest_showcase.py hit "zstd decompress
failed: Restored data doesn't match checksum" on roughly one probe in ten
against large compressed tables, and grew a retry. On 2026-09-07 the error did
not reproduce in ~550 CLI runs and every block of the 233-table corpus
(8,099,259 blocks) decoded cleanly with this script. The reader had not
changed between the two dates. A checksum failure that comes and goes on
identical bytes is not something the reader can cause on its own, so the
question to ask when it appears is whether the bytes on disk are sound, and
this is how to ask it. A table that fails here is corrupt on disk; one that
passes here and still fails in helpmate points at the machine.

Exit status: 0 when every table checked is clean, 1 when any is not, 2 on
usage errors. Layout follows TableHeader in src/core/format/table_file.h.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

# The block check lives in the helpmate-tables package now (it is verify's
# V3); this script keeps its command line and output for existing runbooks.
try:
    from helpmate_server.contrib.tablefile import check_blocks
except ImportError:  # running from a checkout without helpmate-api installed
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "packages" / "api"))
    from helpmate_server.contrib.tablefile import check_blocks


def check_table(path: str) -> tuple[str, str, int, float]:
    """Return (path, verdict, blocks_checked, seconds). verdict is 'OK', a
    'skip ...' reason, or 'BAD ...' with the first bad blocks listed."""
    t0 = time.time()
    verdict, nb = check_blocks(path)
    return path, verdict, nb, time.time() - t0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("target", help="a .hm file or a directory of them")
    ap.add_argument(
        "-j", "--jobs", type=int, default=2, help="tables checked in parallel (default 2)"
    )
    a = ap.parse_args(argv)

    target = Path(a.target).expanduser()
    if target.is_dir():
        paths = sorted((str(p) for p in target.glob("*.hm")), key=os.path.getsize)
    elif target.is_file():
        paths = [str(target)]
    else:
        print(f"verify_corpus: no such file or directory: {target}", file=sys.stderr)
        return 2
    if not paths:
        print(f"verify_corpus: no .hm files in {target}", file=sys.stderr)
        return 2

    failed = 0
    checked = blocks = 0
    with Pool(max(1, a.jobs)) as pool:
        for path, verdict, nb, dt in pool.imap_unordered(check_table, paths):
            print(f"{Path(path).name:20} {verdict}  blocks={nb} {dt:.0f}s", flush=True)
            if verdict.startswith("BAD"):
                failed += 1
            if not verdict.startswith("skip"):
                checked += 1
                blocks += nb
    print(
        f"\n{checked} table(s) checked, {blocks:,} blocks, {failed} bad, "
        f"{len(paths) - checked} skipped (markers / raw)"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

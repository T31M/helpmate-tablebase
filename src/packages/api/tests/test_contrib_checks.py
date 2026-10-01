# src/packages/api/tests/test_contrib_checks.py
import json
import struct

from contrib_helpers import edit_sidecar, flip_frame_byte, rewrite_payload
from helpmate_server.contrib.checks import (
    check_block_integrity, check_deepest, check_header, check_sidecar,
)

V = "99.0.0"  # "installed" version newer than any generator


def test_clean_tables_pass_v2_to_v5(compressed_tables):
    for mat in ("KQvk", "KPvk"):
        p = compressed_tables / f"{mat}.hm"
        assert check_header(p, V).status == "pass"
        assert check_block_integrity(p).status == "pass"
        assert check_sidecar(p).status == "pass", check_sidecar(p).detail
        assert check_deepest(p, compressed_tables).status == "pass"


def test_v2_catches_a_renamed_file(table_copy):
    (table_copy / "KQvk.hm").rename(table_copy / "KBBvk.hm")      # not in the closure
    (table_copy / "KQvk.stats.json").rename(table_copy / "KBBvk.stats.json")
    c = check_header(table_copy / "KBBvk.hm", V)
    assert c.status == "fail" and "header says 'KQvk'" in c.detail


def test_v2_catches_a_raw_table_and_a_newer_generator(table_copy):
    p = table_copy / "KQvk.hm"
    assert "newer than the installed" in check_header(p, "0.0.1").detail
    raw = bytearray(p.read_bytes())
    struct.pack_into("<I", raw, 4, 1)          # version 1
    raw[8] = 1                                 # encoding raw
    p.write_bytes(bytes(raw))
    assert "block-compressed" in check_header(p, V).detail


def test_v2_catches_sidecar_drift(table_copy):
    edit_sidecar(table_copy / "KQvk.hm", lambda d: d.update(max_dtm=3))
    assert "sidecar differs" in check_header(table_copy / "KQvk.hm", V).detail


def test_v3_catches_a_damaged_frame(table_copy):
    flip_frame_byte(table_copy / "KQvk.hm", 3)
    assert check_block_integrity(table_copy / "KQvk.hm").status == "fail"


def test_v4_catches_one_changed_dtm_cell(table_copy):
    p = table_copy / "KQvk.hm"

    def bump(payload, ps):                     # first solvable btm cell: +2 plies
        for i in range(ps, 2 * ps):
            if payload[i] < 250:
                payload[i] += 2
                return
    rewrite_payload(p, bump)
    c = check_sidecar(p)
    assert c.status == "fail" and "dtm_histogram" in c.detail
    assert check_block_integrity(p).status == "pass"   # V3 cannot see it


def test_v4_catches_a_changed_count_cell(table_copy):
    p = table_copy / "KQvk.hm"

    def bump(payload, ps):
        for i in range(ps, 2 * ps):
            if payload[i] < 250:
                payload[2 * ps + i] = 2 if payload[2 * ps + i] == 1 else 1
                return
    rewrite_payload(p, bump)
    c = check_sidecar(p)
    assert c.status == "fail" and "uniqueness" in c.detail


def test_v5_catches_a_wrong_deepest_list(table_copy):
    p = table_copy / "KQvk.hm"
    sc = json.loads((table_copy / "KQvk.stats.json").read_text())
    sc["deepest"] = sc["deepest_unique"][:1]   # a unique-deepest position is shallower
    (table_copy / "KQvk.stats.json").write_text(json.dumps(sc))
    c = check_deepest(p, table_copy)
    assert c.status == "fail", c.detail


def test_malformed_sidecar_fails_every_check_without_raising(table_copy):
    p = table_copy / "KQvk.hm"
    (table_copy / "KQvk.stats.json").write_text("{not json")
    assert check_header(p, V).status == "fail"
    assert check_sidecar(p).status == "fail"
    assert check_deepest(p, table_copy).status == "fail"


def test_missing_sidecar_fails_v4_and_v5_without_raising(table_copy):
    p = table_copy / "KQvk.hm"
    (table_copy / "KQvk.stats.json").unlink()
    assert check_header(p, V).status == "fail"
    for c in (check_sidecar(p), check_deepest(p, table_copy)):
        assert c.status == "fail" and "no .stats.json" in c.detail


def test_v4_reports_a_bad_header_as_fail(table_copy):
    p = table_copy / "KQvk.hm"
    p.write_bytes(b"XXXX" + p.read_bytes()[4:])
    assert check_sidecar(p).status == "fail"

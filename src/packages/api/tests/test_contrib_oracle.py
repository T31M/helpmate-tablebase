import helpmate
import pytest

from contrib_helpers import rewrite_payload
from helpmate_server.contrib.oracle import check_oracle, solve


def test_solve_mate_in_zero_one_and_none():
    assert solve("k7/1Q6/1K6/8/8/8/8/8 b - - 0 1", 3) == (0, 1)
    d, n = solve("k7/2Q5/1K6/8/8/8/8/8 w - - 0 1", 3)
    assert d == 1 and n >= 1
    assert solve("k7/2Q5/1K6/8/8/8/8/8 b - - 0 1", 3) is None     # stalemate


def test_solve_agrees_with_table_probe(compressed_tables):
    tb = helpmate.Tablebase(str(compressed_tables))
    for d in range(4):
        for fen in tb.mine("KQvk", dtm=d, max=5):
            p = tb.probe(fen)
            assert solve(fen, 3) == (p[0], p[1]), fen


@pytest.mark.parametrize("mat", ["KQvk", "KPvk"])
def test_clean_tables_pass(compressed_tables, mat):
    c = check_oracle(mat, compressed_tables, samples=5, max_plies=3, seed=3, others=[])
    assert c.status == "pass", c.detail


def test_shallow_value_error_is_caught(table_copy):
    def damage(payload, ps):                   # every wtm mate-in-1 becomes mate-in-3
        for i in range(ps):
            if payload[i] == 1:
                payload[i] = 3
    rewrite_payload(table_copy / "KQvk.hm", damage)
    c = check_oracle("KQvk", table_copy, samples=40, max_plies=3, seed=3, others=[])
    assert c.status == "fail", c.detail

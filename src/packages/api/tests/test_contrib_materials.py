from helpmate_server.contrib.materials import Material, canonical, expand, universe


def test_universe_has_1000_materials_by_piece_count():
    by = {}
    for m in universe():
        by[m.pieces] = by.get(m.pieces, 0) + 1
    assert by == {3: 10, 4: 55, 5: 220, 6: 715}
    names = [m.name for m in universe()]
    assert len(set(names)) == 1000


def test_bare_white_king_count_at_six_pieces():
    six = [m for m in universe() if m.pieces == 6]
    assert sum(m.bare_king for m in six) == 70
    assert sum(not m.bare_king for m in six) == 645


def test_canonical_orders_each_side_and_rejects_non_materials():
    assert canonical("KBRvkqq") == "KRBvkqq"
    assert canonical("KRBvkqq") == "KRBvkqq"
    assert canonical("KPBBvk") == "KBBPvk"
    assert canonical("Kvk") is None            # 2 pieces: outside the universe
    assert canonical("KQQQQQvk") is None        # 7 pieces (K + 5 Q's + v + k = 2 + 5)
    assert canonical("KQvkK") is None
    assert canonical("kqvK") is None


def test_plane_size_matches_corpus_headers():
    assert Material("KQvk").plane_size == 29568
    assert Material("KRBvkqq").plane_size == 7751073792
    assert Material("KBBPvk").plane_size == 1806 * 48 * 64 ** 2


def test_expand_wildcards():
    got = expand("KQvk???")
    assert len(got) == 35                      # multisets of 3 over 5 black kinds
    assert "KQvkqbb" in got and "KQvkppp" in got
    assert expand("KRRvk??") == sorted(expand("KRRvk??"), key=lambda n: universe_index(n))
    assert expand("KRBvkqq") == ["KRBvkqq"]
    assert expand("KQvk?????") == []           # 7 pieces


def universe_index(name):
    return [m.name for m in universe()].index(name)


def test_ram_tiers():
    assert Material("KRBvkqq").ram_tier_gib == 32
    assert Material("KRBvkqp").ram_tier_gib == 96
    assert Material("KRPvkpp").ram_tier_gib == 64

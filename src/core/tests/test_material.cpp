#include <catch2/catch_test_macros.hpp>
#include "indexing/material.h"
#include <set>
using namespace hm;
TEST_CASE("parse and canonical name") {
    auto m = Material::parse("KBkqrbp"); REQUIRE(m);
    CHECK(m->name() == "KBvkqrbp");
    CHECK(Material::parse("KQvk")->name() == "KQvk");
    CHECK(Material::parse("KPpk"));                    // order-insensitive within a color
    CHECK(!Material::parse("KQ"));                     // missing black king
    CHECK(!Material::parse("KKk"));                    // two white kings
    CHECK(Material::parse("KQvk")->total() == 3);
    CHECK(!Material::parse("KQvk")->has_pawns());
    CHECK(Material::parse("KPvkp")->pawn_count() == 2);
}
TEST_CASE("successors of KPvk") {
    auto m = *Material::parse("KPvk");
    std::set<std::string> names;
    for (auto& s : m.successors()) names.insert(s.name());
    CHECK(names == std::set<std::string>{"Kvk", "KQvk", "KRvk", "KBvk", "KNvk"});
}
TEST_CASE("closure is topologically ordered") {
    auto order = Material::closure_topo(*Material::parse("KQvkp"));
    CHECK(order.back().name() == "KQvkp");
    auto pos_of = [&](const std::string& n) {
        for (size_t i = 0; i < order.size(); ++i) if (order[i].name() == n) return (int)i;
        return -1; };
    for (auto& m : order)                              // property: successors appear strictly earlier
        for (auto& s : m.successors()) {
            INFO(m.name() << " -> " << s.name());
            CHECK(pos_of(s.name()) >= 0);
            CHECK(pos_of(s.name()) < pos_of(m.name()));
        }
}
TEST_CASE("closure of KPvk exact") {
    auto order = Material::closure_topo(*Material::parse("KPvk"));
    REQUIRE(order.size() == 6);
    CHECK(order.front().name() == "Kvk");
    CHECK(order.back().name() == "KPvk");
}
TEST_CASE("mating_side_is_bare_king identifies materials white can never mate with") {
    auto bare = [](const char* n) {
        return Material::parse(n)->mating_side_is_bare_king();
    };
    // White is a bare king: it can never give check, so no mate can exist.
    CHECK(bare("Kvk"));
    CHECK(bare("Kvkq"));
    CHECK(bare("Kvkqrp"));      // black may promote; white stays a bare king
    // White has material: not this rule's business (solvability decided elsewhere).
    CHECK_FALSE(bare("KQvk"));
    CHECK_FALSE(bare("KBvkqqr"));
    CHECK_FALSE(bare("KPvk"));  // a white pawn can promote
}
TEST_CASE("packed counts round-trip and match per-type counts") {
    for (const char* name : {"Kvk", "KQvk", "KRBvkq", "KPPvkpp", "KQRBNPvkqrbnp", "KBBBvk"}) {
        Material m = *Material::parse(name);
        auto c = m.counts();
        for (int t = 0; t < 6; ++t) {
            CHECK((uint8_t)(c[0] >> (8 * t)) == m.white[t]);
            CHECK((uint8_t)(c[1] >> (8 * t)) == m.black[t]);
        }
        CHECK(Material::from_counts(c) == m);
    }
    CHECK(Material::parse("KRvk")->counts() != Material::parse("KBvk")->counts());
}

#include <unistd.h>

#include <atomic>
#include <catch2/catch_test_macros.hpp>
#include <cstddef>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <random>
#include <thread>
#include <vector>

#include "format/block_codec.h"
#include "format/table_file.h"
#include "indexing/material.h"
#include "probe/tablebase.h"
using namespace hm;
TEST_CASE("header is 64 bytes") { CHECK(sizeof(TableHeader) == 64); }
TEST_CASE("write/read round trip") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "KQvk.hm").string();
    const uint64_t n = 1000;
    std::vector<uint8_t> dw(n), db(n), cw(n), cb(n);
    for (uint64_t i = 0; i < n; ++i) {
        dw[i] = i % 250;
        db[i] = (i * 7) % 250;
        cw[i] = i % 3;
        cb[i] = 1;
    }
    TableWriter::write(path, *Material::parse("KQvk"), n, 42, "{\"hello\":1}", dw.data(), db.data(),
                       cw.data(), cb.data());
    auto r = TableReader::open(path);
    REQUIRE(r);
    CHECK(r->plane_size() == n);
    CHECK(r->max_dtm() == 42);
    CHECK(r->material_name() == "KQvk");
    CHECK(r->meta_json() == "{\"hello\":1}");
    for (uint64_t i : {0ull, 1ull, 500ull, 999ull}) {
        CHECK(r->get(Color::White, i).dtm == dw[i]);
        CHECK(r->get(Color::White, i).count == cw[i]);
        CHECK(r->get(Color::Black, i).dtm == db[i]);
        CHECK(r->get(Color::Black, i).count == cb[i]);
    }
    CHECK(!TableReader::open((dir / "missing.hm").string()));
}
TEST_CASE("reader rejects a header with an overflow-crafted plane_size") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "overflow.hm").string();
    TableHeader hdr{};
    std::memcpy(hdr.magic, "HM8P", 4);
    hdr.version = 1;
    hdr.encoding = 1;
    hdr.symmetry = 1;
    std::memcpy(hdr.material, "Kvk", 3);
    hdr.plane_size = (1ull << 62);  // 4 * plane_size overflows uint64_t
    hdr.max_dtm = 0;
    hdr.json_len = 0;
    {
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(&hdr), sizeof(hdr));
    }
    CHECK(!TableReader::open(path));
}
TEST_CASE("reader rejects a truncated file") {
    auto dir = std::filesystem::temp_directory_path() / "hm_test_tables";
    std::filesystem::create_directories(dir);
    auto path = (dir / "trunc.hm").string();
    const uint64_t n = 100;
    std::vector<uint8_t> p(n, 1);
    TableWriter::write(path, *Material::parse("Kvk"), n, 5, "{}", p.data(), p.data(), p.data(), p.data());
    auto sz = std::filesystem::file_size(path);
    std::filesystem::resize_file(path, sz - 3);
    CHECK(!TableReader::open(path));
}
TEST_CASE("marker tables expand to DTM_UNSOLVABLE without a payload") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_marker_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "KBvkq.hm").string();
    Material m = *Material::parse("KBvkq");
    const uint64_t ps = 1234;

    TableWriter::write_unsolvable(path, m, ps, R"({"material":"KBvkq"})");

    // A marker is tiny: header + JSON, no planes.
    CHECK(fs::file_size(path) < 512);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK(r->all_unsolvable());
    CHECK(r->plane_size() == ps);
    CHECK(r->material_name() == "KBvkq");
    CHECK(r->max_dtm() == DTM_UNSOLVABLE);
    for (uint64_t c : {uint64_t(0), ps / 2, ps - 1}) {
        auto v = r->get(Color::White, c);
        CHECK(v.dtm == DTM_UNSOLVABLE);
        CHECK(v.count == 0);
        CHECK(r->get(Color::Black, c).dtm == DTM_UNSOLVABLE);
    }
    CHECK_THROWS_AS(r->get(Color::White, ps), std::out_of_range);
    CHECK_THROWS_AS(r->get(Color::White, ~uint64_t(0)), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("ordinary tables stay format version 1 and keep reading") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_v1_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "Kvk.hm").string();
    std::vector<uint8_t> dw(4, 7), db(4, 8), cw(4, 1), cb(4, 2);
    TableWriter::write(path, *Material::parse("Kvk"), 4, 7, "{}", dw.data(), db.data(), cw.data(), cb.data());

    std::ifstream in(path, std::ios::binary);
    TableHeader hdr{};
    in.read(reinterpret_cast<char*>(&hdr), sizeof(hdr));
    CHECK(hdr.version == 1);
    CHECK((hdr.flags & 0x01) == 0);

    auto r = TableReader::open(path);
    REQUIRE(r.has_value());
    CHECK_FALSE(r->all_unsolvable());
    CHECK(r->get(Color::White, 0).dtm == 7);
    CHECK(r->get(Color::Black, 3).dtm == 8);
    fs::remove_all(dir);
}

TEST_CASE("malformed marker headers are rejected") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_marker_bad_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string valid_path = (dir / "KBvkq.hm").string();
    Material m = *Material::parse("KBvkq");
    const uint64_t ps = 1234;

    TableWriter::write_unsolvable(valid_path, m, ps, R"({"material":"KBvkq"})");

    std::vector<uint8_t> bytes;
    {
        std::ifstream in(valid_path, std::ios::binary);
        bytes.assign(std::istreambuf_iterator<char>(in), std::istreambuf_iterator<char>());
    }
    REQUIRE(bytes.size() >= sizeof(TableHeader));

    // (a) version == 2 but the marker flag is CLEAR -> must be rejected.
    {
        std::vector<uint8_t> corrupt = bytes;
        corrupt[offsetof(TableHeader, flags)] = 0;
        std::string path = (dir / "flag_clear.hm").string();
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(corrupt.data()),
                  static_cast<std::streamsize>(corrupt.size()));
        out.close();
        CHECK(!TableReader::open(path));
    }

    // (b) version == 2, marker flag SET, but a non-empty trailing payload -> must be rejected.
    {
        std::vector<uint8_t> corrupt = bytes;
        corrupt.push_back(0);
        corrupt.push_back(0);
        corrupt.push_back(0);
        corrupt.push_back(0);
        std::string path = (dir / "extra_payload.hm").string();
        std::ofstream out(path, std::ios::binary | std::ios::trunc);
        out.write(reinterpret_cast<const char*>(corrupt.data()),
                  static_cast<std::streamsize>(corrupt.size()));
        out.close();
        CHECK(!TableReader::open(path));
    }

    fs::remove_all(dir);
}

TEST_CASE("a future-format table reports UnsupportedVersion, not NotFound") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_future_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "Kvk.hm").string();

    // Write a valid marker, then bump its version byte to a value this build
    // does not know -- exactly what an older binary sees when it meets a newer table.
    TableWriter::write_unsolvable(path, *Material::parse("Kvk"), 462, "{}");
    {
        std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
        uint32_t v = 99;
        f.seekp(offsetof(TableHeader, version));
        f.write(reinterpret_cast<const char*>(&v), sizeof(v));
    }

    TableReader::OpenError err = TableReader::OpenError::None;
    auto r = TableReader::open(path, &err);
    CHECK_FALSE(r.has_value());
    CHECK(err == TableReader::OpenError::UnsupportedVersion);

    // A genuinely absent file is still NotFound.
    TableReader::OpenError err2 = TableReader::OpenError::None;
    CHECK_FALSE(TableReader::open((dir / "KQvk.hm").string(), &err2).has_value());
    CHECK(err2 == TableReader::OpenError::NotFound);

    fs::remove_all(dir);
}

TEST_CASE("header keeps its 64-byte layout after claiming reserved bytes") {
    static_assert(sizeof(hm::TableHeader) == 64);
    // The two new fields come out of `reserved`, which was 14 bytes.
    hm::TableHeader h{};
    h.block_size = 65536;
    h.codec = hm::kCodecZstd;
    CHECK(h.block_size == 65536u);
    CHECK(h.codec == 1);
    CHECK(sizeof(h.reserved) == 9);
    // A default-constructed header must still describe a raw table, so any
    // code path that forgets to set these does not silently claim compression.
    hm::TableHeader zero{};
    CHECK(zero.codec == hm::kCodecNone);
    CHECK(zero.block_size == 0u);
}

TEST_CASE("every cell reads identically through raw and compressed tables") {
    // The central correctness claim of the whole rung, checked exhaustively at
    // a size where exhaustive is cheap.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_test";
    fs::remove_all(dir);
    fs::create_directories(dir);

    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 4096;
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    std::mt19937 rng(99);
    for (uint64_t i = 0; i < ps; ++i) {
        // A realistic mix: mostly the two constants, some real values.
        uint32_t r = rng() % 100;
        dw[i] = r < 45 ? DTM_INVALID : (r < 70 ? DTM_UNSOLVABLE : uint8_t(rng() % 30));
        db[i] = r < 40 ? DTM_INVALID : (r < 65 ? DTM_UNSOLVABLE : uint8_t(rng() % 30));
        // `count` is the number of distinct optimal lines (docs/USAGE.md): in
        // real tables it is almost always small, occasionally larger, never
        // uniform over the full byte range. `uint8_t(rng() % 256)` here would
        // be literally incompressible noise for half the logical payload,
        // which makes the ratio assertion below unsatisfiable regardless of
        // codec quality -- so mirror the real distribution instead.
        cw[i] = (rng() % 100 < 95) ? uint8_t(rng() % 4) : uint8_t(rng() % 40);
        cb[i] = (rng() % 100 < 95) ? uint8_t(rng() % 4) : uint8_t(rng() % 40);
    }
    std::string meta = R"({"material":"KQvk"})";

    std::string raw = (dir / "raw.hm").string();
    std::string zip = (dir / "zip.hm").string();
    TableWriter::write(raw, mat, ps, 30, meta, dw.data(), db.data(), cw.data(), cb.data());
    TableWriter::write_compressed(zip, mat, ps, 30, meta, dw.data(), db.data(), cw.data(), cb.data());

    auto r = TableReader::open(raw);
    auto z = TableReader::open(zip);
    REQUIRE(r.has_value());
    REQUIRE(z.has_value());
    CHECK_FALSE(r->is_compressed());
    CHECK(z->is_compressed());
    CHECK(z->plane_size() == ps);
    CHECK(z->max_dtm() == 30);
    CHECK(z->material_name() == "KQvk");
    CHECK(z->meta_json() == meta);

    for (uint64_t i = 0; i < ps; ++i) {
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair a = r->get(stm, i), b = z->get(stm, i);
            REQUIRE(a.dtm == b.dtm);
            REQUIRE(a.count == b.count);
        }
    }
    CHECK(fs::file_size(zip) < fs::file_size(raw) / 2);
    fs::remove_all(dir);
}

TEST_CASE("a compressed table whose last block is partial round-trips") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_partial";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    // 4 * 5000 = 20000 bytes: not a multiple of 65536, so there is exactly one
    // short block and nothing else.
    const uint64_t ps = 5000;
    std::vector<uint8_t> dw(ps, 3), db(ps, 4), cw(ps, 5), cb(ps, 6);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 4, "{}", dw.data(), db.data(), cw.data(), cb.data());
    auto z = TableReader::open(p);
    REQUIRE(z.has_value());
    CHECK(z->get(Color::White, ps - 1).dtm == 3);
    CHECK(z->get(Color::Black, ps - 1).dtm == 4);
    CHECK(z->get(Color::White, ps - 1).count == 5);
    CHECK(z->get(Color::Black, ps - 1).count == 6);
    fs::remove_all(dir);
}

TEST_CASE("an out-of-range cell throws on a compressed table too") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_range";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 1000;
    std::vector<uint8_t> v(ps, 1);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 1, "{}", v.data(), v.data(), v.data(), v.data());
    auto z = TableReader::open(p);
    REQUIRE(z.has_value());
    CHECK_THROWS_AS(z->get(Color::White, ps), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("the committed golden compressed table still reads correctly") {
    // Pins the ON-DISK format. Every other compressed test writes and reads
    // with the same build, so a layout change that breaks compatibility would
    // pass them all. This one fails.
    std::string fixture = std::string(HM_TEST_FIXTURES) + "/golden-KQvk-v3.hm";
    auto z = TableReader::open(fixture);
    REQUIRE(z.has_value());
    CHECK(z->is_compressed());
    CHECK(z->material_name() == "KQvk");
    CHECK(z->plane_size() == 29568);
    CHECK(z->max_dtm() == 14);

    // The golden position from the README: dtm 2 (h#1), count 4. Its canonical
    // cell index is asserted by the existing probe tests, so read through the
    // Tablebase layer rather than hardcoding a cell number here. Tablebase
    // resolves "<dir>/<material>.hm", so stage the fixture under that name.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_golden_probe";
    fs::remove_all(dir);
    fs::create_directories(dir);
    fs::copy_file(fixture, dir / "KQvk.hm");

    Tablebase tb(dir.string());
    auto p = tb.probe("8/7k/5K2/8/8/8/8/6Q1 b - - 0 1");
    REQUIRE(p.has_value());
    CHECK(p->dtm == 2);
    CHECK(p->count == 4);
    CHECK_FALSE(p->flipped);
    fs::remove_all(dir);
}

// Shared by the two adversarial-index tests below: writes a valid
// block-compressed table with at least 3 blocks and returns the byte offset
// of offs[0] in the file, i.e. sizeof(TableHeader) + json_len +
// sizeof(uint64_t) (the stated block count precedes the offsets array).
namespace {
uint64_t write_compressed_for_index_tamper(const std::string& path) {
    Material mat = Material::parse("KQvk").value();
    // 4 * plane_size must exceed 2 * 65536 so there are at least 3 blocks
    // (kDefaultBlockSize) to give the monotonicity check an interior pair.
    const uint64_t ps = 40000;
    std::vector<uint8_t> dw(ps, 1), db(ps, 2), cw(ps, 3), cb(ps, 4);
    const std::string meta = "{}";
    TableWriter::write_compressed(path, mat, ps, 5, meta, dw.data(), db.data(), cw.data(), cb.data());

    const uint64_t nb = block_count(4 * ps, kDefaultBlockSize);
    REQUIRE(nb >= 3);
    return sizeof(TableHeader) + meta.size() + sizeof(uint64_t);
}

void patch_u64_at(const std::string& path, uint64_t byte_offset, uint64_t value) {
    std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
    REQUIRE(f.is_open());
    f.seekp(static_cast<std::streamoff>(byte_offset));
    f.write(reinterpret_cast<const char*>(&value), sizeof(value));
    REQUIRE(f.good());
}
}  // namespace

TEST_CASE("a crafted interior block offset is rejected at open, not left to crash get()") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_offs_huge_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "t.hm").string();

    const uint64_t offs0_pos = write_compressed_for_index_tamper(path);
    const uint64_t offs1_pos = offs0_pos + sizeof(uint64_t);

    // Sanity: the table is readable before tampering.
    {
        auto z = TableReader::open(path);
        REQUIRE(z.has_value());
    }

    // Mirrors the reviewer's reproduction: an interior offset set far past the
    // end of the payload. Before Fix 1, open() only checked offs[nb]; this
    // offs[1] was invisible to it, and get() would later hand it straight to
    // the block cache / zstd and segfault (ZSTD_decompress_usingDDict via
    // hm::decompress_block via BlockCache::byte_at).
    patch_u64_at(path, offs1_pos, 100000000000ull);

    TableReader::OpenError err = TableReader::OpenError::None;
    auto z = TableReader::open(path, &err);
    CHECK_FALSE(z.has_value());
    CHECK(err == TableReader::OpenError::Unreadable);
    fs::remove_all(dir);
}

TEST_CASE("a non-monotonic interior offset pair is rejected at open") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_offs_nonmono_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "t.hm").string();

    const uint64_t offs0_pos = write_compressed_for_index_tamper(path);
    const uint64_t offs1_pos = offs0_pos + sizeof(uint64_t);
    const uint64_t offs2_pos = offs1_pos + sizeof(uint64_t);

    // offs[0] is fixed at 0 by construction (the first block starts at the
    // beginning of the payload), so a decreasing pair can't be built by
    // pushing offs[1] below offs[0] -- that would require an offset less than
    // zero, which doesn't exist for uint64_t. Instead read the real offs[2]
    // and set offs[1] just above it: offs[1] > offs[2] is exactly the
    // violation `offs[i] <= offs[i+1]` exists to catch, and it stays within
    // the payload (<= offs[nb]) so this isolates the monotonicity check from
    // the final-bound check exercised by the previous test.
    uint64_t offs2;
    {
        std::ifstream in(path, std::ios::binary);
        REQUIRE(in.is_open());
        in.seekg(static_cast<std::streamoff>(offs2_pos));
        in.read(reinterpret_cast<char*>(&offs2), sizeof(offs2));
        REQUIRE(in.good());
    }
    patch_u64_at(path, offs1_pos, offs2 + 1);

    TableReader::OpenError err = TableReader::OpenError::None;
    auto z = TableReader::open(path, &err);
    CHECK_FALSE(z.has_value());
    CHECK(err == TableReader::OpenError::Unreadable);
    fs::remove_all(dir);
}

TEST_CASE("block_count is overflow-free by construction") {
    // The case Task 2 documented as wrapping under the old
    // (logical_size + block_size - 1) / block_size formulation: with the old
    // formula, UINT64_MAX + 65536 - 1 wraps mod 2^64 and yields 0. The
    // division-based formulation below has no such term.
    CHECK(block_count(UINT64_MAX, 65536) == 281474976710656ull);
    // Ordinary cases, unchanged behavior: zero, exact multiple, one over.
    CHECK(block_count(0, 65536) == 0ull);
    CHECK(block_count(65536, 65536) == 1ull);
    CHECK(block_count(65537, 65536) == 2ull);
}

TEST_CASE("a table from a newer helpmate reports UnsupportedVersion, not Unreadable") {
    // The reason compressed tables carry version 3 as well as encoding 2:
    // older binaries validate `encoding` but only `version` produces the
    // actionable "upgrade this build" message.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_blockfmt_future";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 512;
    std::vector<uint8_t> v(ps, 1);
    std::string p = (dir / "t.hm").string();
    TableWriter::write_compressed(p, mat, ps, 1, "{}", v.data(), v.data(), v.data(), v.data());

    // Bump the on-disk version past what this build knows.
    std::fstream f(p, std::ios::binary | std::ios::in | std::ios::out);
    uint32_t future = 99;
    f.seekp(4);
    f.write(reinterpret_cast<const char*>(&future), sizeof(future));
    f.close();

    TableReader::OpenError err = TableReader::OpenError::None;
    auto r = TableReader::open(p, &err);
    CHECK_FALSE(r.has_value());
    CHECK(err == TableReader::OpenError::UnsupportedVersion);
    fs::remove_all(dir);
}

TEST_CASE("compress_existing streams a raw table's payload without buffering the planes") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_compress_existing";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 3000;
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    for (uint64_t i = 0; i < ps; ++i) {
        dw[i] = static_cast<uint8_t>(i % 200);
        db[i] = static_cast<uint8_t>((i * 3) % 200);
        cw[i] = static_cast<uint8_t>(i % 5);
        cb[i] = static_cast<uint8_t>((i + 1) % 5);
    }
    std::string raw = (dir / "raw.hm").string();
    TableWriter::write(raw, mat, ps, 17, "{\"k\":1}", dw.data(), db.data(), cw.data(), cb.data());

    auto src = TableReader::open(raw);
    REQUIRE(src.has_value());
    CHECK(src->raw_payload() != nullptr);

    std::string out = (dir / "out.hm").string();
    TableWriter::compress_existing(out, *src);

    auto z = TableReader::open(out);
    REQUIRE(z.has_value());
    CHECK(z->is_compressed());
    CHECK(z->raw_payload() == nullptr);  // compressed: not a flat byte range
    CHECK(z->material_name() == "KQvk");
    CHECK(z->plane_size() == ps);
    CHECK(z->max_dtm() == 17);
    CHECK(z->meta_json() == "{\"k\":1}");
    for (uint64_t i = 0; i < ps; ++i)
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair a = src->get(stm, i), b = z->get(stm, i);
            CHECK(a.dtm == b.dtm);
            CHECK(a.count == b.count);
        }
    fs::remove_all(dir);
}

TEST_CASE("a header with an oversized block_size is rejected at open()") {
    // A crafted header claiming an absurd block_size must not reach get():
    // the reader sizes its decompressed-block cache off block_size (see
    // kBlockCacheBytes in table_file.cpp), so an unbounded value is a memory
    // exhaustion vector on the first probe if it were allowed through.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_block_size_huge_" + std::to_string(::getpid()));
    fs::create_directories(dir);
    std::string path = (dir / "t.hm").string();

    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 100;
    std::vector<uint8_t> v(ps, 1);
    TableWriter::write_compressed(path, mat, ps, 1, "{}", v.data(), v.data(), v.data(), v.data());

    // Sanity: readable before tampering.
    {
        auto z = TableReader::open(path);
        REQUIRE(z.has_value());
    }

    {
        std::fstream f(path, std::ios::in | std::ios::out | std::ios::binary);
        REQUIRE(f.is_open());
        uint32_t huge_block_size = (1u << 31);
        f.seekp(offsetof(TableHeader, block_size));
        f.write(reinterpret_cast<const char*>(&huge_block_size), sizeof(huge_block_size));
        REQUIRE(f.good());
    }

    TableReader::OpenError err = TableReader::OpenError::None;
    auto z = TableReader::open(path, &err);
    CHECK_FALSE(z.has_value());
    CHECK(err == TableReader::OpenError::Unreadable);
    fs::remove_all(dir);
}

TEST_CASE("compress_existing spans multiple blocks") {
    // The other compress_existing test uses ps = 3000 (4 * 3000 = 12000
    // bytes: one block, well under kDefaultBlockSize). The ctest skip-recent
    // case elsewhere in this suite uses Kvk, also one block. That left the
    // block loop over the mmap in write_block_compressed -- and the offset
    // bookkeeping across a block boundary -- with zero coverage from
    // compress_existing specifically (write_compressed's multi-block case is
    // covered separately). ps >= 50000 makes 4 * ps span several 64 KB
    // blocks.
    //
    // Note: this does NOT exercise SequentialPageReleaser::advance() firing a
    // real madvise(MADV_DONTNEED) -- advance() only releases once 8 MiB of
    // pages have been fully consumed (see its kChunk comment), and this
    // table's logical size is far smaller than that. Covering the release
    // path itself needs a table on the order of tens of MB, which is out of
    // scope for a fast unit test.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_compress_existing_multiblock";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 50000;  // 4 * ps = 200000 bytes -> more than 3 blocks at 64 KB
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    for (uint64_t i = 0; i < ps; ++i) {
        dw[i] = static_cast<uint8_t>(i % 200);
        db[i] = static_cast<uint8_t>((i * 3) % 200);
        cw[i] = static_cast<uint8_t>(i % 5);
        cb[i] = static_cast<uint8_t>((i + 1) % 5);
    }
    std::string raw = (dir / "raw.hm").string();
    TableWriter::write(raw, mat, ps, 17, "{\"k\":1}", dw.data(), db.data(), cw.data(), cb.data());

    auto src = TableReader::open(raw);
    REQUIRE(src.has_value());
    CHECK(src->raw_payload() != nullptr);

    std::string out = (dir / "out.hm").string();
    TableWriter::compress_existing(out, *src);

    auto z = TableReader::open(out);
    REQUIRE(z.has_value());
    CHECK(z->is_compressed());
    CHECK(block_count(4 * ps, kDefaultBlockSize) > 1);
    CHECK(z->plane_size() == ps);
    CHECK(z->max_dtm() == 17);
    for (uint64_t i = 0; i < ps; ++i)
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair a = src->get(stm, i), b = z->get(stm, i);
            CHECK(a.dtm == b.dtm);
            CHECK(a.count == b.count);
        }
    fs::remove_all(dir);
}

TEST_CASE("compress_existing refuses a marker table") {
    // A marker has no payload at all -- unlike a compressed source (see the
    // re-blocking test below), there is nothing read_range could stream.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_compress_existing_refuse_marker";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 100;

    std::string marker = (dir / "marker.hm").string();
    TableWriter::write_unsolvable(marker, mat, ps, "{}");
    auto m = TableReader::open(marker);
    REQUIRE(m.has_value());
    CHECK(m->raw_payload() == nullptr);
    CHECK_THROWS_AS(TableWriter::compress_existing((dir / "marker2.hm").string(), *m), std::runtime_error);
    fs::remove_all(dir);
}

TEST_CASE("compress_existing re-blocks an already-compressed table to a different block size") {
    // The trap this closes: before read_range existed, compress_existing
    // called src.raw_payload(), which is nullptr for a compressed source, so
    // moving a table from one block size to another required regenerating it
    // from scratch -- hours for a 5-piece table, over a day for a 6-piece.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_reblock_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 50000;  // 4*ps = 200000 bytes: several blocks at both 65536 and 4096
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    for (uint64_t i = 0; i < ps; ++i) {
        dw[i] = static_cast<uint8_t>(i % 200);
        db[i] = static_cast<uint8_t>((i * 3) % 200);
        cw[i] = static_cast<uint8_t>(i % 5);
        cb[i] = static_cast<uint8_t>((i + 1) % 5);
    }
    std::string big = (dir / "big.hm").string();
    TableWriter::write_compressed(big, mat, ps, 17, "{\"k\":1}", dw.data(), db.data(), cw.data(), cb.data(),
                                  65536);

    auto src = TableReader::open(big);
    REQUIRE(src.has_value());
    REQUIRE(src->is_compressed());
    REQUIRE(src->block_size() == 65536u);
    REQUIRE(src->raw_payload() == nullptr);  // confirms this path cannot use raw_payload

    std::string small = (dir / "small.hm").string();
    TableWriter::compress_existing(small, *src, 4096);  // a genuinely different block size

    auto dst = TableReader::open(small);
    REQUIRE(dst.has_value());
    CHECK(dst->is_compressed());
    CHECK(dst->block_size() == 4096u);
    CHECK(dst->material_name() == "KQvk");
    CHECK(dst->plane_size() == ps);
    CHECK(dst->max_dtm() == 17);
    CHECK(dst->meta_json() == "{\"k\":1}");
    // Byte-identical DECOMPRESSED content at both block sizes -- re-blocking
    // must never change what a probe reads, only how it is stored.
    for (uint64_t i = 0; i < ps; ++i)
        for (Color stm : {Color::White, Color::Black}) {
            ValuePair a = src->get(stm, i), b = dst->get(stm, i);
            CHECK(a.dtm == b.dtm);
            CHECK(a.count == b.count);
        }
    fs::remove_all(dir);
}

TEST_CASE("TableReader::read_range agrees with get() for both raw and compressed tables") {
    // read_range must never be a byte-at-a-time loop over the cache (that
    // would take the cache mutex once per byte); this pins the actual
    // contract -- an arbitrary [offset, offset+len) span, straddling block
    // boundaries, matches what get() reports cell by cell.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_read_range_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 20000;  // 4*ps = 80000 bytes: multiple blocks at a small block size
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    for (uint64_t i = 0; i < ps; ++i) {
        dw[i] = static_cast<uint8_t>((i * 7) % 251);
        db[i] = static_cast<uint8_t>((i * 11) % 251);
        cw[i] = static_cast<uint8_t>(i % 5);
        cb[i] = static_cast<uint8_t>((i + 2) % 5);
    }
    std::string raw = (dir / "raw.hm").string();
    TableWriter::write(raw, mat, ps, 9, "{}", dw.data(), db.data(), cw.data(), cb.data());
    std::string zip = (dir / "zip.hm").string();
    TableWriter::write_compressed(zip, mat, ps, 9, "{}", dw.data(), db.data(), cw.data(), cb.data(), 4096);

    auto r = TableReader::open(raw);
    auto z = TableReader::open(zip);
    REQUIRE(r.has_value());
    REQUIRE(z.has_value());
    REQUIRE_FALSE(r->is_compressed());
    REQUIRE(z->is_compressed());

    const uint64_t total = 4 * ps;
    // A handful of ranges: from the start, straddling a block boundary
    // (4096), a large span crossing many blocks, and right up to the end.
    struct Range {
        uint64_t begin;
        size_t len;
    };
    std::vector<Range> ranges = {{0, 10}, {4090, 20}, {0, total}, {total - 5, 5}, {12345, 9000}};
    for (auto& rg : ranges) {
        std::vector<uint8_t> from_raw(rg.len), from_zip(rg.len);
        r->read_range(rg.begin, rg.len, from_raw.data());
        z->read_range(rg.begin, rg.len, from_zip.data());
        CHECK(from_raw == from_zip);
        // Cross-check a few bytes in the span directly against get()'s own
        // indexing (dtm_w, dtm_b, cnt_w, cnt_b planes in that order).
        for (uint64_t off : {uint64_t(0), rg.len / 2, rg.len - 1}) {
            uint64_t logical = rg.begin + off;
            uint64_t plane = logical / ps, cell = logical % ps;
            uint8_t expected;
            if (plane == 0) expected = r->get(Color::White, cell).dtm;
            else if (plane == 1) expected = r->get(Color::Black, cell).dtm;
            else if (plane == 2) expected = r->get(Color::White, cell).count;
            else expected = r->get(Color::Black, cell).count;
            CHECK(from_raw[off] == expected);
        }
    }
    CHECK_THROWS_AS(r->read_range(total - 1, 5, nullptr), std::out_of_range);
    CHECK_THROWS_AS(z->read_range(total - 1, 5, nullptr), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("TableReader::read_values agrees with get() cell for cell") {
    // read_values is what every plane-wide scan goes through (mine, compact),
    // so it has to be exactly get() in bulk -- including at chunk boundaries
    // that do not line up with block boundaries, which is the normal case:
    // plane_size is a product of 462/1806 and 64/48 and rarely divides the
    // block size.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_read_values_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 9999;  // deliberately coprime-ish with every chunk below
    std::vector<uint8_t> dw(ps), db(ps), cw(ps), cb(ps);
    for (uint64_t i = 0; i < ps; ++i) {
        dw[i] = static_cast<uint8_t>((i * 7) % 253);
        db[i] = static_cast<uint8_t>((i * 11) % 253);
        cw[i] = static_cast<uint8_t>(i % 251);
        cb[i] = static_cast<uint8_t>((i + 3) % 251);
    }
    std::string raw = (dir / "raw.hm").string();
    std::string zip = (dir / "zip.hm").string();
    TableWriter::write(raw, mat, ps, 9, "{}", dw.data(), db.data(), cw.data(), cb.data());
    TableWriter::write_compressed(zip, mat, ps, 9, "{}", dw.data(), db.data(), cw.data(), cb.data(), 4096);

    auto r = TableReader::open(raw);
    auto z = TableReader::open(zip);
    REQUIRE(r.has_value());
    REQUIRE(z.has_value());

    for (const TableReader* t : {&*r, &*z}) {
        for (size_t chunk : {size_t(1), size_t(7), size_t(4096), size_t(5000), size_t(ps)}) {
            for (Color stm : {Color::White, Color::Black}) {
                std::vector<uint8_t> d(chunk), c(chunk);
                for (uint64_t base = 0; base < ps; base += chunk) {
                    const size_t n = (size_t)std::min<uint64_t>(chunk, ps - base);
                    t->read_values(stm, base, n, d.data(), c.data());
                    for (size_t i = 0; i < n; ++i) {
                        ValuePair want = t->get(stm, base + i);
                        REQUIRE(d[i] == want.dtm);
                        REQUIRE(c[i] == want.count);
                    }
                }
            }
        }
        // A null count buffer must leave DTM identical, not shift the plane.
        std::vector<uint8_t> d(100);
        t->read_values(Color::Black, 500, 100, d.data(), nullptr);
        for (size_t i = 0; i < 100; ++i) REQUIRE(d[i] == t->get(Color::Black, 500 + i).dtm);
        // Out of range is an error on both shapes, and n == 0 is a no-op.
        std::vector<uint8_t> scratch(8);
        CHECK_THROWS_AS(t->read_values(Color::White, ps - 1, 5, scratch.data(), scratch.data()),
                        std::out_of_range);
        CHECK_THROWS_AS(t->read_values(Color::White, ps + 1, 1, scratch.data(), nullptr), std::out_of_range);
        CHECK_NOTHROW(t->read_values(Color::White, ps, 0, nullptr, nullptr));
    }
    fs::remove_all(dir);
}

TEST_CASE("read_values on a marker table matches get() without touching a payload") {
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / ("hm_read_values_marker_" + std::to_string(::getpid()));
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KBvkb").value();
    const uint64_t ps = 1234;
    std::string path = (dir / "m.hm").string();
    TableWriter::write_unsolvable(path, mat, ps, "{}");
    auto t = TableReader::open(path);
    REQUIRE(t.has_value());
    REQUIRE(t->all_unsolvable());
    std::vector<uint8_t> d(ps), c(ps);
    t->read_values(Color::White, 0, ps, d.data(), c.data());
    for (uint64_t i = 0; i < ps; ++i) {
        REQUIRE(d[i] == DTM_UNSOLVABLE);
        REQUIRE(c[i] == 0);
    }
    CHECK_THROWS_AS(t->read_values(Color::White, ps, 1, d.data(), c.data()), std::out_of_range);
    fs::remove_all(dir);
}

TEST_CASE("interleaved compressed readers never answer from each other's blocks") {
    // TableReader keeps recently read blocks per thread, keyed by cache id and
    // block index. Two tables with the same layout share every block index;
    // a reader reopened after another is destroyed may reuse its address.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_local_blocks_test";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint64_t ps = 3000;
    std::vector<uint8_t> planes[2][4];
    for (int t = 0; t < 2; ++t)
        for (int k = 0; k < 4; ++k) {
            planes[t][k].resize(ps);
            for (uint64_t i = 0; i < ps; ++i)
                planes[t][k][i] = uint8_t((i * (t + 3) + k * 11 + t * 101) % 251);
        }
    std::string path[2] = {(dir / "a.hm").string(), (dir / "b.hm").string()};
    for (int t = 0; t < 2; ++t)
        TableWriter::write_compressed(path[t], mat, ps, 30, "{}", planes[t][0].data(), planes[t][1].data(),
                                      planes[t][2].data(), planes[t][3].data(), 1024);
    auto check_cell = [&](const TableReader& r, int t, Color stm, uint64_t i) {
        ValuePair v = r.get(stm, i);
        int s = stm == Color::White ? 0 : 1;
        return v.dtm == planes[t][s][i] && v.count == planes[t][2 + s][i];
    };

    {
        auto a = TableReader::open(path[0]);
        auto b = TableReader::open(path[1]);
        REQUIRE(a);
        REQUIRE(b);
        bool ok = true;
        for (uint64_t i = 0; i < ps; ++i)
            for (Color stm : {Color::White, Color::Black})
                ok = ok && check_cell(*a, 0, stm, i) && check_cell(*b, 1, stm, i);
        CHECK(ok);

        std::atomic<bool> mismatch{false};
        std::vector<std::thread> workers;
        for (unsigned seed = 1; seed <= 8; ++seed)
            workers.emplace_back([&, seed] {
                std::mt19937_64 rng(seed);
                for (int n = 0; n < 20000; ++n) {
                    uint64_t i = rng() % ps;
                    int t = (int)(rng() & 1);
                    Color stm = (rng() & 2) ? Color::Black : Color::White;
                    if (!check_cell(t ? *b : *a, t, stm, i)) mismatch = true;
                }
            });
        for (auto& w : workers) w.join();
        CHECK_FALSE(mismatch.load());
    }
    // This thread still holds blocks of the destroyed readers; reopened
    // readers must not be served from them.
    for (int round = 0; round < 3; ++round) {
        int t = round % 2 ? 0 : 1;
        auto r = TableReader::open(path[t]);
        REQUIRE(r);
        bool ok = true;
        for (uint64_t i = 0; i < ps; i += 7) ok = ok && check_cell(*r, t, Color::Black, i);
        CHECK(ok);
    }
    fs::remove_all(dir);
}

TEST_CASE("a cell's DTM and count bytes stay in the per-thread slots together") {
    // get() reads the DTM byte at o and the count byte at 2 * ps + o. Here
    // 2 * ps is exactly 8 blocks, the geometry of every five-piece pawnless
    // table at the default block size: both blocks once mapped to the same
    // slot and evicted each other, so every get() went to the shared cache.
    namespace fs = std::filesystem;
    fs::path dir = fs::temp_directory_path() / "hm_slot_pair_test";
    fs::remove_all(dir);
    fs::create_directories(dir);
    Material mat = Material::parse("KQvk").value();
    const uint32_t block = 1024;
    const uint64_t ps = 4 * block;
    std::vector<uint8_t> planes[4];
    for (int k = 0; k < 4; ++k) {
        planes[k].resize(ps);
        for (uint64_t i = 0; i < ps; ++i) planes[k][i] = uint8_t((i * 7 + k * 31) % 253);
    }
    std::string path = (dir / "pair.hm").string();
    TableWriter::write_compressed(path, mat, ps, 30, "{}", planes[0].data(), planes[1].data(),
                                  planes[2].data(), planes[3].data(), block);
    auto r = TableReader::open(path);
    REQUIRE(r);
    REQUIRE(r->block_size() == block);
    bool ok = true;
    for (int pass = 0; pass < 4; ++pass)
        for (uint64_t i = 0; i < block; ++i) {  // all in DTM block 0 and count block 8
            ValuePair v = r->get(Color::White, i);
            ok = ok && v.dtm == planes[0][i] && v.count == planes[2][i];
        }
    CHECK(ok);
    // One fill per block; every later probe is a slot hit.
    CHECK(r->cache_lookups() == 2);
    fs::remove_all(dir);
}

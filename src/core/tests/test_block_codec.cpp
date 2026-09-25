#include <atomic>
#include <catch2/catch_test_macros.hpp>
#include <functional>
#include <numeric>
#include <random>
#include <stdexcept>
#include <thread>
#include <vector>

#include "chess/types.h"
#include "format/block_cache.h"
#include "format/block_codec.h"
#include "format/table_file.h"

using namespace hm;

TEST_CASE("block_count rounds up and handles an exact multiple") {
    CHECK(block_count(0, 1024) == 0);
    CHECK(block_count(1, 1024) == 1);
    CHECK(block_count(1024, 1024) == 1);
    CHECK(block_count(1025, 1024) == 2);
    // 4 * 7'751'073'792 = 31'004'295'168, which is an exact multiple of 65536,
    // so the ceiling division lands exactly on 473'088 (verified independently
    // in Python: 31004295168 / 65536 == 473088.0). The brief's literal here
    // (473'115) does not match that arithmetic; corrected to the true value.
    CHECK(block_count(4ull * 7'751'073'792ull, 65536) == 473'088ull);
}

TEST_CASE("a block round-trips byte for byte") {
    std::vector<uint8_t> src(65536);
    std::mt19937 rng(12345);
    for (auto& b : src) b = static_cast<uint8_t>(rng() & 0xFF);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a constant block compresses hard and still round-trips") {
    // Half of a real 6-piece plane is DTM_INVALID; this is the case the whole
    // format exists to exploit, so it is pinned rather than assumed.
    std::vector<uint8_t> src(65536, DTM_INVALID);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    CHECK(packed.size() < src.size() / 50);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a short final block round-trips at its own length") {
    // 4 * plane_size is not a multiple of 65536 in general.
    std::vector<uint8_t> src(1237);
    std::iota(src.begin(), src.end(), 0);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    decompress_block(packed.data(), packed.size(), back.data(), back.size());
    CHECK(back == src);
}

TEST_CASE("a corrupt block throws instead of returning garbage") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    REQUIRE(packed.size() > 8);
    packed[packed.size() / 2] ^= 0xFF;  // flip a bit in the middle
    std::vector<uint8_t> back(src.size());
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}

TEST_CASE("a block that decompresses to the wrong size throws") {
    std::vector<uint8_t> src(4096, 7);
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(2048);  // caller expects half
    CHECK_THROWS_AS(decompress_block(packed.data(), packed.size(), back.data(), back.size()),
                    std::runtime_error);
}

TEST_CASE("block_count throws on a zero block_size") {
    CHECK_THROWS_AS(block_count(1024, 0), std::runtime_error);
}

TEST_CASE("every single-bit corruption in a compressed block is detected") {
    // Not one flip in a degenerate fixture: sweep a realistic block so this
    // fails if the frame checksum is ever turned off again.
    std::vector<uint8_t> src(4096);
    std::mt19937 rng(4242);
    for (auto& b : src) b = static_cast<uint8_t>(rng() % 7);  // compressible but not constant
    auto packed = compress_block(src.data(), src.size(), kDefaultZstdLevel);
    std::vector<uint8_t> back(src.size());
    size_t undetected = 0;
    for (size_t byte = 0; byte < packed.size(); ++byte) {
        for (int bit = 0; bit < 8; ++bit) {
            auto bad = packed;
            bad[byte] ^= static_cast<uint8_t>(1u << bit);
            try {
                decompress_block(bad.data(), bad.size(), back.data(), back.size());
                if (back != src) ++undetected;  // decoded, but to the wrong bytes
            } catch (const std::runtime_error&) {
                // detected, which is the point
            }
        }
    }
    CHECK(undetected == 0);
}

TEST_CASE("the cache fills once and serves the second read from memory") {
    BlockCache c(4, 1024);
    size_t calls = 0;
    auto fill = [&](uint8_t* dst, size_t len) {
        ++calls;
        std::fill(dst, dst + len, 0xAB);
    };
    uint8_t a = c.byte_at(7, 0, 1024, fill);
    CHECK(a == 0xAB);
    CHECK(calls == 1);
    uint8_t b = c.byte_at(7, 0, 1024, fill);
    CHECK(b == 0xAB);
    CHECK(calls == 1);  // served from cache, not refilled
    CHECK(c.fills() == 1);
    CHECK(c.hits() == 1);
}

TEST_CASE("evicting past capacity still returns correct bytes") {
    BlockCache c(2, 16);  // deliberately tiny
    auto fill_with = [](uint8_t v) {
        return [v](uint8_t* dst, size_t len) { std::fill(dst, dst + len, v); };
    };
    CHECK(c.byte_at(1, 0, 16, fill_with(1)) == 1);
    CHECK(c.byte_at(2, 0, 16, fill_with(2)) == 2);
    CHECK(c.byte_at(3, 0, 16, fill_with(3)) == 3);  // evicts block 1
    CHECK(c.byte_at(1, 0, 16, fill_with(1)) == 1);  // refilled, still correct
    CHECK(c.fills() == 4);
}

TEST_CASE("a short final block is cached at its own length") {
    BlockCache c(2, 1024);
    auto fill = [](uint8_t* dst, size_t len) { std::fill(dst, dst + len, 0x5A); };
    uint8_t p = c.byte_at(0, 299, 300, fill);  // shorter than block_size
    CHECK(p == 0x5A);
    CHECK(c.byte_at(0, 0, 300, fill) == 0x5A);
    CHECK(c.fills() == 1);
}

TEST_CASE("the cache is safe under concurrent byte_at from multiple threads, with forced eviction") {
    // Exercise the many-shard case with a working set larger than capacity.
    // byte_at never hands out a pointer, so eviction cannot leave a dangling
    // one. Each block's contents depend on its index, catching cross-
    // contamination between concurrent fills and evictions.
    constexpr size_t kIters = 5000;
    constexpr uint64_t kNumIndices = 256;
    BlockCache c(64, 32);
    std::atomic<bool> mismatch{false};

    auto worker = [&](unsigned seed) {
        std::mt19937 rng(seed);
        std::uniform_int_distribution<uint64_t> dist(0, kNumIndices - 1);
        for (size_t i = 0; i < kIters; ++i) {
            uint64_t idx = dist(rng);
            auto fill = [idx](uint8_t* dst, size_t len) {
                std::fill(dst, dst + len, static_cast<uint8_t>(idx & 0xFF));
            };
            size_t offset = static_cast<size_t>(idx % 32);
            uint8_t b = c.byte_at(idx, offset, 32, fill);
            if (b != static_cast<uint8_t>(idx & 0xFF)) mismatch = true;
        }
    };

    std::vector<std::thread> workers;
    for (unsigned seed = 1; seed <= 16; ++seed) workers.emplace_back(worker, seed);
    for (auto& thread : workers) thread.join();

    CHECK_FALSE(mismatch.load());
    CHECK(c.fills() > kNumIndices);  // capacity < working set forces repeated refills
}

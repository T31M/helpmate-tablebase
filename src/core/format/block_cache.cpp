#include "format/block_cache.h"

#include <algorithm>
#include <atomic>
#include <cstring>
#include <stdexcept>

namespace hm {

namespace {
std::atomic<uint64_t> next_cache_id{1};  // 0 never names a cache
}  // namespace

BlockCache::BlockCache(size_t capacity_blocks, uint32_t block_size)
    : id_(next_cache_id.fetch_add(1, std::memory_order_relaxed)),
      cap_(capacity_blocks ? capacity_blocks : 1),
      block_size_(block_size),
      shard_count_(std::min<size_t>(cap_, 32)),
      shards_(std::make_unique<Shard[]>(shard_count_)) {
    // Divide the existing block budget exactly: sharding must not multiply
    // the reader's memory ceiling as the thread count grows.
    for (size_t i = 0; i < shard_count_; ++i)
        shards_[i].cap = cap_ / shard_count_ + (i < cap_ % shard_count_);
}

uint8_t BlockCache::byte_at(uint64_t index, size_t offset, size_t len,
                            const std::function<void(uint8_t*, size_t)>& fill) {
    if (offset >= len) throw std::runtime_error("BlockCache: offset out of range");
    uint8_t b;
    read_range(index, offset, 1, len, &b, fill);
    return b;
}

void BlockCache::read_range(uint64_t index, size_t offset, size_t count, size_t len, uint8_t* dst,
                            const std::function<void(uint8_t*, size_t)>& fill) {
    if (len > block_size_) throw std::runtime_error("BlockCache: len exceeds block_size");
    if (offset + count > len) throw std::runtime_error("BlockCache: range out of block bounds");
    if (count == 0) return;
    // The shared owner keeps the block alive for the copy even if another
    // thread evicts it as soon as acquire() releases the shard lock.
    std::memcpy(dst, acquire(index, len, fill)->data() + offset, count);
}

std::shared_ptr<const BlockCache::Block> BlockCache::block(
    uint64_t index, size_t len, const std::function<void(uint8_t*, size_t)>& fill) {
    if (len > block_size_) throw std::runtime_error("BlockCache: len exceeds block_size");
    return acquire(index, len, fill);
}

std::shared_ptr<const BlockCache::Block> BlockCache::acquire(
    uint64_t index, size_t len, const std::function<void(uint8_t*, size_t)>& fill) {
    // The shard comes from a multiplicative hash of the index, not from
    // index % shard_count_: block indices that a lookup pattern visits
    // together often differ by multiples of the shard count (mine's solution
    // search steps through a six-piece index in strides of 64^k cells), and
    // with the modulus they all fell into one shard of capacity / 32 blocks.
    // On `mine KBvkqrn --dtm 14 --count 2 --starts 2 --ends 2 --threads 16`
    // that cost 15% more CPU and decompression (31.3 s against 24.4 s).
    // The top bits of the product are the well-mixed ones; scaling them into
    // [0, shard_count_) also works when the count is not a power of two.
    const uint64_t mixed = index * 0x9E3779B97F4A7C15ull;
    Shard& shard = shards_[static_cast<size_t>((static_cast<unsigned __int128>(mixed) * shard_count_) >> 64)];

    std::shared_ptr<Block> local;
    {
        std::lock_guard<std::mutex> lock(shard.mu);
        auto it = shard.map.find(index);
        if (it != shard.map.end()) {
            shard.lru.splice(shard.lru.begin(), shard.lru, it->second);
            ++shard.hits;
            return shard.lru.front().data;
        }
        if (!shard.spare.empty()) {
            local = std::move(shard.spare.back());
            shard.spare.pop_back();
        }
    }

    // Miss: decompress into a local buffer with no lock held, so a slow fill
    // (up to a 64 KB decompression) never blocks another thread's probe.
    // Another thread may race us and decompress the same block too -- that
    // is fine. A reused buffer is only resized: fill() writes all `len`
    // bytes or throws.
    if (local) local->resize(len);
    else local = std::make_shared<Block>(len);
    fill(local->data(), len);

    std::lock_guard<std::mutex> lock(shard.mu);
    ++shard.fills;
    auto it = shard.map.find(index);
    if (it != shard.map.end()) {
        // Another thread inserted this index while we were decompressing.
        // Use its entry and discard our redundant copy.
        shard.lru.splice(shard.lru.begin(), shard.lru, it->second);
        return shard.lru.front().data;
    }
    if (shard.lru.size() >= shard.cap) {
        shard.map.erase(shard.lru.back().index);
        // Reusable only if the cache holds the last reference: a thread's
        // block slot or a block() caller may still read it. Every new
        // reference is taken under this lock, so the count cannot grow here.
        auto& victim = shard.lru.back().data;
        if (victim.use_count() == 1 && shard.spare.size() < kMaxSpare)
            shard.spare.push_back(std::const_pointer_cast<Block>(std::move(victim)));
        shard.lru.pop_back();
    }
    shard.lru.push_front(Entry{index, std::move(local)});
    shard.map[index] = shard.lru.begin();
    return shard.lru.front().data;
}

size_t BlockCache::fills() const {
    size_t total = 0;
    for (size_t i = 0; i < shard_count_; ++i) {
        std::lock_guard<std::mutex> lock(shards_[i].mu);
        total += shards_[i].fills;
    }
    return total;
}

size_t BlockCache::hits() const {
    size_t total = 0;
    for (size_t i = 0; i < shard_count_; ++i) {
        std::lock_guard<std::mutex> lock(shards_[i].mu);
        total += shards_[i].hits;
    }
    return total;
}

}  // namespace hm

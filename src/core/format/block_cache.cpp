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
    Shard& shard = shards_[index % shard_count_];

    {
        std::lock_guard<std::mutex> lock(shard.mu);
        auto it = shard.map.find(index);
        if (it != shard.map.end()) {
            shard.lru.splice(shard.lru.begin(), shard.lru, it->second);
            ++shard.hits;
            return shard.lru.front().data;
        }
    }

    // Miss: decompress into a local buffer with no lock held, so a slow fill
    // (up to a 64 KB decompression) never blocks another thread's probe.
    // Another thread may race us and decompress the same block too -- that
    // is fine.
    auto local = std::make_shared<Block>(len);
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
